#!/bin/sh
# Usage: bin/test.sh
#
# Runs the full pytest suite in the poetry venv and exits through pytest's exit
# code. This is the single source of truth for both callers -- the /test skill
# and the GitHub Actions workflow invoke this script rather than inlining
# `poetry run pytest` so the command can't drift apart.

if ! command -v poetry >/dev/null 2>&1; then
    echo "test: poetry not found on PATH" >&2
    exit 1
fi

exec poetry run pytest tests/ -q
