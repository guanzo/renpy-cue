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
    # Pick by version, not by parser heuristics: an 8.x whose testparser
    # predates the modern DSL would otherwise be classified legacy and shadow
    # the real 7.x SDK (8.1.3 steals the legacy slot from 7.4.10).  Newest
    # within each major wins, so the last write is the highest version seen.
    for d in "$ROOT"/.local/renpy-sdk/renpy-*-sdk; do
        [ -d "$d" ] || continue
        ver="${d##*renpy-}"
        ver="${ver%-sdk}"
        case "$ver" in
            7.*) LEGACY="$d/renpy.sh" ;;
            8.*) MODERN="$d/renpy.sh" ;;
        esac
    done
    if [ -z "$MODERN" ] || [ -z "$LEGACY" ]; then
        echo "need both a 7.x and an 8.x renpy-*-sdk under .local/renpy-sdk/ for --both" >&2
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
GAME="$(mktemp -d "${TMPDIR:-/tmp}/cue_testgame.XXXXXX")"
DATA="$(mktemp -d "${TMPDIR:-/tmp}/cue_testdata.XXXXXX")"
trap 'rm -rf "$GAME" "$DATA"' EXIT
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

# Skip the startup GL performance test: it warns a *user* about a slow GPU,
# which has no meaning for an automated run. It also hangs the 7.2.x leg --
# under Xvfb that SDK renders just under the 15fps pass bar, so __GLTest
# never gets 5 frames within its window and the startup interact spins
# forever, ~5min per engine boot (2h40m for the CI leg). RENPY_PERFORMANCE_TEST
# short-circuits before any interact; 7.4+ happens to clear the bar anyway.
export RENPY_PERFORMANCE_TEST=0

# --- Resolve the launcher's game root and the test-language generation. ---
# The split is DSL generation, not Python generation: the modern grammar
# (until eval, timeout, keysym) exists only in the 8.5+ test parser; 7.x and
# 8.0-8.4 share the old grammar the legacy template uses. Probe the parser
# directly rather than keying off a version literal.
LAUNCHER_DIR="$(cd "$(dirname "$LAUNCHER")" && pwd)"
DSL="${CUE_DSL:-}"
if [ -z "$DSL" ]; then
    if grep -q 'def parse_until' "$LAUNCHER_DIR/renpy/test/testparser.py" 2>/dev/null; then
        DSL="modern"
    else
        DSL="legacy"
    fi
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

# 7.2.x rejects two idioms the modern screen parser accepts (multi-line
# statement calls, Transform xsize/ysize). Rewrite the per-run copy so the
# sub-7.4 leg boots; the repo source stays on the modern form.
if [ "$DSL" = "legacy" ] && grep -q 'version_tuple = (7, [0-3]' "$LAUNCHER_DIR/renpy/__init__.py"; then
    python3 "$ROOT/bin/transform_legacy_screens.py" "$MOD/cue_lib"
fi

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
#
# A worker that dies on a signal (dash drops EXIT traps on signal death) or a
# run that is SIGKILLed leaves its Xvfb behind, reparented to init, and
# nothing reaps it -- servers accumulate across interrupted runs. Sweep before
# launching: kill any Xvfb whose ancestry has no live test_harness.sh. A
# concurrent run's servers always have one, so they're never touched. Skipped
# under CI because the whole invocation runs inside CI's own xvfb-run, whose
# Xvfb has no harness ancestor and must be spared.
_sweep_orphan_xvfb() {
    _has_harness_ancestor() {
        _p=$1
        while [ "$_p" -gt 1 ]; do
            case "$(tr '\0' ' ' < "/proc/$_p/cmdline" 2>/dev/null)" in
                *test_harness.sh*) return 0 ;;
            esac
            _p=$(awk '{print $4}' "/proc/$_p/stat" 2>/dev/null)
            [ -n "$_p" ] && [ "$_p" -gt 1 ] || break
        done
        return 1
    }
    for _xvp in $(pgrep -x Xvfb 2>/dev/null); do
        if ! _has_harness_ancestor "$_xvp"; then
            echo "[cue] sweeping orphaned Xvfb (pid $_xvp)" >&2
            kill "$_xvp" 2>/dev/null || true
        fi
    done
    # xvfb-run auth temp dirs outlive their server the same way; drop stale ones.
    for _d in /tmp/xvfb-run.*; do
        [ -e "$_d" ] || continue
        _inuse=0
        for _xvp in $(pgrep -x Xvfb 2>/dev/null); do
            if tr '\0' ' ' < "/proc/$_xvp/cmdline" 2>/dev/null | grep -q -- "-auth $_d/"; then
                _inuse=1
                break
            fi
        done
        [ "$_inuse" = "0" ] && rm -rf "$_d"
    done
    return 0
}

