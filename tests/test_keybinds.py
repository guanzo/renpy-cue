# -*- coding: utf-8 -*-
# Tests for cue_lib.keybinds -- CueKeybindsManager hotkey rebinding.
#
# The manager is a leaf: its constructor takes only the shared-config db, and
# it mutates renpy.config.keymap (mock: {}), shows/hides the capture screen,
# and persists via db.update_shared_config.  FakeDb + a per-test keymap reset
# keep it fully headless.  The _cue_keybind_* bridge functions are one-line
# delegates through the _cue singleton and are screen-only glue -- skipped.

import pytest

import renpy
import renpy.display.behavior as _behavior

import cue_lib.keybinds as _keybinds
from cue_lib.keybinds import CueKeybindsManager
from cue_lib.constants import (
    CUE_KEYMAP_TOGGLE_OVERLAY,
    CUE_KEYMAP_TOGGLE_SFX_ACTIVE,
    CUE_KEYMAP_TOGGLE_SFX_OVERLAY,
    CUE_KEYMAP_PAGE_SFX,
    CUE_KEYMAP_PAGE_MUSIC,
    CUE_KEYMAP_PAGE_IMPORT,
    CUE_KEYMAP_PAGE_SETTINGS,
    CUE_KEYMAP_QUIT_RELAUNCH,
    CUE_KEYMAP_TARGET_VIDEO,
    CUE_KEYMAP_TARGET_IMAGE,
    CUE_KEYMAP_TARGET_DIALOGUE,
    CUE_KEYMAP_TARGET_LOOP,
    CUE_SHARED_KEY_KEYBINDS,
)

from tests.fakes import FakeDb


@pytest.fixture(autouse=True)
def _clean_keymap():
    """Reset config.keymap and capture state between tests."""
    renpy.config.keymap.clear()
    yield


@pytest.fixture
def db():
    return FakeDb()


@pytest.fixture
def mgr(db):
    return CueKeybindsManager(db)


# ---------------------------------------------------------------------------
# keysym_label
# ---------------------------------------------------------------------------

def test_keysym_label_empty_is_unbound(mgr):
    assert mgr.keysym_label("") == "--"


def test_keysym_label_named_keys(mgr):
    assert mgr.keysym_label("K_BACKQUOTE") == "`"
    assert mgr.keysym_label("K_RETURN") == "Enter"
    assert mgr.keysym_label("K_SLASH") == "/"
    assert mgr.keysym_label("K_SPACE") == "Space"
    assert mgr.keysym_label("K_PAGEUP") == "PgUp"


def test_keysym_label_function_key(mgr):
    assert mgr.keysym_label("K_F5") == "F5"


def test_keysym_label_numpad(mgr):
    assert mgr.keysym_label("K_KP_PERIOD") == "Numpad PERIOD"


def test_keysym_label_single_char(mgr):
    assert mgr.keysym_label("K_x") == "X"
    assert mgr.keysym_label("K_a") == "A"


def test_keysym_label_modifiers(mgr):
    assert mgr.keysym_label("shift_K_1") == "Shift+1"
    assert mgr.keysym_label("ctrl_alt_K_F9") == "Ctrl+Alt+F9"
    assert mgr.keysym_label("meta_shift_K_z") == "Win+Shift+Z"


def test_keysym_label_no_k_returns_verbatim(mgr):
    assert mgr.keysym_label("garbage") == "garbage"


# ---------------------------------------------------------------------------
# _is_valid_keysym
# ---------------------------------------------------------------------------

def test_is_valid_keysym_accepts_valid():
    assert CueKeybindsManager._is_valid_keysym("K_F5")
    assert CueKeybindsManager._is_valid_keysym("shift_K_1")
    assert CueKeybindsManager._is_valid_keysym("ctrl_alt_K_F9")


def test_is_valid_keysym_rejects_bad_input():
    assert not CueKeybindsManager._is_valid_keysym("")
    assert not CueKeybindsManager._is_valid_keysym("garbage")    # no "K_"
    assert not CueKeybindsManager._is_valid_keysym(123)          # non-str
    assert not CueKeybindsManager._is_valid_keysym("foo_K_")     # empty key
    assert not CueKeybindsManager._is_valid_keysym("super_K_a")  # bad modifier


