# Release Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned release pipeline that stamps `CUE_VERSION`, exposes it in-game, builds a `renpy_cue_<ver>.zip` mod asset and a `<sfx>` asset via a local `/release` skill, and publishes both to a GitHub release on a `v*` tag.

**Architecture:** One source of truth — `CUE_VERSION` in `cue_lib/constants.py` — feeds the in-game `_cue.VERSION`, the release tag, and both asset filenames. A local `/release` skill (Claude Code) bumps the version, runs the gates, generates notes/changelog via `git-cliff`, tags, and pushes. A tag-triggered GitHub Actions `release` job rebuilds + attaches the mod zip; the skill adds the SFX zip (source is local, not in git) and edits in the git-cliff notes.

**Tech Stack:** Ren'Py 7.x/8.x, Python 3 (dev tooling), bash-free Python asset builders, `git-cliff` (Rust binary), GitHub Actions (`gh` CLI, `GITHUB_TOKEN`).

**Spec:** `docs/superpowers/specs/2026-08-25-release-pipeline-design.md`

## Global Constraints

- Ren'Py 7.4+ (7.x/8.x). Runtime `.py` files: **no f-strings, no type hints, ASCII only, classes inherit `object`**. This applies to edits in `cue_lib/*.py` (tasks 1) — the dev tools in `bin/` and docs are exempt.
- **Absolute env paths never committed.** The SFX source dir lives in gitignored `.env` (`CUE_SFX_SOURCE_DIR`) and is passed to the builder as a parameter. No `E:\`/`/mnt/` path goes into any tracked file or this plan.
- Version string is a single source of truth: `CUE_VERSION` in `constants.py`. The release skill greps it; never re-type the number.
- In-game version is user-facing copy → render with `etext` (the escaped-text statement), not `text`.

---

### Task 1: `CUE_VERSION` constant + store bridge

**Files:**
- Modify: `cue_lib/constants.py` (add near the top, after `import os`)
- Modify: `cue_lib/constants.pyi`
- Modify: `cue_lib/cue_z.rpy` (`init -999` import block ~line 57; `init -900` assignments ~line 308)
- Modify: `cue_lib/state.pyi` (`Cue` class ~line 42)
- Test: `tests/test_version.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `cue_lib.constants.CUE_VERSION` (type `str`, e.g. `"0.1.0"`); `_cue.VERSION` (store attribute, type `str`) — consumed by the UI when the user renders it, and by the release skill (Task 8).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_version.py
import re
from cue_lib.constants import CUE_VERSION

def test_cue_version_is_semver():
    assert re.match(r"^\d+\.\d+\.\d+$", CUE_VERSION) is not None

def test_cue_version_is_nonempty():
    assert len(CUE_VERSION) > 0
