# Ren'Py Compatibility

Code must support Ren'Py 7.4+ (both 7.x and 8.x). 7.2–7.3.x is best effort only: compatibility fixes there are limited to simple workarounds or the feature is disabled.

## Python Restrictions

Ren'Py 7.x uses Python 2.7. In runtime `.py` files:

* No f-strings; use `.format()` or `%`.
* No type hints or `from __future__ import annotations`.
* No `@` operator.
* No non-ASCII characters.
* All classes inherit from `object` or another new-style class.

## Version-Specific APIs

Do not use:

* Character callback kwargs `what`/`start`/`end` -- Ren'Py 8.2+ only. Use `store._last_say_what`.
* `renpy.get_displayable()` with `screen=`/`id=` kwargs.
* `<from N>` movie channel syntax -- it always restarts at 0.

## Screen Language

* Wrap inline conditional expressions in parentheses:

  ```python
  property ("#446644" if cond else "#444444")
  ```
* Also wrap comparisons used as screen arguments:

  ```python
  use foo_btn(label, (_x == some_val), action)
  ```
* `VariableInputValue()` does not support dotted paths. Use `_CueFieldValue()` for paths such as `"_cue.foo.bar"`.

## Safe APIs

Safe across supported versions:

* `store._last_say_what`, `store._last_say_who`
* `renpy.audio.music.get_pos()`, `get_duration()`, `is_playing()`, `get_playing()`
* `set_pause()`, `set_volume()`, `register_channel()`, `channel_defined()`
* `renpy.get_showing_tags()`, `renpy.showing()`, `renpy.list_files()`
* `config.overlay_screens`, `config.all_character_callbacks`, `config.after_load_callbacks`
* `config.developer`, `config.console`
* `renpy.show_screen()` / `hide_screen()` with `_layer=`
* `renpy.restart_interaction()`
* `renpy.add_layer()`

In `.py` files, use `renpy.audio.music`, not `renpy.music`. The latter is a runtime alias unavailable during early initialization.

# Text Escaping

Use `etext`, not `text`, for external or untrusted strings: file/folder names, game dialogue, ffmpeg output, HTTP responses, URLs, and user input.

Use `text` only for deliberate Ren'Py tags or interpolation.

For non-`text` renderers (`textbutton`, `Text()`, `Txt()`, tooltips), call `_cue_escape_text()` directly. Use `brackets=False` when `substitute=False`.

Never escape the same value twice.

# Platform Gotchas

## File Replacement

`os.rename()` does not overwrite existing files on Windows.

For overwrite semantics, use `_cue_replace_file()` from `cue_lib/util.py`. When rewriting a file:

1. Write to a temporary file.
2. Call `_cue_replace_file(tmp, final)`.

# Naming

Because `cue_z.rpy` exposes names into Ren'Py's flat store namespace:

* Module functions: `_cue_` prefix.
* Module classes: `Cue` prefix.
* Singleton: `_cue`.
* `.py` imports: `import foo as _foo`.

Function-local variables need no prefix.

Boolean names must begin with `is_`, `has_`, `can_`, `did_`, `was_`, `should_`, or `will_`.

# UI Language

User-facing copy uses these words deliberately. Choose by what you're naming:

| UI word | Means | Code term |
| --- | --- | --- |
| **Scene** | a playable gallery entry (a replay label that has markers) | `replay` |
| **Shot** | the image/video on screen right now | `context` (video/image) |
| **Marker** | editable per-context data | `marker` |
| **Video / Image / Dialogue / Loop** | the four "Target" pools | `CueContextType` |
| **Replay** | Ren'Py's playback machinery | `replay` (keep in code) |
| **Target** | which pool a marker belongs to | `context` / `ctx` |

Rules:

* "context" never appears in UI copy — say "Target" or the four pool names.
* "replay" stays in copy only where it names the machinery ("Customizing Music is only fully supported in replays", "Preview import and start replay").
* "Copy current scene markers" keeps "scene" — it names the markers of a scene, not the visual.

# Constants

Use a `CUE_` constant when the value:

* Is duplicated in 2+ places that could silently drift out of sync.
* Is a magic literal whose meaning isn't self-evident at the call site (a tolerance, pixel gap, channel count).
* Is a contract others depend on (format version, filename, shared-config key, a default callers may override).

Inline the literal when it is single-use and self-explanatory (`"imports"`, `"exports"`, a 5px offset), or a local tuning value (retry count, sleep delay, layout pixel) whose number is the spec.

Then place it by consumer count:

| Situation                                     | Location                                                            |
| --------------------------------------------- | ------------------------------------------------------------------- |
| Referenced in 2+ files                        | `constants.py`, mirrored in `constants.pyi` with `Final`            |
| Referenced once, used several times in module | Module-level `CUE_` constant in the owning module, mirrored in its `.pyi` |
| Single-use, self-explanatory                  | Inline the literal; no constant                                     |

`cue_z.rpy` bridge imports exist only for names `.rpy` screens actually consume. Test assertions and stub re-exports are not consumers.

## Enum Classes

For discrete behavior values, use flat classes inheriting from `object`; do not use Python's `enum` module.

Bridge enums into the store through `cue_z.rpy` when screens need them.

# Code Organization

* Before writing a new function or module, search the codebase for existing
  logic that already does the job and reuse it. Add a new helper only when no existing one
  fits.
