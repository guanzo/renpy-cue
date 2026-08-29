---
name: release
description: Stamp a new version and publish it — bump CUE_VERSION, run the gates, build the mod + SFX assets, cut a vX.Y.Z tag, and attach a GitHub release. `/release sfx` rebuilds only the SFX pack and overwrites it on the latest release. Use when the user types /release (or /release sfx) or asks to publish a release.
---

# /release

Publish a release. `CUE_VERSION` in `cue_lib/constants.py` is the single source
of truth; never retype the number.

Invoked as **`/release sfx`**, skip the full flow below and run the
[SFX-only flow](#sfx-only-flow) instead: no version bump, no gates, no
release notes, no mod asset, no new tag.

## Before you start

- Confirm `gh auth login` is done and `git-cliff` is installed
  (`command -v git-cliff`).
- Confirm the tree is clean (`git status`). Abort if there is uncommitted work.

## Steps

1. **Read the current version.**

   ```bash
   grep -E '^CUE_VERSION = ' cue_lib/constants.py
   ```

2. **Choose the bump.** Ask the user: major, minor, or patch. Compute the new
   version from the current one (semver). The first release is minor from `0.x`
   (e.g. `0.1.0`).

3. **Write the new version.** Update `CUE_VERSION` in `cue_lib/constants.py`
   and `constants.pyi` to the same string.

4. **Run the gate.** `/lint`, then `/test`, then `/test-harness`
   (`bin/test_harness.sh --both`). Any failure: stop, report, do not publish.
   The harness is the slow leg (~15 min for legacy) and only boots the engine —
   if the change is pure infra, `/lint` + `/test` may be enough, but bumping
   `CUE_VERSION` touches `cue_z.rpy` bridge code, so run the full gate.

5. **Generate release notes.** GitHub release notes are the single source of
   truth — there is no `CHANGELOG.md` in the repo.
   - **First release** (no prior `v*` tag): write a short hand-written note
     (version, a README link, both assets).
   - **Later releases**: run `git-cliff -u` to draft the categorized notes for
     the unreleased range, then **curate — don't dump.** git-cliff lists every
     commit; the notes list only changes a user would notice and care about:
     notable features, user-visible fixes, real perf wins, and a **Breaking**
     callout near the top when a change affects existing users. Drop the
     routine and internal regardless of category — refactors, chores, docs,
     tests, CI, and one-off bug fixes that don't change how the mod behaves.
     Two to five lines per category beats every commit. Save the curated draft
     to a temp file for step 9.

6. **Dry-run the mod asset** (verify contents, don't ship it):

   ```bash
   python3 bin/build_release_asset.py --out "/tmp/Cue_<ver>.zip"
   ```
   Check the zip: no `.rpyc`/`.pyo`/`__pycache__`; has `cue_lib/__init__.py`;
   no tests/, bin/, tools/, docs/.

7. **Build the SFX asset locally** (the path comes from gitignored `.env`,
   never from a committed path):

   ```bash
   source .env   # sets CUE_SFX_SOURCE_DIR
   python3 bin/build_sfx_asset.py "$CUE_SFX_SOURCE_DIR" --out "/tmp/cue_sfx.zip"
   ```
   Verify `test_bad` is not in the zip.

8. **STOP — present the plan and wait.** Show the new version, the asset
   filenames, the `git log` of what will ship, and the draft release notes.
   Wait for explicit confirmation (the user commits themselves; publishing is
   outward-facing).

9. **Publish.** On confirm:
   - Commit the version bump:
     `git add cue_lib/constants.py cue_lib/constants.pyi && git commit -m "chore(release): CUE_VERSION <ver>"`
   - Tag and push (triggers the `release` workflow):
     `git tag v<ver> && git push origin main --tags`

10. **Wait for CI**, then add the local pieces. Poll `gh release view v<ver>`
    until it exists (the runner builds + attaches the mod zip), then:
    - Swap in the categorized notes:
      `gh release edit v<ver> --notes-file <notes-file>`
    - Upload the SFX asset:
      `gh release upload v<ver> /tmp/cue_sfx.zip --clobber`
    - Publish the release (CI created it as a draft; drafts are invisible to
      `releases/latest`, so the stable SFX link never 404s before the pack is
      attached):
      `gh release edit v<ver> --draft=false`

11. **Report.** Print the release URL and confirm both assets are attached.

## SFX-only flow

Run when the skill is invoked as `/release sfx` — the SFX source changed but no
code did. Rebuilds the pack and overwrites the asset on the latest release.
Standalone: never touches the full-release steps above.

1. **Read the current version.**

   ```bash
   grep -E '^CUE_VERSION = ' cue_lib/constants.py
   ```

2. **Source the source dir.** `source .env` sets `CUE_SFX_SOURCE_DIR` (WSL
   path, e.g. `/mnt/e/Porn/pGames/renpy_cue_data/audio`). If it's unset, stop
   and ask the user to add it — never guess or hardcode the path.

3. **Build the pack.**

   ```bash
   python3 bin/build_sfx_asset.py "$CUE_SFX_SOURCE_DIR" --out "/tmp/cue_sfx.zip"
   ```

4. **Verify the zip** has the category folders and no `test_bad`.

5. **Resolve the latest release.** `gh release list --limit 1` → tag name.
   If its tag ≠ `v<ver>`, surface the mismatch before continuing.

6. **STOP — confirm.** Show the target tag and the zip name. Publishing is
   outward-facing; wait for explicit confirmation.

7. **Upload** (in-place overwrite of the existing pack):

   ```bash
   gh release upload <tag> /tmp/cue_sfx.zip --clobber
   ```

8. **Report.** Print the release URL and confirm the SFX asset is attached.

## Notes

- GitHub release notes are the single source of truth — there is no
  `CHANGELOG.md`. Release notes are hand-curated: only changes a user would
  notice and care about, drawn from Features / Bug Fixes / Performance plus a
  Breaking callout. Refactors, chores, docs, tests, and CI never ship;
  routine bug fixes don't either. A short list beats a complete one.
- The SFX asset comes from the local machine (its source is not in git), so the
  skill uploads it after CI creates the release. The mod zip is CI-built.
- First-release detection: `git tag --list 'v*'` is empty, or no prior release.
- `/release sfx` overwrites `cue_sfx.zip` in place — users must
  re-download the pack from the same release page to pick up the change.
- The SFX asset name is deliberately versionless so the README link
  `https://github.com/guanzo/renpy-cue/releases/latest/download/cue_sfx.zip`
  stays stable across releases. `releases/latest` resolves only to published
  releases, not drafts. The release workflow creates each release as a draft
  and the full flow publishes it after the SFX upload, so the link never
  resolves to a release missing the pack.
