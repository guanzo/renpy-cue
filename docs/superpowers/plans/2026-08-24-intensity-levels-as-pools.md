# Intensity Levels as Pools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make intensity-group levels first-class pools (arbitrary folders *and* files, editable in-app) and replace the implicit folder-hook with an explicit `igroup` + `ilevel_id` reference on each pool.

**Architecture:** Igroups store `levels` (a list of `{id, files}`) instead of `folders` + two multiplier arrays; the volume/frequency ramp is derived from level count at resolve time. Pools reference a group by `igroup` and a stable level by `ilevel_id`. The folder-scan hook machinery (`resolve_hook`, `_folder_index`, `check_add_folder`, `group_for_folder`, `pool_group`, `level_folder`) is deleted. Loop pools get the hook for free (they are `PoolDict`s and already resolve through `resolve_pool_intensity`).

**Tech Stack:** Ren'Py 7.x/8.x (Python 2.7-compatible `.py`), pytest for logic, the Ren'Py harness for UI/engine behavior.

**Spec:** `docs/superpowers/specs/2026-08-24-intensity-levels-as-pools-design.md`

## Global Constraints

- Ren'Py 7.4+ (7.x and 8.x). Runtime `.py` is Python 2.7: no f-strings (`.format()`/`%`), no type hints, no `@` operator, no non-ASCII, classes inherit `object`/new-style.
- `cue_lib/*.py`: module functions `_cue_` prefix; classes `Cue` prefix; `.py` imports `import x as _x`.
- Naming for this feature: `igroup`, `ilevel_id`, `next_ilevel_id` — **always `ilevel`-prefixed, never bare `level`**.
- Before any commit: `/lint` prints `CLEAN` and `python3 -m pytest tests/ -q` passes.
- After changing `cue_lib/*.py`: update its `.pyi`, then run `/lint`, `/test`, `/test-harness`.
- After adding/changing a TypedDict: update `cue_lib/_types.py` (single canonical source); do not redeclare in `.pyi`.
- In `.py` files use `renpy.audio.music`, not `renpy.music`.

## File Structure

- **`cue_lib/_types.py`** — add `LevelDict`; extend `PoolDict` with `igroup`/`ilevel_id`. (Canonical types.)
- **`cue_lib/marker_store.py`** — `ResolvedPool` gains `igroup`/`ilevel_id`; `resolve_pool` surfaces them; pool migration.
- **`cue_lib/marker_store.pyi`** — `ResolvedPool` stub.
- **`cue_lib/intensity/intensity.py`** — the rewrite: levels model, stable ids, derived ramp, new resolution; delete folder-hook machinery; igroup migration.
- **`cue_lib/intensity/intensity.pyi`** — new manager API.
- **`cue_lib/trigger.py`** — pass `igroup`/`ilevel_id` to `resolve_pool_intensity`.
- **`cue_lib/marker_context.py`** — remove `check_add_folder` calls.
- **`cue_lib/ui/displayables.py`** — `is_pool_intensity_active` / `current_level` new signatures.
- **`cue_lib/ui/views/video_vfx.rpy`** — inspector reads pool fields; `level_files`.
- **`cue_lib/util.py`** — `_cue_filter_igroup_folders` / `_cue_igroup_search_matches` read `levels`.
- **`cue_lib/ui/views/sfx_library.rpy`** — level rows, `[+ Level]`, add-files toggle, target-aware `[+]`.
- **`cue_lib/markers.py`** — level-send store bridge.
- **Tests:** `tests/test_intensity.py`, `tests/test_intensity_resolution.py` (rewrite); `tests/test_marker_store.py`, `tests/test_markers_context.py`, `tests/test_trigger_engine.py`, `tests/test_displayables.py`, `tests/test_speed.py`, `tests/test_runtime.py` (update).

---

### Task 1: Type definitions

**Files:**
- Modify: `cue_lib/_types.py:33-57`

**Interfaces:**
- Produces: `LevelDict` (`id: int`, `files: List[str]`, both optional); `PoolDict` gains `igroup: str` and `ilevel_id: int`.

- [ ] **Step 1: Add `LevelDict` after `PoolDict`**

In `cue_lib/_types.py`, after the `PoolDict` class (ends line 43), insert:

```python
class LevelDict(TypedDict, total=False):
    """One intensity-group level: a pool of folders/files, plus a stable id.

    ``id`` is a monotonic per-group identity that survives reorder/insert.
    ``files`` are folder refs (trailing ``/``) and direct file entries, the
    same shape as a marker pool's ``files``."""

    id: int
    files: List[str]
```

- [ ] **Step 2: Extend `PoolDict`**

In the `PoolDict` class body, add two fields before `preset` (line 43):

```python
    igroup: str  # intensity group name (hook)
    ilevel_id: int  # stable id of the pinned level (fallback content)
```

- [ ] **Step 3: Commit**

```bash
git add cue_lib/_types.py
git commit -m "feat(intensity): add LevelDict and pool igroup/ilevel_id fields"
```

---

### Task 2: ResolvedPool surfaces the hook

