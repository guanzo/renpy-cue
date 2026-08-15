#!/bin/sh
# Usage: bin/lint.sh
#
# Runs pyright + the 120-char line-length check on cue_lib/ and tests/ and
# reports ALL diagnostics. Exits 1 if any diagnostic or line-length violation
# is found; exits 0 and prints "CLEAN" otherwise.
#
# This is the single source of truth for both callers -- the /lint skill and
# the GitHub Actions workflow invoke this script rather than inlining the
# commands, so the checks can't drift apart. It deliberately exits nonzero on
# findings (unlike bare pyright/awk, which always exit 0) so CI can fail a
# job; the skill interprets the same output.

status=0

# --- 1. pyright ---
if ! command -v pyright >/dev/null 2>&1; then
    echo "lint: pyright not found on PATH" >&2
    exit 1
fi

PYRIGHT_JSON="$(pyright cue_lib/ tests/ --outputjson 2>/dev/null)"
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

# --- 2. line length (120 chars) ---
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

if [ "$status" -eq 0 ]; then
    echo "CLEAN"
fi
exit "$status"