# ---------------------------------------------------------------------------
# get_keysym / shortcut_label / current_label
# ---------------------------------------------------------------------------

def test_get_keysym_unknown_action_returns_id(mgr):
    assert mgr.get_keysym("not_a_real_action") == "not_a_real_action"


def test_get_keysym_falls_back_to_default(mgr):
    assert mgr.get_keysym(CUE_KEYMAP_TOGGLE_OVERLAY) == "K_BACKQUOTE"


def test_get_keysym_reads_keymap(mgr):
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] = ["K_F1"]
    assert mgr.get_keysym(CUE_KEYMAP_TOGGLE_OVERLAY) == "K_F1"


def test_get_keysym_explicitly_unbound(mgr):
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] = []
    assert mgr.get_keysym(CUE_KEYMAP_TOGGLE_OVERLAY) == ""


def test_shortcut_label(mgr):
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_SFX_ACTIVE] = ["shift_K_3"]
    assert mgr.shortcut_label(CUE_KEYMAP_TOGGLE_SFX_ACTIVE) == "Shift+3"


def test_current_label_empty_when_not_capturing(mgr):
    assert mgr.current_label() == ""


def test_current_label_when_capturing(mgr):
    mgr.start_capture(CUE_KEYMAP_TOGGLE_OVERLAY)
    assert mgr.current_label() == "Toggle Overlay"


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

def test_setup_registers_defaults(mgr):
    mgr.setup()
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] == ["K_BACKQUOTE"]
    assert renpy.config.keymap[CUE_KEYMAP_QUIT_RELAUNCH] == ["K_F5"]
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_SFX_OVERLAY] == ["alt_K_a"]
    assert renpy.config.keymap[CUE_KEYMAP_PAGE_SFX] == ["alt_K_1"]
    assert renpy.config.keymap[CUE_KEYMAP_PAGE_MUSIC] == ["alt_K_2"]
    assert renpy.config.keymap[CUE_KEYMAP_PAGE_IMPORT] == ["alt_K_3"]
    assert renpy.config.keymap[CUE_KEYMAP_PAGE_SETTINGS] == ["alt_K_4"]
    assert len(renpy.config.keymap) == 20  # one entry per action


def test_setup_does_not_overwrite_existing(mgr):
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] = ["K_F1"]
    mgr.setup()
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] == ["K_F1"]


def test_setup_applies_saved_override(db, mgr):
    db.shared[CUE_SHARED_KEY_KEYBINDS] = {CUE_KEYMAP_TOGGLE_OVERLAY: "K_F2"}
    mgr.setup()
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] == ["K_F2"]


def test_setup_ignores_invalid_saved_override(db, mgr):
    db.shared[CUE_SHARED_KEY_KEYBINDS] = {CUE_KEYMAP_TOGGLE_OVERLAY: "garbage"}
    mgr.setup()
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] == ["K_BACKQUOTE"]


def test_setup_ignores_non_dict_saved(db, mgr):
    db.shared[CUE_SHARED_KEY_KEYBINDS] = "not a dict"
    mgr.setup()
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] == ["K_BACKQUOTE"]


def test_setup_applies_saved_unbound(db, mgr):
    """An explicitly-unbound saved override must stay unbound on restart.

    confirm_override writes "" for an action whose key was stolen when the
    victim's default is still the stolen key.  setup() used `if ks`, which
    dropped "" -- the action silently reverted to its default and the
    collision came back on the next launch."""
    db.shared[CUE_SHARED_KEY_KEYBINDS] = {CUE_KEYMAP_TOGGLE_OVERLAY: ""}
    mgr.setup()
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] == []


def test_setup_clears_keymap_cache(mgr, monkeypatch):
    calls = []
    monkeypatch.setattr(_behavior, "clear_keymap_cache", lambda: calls.append(1))
    mgr.setup()
    assert calls == [1]


def test_saved_override_applies_after_restart(cue_env):
    """Rebind -> save -> fresh manager setup (as on game restart) applies the
    persisted override instead of falling back to the default."""
    from cue_lib.db import CueDatabase

    mgr = CueKeybindsManager(cue_env.db)
    mgr.setup()
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_SFX_ACTIVE] = ["alt_K_3"]
    mgr.save()

    mgr2 = CueKeybindsManager(CueDatabase(cue_env.paths))
    mgr2.setup()
    assert mgr2.get_keysym(CUE_KEYMAP_TOGGLE_SFX_ACTIVE) == "alt_K_3"


