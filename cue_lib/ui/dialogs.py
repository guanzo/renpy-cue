# -*- coding: utf-8 -*-
# Python logic backing the overlay UI screens.
# Dialog state classes and preset confirmation/apply helper functions.

import renpy
from renpy.store import Function

from cue_lib.constants import CueImportMatch
from cue_lib.importer_io import _cue_category_counts, _cue_filter_contents, _cue_merge_overwrites
from cue_lib.state import _cue
from cue_lib.util import _cue_shift_held, create_vid_key

MYPY = False
if MYPY:
    from typing import Any, Callable, Dict  # pyright: ignore[reportUnusedImport]


class CuePresetDialog(object):
    """Self-contained state for the Save Preset popup (SFX + music).

    The target discriminates the save: `marker_key`/`pool_idx` names an SFX
    pool, `music_key`/`songs` names a music trigger.  Exactly one is set while
    the popup is open; commit() dispatches on whichever is."""

    def __init__(self):
        self.marker_key = None
        self.pool_idx = 0
        self.name = ""
        self.music_key = None
        self.songs = []

    def open(self, marker_key, pool_idx):
        # type: (str, int) -> None
        """Open the popup for an SFX pool (detached so the save is atomic)."""
        entry = _cue.markers.get(marker_key)
        if entry is None:
            return
        pools = entry.get("pools", [])
        if pool_idx >= len(pools):
            return
        _cue.markers._detach_pool(marker_key, pool_idx)
        self.marker_key = marker_key
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
        self.marker_key = None
        self.name = ""
        renpy.show_screen("cue_save_preset_dialog", _layer="cue_layer")

    def commit(self):
        # type: () -> None
        name = self.name.strip()
        if name:
            if self.music_key is not None:
                _cue.music.create_preset(name, self.songs)
            elif self.marker_key is not None:
                entry = _cue.markers.get(self.marker_key)
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
        self.marker_key = None
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


class CueIntensityGroupDialog(object):
    """Self-contained state for the New / Rename Group popup.

    `renaming` holds the group being renamed (None = create).  Errors from
    the intensity manager (empty/duplicate name) are shown inline and the
    popup stays open until a valid commit or cancel."""

    def __init__(self):
        self.name = ""
        self.renaming = None
        self.error = ""

    def open(self):
        # type: () -> None
        self.name = ""
        self.renaming = None
        self.error = ""
        renpy.show_screen("cue_new_igroup_dialog", _layer="cue_layer")

    def open_rename(self, group_name):
        # type: (str) -> None
        self.name = group_name
        self.renaming = group_name
        self.error = ""
        renpy.show_screen("cue_new_igroup_dialog", _layer="cue_layer")

    def commit(self):
        # type: () -> None
        if self.renaming is not None:
            error = _cue.intensity.rename_igroup(self.renaming, self.name)
        else:
            error = _cue.intensity.create_igroup(self.name)
        if error is None:
            renpy.hide_screen("cue_new_igroup_dialog", layer="cue_layer")
            self._reset()
        else:
            self.error = error
            renpy.restart_interaction()

    def cancel(self):
        # type: () -> None
        self._reset()
        renpy.hide_screen("cue_new_igroup_dialog", layer="cue_layer")

    def _reset(self):
        # type: () -> None
        self.name = ""
        self.renaming = None
        self.error = ""


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

    def show_or_run(self, message, confirm_action):
        # type: (str, Callable[..., None]) -> None
        """Show the confirm dialog, or run the action directly when the user
        shift+clicks -- delete buttons skip confirmation that way."""
        if _cue_shift_held():
            confirm_action()
        else:
            self.show(message, confirm_action)

    def hide(self):
        # type: () -> None
        self.message = ""
        self.on_confirm = None
        renpy.hide_screen("cue_confirm_dialog", layer="cue_layer")