**Files:**
- Modify: `cue_lib/marker_store.py:48-56`, `cue_lib/marker_store.py:200-208`
- Modify: `cue_lib/marker_store.pyi:21-32`
- Test: `tests/test_marker_store.py`

**Interfaces:**
- Consumes: `PoolDict.igroup`/`ilevel_id` (Task 1).
- Produces: `ResolvedPool.igroup: Optional[str]`, `ResolvedPool.ilevel_id: Optional[int]` — `None` when the pool isn't hooked.

- [ ] **Step 1: Extend `ResolvedPool.__init__`**

In `cue_lib/marker_store.py`, change the `ResolvedPool` class (line 48):

```python
class ResolvedPool(object):
    """Immutable snapshot of a resolved pool."""
    def __init__(self, files, volume, frequency, trigger_on_shake, exclusive=None, igroup=None, ilevel_id=None):
        # type: (List[str], float, int, bool, Optional[Any], Optional[str], Optional[int]) -> None
        self.files = files
        self.volume = volume
        self.frequency = frequency
        self.trigger_on_shake = trigger_on_shake
        self.exclusive = exclusive if exclusive is not None else ResolvedExclusive()
        self.igroup = igroup
        self.ilevel_id = ilevel_id
```

- [ ] **Step 2: Surface in `resolve_pool`**

In `resolve_pool` (line 200), after the existing fields, add:

```python
        igroup = pool.get("igroup", defaults.get("igroup"))
        ilevel_id = pool.get("ilevel_id", defaults.get("ilevel_id"))
        return ResolvedPool(list(files), volume, frequency, trigger_on_shake, exclusive, igroup, ilevel_id)
```

(`defaults` is the preset dict when the pool is preset-backed; a preset carries no `igroup`, so `defaults.get("igroup")` is `None` — correct.)

- [ ] **Step 3: Write the failing test**

In `tests/test_marker_store.py`, add:

```python
def test_resolve_pool_surfaces_intensity_hook(cue_env):
    store = cue_env.markers.store  # adjust to the actual store fixture access
    pool = {"files": [], "igroup": "Impacts", "ilevel_id": 2}
    resolved = store.resolve_pool(pool)
    assert resolved.igroup == "Impacts"
    assert resolved.ilevel_id == 2

def test_resolve_pool_unhooked_has_none(cue_env):
    store = cue_env.markers.store
    resolved = store.resolve_pool({"files": ["a.ogg"]})
    assert resolved.igroup is None
    assert resolved.ilevel_id is None
```

Check the existing `test_marker_store.py` for how it obtains a `CueMarkerStore` (there is a `store` fixture or it is built from `cue_env`); match that.

- [ ] **Step 4: Run tests to verify green**

Run: `python3 -m pytest tests/test_marker_store.py -q`
Expected: PASS

- [ ] **Step 5: Update `.pyi` and commit**

In `cue_lib/marker_store.pyi`, add to the `ResolvedPool` class: `igroup: Optional[str]` and `ilevel_id: Optional[int]` (import `Optional` at the top if not already). Then:

```bash
git add cue_lib/marker_store.py cue_lib/marker_store.pyi tests/test_marker_store.py
git commit -m "feat(marker_store): surface igroup/ilevel_id on ResolvedPool"
```

---

### Task 3: Intensity core rewrite (data model + resolution + consumers)

This is the coupled core: the igroup JSON shape, the level CRUD, the resolution
signatures, and every consumer change together. It is one commit because the
`folders`→`levels` change and the `resolve_pool_intensity` signature change
cannot each be green on their own (call sites and tests reference the old
contract). Work through the steps in order; the suite goes red after Step 5 and
returns green at Step 9.

**Files:**
- Modify: `cue_lib/intensity/intensity.py` (large)
- Modify: `cue_lib/intensity/intensity.pyi`
- Modify: `cue_lib/trigger.py:262-275`, `:394-419`, `:567-610`
- Modify: `cue_lib/marker_context.py:258-276`, `:448-479`
- Modify: `cue_lib/ui/displayables.py:341-346`, `:884-895`
- Modify: `cue_lib/ui/views/video_vfx.rpy:192-194`, `:235-237`, `:294-298`
- Modify: `cue_lib/util.py:453-462`, `:480-488`
- Modify: `cue_lib/audio/sfx_manager.py:482-491`
- Test: `tests/test_intensity.py`, `tests/test_intensity_resolution.py` (rewrite); `tests/test_markers_context.py`, `tests/test_trigger_engine.py`, `tests/test_displayables.py`, `tests/test_speed.py`, `tests/test_runtime.py`

**Interfaces (the new `CueIntensityManager` API — exact):**