def test_key_string_types_includes_native_str():
    """The string-type gate must accept the native str on every interpreter.

    On Ren'Py 7.x (Py2) the tuple also carries `unicode` -- the type json
    decodes to -- so saved overrides aren't rejected as invalid on restart.
    That branch is Py2-only and not exercisable here, but the gate existing
    as a tuple (rather than a bare `isinstance(x, str)`) is the guard."""
    assert str in _keybinds._KEY_STRING_TYPES
    assert CueKeybindsManager._is_valid_keysym("alt_K_3")


# ---------------------------------------------------------------------------
# visible_actions
# ---------------------------------------------------------------------------

def test_visible_actions_excludes_quit_relaunch(mgr):
    ids = [a["id"] for a in mgr.visible_actions()]
    assert CUE_KEYMAP_QUIT_RELAUNCH not in ids
    assert len(ids) == 19  # 20 actions minus quit_relaunch


def test_visible_actions_filters_debug_only(mgr, monkeypatch):
    monkeypatch.setattr(_keybinds, "CUE_DEBUG", False)
    fake = {"id": "cue_fake_debug", "default": "K_F9", "label": "Fake",
            "desc": "", "debug_only": True}
    mgr.actions = mgr.actions + [fake]
    ids = [a["id"] for a in mgr.visible_actions()]
    assert "cue_fake_debug" not in ids


def test_visible_actions_includes_debug_only_when_debug(mgr, monkeypatch):
    monkeypatch.setattr(_keybinds, "CUE_DEBUG", True)
    fake = {"id": "cue_fake_debug", "default": "K_F9", "label": "Fake",
            "desc": "", "debug_only": True}
    mgr.actions = mgr.actions + [fake]
    ids = [a["id"] for a in mgr.visible_actions()]
    assert "cue_fake_debug" in ids


def test_visible_actions_includes_plain_action(mgr):
    fake = {"id": "cue_fake_plain", "default": "K_F9", "label": "Fake", "desc": ""}
    mgr.actions = mgr.actions + [fake]
    ids = [a["id"] for a in mgr.visible_actions()]
    assert "cue_fake_plain" in ids


# ---------------------------------------------------------------------------
# start_capture / cancel_capture
# ---------------------------------------------------------------------------

def test_start_capture_sets_state(mgr):
    mgr.start_capture(CUE_KEYMAP_TOGGLE_OVERLAY)
    assert mgr._capturing_id == CUE_KEYMAP_TOGGLE_OVERLAY
    assert mgr.collision_message == ""
    assert mgr._pending_keysym == ""


def test_cancel_capture_resets_state(mgr):
    mgr.start_capture(CUE_KEYMAP_TOGGLE_OVERLAY)
    mgr.collision_message = "boom"
    mgr.cancel_capture()
    assert mgr._capturing_id == ""
    assert mgr.collision_message == ""
    assert mgr._pending_keysym == ""


# ---------------------------------------------------------------------------
# on_captured
# ---------------------------------------------------------------------------

def test_on_captured_noop_when_not_capturing(mgr):
    mgr.on_captured("K_F5")
    assert mgr._capturing_id == ""


def test_on_captured_escape_cancels(mgr):
    mgr.start_capture(CUE_KEYMAP_TOGGLE_OVERLAY)
    mgr.on_captured("K_ESCAPE")
    assert mgr._capturing_id == ""


def test_on_captured_same_key_cancels(mgr):
    mgr.start_capture(CUE_KEYMAP_TOGGLE_OVERLAY)  # default K_BACKQUOTE
    mgr.on_captured("K_BACKQUOTE")
    assert mgr._capturing_id == ""
    assert CUE_KEYMAP_TOGGLE_OVERLAY not in renpy.config.keymap  # unchanged


