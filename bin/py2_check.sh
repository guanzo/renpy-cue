#!/bin/sh
# Usage: bin/py2_check.sh [SDK_DIR]
#   SDK_DIR defaults to .local/renpy-sdk/renpy-7.4.10-sdk (repo-relative).
#
# Python 2.7 (Ren'Py 7.x) is the base runtime requirement for cue_lib. pytest
# runs under py3 with a mock renpy, so it cannot catch py2-only breaks: py3.6+
# stdlib APIs used from runtime code (e.g. zipfile.ZipInfo.is_dir()) and any
# syntax py2 rejects. This gate:
#   1. py2-compiles every cue_lib/**/*.py under the bundled 7.4.10 interpreter,
#   2. boots `import cue_lib` with the test mock renpy on the path, and
#   3. runs targeted runtime smokes for pure-stdlib logic pytest cannot
#      py2-test (the smoke list is a spot-check for py2-only API gaps, not a
#      substitute for pytest).
# Exits 1 on any break. CI runs this on the 7.4.10 harness leg where the SDK
# exists; local dev runs it as part of the /lint gate.
#
# Note: the SDK's bundled python2.7 ignores PYTHONPATH (fixed sys.path), so
# the mock renpy dir is injected from inside the -c scripts.

ROOT="$(cd "$(dirname "$0")/.."; pwd)"
cd "$ROOT"

SDK="${1:-$ROOT/.local/renpy-sdk/renpy-7.4.10-sdk}"
case "$SDK" in
    /*) ;;
    *)  SDK="$ROOT/$SDK" ;;
esac

if [ ! -x "$SDK/lib/linux-x86_64/python" ]; then
    echo "[py2] FAIL: no 7.4.10 SDK python at $SDK/lib/linux-x86_64/python" >&2
    echo "[py2]       download/extract it to .local/ (see memory: renpy-local-sdks)" >&2
    exit 1
fi

PY="$SDK/lib/linux-x86_64/python"
export PYTHONHOME="$SDK"
status=0

echo "[py2] interpreter: $PY"

# --- 1. py2-compile every cue_lib module -----------------------------------
# _types.py is the one documented exception: TypedDict defs use py3 syntax
# because it is never imported at runtime (stubs + `if MYPY:` blocks only).
FILES="$(find cue_lib -name '*.py' ! -path 'cue_lib/_types.py')"
if [ -z "$FILES" ]; then
    echo "[py2] FAIL: no cue_lib .py files found" >&2
    exit 1
fi
if ! "$PY" -c "
import py_compile, sys
ok = True
for f in sys.argv[1:]:
    try:
        py_compile.compile(f, doraise=True)
    except Exception as err:
        ok = False
        print 'PY2 COMPILE FAIL: {0}: {1}'.format(f, err)
sys.exit(0 if ok else 1)
" $FILES; then
    status=1
else
    echo "[py2] compile: OK ($(printf '%s\n' "$FILES" | wc -l | tr -d ' ') modules)"
fi

# --- 2. boot import cue_lib under py2 --------------------------------------
if ! "$PY" -c "
import sys
sys.path.insert(0, 'tests/mock_renpy')
import cue_lib
print 'py2 boot OK'
"; then
    status=1
fi

# --- 3. targeted runtime smokes (py2-only API risk) -------------------------
if ! "$PY" -c "
import sys
sys.path.insert(0, 'tests/mock_renpy')
import os, tempfile, zipfile
from cue_lib.sharing.importer_io import _cue_extract_zip_to

def zip_with(entries):
    zpath = os.path.join(tempfile.mkdtemp(), 'p.zip')
    with zipfile.ZipFile(zpath, 'w') as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return zpath

# unwrap a single shared root dir (the SFX pack bootstrap path)
out = tempfile.mkdtemp()
n = _cue_extract_zip_to(zip_with([('wrap/a.ogg', 'a'), ('wrap/g1/b.ogg', 'b')]), out, unwrap_root=True)
assert n == 2, n
assert os.path.isfile(os.path.join(out, 'a.ogg'))
assert os.path.isfile(os.path.join(out, 'g1', 'b.ogg'))
assert not os.path.isdir(os.path.join(out, 'wrap'))

# mixed archive stays untouched even with unwrap_root=True
out2 = tempfile.mkdtemp()
n = _cue_extract_zip_to(zip_with([('a.ogg', 'a'), ('wrap/b.ogg', 'b')]), out2, unwrap_root=True)
assert n == 2 and os.path.isfile(os.path.join(out2, 'a.ogg')) and os.path.isfile(os.path.join(out2, 'wrap', 'b.ogg'))

# progress callback path (exercises the total-sum branch)
calls = []
_cue_extract_zip_to(zip_with([('wrap/a.ogg', 'a')]), tempfile.mkdtemp(), unwrap_root=True,
                    progress=lambda w, t: calls.append((w, t)))
assert calls and calls[-1][0] == calls[-1][1], calls

print 'py2 extract smokes OK'
"; then
    status=1
fi

if [ "$status" -eq 0 ]; then
    echo "[py2] CLEAN"
fi
exit "$status"