```python
list_igroups() -> List[str]
get_igroup(name) -> Optional[Dict[str, Any]]
create_igroup(name) -> Optional[str]
rename_igroup(old_name, new_name) -> Optional[str]
delete_igroup(name) -> None
add_level(name) -> Optional[int]                       # new level's id, or None
add_level_file(name, ilevel_id, file_ref) -> Optional[str]   # error str or None
remove_level_file(name, ilevel_id, file_ref) -> None
remove_level(name, index) -> None
move_level(name, index, delta) -> None
level_files(name, level_index) -> Optional[List[str]]         # 1-based index
level_files_by_id(name, ilevel_id) -> Optional[List[str]]     # dangling -> level 1
level_multipliers(name, level_index) -> Tuple[float, float]   # derived ramp
flags_from_entry(entry) -> CueIntensityFlags
resolve_pool_intensity(igroup, ilevel_id, current_speed, variants, flags=None, resolve_files=None) -> Optional[CueIntensityResolution]
resolve_video_intensity(pool_hooks, current_speed, variants, flags=None, resolve_files=None) -> Optional[CueIntensityResolution]
current_level(pool_hooks, current_speed, variants, flags=None) -> Optional[Tuple[int, int]]
video_hook(pool_hooks) -> Optional[str]
is_pool_intensity_active(igroup, variants, flags=None) -> bool
variant_levels(group_name, variants) -> Optional[List[Tuple[float, int]]]
```

`pool_hooks` is `List[Tuple[Optional[str], Optional[int]]]` — one `(igroup, ilevel_id)` per pool. `resolve_files` is an injectable `(List[str]) -> List[str]`, defaulting to `_cue_resolve_files`; it replaces the old `is_populated`.

- [ ] **Step 1: Rewrite `tests/test_intensity.py` (failing — new shape)**

Replace the level-editing tests with the levels model. Keep the `_level_ramp` tests (unchanged) and the create/rename/delete tests (change `data["folders"]` assertions to `data["levels"]`). Key new tests:

```python
def test_create_empty_igroup(cue_env, imgr):
    assert imgr.create_igroup("Impacts") is None
    data = imgr.get_igroup("Impacts")
    assert data is not None
    assert data["levels"] == []
    assert data["next_ilevel_id"] == 1

def test_add_level_assigns_stable_ids(cue_env, imgr):
    imgr.create_igroup("Impacts")
    assert imgr.add_level("Impacts") == 1
    assert imgr.add_level("Impacts") == 2
    data = imgr.get_igroup("Impacts")
    assert [lv["id"] for lv in data["levels"]] == [1, 2]
    assert data["next_ilevel_id"] == 3

def test_add_level_file_appends_and_dedupes(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    assert imgr.add_level_file("Impacts", 1, "soft/") is None
    assert imgr.add_level_file("Impacts", 1, "soft/a.ogg") is None
    err = imgr.add_level_file("Impacts", 1, "soft/")
    assert err is not None
    assert imgr.get_igroup("Impacts")["levels"][0]["files"] == ["soft/", "soft/a.ogg"]

def test_remove_level_file(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    imgr.add_level_file("Impacts", 1, "soft/")
    imgr.remove_level_file("Impacts", 1, "soft/")
    assert imgr.get_igroup("Impacts")["levels"][0]["files"] == []

def test_remove_level_keeps_ids(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")  # id 1
    imgr.add_level("Impacts")  # id 2
    imgr.remove_level("Impacts", 0)
    assert [lv["id"] for lv in imgr.get_igroup("Impacts")["levels"]] == [2]

def test_move_level_preserves_ids(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")  # id 1
    imgr.add_level("Impacts")  # id 2
    imgr.move_level("Impacts", 0, 1)
    assert [lv["id"] for lv in imgr.get_igroup("Impacts")["levels"]] == [2, 1]

def test_level_multipliers_derived_from_ramp(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    imgr.add_level("Impacts")
    assert imgr.level_multipliers("Impacts", 1) == (1.0, 1.0)
    assert imgr.level_multipliers("Impacts", 2) == (1.25, 1.5)

def test_level_files_by_id_dangling_falls_back_to_level_one(cue_env, imgr):
    imgr.create_igroup("Impacts")
    imgr.add_level("Impacts")
    imgr.add_level_file("Impacts", 1, "soft/")
    imgr.add_level("Impacts")
    imgr.add_level_file("Impacts", 2, "hard/")
    assert imgr.level_files_by_id("Impacts", 99) == ["soft/"]  # dangling -> level 1
    assert imgr.level_files_by_id("Impacts", 2) == ["hard/"]
```

Delete `test_add_folder_*` tests (the `add_folder` method is gone).

- [ ] **Step 2: Run to verify failing**

Run: `python3 -m pytest tests/test_intensity.py -q`
Expected: FAIL (no `add_level`, `levels`, etc.)

- [ ] **Step 3: Rewrite `tests/test_intensity_resolution.py` (failing — new API)**

Replace `resolve_hook`/`level_folder`/`group_for_folder`/`pool_group`/`check_add_folder` tests with the new API. Use a `_resolve` injectable:

```python
def _resolve(files):
    # type: (List[str]) -> List[str]
    return [f for f in files if f != "hard/" or True]  # identity resolver
```

Representative tests:

