# -*- coding: utf-8 -*-
# Tests for cue_lib.paths -- CuePaths directory layout and root resolution.
#
# The layout properties are covered via the real CuePaths used by db/state
# tests; these tests focus on the class-level root resolution (platform
# branches, pointer file, env override) and the in-game base dir/icon paths,
# which the fixture-heavy video tests shadow with FakePathsVideo.

import os
import sys

from cue_lib.constants import CUE_DIR_OVERRIDE_FILENAME
from cue_lib.paths import CUE_MOD_DIRNAME, CuePaths


def test_in_game_base_dir_and_icon(tmp_path):
    p = CuePaths(str(tmp_path), "game1")
    assert p.in_game_base_dir == CUE_MOD_DIRNAME
    assert p.icon("x.png") == CUE_MOD_DIRNAME + "/cue_lib/images/icons/x.png"


def test_root_and_game_id_props(tmp_path):
    p = CuePaths(str(tmp_path / "root"), "mygame")
    assert p.root == str(tmp_path / "root")
    assert p.game_id == "mygame"


# ---------------------------------------------------------------------------
# Active-root swap -- import preview points every serving dir at the package
# ---------------------------------------------------------------------------

def test_original_root_stays_original_while_active_root_swaps(tmp_path):
    root = str(tmp_path / "root")
    imp = str(tmp_path / "root" / "imports" / "imp")
    p = CuePaths(root, "g1")
    assert p.original_root == root
    assert p._active_root is None
    p._active_root = imp
    assert p.root == imp
    assert p.original_root == root
    p._active_root = None
    assert p.root == root


def test_serving_dirs_follow_active_root(tmp_path):
    root = str(tmp_path / "root")
    imp = str(tmp_path / "root" / "imports" / "imp")
    p = CuePaths(root, "g1")
    p._active_root = imp
    assert p.audio_dir == imp + "/audio/"
    assert p.music_dir == imp + "/music/"
    assert p.marker_dir == os.path.join(imp, "data", "markers", "g1") + "/"
    assert p.presets_dir == os.path.join(imp, "data", "presets") + "/"
    assert p.audio_preset_dir == os.path.join(imp, "data", "presets", "audio") + "/"
    assert p.video_preset_dir == os.path.join(imp, "data", "presets", "video") + "/"
    assert p.music_preset_dir == os.path.join(imp, "data", "presets", "music") + "/"
    assert p.video_dir == os.path.join(imp, "video", "g1").replace("\\", "/") + "/"


def test_shared_config_path_never_follows_active_root(tmp_path):
    root = str(tmp_path / "root")
    imp = str(tmp_path / "root" / "imports" / "imp")
    p = CuePaths(root, "g1")
    p._active_root = imp
    assert p.shared_config_path == os.path.join(root, "data", "cue_config.json")


# ---------------------------------------------------------------------------
# platform_shared_dir -- per-OS default
# ---------------------------------------------------------------------------

def test_platform_shared_dir_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    result = CuePaths.platform_shared_dir()
    assert result.endswith(CUE_MOD_DIRNAME)
    assert ".local/share" in result


def test_platform_shared_dir_linux_xdg(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    result = CuePaths.platform_shared_dir()
    assert result == str(tmp_path / "xdg" / CUE_MOD_DIRNAME)


def test_platform_shared_dir_win32(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    result = CuePaths.platform_shared_dir()
    assert result == str(tmp_path / "AppData" / "Roaming" / CUE_MOD_DIRNAME)


def test_platform_shared_dir_darwin(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    result = CuePaths.platform_shared_dir()
    assert "Library/Application Support" in result
    assert result.endswith(CUE_MOD_DIRNAME)


# ---------------------------------------------------------------------------
# resolve_root -- pointer file, env override, platform default
# ---------------------------------------------------------------------------

def _patch_platform_dir(tmp_path, monkeypatch, subdir="platform"):
    base = tmp_path / subdir
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(CuePaths, "platform_shared_dir", lambda: str(base))
    return base


def test_resolve_root_pointer_file(tmp_path, monkeypatch):
    base = _patch_platform_dir(tmp_path, monkeypatch)
    override = tmp_path / "chosen" / "root"
    override.mkdir(parents=True)
    (base / CUE_DIR_OVERRIDE_FILENAME).write_text(str(override))
    monkeypatch.delenv("RENPY_CUE_DIR", raising=False)
    assert CuePaths.resolve_root() == os.path.normpath(str(override)).replace("\\", "/")


def test_resolve_root_empty_pointer_uses_env(tmp_path, monkeypatch):
    base = _patch_platform_dir(tmp_path, monkeypatch)
    (base / CUE_DIR_OVERRIDE_FILENAME).write_text("   ")
    monkeypatch.setenv("RENPY_CUE_DIR", str(tmp_path / "envroot"))
    assert CuePaths.resolve_root() == os.path.normpath(str(tmp_path / "envroot")).replace("\\", "/")


def test_resolve_root_pointer_unreadable_uses_env(tmp_path, monkeypatch):
    _patch_platform_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(os.path, "isfile", lambda p: True)

    def _boom(path, mode, *a, **k):
        raise OSError("unreadable pointer")
    monkeypatch.setattr("builtins.open", _boom)
    monkeypatch.setenv("RENPY_CUE_DIR", str(tmp_path / "envroot"))
    assert CuePaths.resolve_root() == os.path.normpath(str(tmp_path / "envroot")).replace("\\", "/")


def test_resolve_root_default(tmp_path, monkeypatch):
    _patch_platform_dir(tmp_path, monkeypatch)
    monkeypatch.delenv("RENPY_CUE_DIR", raising=False)
    assert CuePaths.resolve_root() == os.path.normpath(str(tmp_path / "platform")).replace("\\", "/")


# ---------------------------------------------------------------------------
# save_root -- pointer persistence + clean reset
# ---------------------------------------------------------------------------

def test_save_root_writes_pointer(tmp_path, monkeypatch):
    base = _patch_platform_dir(tmp_path, monkeypatch)
    chosen = tmp_path / "chosen"
    CuePaths.save_root(str(chosen))
    assert (base / CUE_DIR_OVERRIDE_FILENAME).read_text() == str(chosen)


def test_save_root_missing_default_dir_creates_it(tmp_path, monkeypatch):
    base = tmp_path / "platform"
    # base intentionally not created -- save_root makedirs it
    chosen = tmp_path / "chosen"
    monkeypatch.setattr(CuePaths, "platform_shared_dir", lambda: str(base))
    CuePaths.save_root(str(chosen))
    assert (base / CUE_DIR_OVERRIDE_FILENAME).read_text() == str(chosen)


def test_save_root_default_removes_pointer(tmp_path, monkeypatch):
    base = _patch_platform_dir(tmp_path, monkeypatch)
    ptr = base / CUE_DIR_OVERRIDE_FILENAME
    ptr.write_text("old")
    CuePaths.save_root(str(base))
    assert not ptr.exists()