* Encapsulate substantial features in classes that own their state and logic.
* Prefer `_cue.feature = FeatureManager()` over scattered state and global helpers.
* Put substantial standalone classes in their own `cue_lib/*.py` file.
* Screen code and styles belong in `cue_lib/ui/*.rpy`.
* Manager classes handle state, logic, and screen hooks.
* `cue_z.rpy` contains bootstrap and bridging code; other source `.rpy` files do not.
* `Function()` actions can only reference stable module-level objects. Managers should normally be reachable through `_cue`.

## Screen Style Groups

For screens that render displayables, the first line must be:

```renpy
style_group "cue"
```

Follow it with a blank line.

Screens containing only `use`, `key`, or `timer` statements omit it.

Do not explicitly specify default `cue_*` styles inside a `style_group`. Python-created displayables still need explicit styles.

# Rollback

* `_cue` is a module-level `NoRollback()` instance. Never reassign it; mutate its attributes.
* State in `cue_lib/*.py` modules is not tracked by Ren'Py rollback.
* `.rpy` uses Ren'Py's revertable collections; `.py` uses normal builtins.
* Prefer duck typing over `isinstance()` when checking collection-like values, since `list` may be shadowed by `RevertableList`.

# Persistent vs Shared Config

Use:

* `persistent` for per-game settings. This is the default.
* Shared JSON config only for settings that must follow the user across games.

Shared config is accessed through:

```python
_cue.db.load_shared_config()
_cue.db.update_shared_config()
```

# Tests

New logic should follow TDD:

1. Write a failing pytest.
2. Implement the minimum code to pass.
3. Refactor under test coverage.

Use the harness only when pytest cannot express the behavior:

* Pure logic/state transitions -> pytest.
* Screen, rendering, or engine-driven behavior -> testcase harness.

Rules:

* New `cue_lib/*.py` logic ships with tests.
* Do not reduce total `cue_lib` coverage without a one-line note.
* Before committing, run `ruff format cue_lib tests` on `.py`/`.pyi`, `/lint` must print `CLEAN`.
* `python3 -m pytest tests/ -q` must pass.

Harness tests requiring both engine generations belong in both:

* `test_game/templates/testcases_modern.rpy` -- 8.x
* `test_game/templates/testcases_legacy.rpy` -- 7.x

The active `testcases.rpy` is generated per SDK.

Harness runs are headless by default. Set `RENPY_HEADLESS=0` to show the game window.

# Type Stubs

* All Pylance/Pyright configuration belongs in `pyrightconfig.json`.
* Do not add `python.analysis.*` settings to `.vscode/settings.json`.
* `typings/renpy/` contains Ren'Py runtime stubs.
* `cue_lib/*.pyi` contains stubs for Cue modules.
* `cue_lib/_types.py` is the single source of truth for TypedDict definitions.

`_types.py` may use modern Python syntax because it is never imported at runtime.

## After Editing

After changing `cue_lib/*.py`:

* Update the corresponding `.pyi` if its public API changed.
* Run `ruff format cue_lib tests` on `.py`/`.pyi`, `/lint`, then `/test`, then `/test-harness`.

After adding a manager:

* Wire it into the `cue_z.rpy` `init -900` block.
* Add its import and `_cue` attribute to `state.pyi`.

After adding or changing a TypedDict:

* Update `cue_lib/_types.py`.
* Do not duplicate the definition in `.pyi` files.

# Self-File Type Information

Pyright does not use a module's `.pyi` while analyzing that module's own `.py` file.

Runtime `.py` files cannot use inline annotations, so use PEP 484 type comments.

For TypedDict names, add a dead `MYPY` guard after imports:

```python
MYPY = False

if MYPY:
    from typing import Optional
    from cue_lib._types import PoolDict, MarkerEntry
```

Then annotate signatures with type comments:

```python
def resolve_pool(self, pool):
    # type: (PoolDict) -> ResolvedPool
```

Use this for public functions whose `.pyi` signatures reference TypedDicts. Built-in types do not require imports.

`_types.py` is:

* Never imported at runtime.
* Imported by `.pyi` files and `if MYPY:` blocks only.
* The single canonical definition for each TypedDict.
* Located at `cue_lib/_types.py`.

# Commit Convention

Use Conventional Commits. Prefix a commit with one of: `feat`, `fix`, `refactor`,
`perf`, `docs`, `style`, `test`, `build`, `chore`, `revert`, optionally `(scope)`.
A breaking change is marked with `!` after the type or a `BREAKING CHANGE:`
footer, e.g. `feat!: drop 7.x support`. This convention drives the `git-cliff`
release notes and changelog in `/release`.

# Release Tooling

- `git-cliff` (Rust binary) generates release notes + the changelog: install via
  `cargo install git-cliff` or `brew install git-cliff`. The `/release` skill
  runs `git-cliff -u` (unreleased) to draft the next version's notes.
- `gh` (GitHub CLI) is used by the release skill to create/upload a release; it
  must be authenticated (`gh auth login`).

# Maintaining This Document

Keep this document concise and action-oriented.

- State what to do or avoid first.
- Include rationale only when it prevents ambiguity, incorrect generalization,
  or likely violations of the rule.
- Prefer a short constraint over historical context or lengthy explanations.
- Keep examples only when the correct usage is not obvious from the rule.
- Do not document implementation history, past bugs, or background knowledge
  unless it directly affects how code should be written.
- When adding a rule, ask: "Would an agent make the wrong decision without
  knowing why?" If not, omit the explanation.