```python
def test_resolve_pool_intensity_unhooked_is_none(cue_env):
    m = _two_level(cue_env)
    assert m.resolve_pool_intensity(None, None, 1.0, [1.0], resolve_files=_resolve) is None

def test_resolve_pool_intensity_bands_speed_to_level(cue_env):
    m = _two_level(cue_env)
    r = m.resolve_pool_intensity("Impacts", 1, 0.7, [0.7, 1.0, 1.3], resolve_files=_resolve)
    assert r is not None
    assert r.level == 1
    assert r.volume_mult == 1.0

    r = m.resolve_pool_intensity("Impacts", 1, 1.3, [0.7, 1.0, 1.3], resolve_files=_resolve)
    assert r is not None
    assert r.level == 2
    assert r.volume_mult == 1.25

def test_resolve_pool_intensity_enabled_off_plays_pinned_level(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(enabled=False)
    r = m.resolve_pool_intensity("Impacts", 1, 1.3, [0.7, 1.0, 1.3], flags, _resolve)
    assert r is not None
    assert r.level == 1
    assert r.volume_mult == 1.0
    assert r.freq_mult == 1.0

def test_resolve_pool_intensity_sfx_levels_off_plays_pinned_level_scaled(cue_env):
    m = _two_level(cue_env)
    flags = CueIntensityFlags(sfx_levels=False)
    r = m.resolve_pool_intensity("Impacts", 1, 1.3, [0.7, 1.0, 1.3], flags, _resolve)
    assert r is not None
    assert r.level == 2          # active level still drives scaling
    assert r.volume_mult == 1.25
    assert r.files == ["soft/"]  # pinned level's files play

def test_resolve_video_intensity_first_hooked_pool_wins(cue_env):
    m = _two_level(cue_env)
    hooks = [(None, None), ("Impacts", 1)]
    r = m.resolve_video_intensity(hooks, 1.3, [0.7, 1.0, 1.3], resolve_files=_resolve)
    assert r is not None
    assert r.group == "Impacts"

def test_video_hook_first_group(cue_env):
    m = _two_level(cue_env)
    assert m.video_hook([(None, None), ("Impacts", 2)]) == "Impacts"
    assert m.video_hook([(None, None)]) is None

def test_is_pool_intensity_active(cue_env):
    m = _two_level(cue_env)
    assert m.is_pool_intensity_active("Impacts", [0.7, 1.0, 1.3]) is True
    assert m.is_pool_intensity_active(None, [0.7, 1.0, 1.3]) is False
    assert m.is_pool_intensity_active("Impacts", [1.0]) is False
```

Keep the `variant_levels`, `flags_from_entry`, and `_cue_intensity_volume_mult` tests (change `add_folder` calls to `add_level` + `add_level_file`). Port `test_current_level_*` to pass `pool_hooks` tuples. Drop `test_group_for_folder_*`, `test_pool_group_*`, `test_check_add_folder_*`, `test_resolve_hook_*`, `test_level_folder_*` entirely.

- [ ] **Step 4: Run to verify failing**

Run: `python3 -m pytest tests/test_intensity_resolution.py -q`
Expected: FAIL

- [ ] **Step 5: Rewrite `cue_lib/intensity/intensity.py`**

Delete these methods and fields: `_folder_index`, `_folder_index_cache`, `resolve_hook`, `group_for_folder`, `pool_group`, `check_add_folder`, `level_folder`, `add_folder`, `_save_with_ramp`, and the `_band_cache` stays.

Change the module docstring's first paragraph to describe levels-as-pools. Replace `CueIntensityResolution.__init__` to drop `folder`:

```python
class CueIntensityResolution(object):
    def __init__(self, group, level, volume_mult, freq_mult, files=None):
        # type: (str, int, float, float, Optional[List[str]]) -> None
        self.group = group
        self.level = level
        self.volume_mult = volume_mult
        self.freq_mult = freq_mult
        self.files = files if files is not None else []
```

Replace the CRUD with (keeping `create_igroup`/`rename_igroup`/`delete_igroup`/`list_igroups`/`get_igroup`/`_load`/`_invalidate`/`_save`):

