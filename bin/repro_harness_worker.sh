#!/bin/sh
set -e
echo "BASH=$BASH_VERSION"

_worker_cleanup() {
    rm -rf "/tmp/nonexistent_xyz"
    [ -n "$_claim" ] && rmdir "$_claim" 2>/dev/null || true
    [ -n "$XVPID" ] && kill "$XVPID" 2>/dev/null || true
    exit "$rc"
}
trap '_worker_cleanup' EXIT
trap '_worker_cleanup; exit 1' 1 2 15

_worker() {
    trap '_worker_cleanup' 0
    trap '_worker_cleanup; exit 1' 1 2 15
    XVPID=""
    _claim=""
    rc=0
    _failed=0
    for _name in a b c; do
        if ! timeout 10 false; then
            _failed=$((_failed + 1))
            echo "testcase FAILED: $_name" >&2
            rc=1
        fi
    done
    echo "worker: 0 passed, $_failed failed"
    return "$rc"
}

rc=0
_pids=""
_worker &
_pids="$_pids $!"
for _p in $_pids; do
    if ! wait "$_p"; then rc=1; fi
done
if [ "$rc" -eq 0 ]; then echo "Status: PASSED"; else echo "Status: FAILED"; fi
exit $rc