class CueMergeDialog(object):
    """Category picker for merging an import into live data.

    State is reset on open; confirm() hands the checked categories to the
    imports manager, which does the copy.  The imports surface is injected so
    the dialog is testable headlessly."""

    def __init__(self, imports):
        # type: (Any) -> None
        self._imports = imports
        self.imp = None
        self.checked = {}  # type: Dict[int, bool]
        self.counts = {}
        self.overwrites = []
        self.total_files = 0
        self.error = ""

    def open(self, imp):
        # type: (str) -> None
        """Open the picker for a valid, non-mismatched import."""
        entry = self._imports.import_for(imp)
        if entry is None or not entry["valid"]:
            return
        if entry["match"] == CueImportMatch.MISMATCH:
            return
        self.imp = imp
        folder = self._imports.folder_files(imp)
        self.counts = _cue_category_counts(folder)
        self.checked = dict((cat, True) for cat in self.counts)
        self.overwrites = []
        self.total_files = len(folder)
        self.error = ""
        renpy.show_screen("cue_merge_dialog", _layer="cue_layer")

    def toggle(self, cat):
        # type: (int) -> None
        if cat in self.checked:
            self.checked[cat] = not self.checked[cat]

    def is_checked(self, cat):
        # type: (int) -> bool
        return bool(self.checked.get(cat, False))

    def is_category_enabled(self, cat):
        # type: (int) -> bool
        return cat in self.checked

    def summary(self):
        # type: () -> str
        """Live merge summary: selected file count + overwrite count (against
        the real data tree, so it reflects what the merge would hit)."""
        if not self.imp:
            return ""
        folder = self._imports.folder_files(self.imp)
        checked = [cat for cat in self.checked if self.is_checked(cat)]
        filtered = _cue_filter_contents(folder, checked)
        self.overwrites = _cue_merge_overwrites(self._imports._paths.original_root, filtered)
        text = "Merge {} file(s) into your data.".format(len(filtered))
        if self.overwrites:
            plural = "s" if len(self.overwrites) != 1 else ""
            text += "\n\n{} file{} will be overwritten\n(files are backed up to data_bak).".format(
                len(self.overwrites), plural
            )
        entry = self._imports.import_for(self.imp)
        missing = (entry.get("missing") or []) if entry else []
        if missing:
            text += ("\n\n{} listed file(s) are missing from the zip and won't be merged:\n{}").format(
                len(missing), "\n".join(missing)
            )
        return text

    def cancel(self):
        # type: () -> None
        self._reset()
        renpy.hide_screen("cue_merge_dialog", layer="cue_layer")

    def confirm(self):
        # type: () -> None
        imp = self.imp
        checked = [cat for cat in self.checked if self.is_checked(cat)]
        self._reset()
        if imp:
            self._imports.merge_confirm(imp, checked)
        renpy.hide_screen("cue_merge_dialog", layer="cue_layer")

    def _reset(self):
        # type: () -> None
        self.imp = None
        self.checked = {}
        self.counts = {}
        self.overwrites = []
        self.total_files = 0
        self.error = ""


def _cue_confirm_delete_preset(preset_name):
    # type: (str) -> None
    _cue.dialogs.confirm.show_or_run(
        "Delete preset '{}'?".format(preset_name), Function(_cue.markers.delete_preset, preset_name)
    )


def _cue_confirm_delete_video_preset(preset_name):
    # type: (str) -> None
    _cue.dialogs.confirm.show_or_run(
        "Delete video preset '{}'?".format(preset_name), Function(_cue.markers.delete_video_preset, preset_name)
    )


def _cue_confirm_remove_video_preset_pool(preset_name, pool_index):
    # type: (str, int) -> None
    _cue.dialogs.confirm.show_or_run(
        "Remove this pool from video preset?\n\n{}".format(preset_name),
        Function(_cue.markers.remove_video_preset_pool, preset_name, pool_index),
    )


def _cue_confirm_delete_igroup(igroup_name):
    # type: (str) -> None
    _cue.dialogs.confirm.show_or_run(
        "Delete intensity group '{}'?".format(igroup_name), Function(_cue.intensity.delete_igroup, igroup_name)
    )


def _cue_confirm_delete_music_preset(preset_name):
    # type: (str) -> None
    _cue.dialogs.confirm.show_or_run(
        "Delete music preset '{}'?".format(preset_name), Function(_cue.music.delete_preset, preset_name)
    )


def _cue_maybe_apply_video_preset(preset_name):
    # type: (str) -> None
    out_count = _cue.markers.video_preset_out_of_range(preset_name)
    if out_count > 0:
        preset = _cue.markers.get_video_preset(preset_name)
        total = len(preset.get("pools", [])) if preset else 0
        dur = _cue.vid_manager.get_duration()
        msg = "{} of {} marker(s) won't fit (video is {:.1f}s). Apply anyway?".format(out_count, total, dur)
        _cue.dialogs.confirm.show(msg, Function(_cue.markers.apply_video_preset, preset_name))
    else:
        _cue.markers.apply_video_preset(preset_name)