```python
    def _new_ilevel_id(self, data):
        # type: (Dict[str, Any]) -> int
        next_id = data.get("next_ilevel_id", 1)
        data["next_ilevel_id"] = next_id + 1
        return next_id

    def add_level(self, name):
        # type: (str) -> Optional[int]
        data = self.get_igroup(name)
        if data is None:
            return None
        levels = list(data.get("levels", []))
        new_id = self._new_ilevel_id(data)
        levels.append({"id": new_id, "files": []})
        data["levels"] = levels
        self._save(name, data)
        return new_id

    def _find_level(self, data, ilevel_id):
        # type: (Dict[str, Any], int) -> Optional[Dict[str, Any]]
        for level in data.get("levels", []):
            if level.get("id") == ilevel_id:
                return level
        return None

    def add_level_file(self, name, ilevel_id, file_ref):
        # type: (str, int, str) -> Optional[str]
        data = self.get_igroup(name)
        if data is None:
            return "No intensity group named '{}'.".format(name)
        level = self._find_level(data, ilevel_id)
        if level is None:
            return "No level '{}' in '{}'.".format(ilevel_id, name)
        files = level.setdefault("files", [])
        if file_ref in files:
            return "'{}' is already in this level.".format(file_ref)
        files.append(file_ref)
        self._save(name, data)
        return None

    def remove_level_file(self, name, ilevel_id, file_ref):
        # type: (str, int, str) -> None
        data = self.get_igroup(name)
        if data is None:
            return
        level = self._find_level(data, ilevel_id)
        if level is None:
            return
        files = level.get("files", [])
        if file_ref in files:
            files.remove(file_ref)
            self._save(name, data)

    def remove_level(self, name, index):
        # type: (str, int) -> None
        data = self.get_igroup(name)
        if data is None:
            return
        levels = list(data.get("levels", []))
        if 0 <= index < len(levels):
            del levels[index]
            data["levels"] = levels
            self._save(name, data)

    def move_level(self, name, index, delta):
        # type: (str, int, int) -> None
        data = self.get_igroup(name)
        if data is None:
            return
        levels = list(data.get("levels", []))
        new_index = index + delta
        if 0 <= index < len(levels) and 0 <= new_index < len(levels):
            levels[index], levels[new_index] = levels[new_index], levels[index]
            data["levels"] = levels
            self._save(name, data)

    def level_files(self, name, level_index):
        # type: (str, int) -> Optional[List[str]]
        data = self.get_igroup(name)
        if data is None:
            return None
        levels = data.get("levels", [])
        idx = level_index - 1
        if not (0 <= idx < len(levels)):
            return None
        return levels[idx].get("files", [])

    def level_files_by_id(self, name, ilevel_id):
        # type: (str, int) -> Optional[List[str]]
        data = self.get_igroup(name)
        if data is None:
            return None
        levels = data.get("levels", [])
        level = self._find_level(data, ilevel_id)
        if level is not None:
            return level.get("files", [])
        if levels:
            return levels[0].get("files", [])
        return None

    def level_multipliers(self, name, level_index):
        # type: (str, int) -> Tuple[float, float]
        data = self.get_igroup(name)
        if data is None:
            return (1.0, 1.0)
        count = len(data.get("levels", []))
        if count == 0:
            return (1.0, 1.0)
        idx = max(0, min(level_index - 1, count - 1))
        vm = _level_ramp(count, CUE_INTENSITY_VOLUME_MAX)[idx]
        fm = _level_ramp(count, CUE_INTENSITY_FREQ_MAX)[idx]
        return (vm, fm)
```

Replace the resolution block with:

```python
    def resolve_pool_intensity(self, igroup, ilevel_id, current_speed, variants, flags=None, resolve_files=None):
        # type: (Optional[str], Optional[int], float, Optional[List[float]], Optional[CueIntensityFlags], Optional[Callable[[List[str]], List[str]]]) -> Optional[CueIntensityResolution]
        if igroup is None:
            return None
        data = self.get_igroup(igroup)
        if data is None:
            return None
        levels = data.get("levels", [])
        if not levels:
            return None
        if resolve_files is None:
            resolve_files = _cue_resolve_files
        count = len(levels)
        can_band = (flags is None or flags.enabled) and bool(variants)
        swap = can_band and (flags is None or flags.sfx_levels)
        if can_band:
            key = (tuple(sorted(set(variants))), count)
            if key not in self._band_cache:
                self._band_cache[key] = _cue_band_speeds(variants, count)
            speeds, band_levels = self._band_cache[key]
            level = _cue_resolve_level(current_speed, speeds, band_levels)
        else:
            level = 1
        if swap:
            files = self.level_files(igroup, level)
        else:
            files = self.level_files_by_id(igroup, ilevel_id)
        if files is None:
            files = []
        vm, fm = self.level_multipliers(igroup, level)
        if flags is not None:
            if not flags.enabled:
                vm, fm = 1.0, 1.0
            else:
                if not flags.volume:
                    vm = 1.0
                if not flags.frequency:
                    fm = 1.0
        return CueIntensityResolution(igroup, level, _cue_intensity_volume_mult(vm), fm, resolve_files(files))

    def resolve_video_intensity(self, pool_hooks, current_speed, variants, flags=None, resolve_files=None):
        # type: (List[Tuple[Optional[str], Optional[int]]], float, Optional[List[float]], Optional[CueIntensityFlags], Optional[Callable[[List[str]], List[str]]]) -> Optional[CueIntensityResolution]
        for igroup, ilevel_id in pool_hooks:
            res = self.resolve_pool_intensity(igroup, ilevel_id, current_speed, variants, flags, resolve_files)
            if res is not None:
                return res
        return None

    def current_level(self, pool_hooks, current_speed, variants, flags=None):
        # type: (List[Tuple[Optional[str], Optional[int]]], float, Optional[List[float]], Optional[CueIntensityFlags]) -> Optional[Tuple[int, int]]
        if flags is not None and not flags.enabled:
            return None
        if not variants:
            return None
        for igroup, _ilevel_id in pool_hooks:
            if not igroup:
                continue
            data = self.get_igroup(igroup)
            if data is None:
                continue
            count = len(data.get("levels", []))
            if count == 0:
                continue
            key = (tuple(sorted(set(variants))), count)
            if key not in self._band_cache:
                self._band_cache[key] = _cue_band_speeds(variants, count)
            speeds, band_levels = self._band_cache[key]
            level = _cue_resolve_level(current_speed, speeds, band_levels)
            return (level, count)
        return None

    def video_hook(self, pool_hooks):
        # type: (List[Tuple[Optional[str], Optional[int]]]) -> Optional[str]
        for igroup, _ilevel_id in pool_hooks:
            if igroup:
                return igroup
        return None

    def is_pool_intensity_active(self, igroup, variants, flags=None):
        # type: (Optional[str], Optional[List[float]], Optional[CueIntensityFlags]) -> bool
        if flags is not None and not flags.enabled:
            return False
        if not variants or len(variants) < 2:
            return False
        return bool(igroup)

    def variant_levels(self, group_name, variants):
        # type: (str, List[float]) -> Optional[List[Tuple[float, int]]]
        if not variants:
            return None
        data = self.get_igroup(group_name)
        if data is None:
            return None
        level_count = len(data.get("levels", []))
        if level_count < 2:
            return None
        speeds, levels = _cue_band_speeds(list(variants), level_count)
        return list(zip(speeds, levels))
```

