# Tree Component Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the SFX Library and Music Library file-tree screens with a single shared `cue_tree_rows` renderer driven by `tree_rows()` builder methods on the audio-tree managers, with byte-identical UI output.

**Architecture:** Row dicts are data; `cue_tree_rows` renders any dict. `CueAudioTreeManager.tree_rows(*state)` walks the already-unified `visible_tree` and emits one dict per row (buttons via `row_buttons`, warn via `warn_reason`, gap via `file_gap`). SFX and music override `row_buttons`/`warn_reason` with their exact current button configs. Screens shrink to computing non-owned state and calling `tree_rows()`.

**Tech Stack:** Ren'Py 7.x (Python 2.7) + 8.x, Ren'Py screen language, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-25-tree-component-design.md`

## Global Constraints

Copy these rules verbatim into any review:

- **Ren'Py 7.4+ / Py2.7 runtime code:** no f-strings (`.format()`), no type hints (PEP 484 type comments), no `@` operator, ASCII only, classes inherit from `object`.
- **Naming:** module functions `_cue_`-prefixed, classes `Cue`-prefixed, singleton `_cue`. `.py` imports are aliased (`import foo as _foo`).
- **`Function()` actions reference only stable module-level objects.** Managers are reached through `_cue` or through `self` (constructor-injected).
- **`.pyi` stubs updated** whenever a `cue_lib/*.py` public API changes. Pyright ignores a module's own `.pyi` for self-analysis, so the `.py` needs type comments.
- **1:1 UI output.** Nothing added, removed, or reordered visually. Every button, tooltip, enabled-gate, gap, and warn icon reproduces the current UI exactly. The refactor moves where logic lives, not what it is.
- **Do NOT flatten `cue_tree_rows`** into the SFX content vbox: it is a `vbox spacing 2` and renders as one nested child. Visually identical to direct children; leave it nested.
- **TDD.** New logic ships with passing pytest. `python3 -m pytest tests/ -q` must pass. Do not reduce `cue_lib` coverage without a note.
- **Lint:** `ruff format cue_lib tests` before/after; ruff is a poetry dep, so prepend the venv: `PATH="$(poetry env info -p)/bin:$PATH" ruff check cue_lib tests`.
- **Harness:** run on both engine generations (`test_game/templates/testcases_modern.rpy` = 8.x, `testcases_legacy.rpy` = 7.x). Local SDKs in `.local/`.
- **No commits.** The user commits themselves. End every task by running its tests and presenting the diff; do not `git commit`.
- **Variadic type-comment precedent** exists: `# type: (str, *MarkerEntry) -> ...` (markers.py:146), `# type: (*Any) -> None` (markers.py:360). Use `# type: (Dict[str, Any], *Any)` for `*state` params.

## File Structure

| File | Responsibility |
|---|---|
| `cue_lib/audio/audio_tree.py` | Base `tree_rows(*state)`, `row_buttons(item, *state)` (default `[]`), `warn_reason(item, *state)` (default `""`), class attr `file_gap = 1` |
| `cue_lib/audio/sfx_manager.py` | `CueSfxLibraryTree.row_buttons(item, target_ok, target_tt, unplayable)` + `_add_row_button` + `warn_reason(item, unplayable)`; `_sfx` back-ref to parent manager |
| `cue_lib/audio/music_tree.py` | `CueCombinedMusicTree.row_buttons(item, current_file)`; `file_gap = 2` |
| `cue_lib/ui/components.rpy` | `cue_tree_rows(rows)` renderer |
| `cue_lib/ui/views/sfx_library.rpy` | `cue_file_tree` body → one `use cue_tree_rows(...)` |
| `cue_lib/ui/views/music_page.rpy` | `cue_music_tree` body → one `use cue_tree_rows(...)`; delete `_cue_music_file_tree` |
| `cue_lib/audio/{audio_tree,sfx_manager,music_tree}.pyi` | Stub the new methods |
| `tests/test_audio_tree.py`, `tests/test_music_library.py` | pytest for the builders |
| `test_game/templates/testcases_{modern,legacy}.rpy` | `tree_render` harness testcase |

---

## Task 1: Base `tree_rows` / `row_buttons` / `warn_reason` / `file_gap`

**Files:**
- Modify: `cue_lib/audio/audio_tree.py`
- Modify: `cue_lib/audio/audio_tree.pyi`
- Test: `tests/test_audio_tree.py`

**Interfaces:**
- Consumes: `CueAudioTreeManager.visible_tree` (existing flat, depth-annotated rows), `toggle_folder(full_path)`.
- Produces: `CueAudioTreeManager.tree_rows(*state) -> List[Dict[str, Any]]`, `row_buttons(item, *state) -> List[Dict[str, Any]]`, `warn_reason(item, *state) -> str`, class attr `file_gap: int`. Row dicts: `{key, type, label, depth, buttons, toggle (folder only), warn (file only), gap (file only)}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audio_tree.py`:

```python
# ==========================================================================
# tree_rows builders
# ==========================================================================


def test_tree_rows_folder_and_file_shape():
    tree = _ScanSrc(["v2/01_NormalMo.mp3", "v2/02_IntenseMo.mp3"])
    tree.scan()
    tree.expanded_folders["v2/"] = True
    tree.rebuild_tree()
    rows = tree.tree_rows()
    assert [r["type"] for r in rows] == ["folder", "file", "file"]
    folder = rows[0]
    assert folder["key"] == "tree:v2/"
    assert folder["label"] == "v2/"
    assert folder["depth"] == 0
    assert folder["buttons"] == []  # base row_buttons default
    # toggle wraps toggle_folder(full_path)
    assert folder["toggle"]._args[1] == "v2/"
    f = rows[1]
    assert f["key"] == "tree:v2/01_NormalMo.mp3"
    assert f["depth"] == 1
    assert f["gap"] == 1
    assert f["warn"] == ""
    assert f["buttons"] == []


def test_tree_rows_visible_tree_collapsed_emits_only_folder():
    tree = _ScanSrc(["v2/01_NormalMo.mp3"])
    tree.scan()  # nothing expanded -> only the top-level folder
    rows = tree.tree_rows()
    assert [r["type"] for r in rows] == ["folder"]


def test_tree_rows_ignores_search_state():
    # tree_rows is a pure reader of visible_tree (which already reflects a
    # search via rebuild_tree): it must not touch search or expand state.
    tree = _ScanSrc(["v2/01_NormalMo.mp3"])
    tree.scan()
    tree.expanded_folders["v2/"] = True
    tree.rebuild_tree()
    tree.search_query = "norm"
    before_folders = dict(tree.expanded_folders)
    rows = tree.tree_rows()
    assert [r["type"] for r in rows] == ["folder", "file"]
    assert tree.search_query == "norm"
    assert tree.expanded_folders == before_folders
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_audio_tree.py -q -k "tree_rows" -v`
Expected: FAIL with `AttributeError: 'CueAudioTreeManager' object has no attribute 'tree_rows'`.

- [ ] **Step 3: Implement the base builders**

In `cue_lib/audio/audio_tree.py`:

1. Add the import after `import time` (line 11):

```python
from renpy.store import Function
```

2. Add the class attr after `_auto_expand_roots = False`:

```python
    # null-width px before a file row's label (music overrides to 2)
    file_gap = 1
```

3. Append these methods at the end of `CueAudioTreeManager` (after `toggle_folder`):

```python
    def tree_rows(self, *state):
        # type: (*Any) -> List[Dict[str, Any]]
        """Flat row stream for the cue_tree_rows renderer: one row dict per
        visible_tree item, buttons from row_buttons(), warn from
        warn_reason(), file gap from file_gap."""
        rows = []
        for item in self.visible_tree:
            if item["type"] == "folder":
                rows.append(
                    {
                        "key": "tree:" + item["full_path"],
                        "type": "folder",
                        "label": item["name"],
                        "depth": item["depth"],
                        "buttons": self.row_buttons(item, *state),
                        "toggle": Function(self.toggle_folder, item["full_path"]),
                    }
                )
            else:
                rows.append(
                    {
                        "key": "tree:" + item["full_path"],
                        "type": "file",
                        "label": item["name"],
                        "depth": item["depth"],
                        "buttons": self.row_buttons(item, *state),
                        "warn": self.warn_reason(item, *state),
                        "gap": self.file_gap,
                    }
                )
        return rows

    def row_buttons(self, item, *state):
        # type: (Dict[str, Any], *Any) -> List[Dict[str, Any]]
        """Buttons for one tree row ([] by default; subclasses fill in)."""
        return []

    def warn_reason(self, item, *state):
        # type: (Dict[str, Any], *Any) -> str
        """Invalid-file reason for a file row's warn icon ("" = none)."""
        return ""
```

- [ ] **Step 4: Update `audio_tree.pyi`**

Add to `CueAudioTreeManager` in `cue_lib/audio/audio_tree.pyi`:

```python
    file_gap: int
```

and after `toggle_folder`:

```python
    def tree_rows(self, *state: object) -> List[Dict[str, Any]]: ...
    def row_buttons(self, item: Dict[str, Any], *state: object) -> List[Dict[str, Any]]: ...
    def warn_reason(self, item: Dict[str, Any], *state: object) -> str: ...
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_audio_tree.py -q`
Expected: PASS.

- [ ] **Step 6: Ruff + present**

Run: `ruff format cue_lib tests` then `PATH="$(poetry env info -p)/bin:$PATH" ruff check cue_lib/audio/audio_tree.py`.
Present the diff to the user for their review/commit. Do not commit.

---

## Task 2: SFX `row_buttons` / `warn_reason` + parent back-ref

**Files:**
- Modify: `cue_lib/audio/sfx_manager.py`
- Modify: `cue_lib/audio/sfx_manager.pyi`
- Test: `tests/test_audio_tree.py`

**Interfaces:**
- Consumes: Task 1 base builders. `self.ilevel_add_target`, `ilevel_add_file`, `ilevel_add_folder`, `level_has_file` (existing); `self._paths.audio_dir`; parent manager's `preview_sfx`/`preview_folder` via new `self._sfx`.
- Produces: `CueSfxLibraryTree.row_buttons(item, target_ok, target_tt, unplayable)`, `warn_reason(item, unplayable)`, private `_add_row_button(item, kind, target_ok, target_tt)`. New attr `_sfx: CueSfxManager` wired by the parent.

- [ ] **Step 1: Write the failing tests**

In `tests/test_audio_tree.py`, extend the sfx_manager import on line 26 (add `CueSfxLibraryTree`) and add the module alias:

```python
import cue_lib.audio.sfx_manager as _sfx_mod
from cue_lib.audio.sfx_manager import (
    CueSfxLibraryTree,
    CueSfxManager,
    _cue_sfx_channel_index,
    _cue_sfx_channel_name,
)
```

Append:

```python
def _sfx_tree_rows(sfx, target_ok=True, target_tt="Add to pool", unplayable=None):
    # type: (CueSfxLibraryTree, bool, str, object) -> list
    """Row stream for a two-row SFX tree (folder + file) with default state."""
    sfx.visible_tree = [
        {"type": "folder", "name": "v2/", "full_path": "v2/", "depth": 0,
         "expanded": True, "has_files": True},
        {"type": "file", "name": "a.wav", "full_path": "v2/a.wav", "depth": 1, "index": 0},
    ]
    return sfx.tree_rows(target_ok, target_tt, unplayable or {})


def test_sfx_row_buttons_normal_mode(sfx):
    folder, file_row = _sfx_tree_rows(sfx)
    assert [b["icon"] for b in folder["buttons"]] == ["play", "plus"]
    assert folder["buttons"][0]["tt"] == "Play random file from folder"
    assert folder["buttons"][0]["action"]._args[0] == sfx._sfx.preview_folder
    assert folder["buttons"][1]["tt"] == "Add to pool"
    assert folder["buttons"][1]["enabled"] is True
    assert folder["buttons"][1]["action"]._args[0] is _sfx_mod._cue_markers_send
    assert folder["buttons"][1]["action"]._args[1] == "folder"
    assert folder["buttons"][1]["action"]._args[2] == "v2/"
    assert [b["icon"] for b in file_row["buttons"]] == ["play", "plus"]
    assert file_row["buttons"][0]["tt"] == "Preview audio"
    assert file_row["buttons"][0]["action"]._args[0] == sfx._sfx.preview_sfx
    assert file_row["buttons"][1]["action"]._args[1] == "file"
    assert file_row["buttons"][1]["action"]._args[2] == 0  # file index
    assert file_row["gap"] == 1
    assert file_row["warn"] == ""


def test_sfx_row_buttons_disabled_when_target_unavailable(sfx):
    folder, file_row = _sfx_tree_rows(sfx, target_ok=False)
    assert folder["buttons"][1]["enabled"] is False
    assert file_row["buttons"][1]["enabled"] is False


def test_sfx_row_buttons_add_mode(sfx, monkeypatch):
    monkeypatch.setattr(renpy.store, "_cue_color_selected_alt", "#446688")
    sfx.ilevel_add_target = ("g", 1)
    folder, file_row = _sfx_tree_rows(sfx)
    fplus = folder["buttons"][1]
    assert fplus["tt"] == "Add this folder to Level 1 of g."
    assert fplus["enabled"] is True
    assert fplus["bg"] == "#446688"
    assert fplus["action"]._args[0] == sfx.ilevel_add_folder
    assert fplus["action"]._args[1:3] == ("g", 1)
    fplus2 = file_row["buttons"][1]
    assert fplus2["tt"] == "Add this file to Level 1 of g."
    assert fplus2["action"]._args[0] == sfx.ilevel_add_file
    assert fplus2["action"]._args[1:3] == ("g", 1)


def test_sfx_row_buttons_add_mode_dup_gates(sfx, monkeypatch):
    monkeypatch.setattr(renpy.store, "_cue_color_selected_alt", "#446688")
    sfx.ilevel_add_target = ("g", 1)
    sfx.level_has_file = lambda g, lv, ref: True  # shadow: simulate dup
    _folder, file_row = _sfx_tree_rows(sfx)
    plus = file_row["buttons"][1]
    assert plus["enabled"] is False
    assert plus["bg"] is None


def test_sfx_folder_without_files_has_only_plus(sfx):
    sfx.visible_tree = [
        {"type": "folder", "name": "empty/", "full_path": "empty/", "depth": 0,
         "expanded": False, "has_files": False},
    ]
    rows = sfx.tree_rows(False, "tt", {})
    assert [b["icon"] for b in rows[0]["buttons"]] == ["plus"]


def test_sfx_warn_reason(sfx):
    audio = sfx._paths.audio_dir
    sfx.visible_tree = [
        {"type": "file", "name": "bad.wav", "full_path": "bad.wav", "depth": 0, "index": 0},
        {"type": "file", "name": "ok.wav", "full_path": "ok.wav", "depth": 0, "index": 1},
    ]
    rows = sfx.tree_rows(True, "tt", {audio + "bad.wav": "unsupported format"})
    assert rows[0]["warn"] == "unsupported format"
    assert rows[1]["warn"] == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_audio_tree.py -q -k "row_buttons or warn_reason or folder_without" -v`
Expected: FAIL — base `row_buttons` returns `[]` so `folder["buttons"][0]` is an IndexError.

- [ ] **Step 3: Implement SFX row builders + back-ref**

In `cue_lib/audio/sfx_manager.py`:

1. Add imports (with the existing `from renpy.store import persistent` block):

```python
from renpy.store import Function
```

and with the other `cue_lib.*` imports:

```python
from cue_lib.markers import _cue_markers_send
```

2. In `CueSfxLibraryTree.__init__`, after `self._paths = paths`:

```python
        # Parent CueSfxManager, wired by CueSfxManager.__init__ (preview fns).
        self._sfx = None  # type: Any
```

3. In `CueSfxManager.__init__`, right after `self.library = CueSfxLibraryTree(paths, db)`:

```python
        self.library._sfx = self
```

4. Add these methods to `CueSfxLibraryTree` (place after `_file_node`):

```python
    def row_buttons(self, item, target_ok, target_tt, unplayable):
        # type: (Dict[str, Any], bool, str, Dict[str, str]) -> List[Dict[str, Any]]
        """SFX row buttons: [play, plus].  Plus adds to the target context, or
        in intensity add-mode appends to the active (group, level)."""
        buttons = []
        if item["type"] == "folder":
            if item.get("has_files", False):
                buttons.append(
                    {
                        "icon": "play",
                        "action": Function(self._sfx.preview_folder, item["full_path"]),
                        "tt": "Play random file from folder",
                    }
                )
            buttons.append(self._add_row_button(item, "folder", target_ok, target_tt))
        else:
            buttons.append(
                {
                    "icon": "play",
                    "action": Function(self._sfx.preview_sfx, item["full_path"]),
                    "tt": "Preview audio",
                }
            )
            buttons.append(self._add_row_button(item, "file", target_ok, target_tt))
        return buttons

    def _add_row_button(self, item, kind, target_ok, target_tt):
        # type: (Dict[str, Any], str, bool, str) -> Dict[str, Any]
        """The tree [+] button.  In intensity add-mode it appends item to the
        active (group, level) -- dup-checked, marked with the selected_alt bg;
        otherwise it sends item to the target context."""
        target = self.ilevel_add_target
        if target is not None:
            group, lv_id = target
            if kind == "folder":
                action = Function(self.ilevel_add_folder, group, lv_id, item["full_path"])
                label = "Add this folder to Level {} of {}.".format(lv_id, group)
            else:
                action = Function(self.ilevel_add_file, group, lv_id, item["full_path"])
                label = "Add this file to Level {} of {}.".format(lv_id, group)
            is_dup = self.level_has_file(group, lv_id, item["full_path"])
            return {
                "icon": "plus",
                "action": action,
                "tt": label,
                "enabled": not is_dup,
                "bg": (getattr(renpy.store, "_cue_color_selected_alt", None) if not is_dup else None),
            }
        if kind == "folder":
            return {
                "icon": "plus",
                "action": Function(_cue_markers_send, "folder", item["full_path"]),
                "tt": target_tt,
                "enabled": target_ok,
            }
        return {
            "icon": "plus",
            "action": Function(_cue_markers_send, "file", item["index"]),
            "tt": target_tt,
            "enabled": target_ok,
        }

    def warn_reason(self, item, target_ok, target_tt, unplayable):
        # type: (Dict[str, Any], bool, str, Dict[str, str]) -> str
        """Unplayable-file reason for a file row's warn icon ("" = playable).
        target_ok / target_tt ride along in tree_rows' *state but are unused
        here; only unplayable feeds the icon."""
        return unplayable.get(self._paths.audio_dir + item["full_path"], "")
```

- [ ] **Step 4: Update `sfx_manager.pyi`**

In `cue_lib/audio/sfx_manager.pyi`, add to `CueSfxLibraryTree`:

```python
    _sfx: CueSfxManager
```

and after `level_has_file`:

```python
    def row_buttons(
        self, item: Dict[str, Any], target_ok: bool, target_tt: str, unplayable: Dict[str, str]
    ) -> List[Dict[str, Any]]: ...
    def _add_row_button(
        self, item: Dict[str, Any], kind: str, target_ok: bool, target_tt: str
    ) -> Dict[str, Any]: ...
    def warn_reason(
        self, item: Dict[str, Any], target_ok: bool, target_tt: str, unplayable: Dict[str, str]
    ) -> str: ...
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_audio_tree.py -q`
Expected: PASS.

- [ ] **Step 6: Ruff + present**

Run: `ruff format cue_lib tests` then `PATH="$(poetry env info -p)/bin:$PATH" ruff check cue_lib/audio/sfx_manager.py`.
Present the diff to the user for their review/commit. Do not commit.

---

## Task 3: Music `row_buttons` + `file_gap = 2`

**Files:**
- Modify: `cue_lib/audio/music_tree.py`
- Modify: `cue_lib/audio/music_tree.pyi`
- Test: `tests/test_music_library.py`

**Interfaces:**
- Consumes: Task 1 base builders; `self._music.selected_trigger_label()`, `self._music.selected_key`; `self.add_folder_to_trigger`, `self.add_song_to_trigger`, `self.preview`.
- Produces: `CueCombinedMusicTree.row_buttons(item, current_file)`, class attr `file_gap: int` (= 2).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_music_library.py`:

```python
# ==========================================================================
# row_buttons (music tree)
# ==========================================================================


def _row_lib(sel_label="", selected_key=None, has_files=True):
    # type: (str, object, bool) -> CueCombinedMusicTree
    """Lib with a two-row visible_tree (folder + file) and a fake music mgr."""
    user = types.SimpleNamespace(tree=[], files=[], scan_error="")
    game = types.SimpleNamespace(tree=[], files=[], scan_error="")
    music = types.SimpleNamespace(
        selected_trigger_label=lambda: sel_label,
        selected_key=selected_key,
    )
    lib = CueCombinedMusicTree(music, user, game)
    lib.visible_tree = [
        {"type": "folder", "name": "My Music/", "full_path": "My Music/", "depth": 0,
         "expanded": True, "has_files": has_files},
        {"type": "file", "name": "a.ogg", "full_path": "My Music/a.ogg", "depth": 1},
    ]
    return lib


def test_music_row_buttons_plus_play_order():
    lib = _row_lib(sel_label="S1", selected_key="replay:r")
    rows = lib.tree_rows("x.ogg")
    folder, file_row = rows
    assert [b["icon"] for b in folder["buttons"]] == ["plus"]  # no play on folders
    assert folder["buttons"][0]["tt"] == "Add folder to S1"
    assert folder["buttons"][0]["enabled"] is True
    assert folder["buttons"][0]["action"]._args[0] == lib.add_folder_to_trigger
    assert folder["buttons"][0]["action"]._args[1] == "My Music/"
    assert [b["icon"] for b in file_row["buttons"]] == ["plus", "play"]
    assert file_row["buttons"][0]["tt"] == "Add song to S1"
    assert file_row["buttons"][0]["action"]._args[0] == lib.add_song_to_trigger
    assert file_row["buttons"][1]["tt"] == "Play song"
    assert file_row["buttons"][1]["action"]._args[0] == lib.preview
    assert file_row["gap"] == 2  # music gap override


def test_music_row_buttons_gates_on_selection_or_current_file():
    lib = _row_lib(sel_label="", selected_key=None)  # no selection, no current
    rows = lib.tree_rows("")
    assert rows[0]["buttons"][0]["enabled"] is False
    assert rows[1]["buttons"][0]["enabled"] is False
    lib2 = _row_lib(sel_label="", selected_key=None)
    rows2 = lib2.tree_rows("s.ogg")  # current_file alone enables
    assert rows2[0]["buttons"][0]["enabled"] is True
    lib3 = _row_lib(sel_label="", selected_key="replay:r")
    rows3 = lib3.tree_rows("")  # selected_key alone enables; default target label
    assert rows3[1]["buttons"][0]["enabled"] is True
    assert rows3[1]["buttons"][0]["tt"] == "Add song to a new trigger for the current scene"


def test_music_folder_without_files_has_no_buttons():
    lib = _row_lib(has_files=False)
    rows = lib.tree_rows("")
    assert rows[0]["buttons"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_music_library.py -q -k "row_buttons" -v`
Expected: FAIL — base `row_buttons` returns `[]`.

- [ ] **Step 3: Implement the music row builder**

In `cue_lib/audio/music_tree.py`:

1. Add the import (with the existing imports at the top):

```python
from renpy.store import Function
```

2. Add the class attr override after `_auto_expand_roots = True`:

```python
    # Music rows use a wider null gap before file labels (2px vs SFX 1px).
    file_gap = 2
```

3. Add the method (after `preview`, end of the class):

```python
    def row_buttons(self, item, current_file):
        # type: (Dict[str, Any], object) -> List[Dict[str, Any]]
        """Music row buttons: [plus, play] for files, [plus] for folders (only
        when the folder directly holds files).  Plus adds to the selected
        trigger or creates one for the current scene; disabled without either."""
        sel_label = self._music.selected_trigger_label()
        add_target = sel_label if sel_label else "a new trigger for the current scene"
        add_enabled = self._music.selected_key is not None or bool(current_file)
        buttons = []
        if item["type"] == "folder":
            if item.get("has_files", False):
                buttons.append(
                    {
                        "icon": "plus",
                        "action": Function(self.add_folder_to_trigger, item["full_path"]),
                        "tt": "Add folder to " + add_target,
                        "enabled": add_enabled,
                    }
                )
        else:
            buttons.append(
                {
                    "icon": "plus",
                    "action": Function(self.add_song_to_trigger, item["full_path"]),
                    "tt": "Add song to " + add_target,
                    "enabled": add_enabled,
                }
            )
            buttons.append(
                {
                    "icon": "play",
                    "action": Function(self.preview, item["full_path"]),
                    "tt": "Play song",
                }
            )
        return buttons
```

- [ ] **Step 4: Update `music_tree.pyi`**

In `cue_lib/audio/music_tree.pyi`, add to `CueCombinedMusicTree`:

```python
    file_gap: int
```

and after `preview`:

```python
    def row_buttons(self, item: Dict[str, Any], current_file: object) -> List[Dict[str, Any]]: ...
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_music_library.py -q`
Expected: PASS.

- [ ] **Step 6: Ruff + present**

Run: `ruff format cue_lib tests` then `PATH="$(poetry env info -p)/bin:$PATH" ruff check cue_lib/audio/music_tree.py`.
Present the diff to the user for their review/commit. Do not commit.

---

## Task 4: `cue_tree_rows` renderer + wire both screens + delete dead screen

**Files:**
- Modify: `cue_lib/ui/components.rpy` — add `cue_tree_rows`.
- Modify: `cue_lib/ui/views/sfx_library.rpy` — `cue_file_tree` body (screen at lines 472-532).
- Modify: `cue_lib/ui/views/music_page.rpy` — `cue_music_tree` body (lines 311-319); delete `_cue_music_file_tree` (comment + screen, lines 266-305).
- Modify: `test_game/templates/testcases_modern.rpy`, `test_game/templates/testcases_legacy.rpy` — add `tree_render` testcase.

**Interfaces:**
- Consumes: Task 1-3 builders. Screen state: SFX passes `(_tgt_ok, _tgt_tt, _unplayable)`; music passes `_cue.current_file`.
- Produces: `screen cue_tree_rows(rows)` — the single shared tree renderer (schema per spec).

- [ ] **Step 1: Add the renderer**

Insert before `screen _cue_file_list_vbox(` in `cue_lib/ui/components.rpy`:

```renpy
# Reusable tree: renders row dicts produced by the audio-tree managers'
# tree_rows() builders (one dict per visible row).  Folder rows expand via a
# toggle button; file rows are labels with an optional gap + warn icon.  Rows
# carry buttons in data, so the SFX and music trees share this renderer 1:1.
screen cue_tree_rows(rows):
    style_group "cue"

    default _hovered_key = None
    vbox:
        spacing 2
        for _row in rows:
            hbox:
                spacing 2
                if _row["depth"] > 0:
                    etext _cue_indent * _row["depth"]
                for _b in _row.get("buttons", []):
                    use cue_icon_btn(
                        _b["icon"],
                        _b["action"],
                        tt=_b.get("tt"),
                        enabled=_b.get("enabled", True),
                        bg=_b.get("bg"),
                        on_hover=SetLocalVariable("_hovered_key", _row["key"]),
                        on_unhover=SetLocalVariable("_hovered_key", None))
                for _hb in _row.get("hover_buttons", []):
                    if _hovered_key == _row["key"]:
                        use cue_icon_btn(
                            _hb["icon"],
                            _hb["action"],
                            tt=_hb.get("tt"),
                            enabled=_hb.get("enabled", True),
                            bg=_hb.get("bg"),
                            on_hover=SetLocalVariable("_hovered_key", _row["key"]),
                            on_unhover=SetLocalVariable("_hovered_key", None))
                if _row["type"] == "folder":
                    use cue_txt_button(
                        _row["label"],
                        _row["toggle"],
                        hovered=SetLocalVariable("_hovered_key", _row["key"]),
                        unhovered=SetLocalVariable("_hovered_key", None))
                elif _row["type"] == "file":
                    null width _row.get("gap", 1)
                    etext _row["label"] color _cue_color_text_accent
                    if _row.get("warn"):
                        use cue_icon(
                            "triangle-exclamation",
                            tt=("Invalid file: " + _row["warn"]),
                            icon_color=_cue_color_warn)
                elif _row["type"] == "action":
                    use cue_txt_button(_row["label"], _row["action"], tt=_row.get("tt"))
                elif _row["type"] == "help":
                    etext _row["label"] style "cue_help"
```

Notes: `hover_buttons` is inert in stage 1 (no builder sets it); the four-kind dispatch is included now so stage 2 only adds builders, not renderer branches. The `key` field feeds `_hovered_key`; nothing renders it in stage 1.

The `on_hover`/`on_unhover` on buttons and the folder toggle are the stage-2 hover machinery; they are visual-neutral here — the button's hover look comes from the style's `hover_background` (or `hover_bg` param), independent of the `hovered`/`unhovered` action slots, and the current SFX/music trees have no hover-driven visuals to reproduce. The warn icon deliberately carries NO hover tracking, matching today's SFX tree exactly.

- [ ] **Step 2: Rewire the SFX tree screen**

Replace the whole `screen cue_file_tree():` body in `cue_lib/ui/views/sfx_library.rpy` (lines 472-532) with:

```renpy
screen cue_file_tree():
    style_group "cue"

    $ _tgt_ok = _cue.markers.target_is_available(_cue.markers.resolve_target_context())
    $ _tgt_tt = _cue_target_assign_tt()
    $ _unplayable = _cue.sfx.unplayable_files()
    use cue_tree_rows(_cue.sfx.library.tree_rows(_tgt_ok, _tgt_tt, _unplayable))
```

- [ ] **Step 3: Rewire the music tree screen + delete the dead screen**

In `cue_lib/ui/views/music_page.rpy`:

Replace the body of `screen cue_music_tree():` (lines 311-319) with:

```renpy
screen cue_music_tree():
    style_group "cue"

    use cue_tree_rows(_cue.music.library.tree_rows(_cue.current_file))
```

Delete the whole `screen _cue_music_file_tree(...)` definition plus its docstring comment (lines 266-305). It is defined and used only here (the `use _cue_music_file_tree(...)` at old line 314 is replaced by the `use cue_tree_rows(...)` above).

- [ ] **Step 4: Add the `tree_render` harness testcase (both engines)**

Append at the end of `test_game/templates/testcases_modern.rpy` and the matching spot in `test_game/templates/testcases_legacy.rpy`:

```
testcase tree_render:
    # Every row kind cue_tree_rows draws -- folder, file (warn + gap), action,
    # help.  A compile or layout error in the shared renderer fails this.
    run Jump("start")
    $ _cue_test_reset()
    $ _rows = [
        {"key": "t1", "type": "folder", "label": "Folder/", "depth": 0,
         "buttons": [], "toggle": Function(_cue.sfx.library.toggle_folder, "Folder/")},
        {"key": "t2", "type": "file", "label": "a.wav", "depth": 1,
         "buttons": [{"icon": "play", "action": NullAction(), "tt": "Preview audio"}],
         "warn": "bad format", "gap": 1},
        {"key": "t3", "type": "action", "label": "+ Group", "depth": 0,
         "action": NullAction(), "tt": "Create a new intensity group."},
        {"key": "t4", "type": "help", "label": "No files yet.", "depth": 0},
    ]
    $ renpy.show_screen("cue_tree_rows", _rows, _layer="cue_layer")
    assert eval (renpy.get_screen("cue_tree_rows", layer="cue_layer"))
    $ renpy.hide_screen("cue_tree_rows")
```

- [ ] **Step 5: Verify on the harness (8.x)**

Run: `SDL_AUDIODRIVER=dummy xvfb-run -a bash bin/test_harness.sh .local/renpy-8.5.3-sdk/renpy.sh tree_render`
Expected: suite prints `Status: PASSED`.

- [ ] **Step 6: Verify on the harness (7.x)**

Run: `SDL_AUDIODRIVER=dummy xvfb-run -a bash bin/test_harness.sh .local/renpy-7.4.10-sdk/renpy.sh tree_render`
Expected: `Status: PASSED`.

- [ ] **Step 7: Present**

Present the diff to the user for their review/commit, including a note that the SFX and Music pages need a manual eyeball against the pre-change build (`RENPY_HEADLESS=0`) before the user commits. Do not commit.

---

## Task 5: Full verification

**Files:** none (run gates only).

- [ ] **Step 1: Full pytest**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 2: Lint + format**

Run: `ruff format cue_lib tests` then `PATH="$(poetry env info -p)/bin:$PATH" ruff check cue_lib tests`
Expected: CLEAN.

- [ ] **Step 3: Full harness (both engines)**

Run:
`SDL_AUDIODRIVER=dummy xvfb-run -a bash bin/test_harness.sh .local/renpy-8.5.3-sdk/renpy.sh`
`SDL_AUDIODRIVER=dummy xvfb-run -a bash bin/test_harness.sh .local/renpy-7.4.10-sdk/renpy.sh`
Expected: both suites PASSED (covers the real SFX-page renders of the wired tree).

- [ ] **Step 4: Manual 1:1 eyeball**

Launch with `RENPY_HEADLESS=0` and compare the SFX Library tree and Music Library tree against the current build: button order, tooltips, gaps (1px SFX / 2px music), warn icons, add-mode swap, disabled states, search behavior. Any drift is a bug in Tasks 1-3, not an acceptable outcome.

- [ ] **Step 5: Present for commit**

Summarize the change for the user; they commit each stage. Note stage-2 work (collapsible sections) is next and out of scope here.
