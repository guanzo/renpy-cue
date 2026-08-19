#!/bin/sh
# Usage: bin/test_harness.sh /path/to/game/Game.sh [testcase...] [test-options...]
#
# Runs the harness game (test_game/) under the given Ren'Py runtime with the
# mod's cue_lib symlinked in.  RENPY_CUE_DIR defaults to the committed
# fixtures root (tests/fixtures/data) -- the same tree CI points at -- so
# local runs exercise the sfx/music fixtures exactly like CI does. Generated
# artifacts (video variants, db writes) land under gitignored subdirs.
#
# Runs are headless by default when xvfb-run is installed, so the engine
# window doesn't pop up and steal focus. Set RENPY_HEADLESS=0 to show the
# window (e.g. to watch a testcase run); CI already wraps the invocation in
# xvfb-run and is skipped. Install xvfb (apt-get install xvfb) to enable it.
#
# The testcases DSL differs between Ren'Py generations, so the active
# testcases file is materialized from a template by the bundled version:
#   - 8.x (modern):  testsuite/testcase/keysym/teardown -- one suite run,
#                    pass/fail read from the [rpytest] reporter summary.
#   - 7.x (legacy):  old test DSL -- one `renpy test <name>` invocation per
#                    testcase; failures exit nonzero via renpy.quit(status=1).
set -e

LAUNCHER="$1"; shift || { echo "Usage: $0 /path/to/game/Game.sh [testcase...] [options...]" >&2; exit 2; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GAME="$ROOT/test_game"
TEMPLATES="$GAME/templates"

# --- Resolve the launcher's game root and the bundled Ren'Py major version. ---
# 7.x games carry a literal `version_tuple = (7, ...)` in renpy/__init__.py;
# 8.x builds it dynamically (VersionTuple(...)) and never has that literal.
LAUNCHER_DIR="$(cd "$(dirname "$LAUNCHER")" && pwd)"
if grep -q 'version_tuple = (7,' "$LAUNCHER_DIR/renpy/__init__.py" 2>/dev/null; then
    DSL="legacy"
else
    DSL="modern"
fi

# --- Materialize the active testcases file from the matching template. ---
mkdir -p "$GAME/game"
cp "$TEMPLATES/testcases_$DSL.rpy" "$GAME/game/testcases.rpy"

# Clear stale .rpyc so the engine recompiles from source every run.
# testcases.rpy is rematerialized per DSL, and an orphaned rpyc (a .rpy
# deleted after a manual repro leaves its compiled twin) breaks the 7.4.10
# loader, which refuses a rpyc with no matching .rpy source.  Recompiling a
# handful of small files is negligible next to an engine boot.
rm -f "$GAME/game"/*.rpyc

# Clear stale engine artifacts so a prior run's errors can't be mistaken
# for this run's (the engine overwrites, but a crash may leave them behind).
rm -f "$GAME/errors.txt" "$GAME/traceback.txt"
# The mod's debug log appends -- a fresh run must start empty, or the
# print-on-failure below would surface a prior run's lines instead of this
# run's.
rm -f "$GAME/game/renpy_cue/debug.log"

# --- Wire in the mod and the scratch data root. ---
MOD="$GAME/game/renpy_cue"
mkdir -p "$MOD"
[ -e "$MOD/cue_lib" ] || ln -s "$ROOT/cue_lib" "$MOD/cue_lib"
export RENPY_CUE_DIR="${RENPY_CUE_DIR:-$ROOT/tests/fixtures/data}"

# The mod writes runtime state (marker DB, presets, generated video variants,
# Ren'Py saves/persistent) into the shared fixtures root and the test game's
# saves dir -- all gitignored.  They accumulate across local runs and can flip
# timing-sensitive testcases; CI starts from a fresh checkout, so it never
# sees the residue.  Start every run from the same clean slate (the committed
# audio/ and music/ fixtures are outside these dirs and are left alone).
rm -rf "$RENPY_CUE_DIR/data" "$RENPY_CUE_DIR/backups" "$RENPY_CUE_DIR/video"
rm -rf "$GAME/game/saves"

# Point saves + persistent at the wiped game/saves dir.  Without --savedir,
# save_directory sends persistent to the user-data dir (~/.renpy/...), which
# survives the wipe above and accumulates residue across local runs.  --savedir
# is applied before savelocation.init() -- options.rpy init code runs after it,
# so a game-side config override can't redirect persistent.  It must precede the
# basedir positional: 7.x argparse drops it otherwise ("unrecognized arguments").
SAVEDIR="$GAME/game/saves"

echo "[cue] runtime: $DSL testcases DSL ($LAUNCHER)"

# Headless by default: a local run shouldn't pop a window that steals focus.
# CI already wraps the whole invocation in xvfb-run, so skip the inner wrap
# there (a nested Xvfb server is wasted). Opt out with RENPY_HEADLESS=0 to
# see the engine window.
HEADLESS="${RENPY_HEADLESS:-1}"
RUN_PREFIX=""
if [ "$HEADLESS" = "1" ] && [ -z "${CI:-}" ]; then
    if command -v xvfb-run >/dev/null 2>&1; then
        RUN_PREFIX="xvfb-run -a "
        export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"
    else
        echo "[cue] xvfb-run not found -- engine window will be visible (install xvfb for headless runs)" >&2
    fi
fi

if [ "$DSL" = "legacy" ]; then
    # 7.x registers `test` without uses_display, so post_init forces the dummy
    # video driver and gl_test can't open a window. Override with x11 (WSLg)
    # unless the caller already picked a driver.
    export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"

    # 7.x: one testcase per invocation, selected by name (or the whole file).
    NAMES="$*"
    if [ -z "$NAMES" ]; then
        NAMES=$(grep '^testcase ' "$TEMPLATES/testcases_legacy.rpy" | sed 's/^testcase //; s/:.*//')
    fi

    rc=0
    for name in $NAMES; do
        echo "[cue] running testcase: $name"
        rm -f "$MOD/debug.log"
        if ! $RUN_PREFIX "$LAUNCHER" --savedir "$SAVEDIR" "$GAME" test "$name"; then
            echo "[cue] testcase FAILED: $name" >&2
            if [ -f "$MOD/debug.log" ]; then
                echo "[cue] renpy_cue/debug.log:" >&2
                cat "$MOD/debug.log" >&2
            fi
            rc=1
        fi
    done
    exit $rc
fi

# 8.x: one suite run. The test `exit` statement raises QuitException so the
# process exits 0 regardless of pass/fail -- parse the reporter summary.
LOG="$(mktemp -t cue_testcases.XXXXXX.log)"
$RUN_PREFIX "$LAUNCHER" --savedir "$SAVEDIR" "$GAME" test "$@" > "$LOG" 2>&1 || true
cat "$LOG"

if grep -q "Status: PASSED" "$LOG"; then
    rm -f "$LOG"
    exit 0
fi

echo "[cue] test run did not pass (see summary above)" >&2
if [ -f "$MOD/debug.log" ]; then
    echo "[cue] renpy_cue/debug.log:" >&2
    cat "$MOD/debug.log" >&2
fi
rm -f "$LOG"
exit 1
