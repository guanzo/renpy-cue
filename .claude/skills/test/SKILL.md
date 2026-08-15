---
name: test
description: Run the test suite in the poetry venv and report results
---

# /test

Run the full test suite in the poetry venv and report the result. Run after
`/lint` whenever `cue_lib/` or `tests/` changed.

## Command

```bash
poetry run pytest tests/ -q
```

`-q` prints a per-file progress line. Drop `-q` for the verbose failure dump
when a test is failing.

**/test passes when every test passes and nothing is written into the repo
root.**

## Expected output

A progress line, then a summary:

```
........................................................................ [ 85%]
............                                                             [100%]
84 passed in 1.03s
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