HEADLESS="${RENPY_HEADLESS:-1}"
RUN_PREFIX=""
if [ "$HEADLESS" = "1" ] && [ -z "${CI:-}" ]; then
    _sweep_orphan_xvfb
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
    # tree (concurrent engine processes can't share mutable state) and its own
    # Xvfb display. Sharing one display is the bug: 7.4.10 drops synthetic
    # test-mouse clicks when engines run concurrently on a single X server
    # (pointer position, focus, and window stacking are display-global, and the
    # overlay's async reflow races that state) -- instrumented, 27/27 clicks
    # posted, none reached the button. A display per worker reuses one server
    # across the whole slice, so isolation costs nothing extra.
    # CUE_LEGACY_WORKERS overrides the default. Default is one worker per
    # vCPU, capped at 8 -- self-tunes for dev boxes and CI runners and never
    # oversubscribes.
    WORKERS="${CUE_LEGACY_WORKERS:-$(nproc 2>/dev/null || echo 1)}"
    case "$WORKERS" in
        *[!0-9]*|0|"") WORKERS=1 ;;
    esac
    [ "$WORKERS" -gt 8 ] && WORKERS=8

    # Parallel workers each start their own Xvfb (isolated display) when
    # headless. Workers=1 keeps the per-boot xvfb-run from the headless setup
    # above; CI (wrapped in a single xvfb-run) stays at workers=1.
    XVFB_PER_WORKER=0
    if [ "$WORKERS" -gt 1 ] && [ "$HEADLESS" = "1" ]; then
        if command -v Xvfb >/dev/null 2>&1; then
            export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"
            XVFB_PER_WORKER=1
            RUN_PREFIX=""   # each worker sets its own DISPLAY
            echo "[cue] legacy: ${WORKERS} workers, one Xvfb per worker"
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
        _xvfb="$4"
        WGAME="$(mktemp -d "${TMPDIR:-/tmp}/cue_legacy_${_w}.XXXXXX")"
        WDATA="$(mktemp -d "${TMPDIR:-/tmp}/cue_legdata_${_w}.XXXXXX")"
        # Own Xvfb per worker: -displayfd picks a free display atomically (no
        # cross-worker race on the pick), and the server is reused across the
        # slice. Serial/CI workers skip this and inherit the ambient display.
        XVPID=""
        _claim=""
        if [ "$_xvfb" = "1" ]; then
            # A mkdir claim makes the display-number pick atomic across workers
            # (two workers must not choose the same :NN before either starts a
            # server); once Xvfb's /tmp/.X*-lock exists, that guards the display.
            _d=99
            while :; do
                if [ ! -e "/tmp/.X${_d}-lock" ] && mkdir "/tmp/.cue_xvfb_claim_${_d}" 2>/dev/null; then
                    break
                fi
                _d=$((_d + 1))
                if [ "$_d" -ge 150 ]; then
                    echo "[cue] no free Xvfb display in 99-149" >&2
                    return 1
                fi
            done
            _claim="/tmp/.cue_xvfb_claim_${_d}"
            Xvfb ":$((_d))" -screen 0 1280x800x24 -ac >/dev/null 2>&1 &
            XVPID=$!
            export DISPLAY=":$((_d))"
            # Xvfb creates its lock/socket asynchronously -- wait for it so the
            # first engine's SDL connect doesn't race the server startup.
            _t=0
            while [ ! -e "/tmp/.X${_d}-lock" ]; do
                if ! kill -0 "$XVPID" 2>/dev/null; then
                    echo "[cue] worker $_w Xvfb failed to start on :$((_d))" >&2
                    rmdir "$_claim" 2>/dev/null
                    return 1
                fi
                _t=$((_t + 1))
                [ "$_t" -ge 10 ] && break
                sleep 1
            done
            rmdir "$_claim" 2>/dev/null
        fi
        # `set -e` is inherited: a trap whose final command fails (rmdir of an
        # already-removed claim, kill of a dead pid) overrides the subshell's
        # exit status, so a passing worker would exit 1. `|| true` per chain
        # keeps the trap exit status 0.
        # EXIT alone is not enough: dash drops EXIT traps when the subshell
        # dies on a signal, orphaning this worker's Xvfb. Trap the signals too
        # -- dash does run those -- and exit after cleanup so a killed worker
        # doesn't just continue its slice. The 0 trap re-runs the same
        # idempotent cleanup when the `exit` below triggers it.
        _worker_cleanup() {
            rm -rf "$WGAME" "$WDATA"
            [ -n "$_claim" ] && rmdir "$_claim" 2>/dev/null || true
            [ -n "$XVPID" ] && kill "$XVPID" 2>/dev/null || true
        }
        # The EXIT trap's final status wins in bash 5.1 (the runner's), so a bare
        # `_worker_cleanup` tail (which exits 0 via `|| true`) would mask a failing
        # worker's nonzero rc. Re-raise rc explicitly so failures reach the parent.
        trap '_worker_cleanup; exit "$rc"' 0
        trap '_worker_cleanup; exit 1' 1 2 15
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
        _passed=0
        _failed=0
        for _name in $_slice; do
            echo "[cue] running testcase: $_name (worker $_w)"
            # The legacy engines intermittently die under the Xvfb contention
            # of a fresh parallel worker wave, two ways:
            #   - 7.2.x: "Could not set video mode" at its first interact
            #   - 8.1.3: native SIGSEGV (timeout exits 139, no traceback; the
            #     crashing testcase differs run to run)
            # Both are transient engine failures, not testcase failures -- the
            # same testcase boots fine moments later. Retry only those two
            # signatures (a hang times out as 124, a real assertion differs),
            # resetting mutable state per attempt.
            _attempt=1
            _max="${CUE_LEGACY_RETRIES:-2}"
            _engine_rc=0
            while :; do
                rm -f "$WMODE/debug.log"
                # Each testcase boots a fresh engine, but the data store is
                # shared across testcases on this worker. A store-writing
                # testcase leaks disk state (e.g. a leftover MULTI speed
                # sequence after a pop that only removes in-memory) that a
                # later plain-video testcase then resolves into an absolute
                # play path and fails on. Reset the mutable data tree +
                # persistent before every launch (and retry).
                rm -rf "$WDATA/data" "$WDATA/backups" "$WDATA/video" "$WGAME/game/saves"
                OUT="$(mktemp -t cue_legacy_${_w}.XXXXXX)"
                if timeout "$CUE_ENGINE_TIMEOUT" $_run "$LAUNCHER" --savedir "$WSAVEDIR" "$WGAME" test "$_name" >"$OUT" 2>&1; then
                    _engine_rc=0
                    cat "$OUT"
                    rm -f "$OUT"
                    break
                else
                    _engine_rc=$?
                    _retryable=0
                    _reason=""
                    if [ "$_engine_rc" -ne 124 ] && [ "$_attempt" -lt "$_max" ]; then
                        if grep -q "Could not set video mode" "$OUT"; then
                            _retryable=1
                            _reason="video-mode boot flake"
                        elif [ "$_engine_rc" -eq 139 ]; then
                            _retryable=1
                            _reason="native segfault"
                        fi
                    fi
                    cat "$OUT"
                    rm -f "$OUT"
                    if [ "$_retryable" -eq 1 ]; then
                        echo "[cue] worker $_w testcase $_name: $_reason, retry $_attempt" >&2
                        _attempt=$((_attempt + 1))
                        continue
                    fi
                    break
                fi
            done
            if [ "$_engine_rc" -eq 0 ]; then
                _passed=$((_passed + 1))
                echo "[cue] worker $_w testcase PASSED: $_name"
            else
                _failed=$((_failed + 1))
                echo "[cue] worker $_w testcase FAILED: $_name" >&2
                if [ -f "$WMODE/debug.log" ]; then
                    echo "[cue] worker $_w renpy_cue/debug.log:" >&2
                    cat "$WMODE/debug.log" >&2
                fi
                if [ -f "$WMODE/error.log" ]; then
                    echo "[cue] worker $_w renpy_cue/error.log:" >&2
                    cat "$WMODE/error.log" >&2
                fi
                rc=1
            fi
        done
        echo "[cue] worker $_w: $_passed passed, $_failed failed"
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
            _run_legacy_worker "$w" "$_slice" "$RUN_PREFIX" "$XVFB_PER_WORKER" &
            _pids="$_pids $!"
        fi
        w=$((w + 1))
    done
    for _p in $_pids; do
        if ! wait "$_p"; then
            rc=1
        fi
    done
    if [ "$rc" -eq 0 ]; then
        echo "[cue] Status: PASSED"
    else
        echo "[cue] Status: FAILED" >&2
    fi
    exit $rc
