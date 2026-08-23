#!/bin/sh
# Usage: bin/test_harness.sh /path/to/game/Game.sh [testcase...] [test-options...]
#        bin/test_harness.sh --both [testcase...]  (modern + legacy, concurrently)
#
# Runs the harness game (test_game/) under the given Ren'Py runtime with the
# mod's cue_lib symlinked in.  Each run copies the small game tree and the
# fixture root (tests/fixtures/data by default; an explicit RENPY_CUE_DIR
# seeds the copy) into fresh temp dirs, so concurrent invocations -- e.g.
# modern and legacy side by side -- never share mutable state, and the
# committed test_game/ + fixtures stay pristine.  Generated artifacts (video
# variants, db writes, saves) land in the temp dirs and are removed on exit.
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

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# --both: run the modern (8.x) and legacy (7.x) harnesses concurrently, each
# spawning its own isolated temp dirs below.  Testcase filters: legacy honors
# several names; modern takes exactly one (renpy test's positional nargs="?").
if [ "$1" = "--both" ]; then
    shift
    MODERN=""
    LEGACY=""
    for d in "$ROOT"/.local/renpy-*-sdk; do
        [ -d "$d" ] || continue
        if grep -q 'version_tuple = (7,' "$d/renpy/__init__.py" 2>/dev/null; then
            LEGACY="$d/renpy.sh"
        else
            MODERN="$d/renpy.sh"
        fi
    done
    if [ -z "$MODERN" ] || [ -z "$LEGACY" ]; then
        echo "need both a 7.x and an 8.x renpy-*-sdk under .local/ for --both" >&2
        exit 2
    fi

    MLOG="$(mktemp -t cue_both_modern.XXXXXX.log)"
    LLOG="$(mktemp -t cue_both_legacy.XXXXXX.log)"
    trap 'rm -f "$MLOG" "$LLOG"' EXIT
    if [ $# -gt 0 ]; then
        M_ARGS="$1"
        L_ARGS="$*"
    else
        M_ARGS=""
        L_ARGS=""
    fi
    ( "$0" "$MODERN" $M_ARGS >"$MLOG" 2>&1 ) &
    MPID=$!
    ( "$0" "$LEGACY" $L_ARGS >"$LLOG" 2>&1 ) &
    LPID=$!
    if wait "$MPID"; then MR=0; else MR=$?; fi
    if wait "$LPID"; then LR=0; else LR=$?; fi
    echo "=== MODERN ($MODERN) ==="
    cat "$MLOG"
    echo "=== LEGACY ($LEGACY) ==="
    cat "$LLOG"
    if [ "$MR" -ne 0 ] || [ "$LR" -ne 0 ]; then
        echo "[cue] --both failed: modern=$MR legacy=$LR" >&2
        exit 1
    fi
    exit 0
fi

LAUNCHER="$1"; shift || { echo "Usage: $0 /path/to/game/Game.sh [testcase...] [options...]  (or $0 --both [testcase...])" >&2; exit 2; }

# Per-run isolation: copy the small game tree and fixture root into temp dirs
# so concurrent invocations (e.g. modern + legacy side by side) never share
# mutable state, and the committed test_game/ + fixtures stay pristine.  Only
# the read-only cue_lib source is shared (via the symlink in the mod section).
# An explicit RENPY_CUE_DIR seeds the fixture copy instead of the default.
XVPID=""
GAME="$(mktemp -d "${TMPDIR:-/tmp}/cue_testgame.XXXXXX")"
DATA="$(mktemp -d "${TMPDIR:-/tmp}/cue_testdata.XXXXXX")"
trap 'rm -rf "$GAME" "$DATA"; [ -n "$XVPID" ] && kill "$XVPID" 2>/dev/null' EXIT
cp -r "$ROOT/test_game/." "$GAME/"
cp -r "${RENPY_CUE_DIR:-$ROOT/tests/fixtures/data}/." "$DATA/"
# Dirty fixture sources (prior runs leave data/backups/video residue) must not
# seed the run; the mod's CueDatabase.open() recreates these subdirs at init.
rm -rf "$DATA/data" "$DATA/backups" "$DATA/video"
rm -rf "$GAME/game/saves"
export RENPY_CUE_DIR="$DATA"
TEMPLATES="$GAME/templates"

# A testcase that never yields (an interaction whose rebuild never completes)
# leaves the rpytest executor silent, so no test-level timeout fires and the
# engine hangs the whole CI job. Bound the engine process; when it fires, the
# normal failure path below dumps the partial log. Generous vs real runs.
CUE_ENGINE_TIMEOUT="${CUE_ENGINE_TIMEOUT:-600}"

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

# --- Wire in the mod. ---
# Copy cue_lib instead of symlinking it: the engine compiles .rpy -> .rpyc
# next to the source, so a symlink would write compiles into the shared source
# tree (stale rpyc masks source edits; concurrent engines corrupt each other's
# rpyc). A per-run copy keeps every compile isolated in the temp game dir.
MOD="$GAME/game/renpy_cue"
mkdir -p "$MOD"
rm -rf "$MOD/cue_lib"
cp -r "$ROOT/cue_lib" "$MOD/cue_lib"
find "$MOD/cue_lib" -name '*.rpyc' -delete

# Point saves + persistent at the per-run game/saves dir.  Without --savedir,
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
    [ -n "$NAMES" ] || { echo "[cue] no legacy testcases found" >&2; exit 2; }

    # --- Parallel workers ----------------------------------------------------
    # Each worker runs a slice of the suite in its own isolated GAME/DATA/saves
    # tree (concurrent engine processes can't share mutable state) against one
    # shared Xvfb display instead of a fresh server per boot. Workers=1 is the
    # old sequential behavior. CUE_LEGACY_WORKERS overrides the default.
    WORKERS="${CUE_LEGACY_WORKERS:-4}"
    case "$WORKERS" in
        *[!0-9]*|0) WORKERS=4 ;;
    esac
    [ "$WORKERS" -gt 8 ] && WORKERS=8

    # Shared Xvfb for parallel local runs. CI already wraps the invocation in
    # xvfb-run (DISPLAY inherited); workers=1 keeps the per-boot xvfb-run.
    if [ "$WORKERS" -gt 1 ] && [ "$HEADLESS" = "1" ] && [ -z "${CI:-}" ]; then
        if command -v Xvfb >/dev/null 2>&1; then
            export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"
            _d=99
            while [ -e "/tmp/.X${_d}-lock" ]; do
                _d=$((_d + 1))
                if [ "$_d" -ge 150 ]; then
                    echo "[cue] no free Xvfb display in 99-149" >&2
                    exit 2
                fi
            done
            Xvfb ":$((_d))" -screen 0 1280x800x24 >/dev/null 2>&1 &
            XVPID=$!
            export DISPLAY=":$((_d))"
            # Xvfb creates its lock/socket asynchronously -- wait for it so the
            # first engine's SDL connect doesn't race the server startup.
            _t=0
            while [ ! -e "/tmp/.X${_d}-lock" ]; do
                if ! kill -0 "$XVPID" 2>/dev/null; then
                    echo "[cue] Xvfb failed to start on :$((_d))" >&2
                    exit 2
                fi
                _t=$((_t + 1))
                [ "$_t" -ge 10 ] && break
                sleep 1
            done
            RUN_PREFIX=""
            echo "[cue] legacy: ${WORKERS} workers on shared Xvfb :$((_d))"
        else
            echo "[cue] parallel legacy needs Xvfb (install xvfb) -- running sequential" >&2
            WORKERS=1
        fi
    fi

    # One isolated tree + one slice of the suite per worker. Runs in a subshell
    # (backgrounded), so its globals/traps don't touch the parent.
    _run_legacy_worker() {
        _w="$1"
        _slice="$2"
        _run="$3"
        WGAME="$(mktemp -d "${TMPDIR:-/tmp}/cue_legacy_${_w}.XXXXXX")"
        WDATA="$(mktemp -d "${TMPDIR:-/tmp}/cue_legdata_${_w}.XXXXXX")"
        trap 'rm -rf "$WGAME" "$WDATA"' EXIT
        # Seed from the main path's already-prepared /tmp trees: cue_lib is a
        # real copy there, and /tmp avoids the concurrent-read race on the slow
        # Windows-mounted source FS that intermittently corrupts .rpy parses.
        cp -r "$GAME/." "$WGAME/"
        cp -r "$DATA/." "$WDATA/"
        # Dirty fixture sources (prior runs leave data/backups/video residue) must
        # not seed the run; CueDatabase.open() recreates these at init.
        rm -rf "$WDATA/data" "$WDATA/backups" "$WDATA/video"
        rm -rf "$WGAME/game/saves"
        export RENPY_CUE_DIR="$WDATA"
        cp "$TEMPLATES/testcases_legacy.rpy" "$WGAME/game/testcases.rpy"
        rm -f "$WGAME/game"/*.rpyc
        # The mod's debug log appends -- a fresh run must start empty.
        WMODE="$WGAME/game/renpy_cue"
        mkdir -p "$WMODE"
        rm -f "$WMODE/debug.log"
        # cue_lib arrives via the "$GAME" copy (a real dir, rpyc already cleared);
        # just in case the source was polluted, drop any stray compiles.
        find "$WMODE/cue_lib" -name '*.rpyc' -delete 2>/dev/null || true
        WSAVEDIR="$WGAME/game/saves"
        rc=0
        for _name in $_slice; do
            echo "[cue] running testcase: $_name (worker $_w)"
            rm -f "$WMODE/debug.log"
            if ! timeout "$CUE_ENGINE_TIMEOUT" $_run "$LAUNCHER" --savedir "$WSAVEDIR" "$WGAME" test "$_name"; then
                echo "[cue] worker $_w testcase FAILED: $_name" >&2
                if [ -f "$WMODE/debug.log" ]; then
                    echo "[cue] worker $_w renpy_cue/debug.log:" >&2
                    cat "$WMODE/debug.log" >&2
                fi
                rc=1
            fi
        done
        return "$rc"
    }

    # Round-robin the names across workers: each worker's slice keeps suite order
    # internally, and the boot-heavy cases overlap across workers.
    rc=0
    _pids=""
    w=1
    while [ "$w" -le "$WORKERS" ]; do
        _slice=""
        _i=0
        for name in $NAMES; do
            _i=$((_i + 1))
            if [ $((_i % WORKERS)) -eq $((w - 1)) ]; then
                _slice="$_slice $name"
            fi
        done
        if [ -n "$_slice" ]; then
            _run_legacy_worker "$w" "$_slice" "$RUN_PREFIX" &
            _pids="$_pids $!"
        fi
        w=$((w + 1))
    done
    for _p in $_pids; do
        if ! wait "$_p"; then
            rc=1
        fi
    done
    exit $rc
fi

# 8.x: one suite run. The test `exit` statement raises QuitException so the
# process exits 0 regardless of pass/fail -- parse the reporter summary.
LOG="$(mktemp -t cue_testcases.XXXXXX.log)"
timeout "$CUE_ENGINE_TIMEOUT" $RUN_PREFIX "$LAUNCHER" --savedir "$SAVEDIR" "$GAME" test "$@" > "$LOG" 2>&1 || true
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
