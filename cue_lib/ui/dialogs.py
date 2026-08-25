# -*- coding: utf-8 -*-
# Python logic backing the overlay UI screens.
# Dialog state classes and preset confirmation/apply helper functions.

import renpy
from renpy.store import Function

from cue_lib.constants import CueImportMatch
from cue_lib.importer_io import _cue_category_counts, _cue_filter_contents, _cue_merge_overwrites
from cue_lib.state import _cue
from cue_lib.util import _cue_shift_held, create_vid_key, _cue_log

MYPY = False
if MYPY:
    from typing import Any, Callable, Dict  # pyright: ignore[reportUnusedImport]


class CueDialogs(object):
    """Holds the overlay dialog instances and the active-dialog gate.

    cue_overlay folds each dialog screen in gated on the live active dialog
    instance, so the overlay toggle hides the active dialog without losing
    its state."""

    def __init__(
        self,
        pool_preset=None,
        music_preset=None,
        video_preset=None,
        confirm=None,
        merge=None,
        intensity=None,
        repeater=None,
    ):
        self.pool_preset = pool_preset
        self.music_preset = music_preset
        self.video_preset = video_preset
        self.confirm = confirm
        self.merge = merge
        self.intensity = intensity
        self.repeater = repeater
        self.active_dialog = None

    def show(self, dialog):
        # type: (CueDialogBase) -> None
        self.active_dialog = dialog

    def hide(self):
        # type: () -> None
        self.active_dialog = None


class CueDialogBase(object):
    """Shared plumbing for the overlay dialog popups.

    _show()/_hide() record the dialog instance on the _cue.dialogs gate
    instead of showing/hiding a screen directly, so the overlay toggle can
    fold the active dialog in without losing its state."""

    def _show(self):
        # type: () -> None
        _cue.dialogs.show(self)

    def _hide(self):
        # type: () -> None
        _cue.dialogs.hide()


class CuePoolPresetDialog(CueDialogBase):
    """Self-contained state for the Save Preset popup (SFX pool)."""

    def __init__(self):
        self.marker_key = None
        self.pool_idx = 0
        self.name = ""

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
        self.name = ""
        self._show()

    def commit(self):
        # type: () -> None
        name = self.name.strip()
        marker_key = self.marker_key
        if name and marker_key is not None:
            entry = _cue.markers.get(marker_key)
            if entry:
                pools = entry.get("pools", [])
                if self.pool_idx < len(pools):
                    _cue.markers.create_preset(name, pools[self.pool_idx])
        self._reset()
        self._hide()

    def cancel(self):
        # type: () -> None
        self._reset()
        self._hide()

    def _reset(self):
        # type: () -> None
        self.marker_key = None


class CueMusicPresetDialog(CueDialogBase):
    """Self-contained state for the Save Music Preset popup.

    The song list is captured at open time; empty triggers don't open."""

    def __init__(self):
        self.music_key = None
        self.songs = []
        self.name = ""

    def open(self, music_key):
        # type: (str) -> None
        songs = _cue.music.songs_for_trigger(music_key)
        _cue_log('songs ' + str(songs))

        if not songs:
            return
        self.music_key = music_key
        self.songs = list(songs)
        self.name = ""
        self._show()

    def commit(self):
        # type: () -> None
        name = self.name.strip()
        if name and self.music_key is not None:
            _cue.music.create_preset(name, self.songs)
        self._reset()
        self._hide()

    def cancel(self):
        # type: () -> None
        self._reset()
        self._hide()

    def _reset(self):
        # type: () -> None
        self.music_key = None
        self.songs = []


class CueVideoPresetDialog(CueDialogBase):
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
        self._show()

    def commit(self):
        # type: () -> None
        name = self.name.strip()
        if name:
            vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
            if vid_key:
                entry = _cue.markers.get(vid_key)
                if entry:
                    _cue.markers.create_video_preset(name, entry)
        self._hide()

    def cancel(self):
        # type: () -> None
        self._hide()


class CueIntensityGroupDialog(CueDialogBase):
    """Self-contained state for the New Group popup.

    Errors from the intensity manager (empty/duplicate name) are shown
    inline and the popup stays open until a valid commit or cancel."""

    def __init__(self):
        self.name = ""
        self.error = ""

    def open(self):
        # type: () -> None
        self.name = ""
        self.error = ""
        self._show()

    def commit(self):
        # type: () -> None
        error = _cue.intensity.create_igroup(self.name)
        if error is None:
            self._hide()
            self._reset()
        else:
            self.error = error
            renpy.restart_interaction()

    def cancel(self):
        # type: () -> None
        self._reset()
        self._hide()

    def _reset(self):
        # type: () -> None
        self.name = ""
        self.error = ""


class CueConfirmDialog(CueDialogBase):
    """Reusable confirmation popup matching the overlay UI style."""

    def __init__(self):
        self.message = ""
        self.on_confirm = None

    def show(self, message, confirm_action):
        # type: (str, Callable[..., None]) -> None
        self.message = message
        self.on_confirm = confirm_action
        self._show()

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
        self._hide()


class CueMergeDialog(CueDialogBase):
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
        self._show()

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
        self._hide()

    def confirm(self):
        # type: () -> None
        imp = self.imp
        checked = [cat for cat in self.checked if self.is_checked(cat)]
        self._reset()
        if imp:
            self._imports.merge_confirm(imp, checked)
        self._hide()

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
