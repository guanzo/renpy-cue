---
name: test
description: Run the test suite in the poetry venv and report results
---

# /test

Run the full test suite in the poetry venv and report the result. Run after
`/lint` whenever `cue_lib/` or `tests/` changed.

## Command

```bash
bin/test.sh
```

Runs `poetry run pytest tests/ -q` -- the same command CI invokes
(`bin/test.sh` is the single source of truth shared with the GitHub Actions
workflow, so the two can't drift apart). It exits through pytest's exit code.

**/test passes when `bin/test.sh` exits 0, every test passes, and nothing is
written into the repo root.**

`-q` prints a per-file progress line. If a test is failing, run the verbose
dump yourself (`poetry run pytest tests/ -q -x`, or drop `-q`) for the full
traceback.

## Expected output

A progress line, then a summary:

```
........................................................................ [ 41%]
........................................................................ [ 83%]
.............................                                            [100%]
173 passed in 2.13s
```

## On failure

Fix the failure, then re-run `/test` until green. Most failures are one of:

- **`ImportError` on a `renpy.*` symbol** -- a `cue_lib` module imports
  something the mock doesn't provide yet. Add a stub to the matching module
  under `tests/mock_renpy/renpy/` (mirroring the real runtime's package
  structure, `class X(object):` style), then re-run.
- **`renpy_cue/debug.log` appears in the repo root** -- a test re-enabled
  `_cue_log`. Keep the session-scoped `_silence_debug_log` fixture in
  `tests/conftest.py` intact: backup daemon threads write their log line
  after `save_marker()` returns, past per-test teardown.

## Changing a test (check-in required)

When a failure turns out to be in the test itself -- the assertion or fixture
encodes an expectation the code doesn't document -- do NOT edit the test
unilaterally. Treat the code as guilty first; investigate the failure, and if
the fix requires changing an existing test's assertions, expectations,
fixtures, or logic, check in with the user BEFORE editing. Explain the
failure, why the test (not the code) is wrong, and what the edit is. The user
decides whether to change the test, fix the code instead, or dig deeper.

Adding a brand-new test or a new mock stub does NOT need a check-in -- only
modifications to an existing test in response to a failure do.

## Coverage (optional)

```bash
poetry run coverage run -m pytest tests/ -q
poetry run coverage report -m --include="cue_lib/*" --omit="cue_lib/__init__.py,cue_lib/_types.py"
```

Coverage is informational -- do not gate on a percentage.
