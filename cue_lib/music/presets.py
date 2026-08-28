# -*- coding: utf-8 -*-
# CueMusicPresetsUi -- screen-facing behavior over the shared CueMusicPresets
# collection (CRUD lives on _cue.presets.music).  Owns the Music Library's
# preset expand state; the CueMusicManager delegates preset actions to it.

import random

from cue_lib.music.refs import _cue_resolve_music_files
from cue_lib.util import _cue_shift_held, _cue_ui_refresh

MYPY = False
if MYPY:
    from typing import Any, Dict, List
    from cue_lib.music.manager import CueMusicManager


class CueMusicPresetsUi(object):
    """Music preset screen behavior: apply, display, preview, expand state.

    Split out of CueMusicManager.  Preset data + CRUD stay in the shared
    CuePresetStore.music collection; this owns the preset rows' expand state
    (presets_expanded, expanded_presets) and reaches back through _mgr for the
    trigger/store/playback pieces it composes against."""

    def __init__(self, mgr):
        # type: (CueMusicManager) -> None
        self._mgr = mgr
        self._presets = mgr._presets
        self._store = mgr._store
        self.library = mgr.library
        # Music Presets/ folder + per-preset rows in the Music Library.
        self.presets_expanded = False
        self.expanded_presets = {}  # type: Dict[str, bool]

    @_cue_ui_refresh
    def apply_preset(self, name):
        # type: (str) -> None
        """Apply a music preset to a trigger.

        Click replaces the selected trigger's song list.  Shift+Click applies
        to the scene on screen -- creating a custom trigger there first if the
        scene has none, else replacing that trigger (same as click)."""
        preset = self._presets.music.get(name)
        if preset is None:
            return
        files = preset.get("files", [])
        if _cue_shift_held():
            key = self._mgr._current_scene_key()
            if key and not self._mgr._current_scene_has_trigger(key):
                self._mgr.create_scene_trigger()
            self._set_trigger_songs(key, files)
        else:
            key = self._mgr._resolve_selection()
            self._set_trigger_songs(key or "", files)

    def _set_trigger_songs(self, key, files):
        # type: (str, List[str]) -> None
        """Replace the trigger at `key`'s song list ("" no-ops).  Mirrors
        _add_ref_to_trigger's first-song handling: adding songs to a scene
        with a recorded default disables the default."""
        if not key:
            return
        entry = self._store._get_or_create_entry(key)
        is_first_song = not entry.get("music")
        entry["music"] = list(files)
        if is_first_song and self._mgr.default_path_for(key) and not entry.get("music_default_disabled"):
            entry["music_default_disabled"] = True
        self._store.save_marker(key)

    @_cue_ui_refresh
    def preset_remove_file(self, name, display_path):
        # type: (str, str) -> None
        """Remove one file from a music preset, given its display path.

        `display_path` is what the preset rows show ("My Music/x.ogg" /
        "Game Music/bgm/x.ogg").  A direct ref is dropped outright; a file
        inside a stored folder ref materializes the folder without it
        (mirrors remove_song_from_folder_ref)."""
        preset = self._presets.music.get(name)
        if preset is None:
            return
        files = preset.get("files", [])
        if not files:
            return
        for ref in list(files):
            if not ref.endswith("/") and self.library.display_for_ref(ref) == display_path:
                files.remove(ref)
                self._presets.music.save(name)
                return
        for i, ref in enumerate(files):
            if ref.endswith("/") and display_path in self._folder_display_children(ref):
                # Children are stored-form; the display path drives the match,
                # and the surviving children splice back in as-is (no re-tag).
                resolved = [
                    r
                    for r in _cue_resolve_music_files(self.library, [ref])
                    if self.library.display_for_ref(r) != display_path
                ]
                files[i : i + 1] = resolved
                self._presets.music.save(name)
                return

    def preset_display_files(self, preset):
        # type: (Dict[str, Any]) -> List[str]
        """A preset's stored refs as concrete display paths, for its rows.

        Folder refs expand into their stored-form children, each rendered
        through display_for_ref.  Matches the rows the Music Presets/
        section renders."""
        out = []
        for ref in preset.get("files", []):
            if ref.endswith("/"):
                for child in _cue_resolve_music_files(self.library, [ref]):
                    out.append(self.library.display_for_ref(child))
            else:
                out.append(self.library.display_for_ref(ref))
        return out

    def _folder_display_children(self, folder_ref):
        # type: (str) -> List[str]
        """Display paths of the files a stored folder ref resolves to."""
        return [self.library.display_for_ref(f) for f in _cue_resolve_music_files(self.library, [folder_ref])]

    @_cue_ui_refresh
    def toggle_presets_expand(self):
        # type: () -> None
        """Flip the Music Presets/ folder in the Music Library."""
        self.presets_expanded = not self.presets_expanded
        self._mgr.save_ui_state()

    @_cue_ui_refresh
    def toggle_preset_expand(self, name):
        # type: (str) -> None
        """Flip expand/collapse for one preset's file rows."""
        if name in self.expanded_presets:
            self.expanded_presets[name] = not self.expanded_presets[name]
        else:
            self.expanded_presets[name] = True
        self._mgr.save_ui_state()

    def preview_preset(self, preset_name):
        # type: (str) -> None
        """Preview a random song from a music preset."""
        preset = self._presets.music.get(preset_name)
        if preset is None:
            return
        files = _cue_resolve_music_files(self.library, preset.get("files", []))
        if files:
            self.library.preview(random.choice(files))
