# Cue Architectural Enforcement Checker

A small, custom AST-based static-analysis tool that turns Cue's architectural
decisions into **executable constraints**. It exists because coding agents
(and humans) frequently take shortcuts that work but violate the intended
architecture -- reaching for the global `_cue` instead of injecting a
dependency, or crossing a private boundary. Documentation says "don't"; the
checker says "you cannot."

It is intentionally small and stays out of ruff's lane. Ruff handles
formatting, unused imports, and ordinary code-quality rules. The custom
checker handles **encapsulation, dependency injection, architectural layering,
and Cue-specific forbidden patterns** only.

## What it is

- `tools/cuecheck.py` -- a Python AST analyzer using the stdlib `ast` module.
  Dev-time tooling (runs under Python 3), not runtime Cue code.
- Parses all `cue_lib/**/*.py` (recursive -- includes subpackages like
  `cue_lib/audio/`). Never `tests/` (deliberately white-box) and never `.rpy`
  (the Ren'Py bridge is the wiring point, not a target).
- Own diagnostic namespace `CUE0xx`, so it can't collide with ruff.
- Wired in as check #7 of `bin/lint.sh` -- the single source of truth invoked
  by both the `/lint` skill and CI. It exits nonzero on findings, so both
  paths enforce it identically. Deterministic.
- **Performance:** ~0.4s to parse the tree, ~1s with a full rule pass. Run
  every rule in **one pass over one parse** (parse each file once, visit the
  tree once) → roughly 1s end-to-end. That's the cheapest check in the
  pipeline; quiet compared to ruff format (~0.1s) and pyright (seconds). No
  multiprocessing needed at this size.

## Rule set

### Rule 1 -- No cross-module private member access (Ruff `SLF001`)

Delegated to the existing first-party ruff rule `SLF001` (`flake8-slf`,
"private-member-access"). Enable it in `pyproject.toml`.

- Any access to an underscore-prefixed member from outside the class that
  declares it is a violation. Syntactic, no type inference.
- Existing code is fixed by a **per-manager public/private rename audit**:
  promote any cross-module-used `_method`/`_attr` to public (drop the `_`),
  keep truly-internal ones private, refactoring their one-off callers.
- End state: "underscore = never crossed" is actually true, so the dumb rule
  is correct with **zero declarations**. It catches whatever an agent writes
  next, forever.
- `.pyi` stubs update with each rename.

### Rule 2 -- No global `_cue` access where DI is intended (CUE002, custom)

`_cue` is **context-scoped, not name-banned**. Ren'Py requires the `_cue`
singleton on the store because of global namespacing, so `_cue` at the
glue/bootstrap boundary is legitimate. The violation is pulling a dependency
out of `_cue` when the code could receive it via dependency injection.

**Allowed** (no instance exists to inject into): `runtime.py` (bootstrap
glue) and `cue_z.rpy` (the bridge -- not parsed).

**CUE002** (DI is the intended pattern) -- fires on `_cue.<dep>` when the
access is inside a **class method body** (an injected collaborator should
already be on `self`) **or** a module-level function in a manager module that
is called by a manager (it could take the dep as a param -- calling `_cue` is
a shortcut). Example:

```python
def flush(self):
    return _cue.vid_manager.channel  # CUE002 -- this method has self._vid_manager
```

**Granularity is deliberately (b):** module-level functions count. Consequence:
the allowlist is essentially `{runtime.py}` only, so `markers.py`,
`settings.py`, `util.py`, `paths.py` free functions that read `_cue` become
phase-A refactor work -- they take params.

### Rule 3 -- No direct mutation of declared protected state (CUE003, custom)

The first two rules are blind to the remaining smell because it has no
underscore: mutating a **public-looking attribute** through a foreign chain.

```python
_cue.music.library.external_folders = [...]            # was Rule 2 (a _cue access)
lookup._sfx_manager.library.external_folders = [...]   # ← only Rule 3 sees this
library.files.append(...)
```

There's no `_` (SLF001 quiet) and it's DI-clean (CUE002 quiet). Rule 3 closes
that hole -- the path an agent reaches when it injects properly but then
mutates a public attr directly. See the `__owns__` contract below.

### Rule 4 -- Every cue_lib class subclasses `NoRollback` (CUE004, custom)

Every class in `cue_lib/*.py` must subclass `_renpy_python.NoRollback`. A
non-`NoRollback` mod object parked in the store is reverted by rollback and
its whole object graph walked on every rollback step (~1s). New agent code
that forgets the base class silently adds that cost. Flag any `class` whose
base isn't `NoRollback` (or `object`).

### Rule 5 -- `_cue` is never reassigned (CUE005, custom)

`_cue` is a module-level `NoRollback()` singleton; code mutates its
attributes, never rebinds it. Flag any `_cue = ...` assignment so the
singleton stays a singleton.

### Rule 6 -- Duck-type over `isinstance(x, list/dict)` (CUE006, custom)

`list` may be shadowed by `RevertableList` on the Ren'Py side, so an
`isinstance(x, list)` (or `dict`/`tuple`) check can silently mis-type a
revertable collection. Flag collection-specific `isinstance` in runtime `.py`;
such code should duck-type instead.

### Rule 7 -- Forbidden version-specific APIs (CUE007, custom)

Bans Ren'Py version-gated calls: character-callback kwargs `what` / `start` /
`end`, `renpy.get_displayable()` with `screen=` / `id=`, and `renpy.music`
in `.py` files (use `renpy.audio.music`). Purely syntactic call/attr checks.

### Rule 8 -- Py2 string `isinstance` (CUE008, custom; moved from `bin/lint.sh`)

`isinstance(x, str)` / `(str, bytes)` / `type(x) is str` misses unicode on
Python 2.7 (`str` is bytes there). Moved *into* the tool because AST detects
forms the old grep missed: multi-line `isinstance(\n x, str)`, tuple forms,
and `type(x) is str`. Exits like the old check; text checks go through
`util._cue_is_str()`, real bytes through bare `bytes`.

### Banned imports (Ruff `TID251`, no custom code)

Forbid `enum` and `os.rename` via ruff `TID251` (`flake8-tidy-imports`,
banned-api) in `pyproject.toml`. Flat classes inherit `object` (no `enum`
module); overwrites use `_cue_replace_file()`, not `os.rename`.

## Phases

### Phase A -- the dumb rules, zero type knowledge, land first

Rules 1, 2, 4, 5, 6, 7, 8 + `TID251`/`SLF001` enablement. All purely
syntactic. This is the primary new-code guard.

### Phase B -- the one rule that needs declarations, after A

Rule 3 (`CUE003`) via the `__owns__` contract + a declared type map.

### Gate sequencing

Build the checker + enable the ruff rules now. Burn down phase-A violations
chunk by chunk. Flip to always-on / zero-tolerance after the last chunk. Until
then, track a single `LEGACY` counter that must read 0 to merge. No permanent
baseline or grandfather map.

## `__owns__` contract (rule 3 / CUE003) -- how it works

The mechanical problem is **type resolution**: to reject
`lookup._sfx_manager.library.external_folders = ...` the checker must know
that `.library` has type `CueMusicLibrary`. `__owns__` sidesteps inference
with a **declared, config-driven type map**.

**Declaration** -- a tuple on the owner class naming the mutable state that
outsiders may read but must not mutate:

```python
class CueMusicLibrary(object):
    __owns__ = ("files", "external_folders", "disabled_files", "sidebar_width", "_recent")
```

**Semantics:** outside code may *read* `library.files` (the UI needs it), but
any *write* -- `=`, `.append/.remove/.insert`, `[k]=` -- must go through the
class's own methods. Underscore stays separate: `_`-prefixed names are
"don't even read cross-module" (SLF001); `__owns__` names are "may read, never
mutate." Complementary layers.

**Enforcement (dumb AST, no type inference):**
1. Collect owners from the `__owns__` declarations: `{class_name → set(attrs)}`.
2. Build a small **declared type map** -- the only way a syntactic tool
   resolves a chain. Two sources, both config, neither inferred:
   - The `_cue` object graph (small, fixed): e.g.
     `{"_cue.sfx.library": "CueMusicLibrary", "_cue.sfx": "CueSfxManager", "_cue.markers": "CueMarkerManager"}`.
   - Injected collaborators: read each manager's `__init__` (`self._sfx_manager
     = sfx_manager` → `SfxManager`, chained through the field decl to
     `.library` → `CueMusicLibrary`).
3. Walk the AST for the mutation shapes (`x.attr = v`, `x.attr.append/remove/
   insert(...)`, `x.attr[k] = v`). Resolve `x` left-to-right through the type
   map. If the leaf type owns `attr` and the access isn't on `self`/`cls`
   inside the owning class → CUE003.
4. Chains resolve only as far as the map reaches; an unknown link stops
   resolution and the violation is silently missed. **False negatives are
   expected and acceptable** -- the deliberate tradeoff for avoiding a
   type-inference framework.

**Maintenance cost is the type map, not the tool.** The manager graph is ~15
names; it grows only when a manager or collaborator is added. The checker
reports "undefined type map entry" on an unresolved chain so the map stays
honest.

## Relationship to the other gates

The AST tool is the **static-structure** enforcement layer, a complement not a
replacement. `bin/lint.sh` stays the single gate and still runs all of these:

| Layer | What it enforces | Tool |
| --- | --- | --- |
| Structure | Rules 2–8 above (Python side) | `tools/cuecheck.py` |
| Format/standards + private access + bans | `SLF001`, `TID251`, format | ruff |
| Types | Type safety in `cue_lib/` (`.pyi`-driven) | pyright |
| Py2 runtime proof | Actual 7.4.10 boot + smokes | `bin/py2_check.sh` |

**The tool cannot enforce** (by design, out of scope):
- `.rpy` constraints -- `style_group "cue"`, screen structural rules, the
  `<from N>` movie-channel ban, wrap rules. We don't parse `.rpy`; these stay
  manual per CLAUDE.md.
- **Runtime** py2 validity -- only a real interpreter boot (`py2_check.sh`)
  catches py2-invalid syntax the Python 3 `ast` can't.
- Formatting and types -- different tools.
- **Semantic/taint** rules, e.g. text escaping ("untrusted → `etext`") -- a
  data-flow question a dumb syntactic tool can't answer; skip.

## Phase-A chunk plan (biggest offender first)

1. `marker_store` -- promote ~6 cross-module-private methods to public;
   update callers + `.pyi`.
2. `markers` + `marker_context` -- free functions take params (drop `_cue`);
   route the `_mgr._sfx_manager.library.files[...]` chain through methods.
3. `preset_store` -- same treatment.
4. `sfx`/`music` -- `_recent`, `external_folders`, `sidebar_width` via methods.
5. `paths`/`settings`/`undo`/`pool` -- remainder.

Each chunk is one owner's public/private decision + caller updates + `.pyi`
refresh, independently reviewable.

## Design principles

- **Keep it intentionally dumb.** Don't build a complete Python type
  analyzer. If a rule can be expressed syntactically, prefer that. False
  negatives beat a fragile inference framework.
- **Separate architectural rules from normal linting.** Ruff keeps formatting,
  standards, and code-quality rules; the custom checker owns encapsulation,
  DI, and architectural boundaries.
- **Rule IDs are CUE0xx, not ruff-style.** Keeps the two rule sets distinct.

## Rule ID map

| Rule | Concern | Mechanism | Phase |
| --- | --- | --- | --- |
| 1 | cross-module `_member` access | Ruff `SLF001` | A |
| 2 | `_cue` used where DI is intended | `CUE002` | A |
| 3 | mutation of declared protected state | `CUE003` (`__owns__`) | B |
| 4 | class must subclass `NoRollback` | `CUE004` | A |
| 5 | `_cue` never reassigned | `CUE005` | A |
| 6 | duck-type over `isinstance(list/dict)` | `CUE006` | A |
| 7 | forbidden version-specific APIs | `CUE007` | A |
| 8 | py2 `isinstance(str)` / `type(x) is str` | `CUE008` (moved from lint.sh) | A |
| -- | banned imports (`enum`, `os.rename`) | Ruff `TID251` | A |