Keep `flags_from_entry`, `_level_ramp`, `_cue_intensity_volume_mult`, `CueIntensityFlags`, `create_igroup`, `rename_igroup`, `delete_igroup`, `_load`, `_invalidate`, `_save` as-is. `create_igroup` now writes `{"levels": [], "next_ilevel_id": 1}` instead of the three empty arrays. Update the `MYPY` import block to include `Tuple` if not present and drop unused imports.

- [ ] **Step 6: Update `cue_lib/intensity/intensity.pyi`**

Mirror the new API (add `add_level`, `add_level_file`, `remove_level_file`, `level_files`, `level_files_by_id`; change `resolve_pool_intensity`/`resolve_video_intensity`/`current_level`/`video_hook`/`is_pool_intensity_active` signatures; remove `add_folder`, `resolve_hook`, `group_for_folder`, `pool_group`, `check_add_folder`, `level_folder`; drop `folder` from `CueIntensityResolution`). Import `Tuple` from `typing` and `LevelDict` from `cue_lib._types`.

- [ ] **Step 7: Update consumers**

`cue_lib/trigger.py` — `_vid_intensity_resolution` (line 262): build hooks and call the new signature:

```python
        pool_hooks = []
        for p in entry.get("pools", []):
            rp = self._store.resolve_pool(p)
            pool_hooks.append((rp.igroup, rp.ilevel_id))
        if not pool_hooks:
            return None
        return _cue.intensity.resolve_video_intensity(pool_hooks, speed, variants, flags=flags)
```

In `_tick_loop` (line 409) and `_fire_video_markers` (line 598), replace:

```python
            res = _cue.intensity.resolve_pool_intensity(resolved.igroup, resolved.ilevel_id, speed, variants, flags=flags)
```

(`resolved` is already the `ResolvedPool` in both loops.)

`cue_lib/marker_context.py` — in `CueMarkerContext.add_folder` (line 258) and `CueVideoContext.add_folder` (line 448), delete the `check_add_folder` guardrail block (the `intensity = getattr(...)` lookup and the `err = intensity.check_add_folder(...)` / `if err: return err` lines). The methods now just append the folder ref.

`cue_lib/ui/displayables.py` — line 346: `return _cue.intensity.is_pool_intensity_active(marker.get("igroup"), variants, flags)`. Lines 887-895: build `pool_hooks` from resolved pools' `igroup`/`ilevel_id` instead of `[p.get("files", []) ...]`, then `current_level(pool_hooks, ...)`.