def test_on_captured_clean_applies_and_saves(db, mgr):
    mgr.start_capture(CUE_KEYMAP_TOGGLE_OVERLAY)
    mgr.on_captured("K_F7")
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] == ["K_F7"]
    assert mgr._capturing_id == ""
    assert db.saved[-1] == {CUE_SHARED_KEY_KEYBINDS: {CUE_KEYMAP_TOGGLE_OVERLAY: "K_F7"}}


def test_on_captured_collision_sets_pending(db, mgr):
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_SFX_ACTIVE] = ["K_F7"]
    mgr.start_capture(CUE_KEYMAP_TOGGLE_OVERLAY)
    mgr.on_captured("K_F7")
    assert mgr._capturing_id == CUE_KEYMAP_TOGGLE_OVERLAY  # still capturing
    assert mgr._pending_keysym == "K_F7"
    assert "Toggle SFX Triggers" in mgr.collision_message
    assert CUE_KEYMAP_TOGGLE_OVERLAY not in renpy.config.keymap  # not applied


# ---------------------------------------------------------------------------
# confirm_override
# ---------------------------------------------------------------------------

def test_confirm_override_applies_and_resets_others(db, mgr):
    # Toggle Active currently owns K_F7; rebind Toggle Overlay onto it.
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_SFX_ACTIVE] = ["K_F7"]
    mgr.start_capture(CUE_KEYMAP_TOGGLE_OVERLAY)
    mgr.on_captured("K_F7")
    assert mgr._pending_keysym == "K_F7"  # collision pending

    mgr.confirm_override()
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] == ["K_F7"]
    # Overridden action resets to its default (shift_K_3, no collision).
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_SFX_ACTIVE] == ["shift_K_3"]
    assert mgr._capturing_id == ""
    assert db.saved  # save() ran


def test_confirm_override_without_pending_cancels(mgr):
    mgr.start_capture(CUE_KEYMAP_TOGGLE_OVERLAY)
    mgr.confirm_override()
    assert mgr._capturing_id == ""


def test_confirm_override_unbinds_when_default_collides(db, mgr):
    """Rebinding onto a key whose victim's DEFAULT is the stolen key must
    unbind the victim -- resetting it to default would keep the collision.

    The user scenario: Toggle SFX Triggers (default shift_K_3) rebinds to
    alt_K_3, which is Open Import/Export's default."""
    mgr.setup()
    mgr.start_capture(CUE_KEYMAP_TOGGLE_SFX_ACTIVE)
    mgr.on_captured("alt_K_3")
    assert mgr._pending_keysym == "alt_K_3"  # collision with page_import

    mgr.confirm_override()
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_SFX_ACTIVE] == ["alt_K_3"]
    assert renpy.config.keymap[CUE_KEYMAP_PAGE_IMPORT] == []  # unbound, not alt_K_3
    assert db.saved  # save() ran


def test_saved_unbound_survives_restart(cue_env):
    """Full user scenario: rebind onto a default-owned key, restart, and both
    sides stick -- the thief keeps alt_K_3 and the victim stays unbound."""
    from cue_lib.db import CueDatabase

    mgr = CueKeybindsManager(cue_env.db)
    mgr.setup()
    mgr.start_capture(CUE_KEYMAP_TOGGLE_SFX_ACTIVE)
    mgr.on_captured("alt_K_3")
    mgr.confirm_override()  # save() persists alt_K_3 + "" for page_import

    # Simulate a real restart: the game rebuilds config.keymap from scratch,
    # so cue entries are absent until setup() re-registers defaults.  Without
    # this the leftover in-session keymap would mask the regression.
    renpy.config.keymap.clear()

    mgr2 = CueKeybindsManager(CueDatabase(cue_env.paths))
    mgr2.setup()
    assert mgr2.get_keysym(CUE_KEYMAP_TOGGLE_SFX_ACTIVE) == "alt_K_3"
    assert mgr2.get_keysym(CUE_KEYMAP_PAGE_IMPORT) == ""  # stays unbound


# ---------------------------------------------------------------------------
# reset_binding / save
# ---------------------------------------------------------------------------

def test_reset_binding_restores_default(db, mgr):
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] = ["K_F7"]
    mgr.reset_binding(CUE_KEYMAP_TOGGLE_OVERLAY)
    assert renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] == ["K_BACKQUOTE"]
    assert db.saved


