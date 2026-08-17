#!/bin/sh
# Usage: bin/coverage.sh
#
# Runs the pytest suite under coverage.py in the poetry venv and prints the
# line-coverage report for the cue_lib/ modules. Single source of truth for
# the headless-pytest coverage baseline -- the /test skill, CI, and manual
# spot-checks all measure the same way.
#
# The suite is fast (~5s), so coverage is always measured on a fresh run
# rather than merged into a stale .coverage data file.

if ! command -v poetry >/dev/null 2>&1; then
    echo "coverage: poetry not found on PATH" >&2
    exit 1
fi

poetry run coverage run -m pytest tests/ -q || exit $?

# _types.py is never executed at runtime (MYPY-only imports), so it would
# always report 0% -- exclude it along with the trivial package __init__.
poetry run coverage report -m --include="*/cue_lib/*" \
    --omit="*/cue_lib/__init__.py,*/cue_lib/_types.py"
