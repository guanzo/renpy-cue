#!/bin/sh
# Usage: bin/run_testcases.sh /path/to/game/Game.sh [testcase...] [test-options...]
#
# Runs the harness game (test_game/) under the given Ren'Py runtime with the
# mod's cue_lib symlinked in.  RENPY_CUE_DIR defaults to a gitignored scratch
# dir under test_game/ so runs are self-contained; set the env var explicitly
# to point at a real shared data tree instead.
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
rm -f "$GAME/game/testcases.rpyc"

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
mkdir -p "$GAME/cue_data"
export RENPY_CUE_DIR="${RENPY_CUE_DIR:-$GAME/cue_data}"

echo "[cue] runtime: $DSL testcases DSL ($LAUNCHER)"

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
        if ! "$LAUNCHER" "$GAME" test "$name"; then
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
"$LAUNCHER" "$GAME" test "$@" > "$LOG" 2>&1 || true
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