`cue_lib/ui/views/video_vfx.rpy` — line 192-194: `_pools_files` → build a hook list; pass to `video_hook`/`resolve_video_intensity`. Line 294: replace `level_folder(_hook_group, _lvl)` with `level_files(_hook_group, _lvl)` (the row's file list — join to display). Adjust the "Folder" header (line 286) to "Files".

`cue_lib/util.py` — `_cue_igroup_search_matches` (line 462): iterate `data.get("levels", [])` and match each level's `files`. `_cue_filter_igroup_folders` (line 480): return the level list (or per-level file lists) from `data.get("levels", [])`; the sfx_library screen consumes the return, so align with Task 6's rendering.

`cue_lib/audio/sfx_manager.py` — `igroup_add_folder` (line 482) and `toggle_igroup_add_mode`/`igroup_add_target` still reference group-level add mode; replace `igroup_add_folder` with a no-op body that delegates to `add_level_file` for a `(group, ilevel_id)` target, or remove it here and let Task 6 rewire. For now, change the body to call `self._intensity.add_level_file(...)` only if `igroup_add_target` holds a `(group, ilevel_id)` tuple — but to keep this task minimal, comment out the old `add_folder` call and note Task 6 reworks this UI.

- [ ] **Step 8: Update the remaining tests to the new signatures**

`tests/test_markers_context.py` — remove tests that assert the `check_add_folder` guardrail error (folder add is now always allowed). Keep the folder-add tests that assert `files` gets the folder ref.

`tests/test_trigger_engine.py` / `test_speed.py` / `test_runtime.py` / `test_displayables.py` — search for `resolve_pool_intensity(`, `resolve_video_intensity(`, `current_level(`, `video_hook(`, `is_pool_intensity_active(`, `add_folder(`, `level_folder(`, `resolve_hook(`. Update each call to the new signatures. `test_displayables.py`'s `_is_intensity_marker` path now passes a pool's `igroup`; adapt the fixtures (a pool hook is `{"igroup": "Impacts", "ilevel_id": 1}`).

- [ ] **Step 9: Run the full suite and lint**

Run: `python3 -m pytest tests/ -q`
Expected: PASS

Run: the `/lint` skill
Expected: CLEAN (fix any Pyright diagnostics in the touched `.py`/`.pyi`)

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(intensity): levels as pools with explicit igroup/ilevel_id hook"
```

---

### Task 4: Migrations

**Files:**
- Modify: `cue_lib/intensity/intensity.py` (`_load` igroup migration)
- Modify: `cue_lib/marker_store.py` (pool migration) — or a standalone helper called from the store's load
- Test: `tests/test_intensity.py` (igroup migration), `tests/test_marker_store.py` (pool migration)

**Interfaces:**
- Consumes: `LevelDict`, `ResolvedPool.igroup`/`ilevel_id` (Tasks 1-2), new `CueIntensityManager` (Task 3).

- [ ] **Step 1: Igroup migration (folders → levels)**

In `CueIntensityManager._load`, after `self._igroups = self._db.load_intensity_presets()`, migrate each entry whose dict has `"folders"` (old shape) into `"levels"` with sequential ids and `"next_ilevel_id"`:

```python
    def _load(self):
        # type: () -> Dict[str, Any]
        if self._igroups is None:
            loaded = self._db.load_intensity_presets()
            for name, data in loaded.items():
                if "levels" not in data and "folders" in data:
                    folders = data.get("folders", [])
                    data["levels"] = [
                        {"id": i + 1, "files": [f]} for i, f in enumerate(folders)
                    ]
                    data["next_ilevel_id"] = len(folders) + 1
                    data.pop("folders", None)
                    data.pop("volume_multipliers", None)
                    data.pop("frequency_multipliers", None)
                    self._db.save_preset(CUE_INTENSITY_PRESET_TYPE, name, data)
            self._igroups = loaded
        return self._igroups
```

(The `save_preset` back-write persists the migration so it doesn't rerun.)

- [ ] **Step 2: Pool migration (folder-hook → igroup/ilevel_id)**

Add a module-level helper in `cue_lib/marker_store.py` that, given the migrated igroups, maps each folder ref → `(igroup, ilevel_id)` and rewrites legacy pools. Call it from the store's load/migration path (find where `_migrate_video_timestamps_to_pools` is invoked and follow the same seam). Since the map needs igroups, pass it in from the caller (the coordinator in `cue_z.rpy`/`markers.py` that has both `_cue.intensity` and the store):

```python
def _cue_migrate_intensity_hooks(igroups):
    # type: (Dict[str, Any]) -> None
    """One-time: convert legacy folder-hooked pools to igroup/ilevel_id."""
    folder_map = {}
    for name, data in igroups.items():
        for level in data.get("levels", []):
            for f in level.get("files", []):
                if f.endswith("/") and f not in folder_map:
                    folder_map[f] = (name, level.get("id"))
    # For every pool in every marker entry: if its files contain a folder ref in
    # folder_map (first match), set igroup/ilevel_id and clear files.
    ...
```

Wire the call in `cue_z.rpy`'s init after both managers exist. Keep it guarded so it runs once (a shared-config flag or an idempotent no-op when no legacy hooks remain).

- [ ] **Step 3: Tests**

Igroup migration: write a test that hand-writes an old-shape igroup JSON into the intensity preset dir (via `cue_env.paths.intensity_preset_dir`), then constructs a fresh `CueIntensityManager` and asserts `get_igroup` returns the migrated `levels`. Pool migration: a marker entry with `files: ["soft/"]` and an igroup whose level 1 has `files: ["soft/"]`; after running `_cue_migrate_intensity_hooks`, assert the pool has `igroup`/`ilevel_id` and empty `files`.

- [ ] **Step 4: Lint + full suite + commit**

Run: `python3 -m pytest tests/ -q` and `/lint`.
Expected: PASS / CLEAN.

```bash
git add -A
git commit -m "feat(intensity): migrate legacy folder-hooked igroups and pools"
```

---

### Task 5: UI

**Files:**
- Modify: `cue_lib/ui/views/sfx_library.rpy:311-449`
- Modify: `cue_lib/markers.py:702-749` (add level-send bridge)
- Modify: `cue_lib/audio/sfx_manager.py` (`CueSfxLibraryTree` add-files state)
- Modify: `cue_lib/cue_z.rpy` (bridge exports for any new `_cue_*` function)

**Interfaces:**
- Consumes: `CueIntensityManager.add_level`, `add_level_file`, `remove_level_file`, `remove_level`, `move_level` (Task 3); `_cue_markers_send`/target-context (existing).

- [ ] **Step 1: Level-send store bridge**

In `cue_lib/markers.py`, add (replacing/alongside `_cue_send_folder_to_video`):

```python
def _cue_send_level_to_target(group, ilevel_id):
    # type: (str, int) -> None
    """Set igroup/ilevel_id on the resolved target context's active pool."""
    ctx = getattr(_cue.markers, _cue.markers.resolve_target_context())
    key = ctx._key()
    pool = _cue.markers._ensure_pool(key, ctx.get_active_index())
    pool["igroup"] = group
    pool["ilevel_id"] = ilevel_id
    pool["files"] = []
    _cue.markers._db_save_marker(key)
```

Guard so it no-ops when the resolved target is image/dialogue (see Step 3; the screen disables the button, but keep a safety check here too).

- [ ] **Step 2: `[+ Level]` + per-level add-files state**

In `CueSfxLibraryTree` (`sfx_manager.py`), replace `igroup_add_target` (a group name) with `ilevel_add_target` holding `(group_name, ilevel_id)`, plus `expanded_ilevels` (`group_name -> set of ilevel_id`) for auto-expanding a freshly added level. Add a `add_level` store-bridge method on the tree that calls `_cue.intensity.add_level` and records the id for auto-expansion.

- [ ] **Step 3: Rewrite the igroup/level screens**

In `sfx_library.rpy`:

- Group row: `[x] delete` · `[name]` (drop the old `[folder-plus]` add-mode button from the group row).
- Below the group row, when expanded, an indented `[+ Level]` button (mirrors `[+ Group]` under "Intensity Groups/"): `Function(_cue.intensity.add_level, _gname)`; on success it auto-expands the new level.
- Level row renders the level's `files` (via `level_files(_gname, _idx+1)`), each file with preview + remove (`Function(_cue.intensity.remove_level_file, _gname, _lv_id, _file)`); empty level shows `"Click the folder icon to add files"`.
- Level row keeps `[x] remove` (`remove_level`), `[↑]`/`[↓]` (`move_level`).
- The add-files toggle (`[folder-plus]`) moves to the level row; clicking it sets `ilevel_add_target = (_gname, _lv_id)`.
- The `[+]` add-to-target button (old `[V]`) calls `_cue_send_level_to_target(_gname, _lv_id)`; disable it when `_cue.markers.resolve_target_context()` is `CueContextType.IMAGE` or `CueContextType.DIALOGUE` (use the same availability check as `_cue_markers_send`, plus the image/dialogue exclusion).
- The audio tree's `[+]` (`cue_file_tree`, line 429-442): when `ilevel_add_target` is set, clicking a folder/file appends to the level's files (`_cue.intensity.add_level_file`) instead of sending to the pool; when unset, unchanged.

Update `_cue_filter_igroup_folders` (util.py) to return the levels with their files so the screen can render the list, and `_cue_igroup_search_matches` to match level files.

- [ ] **Step 4: Harness tests (real engine)**

In `test_game/templates/testcases_modern.rpy` and `testcases_legacy.rpy`, add testcases that: create an igroup, `add_level`, `add_level_file`, hook a video pool via `_cue_send_level_to_target`, and assert the pool dict carries `igroup`/`ilevel_id`. Run via `/test-harness`.

- [ ] **Step 5: Lint + full suite + harness + commit**

Run: `/lint`, `/test`, `/test-harness`.
Expected: CLEAN / PASS / PASS.

```bash
git add -A
git commit -m "feat(intensity): levels-as-pools UI with target-aware level hooking"
```

---

## Self-Review

- **Spec coverage:** data model (Task 1), stable ids (Task 3), ramp-derived multipliers (Task 3 `level_multipliers`), resolution semantics incl. `enabled`/`sfx_levels` off → pinned level (Task 3), `ResolvedPool` surfacing (Task 2), call sites incl. loops (Task 3), folder-hook deletion (Task 3), migrations (Task 4), UI incl. `[+ Level]` below the group row and target-aware `[+]` disabled for image/dialogue (Task 5). All sections covered.
- **Placeholder scan:** none — each step names the file/line and gives concrete code or an exact porting instruction.
- **Type consistency:** `LevelDict.id: int`, `PoolDict.ilevel_id: int`, `ResolvedPool.ilevel_id: Optional[int]`, `CueIntensityManager.add_level -> Optional[int]`, `level_files_by_id(name, ilevel_id)`, `resolve_pool_intensity(igroup, ilevel_id, ...)`, `pool_hooks: List[Tuple[Optional[str], Optional[int]]]` — consistent across tasks.