def test_reset_binding_unknown_action_noop(mgr):
    mgr.reset_binding("nope")  # must not raise


def test_save_persists_only_non_default(db, mgr):
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_OVERLAY] = ["K_F7"]
    mgr.save()
    assert db.saved == [{CUE_SHARED_KEY_KEYBINDS: {CUE_KEYMAP_TOGGLE_OVERLAY: "K_F7"}}]


def test_save_with_all_defaults_persists_empty(db, mgr):
    mgr.setup()  # register defaults
    mgr.save()
    assert db.saved == [{CUE_SHARED_KEY_KEYBINDS: {}}]


# ---------------------------------------------------------------------------
# _find_collisions
# ---------------------------------------------------------------------------

def test_find_collisions_renpy_builtin(mgr):
    renpy.config.keymap["rollback"] = ["K_PAGEUP"]  # a Ren'Py built-in name
    owners = mgr._find_collisions("K_PAGEUP", "cue_nonexistent")
    assert owners == ["Ren'Py: rollback"]


def test_find_collisions_ignores_cue_prefixed_builtin(mgr):
    renpy.config.keymap["cue_something_builtin"] = ["K_F1"]
    assert mgr._find_collisions("K_F1", "cue_other") == []


def test_find_collisions_excludes_self(mgr):
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_SFX_ACTIVE] = ["K_F7"]
    assert mgr._find_collisions("K_F7", CUE_KEYMAP_TOGGLE_SFX_ACTIVE) == []


def test_find_collisions_cue_owner(mgr):
    renpy.config.keymap[CUE_KEYMAP_TOGGLE_SFX_ACTIVE] = ["K_F7"]
    owners = mgr._find_collisions("K_F7", CUE_KEYMAP_TOGGLE_OVERLAY)
    assert owners == ["Cue: Toggle SFX Triggers"]


# ---------------------------------------------------------------------------
# Target-context hotkeys (SFX Library [+] target selector: K_1..K_4)
# ---------------------------------------------------------------------------

def test_target_context_actions_visible(mgr):
    ids = [a["id"] for a in mgr.visible_actions()]
    assert CUE_KEYMAP_TARGET_VIDEO in ids
    assert CUE_KEYMAP_TARGET_IMAGE in ids
    assert CUE_KEYMAP_TARGET_DIALOGUE in ids
    assert CUE_KEYMAP_TARGET_LOOP in ids


def test_setup_registers_target_context_defaults(mgr):
    mgr.setup()
    assert renpy.config.keymap[CUE_KEYMAP_TARGET_VIDEO] == ["K_1"]
    assert renpy.config.keymap[CUE_KEYMAP_TARGET_IMAGE] == ["K_2"]
    assert renpy.config.keymap[CUE_KEYMAP_TARGET_DIALOGUE] == ["K_3"]
    assert renpy.config.keymap[CUE_KEYMAP_TARGET_LOOP] == ["K_4"]


def test_get_keysym_target_context_defaults(mgr):
    assert mgr.get_keysym(CUE_KEYMAP_TARGET_VIDEO) == "K_1"
    assert mgr.get_keysym(CUE_KEYMAP_TARGET_IMAGE) == "K_2"
    assert mgr.get_keysym(CUE_KEYMAP_TARGET_DIALOGUE) == "K_3"
    assert mgr.get_keysym(CUE_KEYMAP_TARGET_LOOP) == "K_4"


def test_target_context_key_rebind_and_reset(db, mgr):
    mgr.setup()
    mgr.start_capture(CUE_KEYMAP_TARGET_VIDEO)
    mgr.on_captured("K_F7")
    assert renpy.config.keymap[CUE_KEYMAP_TARGET_VIDEO] == ["K_F7"]
    mgr.reset_binding(CUE_KEYMAP_TARGET_VIDEO)
    assert renpy.config.keymap[CUE_KEYMAP_TARGET_VIDEO] == ["K_1"]


def test_target_context_collision_detects_cue_owner(mgr):
    renpy.config.keymap[CUE_KEYMAP_TARGET_LOOP] = ["K_F7"]
    owners = mgr._find_collisions("K_F7", CUE_KEYMAP_TARGET_VIDEO)
    assert owners == ["Cue: Target Loop"]
