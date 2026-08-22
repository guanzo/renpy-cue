---
name: test-harness
description: Run the Ren'Py engine harness (real engine) on both SDK generations concurrently
---

# /test-harness

Run the engine harness. pytest runs against mock Ren'Py, so it cannot exercise
screen rendering, store-bridge names, or engine-driven behavior -- those live
as testcases that boot a real Ren'Py game (`test_game/`) under both SDK
generations. Run this after changing `cue_lib/ui/**` or bridge code in
`cue_z.rpy` -- the paths pytest can't reach. For pure logic changes, `/test`
(pytest) is the fast gate.

## Command

```bash
bin/test_harness.sh --both
```

Runs the modern (8.x) and legacy (7.x) suites **concurrently**, each in its
own temp dirs (per-run isolation -- they never share mutable state). SDKs are
discovered under `.local/` (`renpy-8.5.3-sdk`, `renpy-7.4.10-sdk`). Pass a
testcase name to filter both runs:

```bash
bin/test_harness.sh --both pages_render_data
```

- Modern takes exactly one filter name; legacy honors several.
- Modern pass/fail reads the `[rpytest] Status: PASSED` line. Legacy fails
  via `renpy.quit(status=1)` per testcase.
- Full modern suite is ~45s. Full legacy suite is 44 testcases x one engine
  boot each (~15 min); wall-clock is the slower of the two.

## Single-SDK runs

```bash
bin/test_harness.sh .local/renpy-8.5.3-sdk/renpy.sh                          # modern
bin/test_harness.sh .local/renpy-7.4.10-sdk/renpy.sh pages_render_data       # legacy
```

Headless by default via xvfb; `RENPY_HEADLESS=0` to show the window.

## Testcase layout

- `test_game/templates/testcases_modern.rpy` -- 8.x `testsuite`/`testcase` DSL.
- `test_game/templates/testcases_legacy.rpy` -- 7.x `testcase` DSL.
- The active `game/testcases.rpy` is materialized per-SDK from the matching
  template. Behavior that must hold across generations belongs in BOTH.

## Gotchas

- Legacy renders don't re-render after `_cue_set_page` until the next
  interaction -- follow it with `pause N`.
- A screen render error fails the interaction (and the testcase). A testcase
  that renders a page under seeded data is what catches a missing store-bridge
  name (`NameError` only fires when the screen renders with data present).
