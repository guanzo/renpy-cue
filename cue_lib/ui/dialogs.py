# -*- coding: utf-8 -*-
# Python logic backing the overlay UI screens.
# Dialog state classes and preset confirmation/apply helper functions.

import renpy
from renpy.store import Function

from cue_lib.state import _cue
from cue_lib.util import create_vid_key

MYPY = False
if MYPY:
    from typing import Callable


class CuePresetDialog(object):
    """Self-contained state for the Save Preset popup (SFX + music).

    The target discriminates the save: `trigger_key`/`pool_idx` names an SFX
    pool, `music_key`/`songs` names a music trigger.  Exactly one is set while
    the popup is open; commit() dispatches on whichever is."""
    def __init__(self):
        self.trigger_key = None
        self.pool_idx = 0
        self.name = ""
        self.music_key = None
        self.songs = []

    def open(self, trigger_key, pool_idx):
        # type: (str, int) -> None
        """Open the popup for an SFX pool (detached so the save is atomic)."""
        entry = _cue.markers.get(trigger_key)
        if entry is None:
            return
        pools = entry.get("pools", [])
        if pool_idx >= len(pools):
            return
        _cue.markers._detach_pool(trigger_key, pool_idx)
        self.trigger_key = trigger_key
        self.pool_idx = pool_idx
        self.music_key = None
        self.songs = []
        self.name = ""
        renpy.show_screen("cue_save_preset_dialog", _layer="cue_layer")

    def open_music(self, music_key):
        # type: (str) -> None
        """Open the popup for a music trigger's song list.

        The song list is captured at open time; empty triggers don't open."""
        songs = _cue.music.songs_for_trigger(music_key)
        if not songs:
            return
        self.music_key = music_key
        self.songs = list(songs)
        self.trigger_key = None
        self.name = ""
        renpy.show_screen("cue_save_preset_dialog", _layer="cue_layer")

    def commit(self):
        # type: () -> None
        name = self.name.strip()
        if name:
            if self.music_key is not None:
                _cue.music.create_preset(name, self.songs)
            elif self.trigger_key is not None:
                entry = _cue.markers.get(self.trigger_key)
                if entry:
                    pools = entry.get("pools", [])
                    if self.pool_idx < len(pools):
                        _cue.markers.create_preset(name, pools[self.pool_idx])
        self._reset()
        renpy.hide_screen("cue_save_preset_dialog", layer="cue_layer")

    def cancel(self):
        # type: () -> None
        self._reset()
        renpy.hide_screen("cue_save_preset_dialog", layer="cue_layer")

    def _reset(self):
        # type: () -> None
        self.trigger_key = None
        self.music_key = None
        self.songs = []


class CueVideoPresetDialog(object):
    """Self-contained state for the Save Video Preset popup."""
    def __init__(self):
        self.name = ""

    def open(self):
        # type: () -> None
        vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
        if not vid_key:
            return
        entry = _cue.markers.get(vid_key)
        if entry is None:
            return
        pools = entry.get("pools", [])
        if not pools:
            return
        self.name = ""
        renpy.show_screen("cue_save_video_preset_dialog", _layer="cue_layer")

    def commit(self):
        # type: () -> None
        name = self.name.strip()
        if name:
            vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
            if vid_key:
                entry = _cue.markers.get(vid_key)
                if entry:
                    _cue.markers.create_video_preset(name, entry)
        renpy.hide_screen("cue_save_video_preset_dialog", layer="cue_layer")

    def cancel(self):
        # type: () -> None
        renpy.hide_screen("cue_save_video_preset_dialog", layer="cue_layer")


class CueConfirmDialog(object):
    """Reusable confirmation popup matching the overlay UI style."""
    def __init__(self):
        self.message = ""
        self.on_confirm = None

    def show(self, message, confirm_action):
        # type: (str, Callable[..., None]) -> None
        self.message = message
        self.on_confirm = confirm_action
        renpy.show_screen("cue_confirm_dialog", _layer="cue_layer")

    def hide(self):
        # type: () -> None
        self.message = ""
        self.on_confirm = None
        renpy.hide_screen("cue_confirm_dialog", layer="cue_layer")


def _cue_confirm_delete_preset(preset_name):
    # type: (str) -> None
    _cue.confirm_dialog.show(
        "Delete preset '{}'?".format(preset_name),
        Function(_cue.markers.delete_preset, preset_name),
    )

def _cue_confirm_delete_video_preset(preset_name):
    # type: (str) -> None
    _cue.confirm_dialog.show(
        "Delete video preset '{}'?".format(preset_name),
        Function(_cue.markers.delete_video_preset, preset_name),
    )

def _cue_confirm_delete_music_preset(preset_name):
    # type: (str) -> None
    _cue.confirm_dialog.show(
        "Delete music preset '{}'?".format(preset_name),
        Function(_cue.music.delete_preset, preset_name),
    )

def _cue_maybe_apply_video_preset(preset_name):
    # type: (str) -> None
    out_count = _cue.markers.video_preset_out_of_range(preset_name)
    if out_count > 0:
        preset = _cue.markers.get_video_preset(preset_name)
        total = len(preset.get("pools", [])) if preset else 0
        dur = _cue.vid_manager.get_duration()
        msg = "{} of {} marker(s) won't fit (video is {:.1f}s). Apply anyway?".format(
            out_count, total, dur)
        _cue.confirm_dialog.show(
            msg,
            Function(_cue.markers.apply_video_preset, preset_name))
    else:
        _cue.markers.apply_video_preset(preset_name)
