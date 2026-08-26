---
name: release
description: Stamp a new version and publish it — bump CUE_VERSION, run the gates, build the mod + SFX assets, cut a vX.Y.Z tag, and attach a GitHub release. Use when the user types /release or asks to publish a release.
---

# /release

Publish a release. `CUE_VERSION` in `cue_lib/constants.py` is the single source
of truth; never retype the number.

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

5. **Generate notes + changelog.**
   - **First release** (no prior `v*` tag): write a short hand-written note
     (version, a README link, both assets) and seed a brief `CHANGELOG.md`.
   - **Later releases**: run `git-cliff -u` to draft the categorized notes for
     the unreleased range; regenerate `CHANGELOG.md` with `git-cliff`. Save the
     draft to a temp file for step 9.
   - The repo is **private**, so git-cliff cannot fetch GitHub metadata
     unauthenticated. Run it with the token exported:

     ```bash
     export GITHUB_TOKEN="$(gh auth token)"
     git-cliff -u
     ```

6. **Dry-run the mod asset** (verify contents, don't ship it):

   ```bash
   python3 bin/build_release_asset.py --out "/tmp/renpy_cue_<ver>.zip"
   ```
   Check the zip: no `.rpyc`/`.pyo`/`__pycache__`; has `cue_lib/__init__.py`;
   no tests/, bin/, tools/, docs/.

7. **Build the SFX asset locally** (the path comes from gitignored `.env`,
   never from a committed path):

   ```bash
   source .env   # sets CUE_SFX_SOURCE_DIR
   python3 bin/build_sfx_asset.py "$CUE_SFX_SOURCE_DIR" --out "renpy_cue_sfx_<ver>.zip"
   ```
   Verify `test_bad` is not in the zip.

8. **STOP — present the plan and wait.** Show the new version, the asset
   filenames, and the `git log` of what will ship. Wait for explicit
   confirmation (the user commits themselves; publishing is outward-facing).

9. **Publish.** On confirm:
   - Commit the version bump + changelog:
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