```

- [ ] **Step 2: Run test and confirm it fails**

Run: `python3 -m pytest tests/test_version.py -v`
Expected: FAIL with `ImportError: cannot import name 'CUE_VERSION'`.

- [ ] **Step 3: Add `CUE_VERSION` to constants.py**

```python
# cue_lib/constants.py (after `import os`)
# The published release version. Read by bin/build_release_asset.py and the
# /release skill; single source of truth for the tag + asset names.
CUE_VERSION = "0.1.0"
```

- [ ] **Step 4: Mirror in constants.pyi**

```python
CUE_VERSION: Final = "0.1.0"
```

- [ ] **Step 5: Bridge into the store (cue_z.rpy)**

Add `CUE_VERSION,` to the `from cue_lib.constants import (` list in the `init -999` block (line 57).

Add to the `init -900` block's `_cue.*` assignment list (near line 308):

```renpy
        _cue.VERSION = CUE_VERSION
```

- [ ] **Step 6: Type the Cue attribute (state.pyi)**

Add to the `Cue` class (line 42):

```python
    VERSION: str
```

- [ ] **Step 7: Run test to confirm pass**

Run: `python3 -m pytest tests/test_version.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Commit**

```bash
git add cue_lib/constants.py cue_lib/constants.pyi cue_lib/cue_z.rpy cue_lib/state.pyi tests/test_version.py
git commit -m "feat(version): add CUE_VERSION single source, bridge _cue.VERSION"
```

---

### Task 2: _(skipped — no UI change)_

**The version is exposed as `_cue.VERSION` (Task 1) but is NOT rendered anywhere.**

> The user chose not to change any UI code. A version render in the overlay header
> (planned here) is deliberately dropped. The value is available for the user to put
> in the UI when they choose; this release-pipeline work does not place it.

Net effect of Task 2: nothing to build or commit. `_cue.VERSION` is the store binding
Task 1 produced; on the engine it is reachable by UI code as e.g. `etext "v" + _cue.VERSION`.

---

### Task 3: Conventional Commits rule in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** None (doc only). Consumed by the `/release` skill (Task 8) and every future commit.

- [ ] **Step 1: Add a commit-convention section**

Insert into `CLAUDE.md` (keep it terse, matching the house style):

```markdown
# Commit Convention

Use Conventional Commits. Prefix a commit with one of: `feat`, `fix`, `refactor`,
`perf`, `docs`, `style`, `test`, `build`, `chore`, `revert`, optionally `(scope)`.
A breaking change is marked with `!` after the type or a `BREAKING CHANGE:`
footer, e.g. `feat!: drop 7.x support`. This convention drives the `git-cliff`
release notes and changelog in `/release`.
```

- [ ] **Step 2: Verify**

Read the section back; confirm the prefixes match `cliff.toml`'s `commit_parsers` (Task 4) so notes categorize correctly.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document Conventional Commits convention"
```

---

### Task 4: `git-cliff` config + tooling note

**Files:**
- Create: `cliff.toml` (repo root)
- Modify: `CLAUDE.md` (dev-tooling note, or README)

**Interfaces:**
- Consumes: Conventional Commits (Task 3).
- Produces: `git-cliff` output used by the `/release` skill for the notes body and `CHANGELOG.md`.

- [ ] **Step 1: Create `cliff.toml`**

```toml
# git-cliff config -- reads the commit history to produce release notes and a
# CHANGELOG. Run by the /release skill. The commit *convention* is CLAUDE.md.
# Tune the render here; the convention feed is fixed.

[remote.github]
repo = "guanzo/renpy-cue"

[changelog]
header = "## Ren'Py Cue Changelog\n"
body = """
### Release {{ version }} — {{ timestamp | date(format="%Y-%m-%d") }}
"""
footer = ""
trim = true

[git]
conventional_commits = true
filter_unconventional = false
split_commits = false
commit_parsers = [
  { message = "^feat", group = "Features" },
  { message = "^fix", group = "Bug Fixes" },
  { message = "^docs", group = "Documentation" },
  { message = "^refactor", group = "Refactoring" },
  { message = "^perf", group = "Performance" },
  { message = "^test", group = "Tests" },
  { message = "^chore|^build", group = "Chores" },
  { message = ".*", group = "Other" },
]
```

- [ ] **Step 2: Add the tooling note (+ install instructions)**

In `CLAUDE.md` (or README dev section):

```markdown
# Release Tooling
- `git-cliff` (Rust binary) generates release notes + the changelog: install via
  `cargo install git-cliff` or `brew install git-cliff`. The `/release` skill
  runs `git-cliff -u` (unreleased) to draft the next version's notes.
- `gh` (GitHub CLI) is used by the release skill to create/upload a release; it
  must be authenticated (`gh auth login`).
```

- [ ] **Step 3: Verify**

Run: `git-cliff -u` (no args tail)
Expected: prints the categorized changelog for the current working tree (unreleased commits). If nothing shows, commits don't yet follow the convention — that's expected pre-Task 3 history; the config is still valid.

- [ ] **Step 4: Commit**

```bash
git add cliff.toml CLAUDE.md
git commit -m "build(release): add git-cliff config + tooling notes"
```

---

### Task 5: `bin/build_release_asset.py` (mod zip)

**Files:**
- Create: `bin/build_release_asset.py`
- Test: `tests/test_build_release_asset.py`

**Interfaces:**
- Consumes: `CUE_VERSION` (grep from `cue_lib/constants.py`), repo `cue_lib/`.
- Produces: `build_release_asset.py <out> [--source DIR]` → `renpy_cue_<ver>.zip` with top-level `renpy_cue/cue_lib/`, bytecode stripped. Called by the GA `release` job (Task 9) and by the skill's dry-run (Task 8).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_release_asset.py
import os, shutil, subprocess, sys, tempfile, zipfile

def make_fixture():
    src = tempfile.mkdtemp()
    cue = os.path.join(src, "cue_lib")
    os.makedirs(os.path.join(cue, "images"))
    open(os.path.join(cue, "__init__.py"), "w").close()
    open(os.path.join(cue, "mod.py"), "w").close()
    open(os.path.join(cue, "z.rpy"), "w").close()
    open(os.path.join(cue, "stale.rpyc"), "w").close()
    open(os.path.join(cue, "stale.pyo"), "w").close()
    os.makedirs(os.path.join(cue, "__pycache__"))
    open(os.path.join(cue, "__pycache__", "x.pyc"), "w").close()
    return src

def test_build_strips_bytecode_and_wraps():
    src = make_fixture()
    out = os.path.join(tempfile.mkdtemp(), "renpy_cue_9.9.9.zip")
    try:
        r = subprocess.run(
            [sys.executable, "bin/build_release_asset.py", "--source", src,
             "--out", out], check=True, capture_output=True)
        assert r.returncode == 0, r.stderr
        names = zipfile.ZipFile(out).namelist()
        assert any(n == "renpy_cue/cue_lib/__init__.py" for n in names)
        assert any(n.startswith("renpy_cue/cue_lib/images/") for n in names)
        assert not any(n.endswith((".rpyc", ".pyo", ".pyc")) for n in names)
        assert not any("__pycache__" in n for n in names)
    finally:
        shutil.rmtree(src, ignore_errors=True)
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python3 -m pytest tests/test_build_release_asset.py -v`
Expected: FAIL (`[Errno 2] No such file or directory: 'bin/build_release_asset.py'`).

- [ ] **Step 3: Write the script**

```python
#!/usr/bin/env python3
"""Build the published mod zip.

Output is a top-level `renpy_cue/` folder whose only child is `cue_lib/` (source
+ images), with version-specific bytecode (.rpyc/.pyo/.pyc/__pycache__) stripped.
Ships only cue_lib/ -- tests/, bin/, tools/, docs/, README never go in the asset.
"""
import argparse, os, re, shutil, sys, tempfile, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BYTECODE = (".rpyc", ".pyo", ".pyc")


def cue_version():
    with open(os.path.join(ROOT, "cue_lib", "constants.py")) as f:
        m = re.search(r'^CUE_VERSION\s*=\s*["\']([^"\']+)["\']', f.read(), re.M)
    if not m:
        raise SystemExit("CUE_VERSION not found in cue_lib/constants.py")
    return m.group(1)


def _ignore(dirpath, names):
    return [n for n in names if n.endswith(BYTECODE) or n == "__pycache__"]


def build_zip(source, out, version):
    stage = tempfile.mkdtemp(prefix="cue_asset_")
    try:
        mod = os.path.join(stage, "renpy_cue")
        shutil.copytree(source, os.path.join(mod, "cue_lib"), ignore=_ignore)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for base, _, files in os.walk(mod):
                for name in files:
                    p = os.path.join(base, name)
                    zf.write(p, os.path.relpath(p, stage))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=os.path.join(ROOT, "cue_lib"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--version", default=None)
    args = ap.parse_args()
    version = args.version or cue_version()
    out = args.out or os.path.join(ROOT, "renpy_cue_{}.zip".format(version))
    if not os.path.isdir(args.source):
        sys.exit("source dir not found: {}".format(args.source))
    print("built {} (CUE_VERSION={})".format(build_zip(args.source, out, version), version))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python3 -m pytest tests/test_build_release_asset.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/build_release_asset.py tests/test_build_release_asset.py
git commit -m "build(release): add cross-platform mod zip builder"
```

---

### Task 6: `bin/build_sfx_asset.py` (SFX pack zip)

**Files:**
- Create: `bin/build_sfx_asset.py`
- Test: `tests/test_build_sfx_asset.py`

**Interfaces:**
- Consumes: no repo code (the source dir is passed in from gitignored `.env`).
- Produces: `build_sfx_asset.py <src_dir> --out <out> [--exclude test_bad ...]` → zip of the source category folders, `test_bad` excluded. Called by the `/release` skill (Task 8) and uploaded with `gh release upload`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_sfx_asset.py
import os, subprocess, sys, tempfile, zipfile

def test_sfx_excludes_test_bad(tmp_path):
    src = tmp_path / "audio"
    for cat in ("Breathe", "Cum", "Moan", "Impact"):
        (src / cat).mkdir(parents=True)
        (src / cat / "a.wav").write_bytes(b"RIFF")
    (src / "test_bad").mkdir()
    (src / "test_bad" / "bad.wav").write_bytes(b"RIFF")
    out = tmp_path / "renpy_cue_sfx_9.9.9.zip"
    r = subprocess.run(
        [sys.executable, "bin/build_sfx_asset.py", str(src),
         "--out", str(out)], check=True, capture_output=True)
    assert r.returncode == 0, r.stderr
    names = zipfile.ZipFile(out).namelist()
    assert any("Breathe" in n for n in names)
    assert any("Cum" in n for n in names)
    assert not any("test_bad" in n for n in names)
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python3 -m pytest tests/test_build_sfx_asset.py -v`
Expected: FAIL (`No such file or directory`).

- [ ] **Step 3: Write the script**

```python
#!/usr/bin/env python3
"""Build the SFX pack zip from a local source dir.

The source dir is passed in (the /release skill reads it from gitignored .env as
CUE_SFX_SOURCE_DIR). No path is committed here. Wraps the category folders in a
top-level renpy_cue_sfx/ dir; `test_bad` is excluded.
"""
import argparse, os, shutil, sys, tempfile, zipfile

PACK = "renpy_cue_sfx"
DEFAULT_EXCLUDE = ("test_bad",)


def build_zip(src, out, exclude):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(os.listdir(src)):
            if entry in exclude:
                continue
            p = os.path.join(src, entry)
            if os.path.isdir(p):
                for base, _, files in os.walk(p):
                    for name in files:
                        fp = os.path.join(base, name)
                        zf.write(fp, os.path.join(PACK, os.path.relpath(fp, src)))
            else:
                zf.write(p, os.path.join(PACK, entry))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default=None)
    ap.add_argument("--exclude", action="append", default=list(DEFAULT_EXCLUDE))
    args = ap.parse_args()
    if not os.path.isdir(args.src):
        sys.exit("source dir not found: {}".format(args.src))
    if args.out is None:
        args.out = "renpy_cue_sfx.zip"
    print("built {} (excluded {})".format(build_zip(args.src, args.out, set(args.exclude)),
                                          ", ".join(args.exclude)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python3 -m pytest tests/test_build_sfx_asset.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/build_sfx_asset.py tests/test_build_sfx_asset.py
git commit -m "build(release): add SFX pack zip builder (excludes test_bad)"
```

---

### Task 7: `/release` skill

**Files:**
- Create: `.claude/skills/release/SKILL.md`
- Modify: `.env` (gitignored — add `CUE_SFX_SOURCE_DIR`, not committed)

**Interfaces:**
- Consumes: `CUE_VERSION` (grep), the gate skills (`/lint`, `/test`, `/test-harness`), `git-cliff` (Task 4), `bin/build_release_asset.py` (Task 5), `bin/build_sfx_asset.py` (Task 6).
- Produces: a version bump commit + `v<ver>` tag pushed, a GitHub release with both assets, final categorized notes.

- [ ] **Step 1: Write the skill**

`.claude/skills/release/SKILL.md`:

```markdown
---
name: release
description: Stamp a new version and publish it — bump CUE_VERSION, run the gates, build the mod + SFX assets, cut a vX.Y.Z tag, and attach a GitHub release. Use when the user types /release or asks to publish a release.
---

# Release

Publish a release. `CUE_VERSION` in `cue_lib/constants.py` is the single source of
truth; never retype the number.

## Before you start

- Confirm `gh auth login` is done and `git-cliff` is installed.
- Confirm the tree is clean (`git status`). Abort if there is uncommitted work.

## Steps

1. **Read the current version.**

   ```bash
   grep -E '^CUE_VERSION = ' cue_lib/constants.py
   ```

2. **Choose the bump.** Ask the user: major, minor, or patch. Compute the new
   version from the current one (semver). The first release is minor from `0.x`
   (e.g. `0.1.0`).

3. **Write the new version.** Update `CUE_VERSION` in `cue_lib/constants.py` and
   `constants.pyi` to the same string.

4. **Run the gate.** `/lint` then `/test`, then the harness on both generations:

   ```bash
   SDL_AUDIODRIVER=dummy xvfb-run -a bash bin/test_harness.sh .local/renpy-8.5.3-sdk/renpy.sh
   SDL_AUDIODRIVER=dummy xvfb-run -a bash bin/test_harness.sh .local/renpy-7.4.10-sdk/renpy.sh
   ```

   Any failure: stop, report, do not publish.

5. **Generate notes + changelog.**
   - **First release** (no prior `v*` tag): write a short hand-written note
     (version, a README link, both assets) and seed a brief `CHANGELOG.md`.
   - **Later releases**: run `git-cliff -u` to draft the categorized notes for
     the unreleased range; regenerate `CHANGELOG.md` with `git-cliff`. Paste the
     output into a temp notes file for step 9.

6. **Dry-run the mod asset** (verify contents, don't ship it):

   ```bash
   python3 bin/build_release_asset.py --out /tmp/renpy_cue_<ver>.zip
   ```
   Check the zip: no `.rpyc`/`.pyo`/`__pycache__`; has `cue_lib/__init__.py`;
   no `tests/`, `bin/`, `tools/`, `docs/`.

7. **Build the SFX asset locally** (path comes from gitignored `.env`, never from
   a committed path):

   ```bash
   python3 bin/build_sfx_asset.py "$CUE_SFX_SOURCE_DIR" --out renpy_cue_sfx_<ver>.zip
   ```
   Verify `test_bad` is not in the zip.

8. **STOP — present the plan and wait.** Show the new version, the asset
   filenames, and the `git log` of what will ship. Wait for explicit confirmation
   (the user commits themselves; publishing is outward-facing).

9. **Publish.** On confirm:
   - Commit the version bump + `CHANGELOG.md`:
     `git add cue_lib/constants.py cue_lib/constants.pyi CHANGELOG.md && git commit -m "chore(release): CUE_VERSION <ver>"`
   - Tag and push (triggers the `release` workflow):
     `git tag v<ver> && git push origin main --tags`

10. **Wait for CI**, then add the local pieces. Poll `gh release view v<ver>`
    until it exists (the runner builds + attaches the mod zip), then:
    - Swap in the categorized notes:
      `gh release edit v<ver> --notes-file <notes-file>`
    - Upload the SFX asset:
      `gh release upload v<ver> renpy_cue_sfx_<ver>.zip --clobber`

11. **Report.** Print the release URL and confirm both assets are attached.

## Notes

- The SFX asset comes from the local machine (its source is not in git), so the
  skill uploads it after CI creates the release. The mod zip is CI-built.
- First-release detection: `git tag --list 'v*'` is empty, or no prior release.
```

- [ ] **Step 2: Add the SFX source dir to gitignored `.env`**

Add to `.env` (gitignored, never committed):

```bash
CUE_SFX_SOURCE_DIR=<your local renpy_cue_data/audio path>
```

Do not put the literal absolute path in any tracked file.

- [ ] **Step 3: Make the skill invocable**

Confirm `.claude/skills/release/SKILL.md` is picked up (the `.gitignore` allows `.claude/skills/`). Verify by running `/release` in a session — it should load this skill. Do **not** run the publish flow yet.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/release/SKILL.md
git commit -m "feat(release): add /release skill for publishing"
```

---

### Task 8: GitHub Actions `release.yml`

**Files:**
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: the tag `v*`, `bin/build_release_asset.py` (Task 5), `CUE_VERSION`.
- Produces: a GitHub release with the mod zip attached, auto-notes as a default body (the skill replaces them).

- [ ] **Step 1: Write the workflow**

`.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags: ['v*']

jobs:
  release:
    name: build + attach mod asset
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      # Confirm the tag matches CUE_VERSION (a stale/foreign tag must not ship).
      - name: Assert tag matches CUE_VERSION
        run: |
          TAG="${GITHUB_REF_NAME#v}"
          VER="$(python3 -c 'import re,sys; print(re.search(r"^CUE_VERSION = \"([^\"]+)\"", open("cue_lib/constants.py").read(), re.M).group(1))')"
          if [ "$TAG" != "$VER" ]; then
            echo "tag v$TAG != CUE_VERSION $VER"; exit 1
          fi

      # Fast gate: the lint+test checks that every main push already runs.
      - name: Lint
        run: |
          export PATH="$(poetry env info -p)/bin:$PATH"
          bash bin/lint.sh
      - name: Test
        run: bash bin/test.sh

      - name: Build mod asset
        run: python3 bin/build_release_asset.py --out "renpy_cue_${GITHUB_REF_NAME#v}.zip"

      - name: Create release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh release create "$GITHUB_REF_NAME" \
            --title "Ren'Py Cue $GITHUB_REF_NAME" \
            --generate-notes \
            "renpy_cue_${GITHUB_REF_NAME#v}.zip"
```

The `poetry env` PATH is set for the lint step because `bin/lint.sh` invokes bare `pyright` (same pattern as `ci.yml`); the SDK symlink step from `ci.yml` is intentionally not added here — pyright's `extraPaths` are repo-relative (`./sdk`) already, and a cache miss on a release tag is acceptable, but if lint fails on the runner due to a missing SDK, add the cache+symlink steps from `ci.yml:121-135`.

- [ ] **Step 2: Validate locally (dry)**

`actionlint .github/workflows/release.yml` if available; otherwise push a throwaway tag on a branch, confirm the job starts in the Actions tab, then delete the tag + release. Do not run this on `main` as a test.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci(release): build + attach mod asset on v* tag"
```

---

## Self-Review

- **Global constraints:** absolute paths never committed (Tasks 6, 7 use `CUE_SFX_SOURCE_DIR` from gitignored `.env`); `CUE_VERSION` single-source grepped by the builders and skill (Tasks 1, 5, 7). No UI code is modified (user constraint) — `_cue.VERSION` is exposed but not rendered.
- **Spec coverage:** version constant + `_cue.VERSION` bridge (Task 1), Conventional Commits rule (Task 3), git-cliff notes + `cliff.toml` (Task 4), mod builder (Task 5), SFX builder excluding `test_bad` (Task 6), `/release` skill incl. first-release short note (Task 7), GA release job (Task 8). The spec's "first release minimal note" maps to Task 7 step 5; the spec's "no env paths" maps to Tasks 6–7. Task 2 (in-game render) is skipped per the user's no-UI-code directive.