fi

# 8.x: one suite run. On the pinned 8.x SDKs the engine exits 0 on pass and
# nonzero on a failing testcase; the PASSED marker stays as a backstop for
# SDKs that always exit 0. A 124 exit is the timeout firing (a hang -- no
# summary, indistinguishable from a crash by the log alone).
LOG="$(mktemp -t cue_testcases.XXXXXX.log)"
if timeout "$CUE_ENGINE_TIMEOUT" $RUN_PREFIX "$LAUNCHER" --savedir "$SAVEDIR" "$GAME" test "$@" > "$LOG" 2>&1; then
    _rc=0
else
    _rc=$?
fi
cat "$LOG"

if [ "$_rc" -eq 124 ]; then
    echo "[cue] engine timed out after ${CUE_ENGINE_TIMEOUT}s -- hung (no summary)" >&2
    rm -f "$LOG"
    exit 1
fi

# rpytest colorizes the status line (Status: <esc[32m>PASSED), so match the
# bare words rather than the contiguous literal. `.*` spans the escape codes.
if [ "$_rc" -eq 0 ] && grep -qE "Status:.*PASSED" "$LOG"; then
    rm -f "$LOG"
    exit 0
fi

echo "[cue] test run did not pass (engine exit $_rc, see summary above)" >&2
if [ -f "$MOD/debug.log" ]; then
    echo "[cue] renpy_cue/debug.log:" >&2
    cat "$MOD/debug.log" >&2
fi
rm -f "$LOG"
exit 1
