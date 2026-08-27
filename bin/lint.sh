#!/bin/sh
# Usage: bin/lint.sh
#
# Runs four checks and reports ALL findings:
#   1. pyright on cue_lib/
#   2. ruff format --check on cue_lib/ and tests/ (the deterministic
#      formatter enforcing the project's wrap rules; .rpy is not parseable
#      by ruff, so its wrap rules stay manual)
#   3. the 120-char line-length check on cue_lib/ and tests/
#   4. py2 trailing-comma guard on cue_lib/ (see below)
# Exits 1 if any finding; exits 0 and prints "CLEAN" otherwise.
#
# tests/ is deliberately left out of the pyright pass: the test suite is
# white-box (pokes private seams, injects fakes, patches module aliases), so
# strict type-checking against the .pyi public contract produces ~150 false
# positives. The ruff and 120-char checks still cover tests/.
#
# This is the single source of truth for both callers -- the /lint skill and
# the GitHub Actions workflow invoke this script rather than inlining the
# commands, so the checks can't drift apart. It deliberately exits nonzero on
# findings (unlike bare pyright/awk, which always exit 0) so CI can fail a
# job; the skill interprets the same output.

ROOT="$(cd "$(dirname "$0")/.."; pwd)"
status=0

# --- 1. pyright ---
if ! command -v pyright >/dev/null 2>&1; then
    echo "lint: pyright not found on PATH" >&2
    exit 1
fi

PYRIGHT_JSON="$(pyright cue_lib/ --outputjson 2>/dev/null)"
if [ -n "$PYRIGHT_JSON" ]; then
    PYRIGHT_OUT="$(printf '%s\n' "$PYRIGHT_JSON" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(2)   # unparseable pyright output -- surface it below

lines = []
for diag in d.get("generalDiagnostics", []):
    lines.append("{}:{}: {}".format(
        diag.get("file", "?"),
        diag.get("range", {}).get("start", {}).get("line", "?"),
        diag.get("message", "")))
for f in d.get("diagnostics", []):
    for diag in f.get("diagnostics", []):
        lines.append("{}:{}: {}".format(
            f.get("file", "?"),
            diag.get("range", {}).get("start", {}).get("line", "?"),
            diag.get("message", "")))

if lines:
    print("\n".join(lines))
sys.exit(1 if lines else 0)
')"
    rc=$?
    if [ "$rc" -eq 2 ]; then
        echo "lint: could not parse pyright output" >&2
        printf '%s\n' "$PYRIGHT_JSON" | head -n 20 >&2
        status=1
    elif [ "$rc" -ne 0 ]; then
        printf '%s\n' "$PYRIGHT_OUT"
        status=1
    fi
fi

# --- 2. ruff format ---
# ruff is a poetry dependency and the venv is not auto-activated (no direnv;
# the poetry venv is cache-path locally, in-project only in CI), so a bare
# `ruff` may not resolve in a non-interactive shell. Fall back to the poetry
# venv's bin exactly like ci.yml does. No-op when ruff is already on PATH.
if ! command -v ruff >/dev/null 2>&1 && command -v poetry >/dev/null 2>&1; then
    VENV_BIN="$(poetry env info -p 2>/dev/null)/bin"
    [ -x "$VENV_BIN/ruff" ] && export PATH="$VENV_BIN:$PATH"
fi
# The deterministic formatter (config in pyproject.toml: line-length=120,
# quote-style=preserve). Ruff parses .py/.pyi only; .rpy is covered by check
# 3's awk pass and the manual wrap rules.
if ! command -v ruff >/dev/null 2>&1; then
    echo "lint: ruff not found on PATH" >&2
    exit 1
fi

RUFF_OUT="$(ruff format --check cue_lib tests 2>&1)"
if [ $? -ne 0 ]; then
    printf '%s\n' "$RUFF_OUT"
    status=1
fi

# --- 3. line length (120 chars) ---
# `# type:` comment lines are exempt -- a comment cannot be wrapped. Lines
# carrying a `# pyright: ignore` comment are exempt too -- see the lint skill.
LONG_LINES="$(find cue_lib tests \( -name '*.py' -o -name '*.rpy' -o -name '*.pyi' \) -print0 \
    | xargs -0 awk 'length($0) > 120 && $0 !~ /^[[:space:]]*# type:/ \
        && $0 !~ /# pyright: ignore/ \
        {printf "%s:%d: %d chars\n", FILENAME, FNR, length($0)}')"
if [ -n "$LONG_LINES" ]; then
    printf '%s\n' "$LONG_LINES"
    status=1
fi

# --- 4. py2 trailing commas (cue_lib runtime only) ---
# Ruff adds a trailing comma to any width-split def ending in *args/**kwargs
# -- py3-only syntax, a SyntaxError under Ren'Py 7.x (Python 2.7). Those defs
# must be wrapped in `# fmt: off` / `# fmt: on` and hand-written without the
# comma (precedent: popper.py CuePopper.__init__). Catches new breakers fast,
# before the legacy harness (one engine boot per testcase, ~15 min) does.
PY2_COMMA="$(grep -rnE '^\s*\*{1,2}[A-Za-z_][A-Za-z0-9_]*,\s*(#.*)?$' cue_lib --include='*.py' || true)"
if [ -n "$PY2_COMMA" ]; then
    printf '%s\n' "$PY2_COMMA"
    echo "lint: trailing comma after *args/**kwargs is a SyntaxError under Python 2.7; wrap the def in # fmt: off / # fmt: on and drop the comma" >&2
    status=1
fi

# --- 5. Python 2.7 compatibility (cue_lib runtime) ---
# pytest runs under py3, so it cannot catch py2-only breaks: py3.6+ stdlib
# APIs (e.g. zipfile.ZipInfo.is_dir) and py2-invalid syntax. bin/py2_check.sh
# compiles every cue_lib module, boots import cue_lib, and runs targeted
# smokes under the bundled 7.4.10 interpreter. CI runs it on the 7.4.10
# harness leg; here it runs when the SDK is present locally and is skipped
# loudly otherwise.
if [ -x "$ROOT/.local/renpy-7.4.10-sdk/lib/linux-x86_64/python" ]; then
    if ! bash "$ROOT/bin/py2_check.sh"; then
        status=1
    fi
else
    echo "lint: py2 check skipped (no .local/renpy-7.4.10-sdk)"
fi

if [ "$status" -eq 0 ]; then
    echo "CLEAN"
fi
exit "$status"
