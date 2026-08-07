###############################################################################
# Python logic backing the overlay UI screens in ui/.
# Dialog state classes, tab-action builder, file-list row counter, and
# preset/video-preset helper functions.
###############################################################################

init -999 python:
    import random as _random

    # --------------------------------------------------------------------------
    # Dialog state classes (UI state for popup dialogs)
    # --------------------------------------------------------------------------

    class CuePresetDialog:
        """Self-contained state for the Save Preset popup."""
        def __init__(self):
            self.trigger_key = None
            self.pool_idx = 0
            self.name = ""

        def open(self, trigger_key, pool_idx):
            entry = _cue.markers.get(trigger_key)
            if entry is None:
                return
            pools = entry.get("pools", [])
            if pool_idx >= len(pools):
                return
            _cue.markers._detach_pool(trigger_key, pool_idx)
            self.trigger_key = trigger_key
            self.pool_idx = pool_idx
            self.name = ""
            renpy.show_screen("cue_save_preset_dialog", _layer="cue_layer")

        def commit(self):
            name = self.name.strip()
            if name:
                entry = _cue.markers.get(self.trigger_key)
                if entry:
                    pools = entry.get("pools", [])
                    if self.pool_idx < len(pools):
                        _cue.markers.create_preset(name, pools[self.pool_idx])
            self.trigger_key = None
            renpy.hide_screen("cue_save_preset_dialog", layer="cue_layer")

        def cancel(self):
            self.trigger_key = None
            renpy.hide_screen("cue_save_preset_dialog", layer="cue_layer")

    class CueVideoPresetDialog:
        """Self-contained state for the Save Video Preset popup."""
        def __init__(self):
            self.name = ""

        def open(self):
            """Open the save dialog for the current video's pools."""
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
            """Create a video preset from the current video's pools."""
            name = self.name.strip()
            if name:
                vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
                if vid_key:
                    entry = _cue.markers.get(vid_key)
                    if entry:
                        _cue.markers.create_video_preset(name, entry)
            renpy.hide_screen("cue_save_video_preset_dialog", layer="cue_layer")

        def cancel(self):
            renpy.hide_screen("cue_save_video_preset_dialog", layer="cue_layer")

    class CueConfirmDialog:
        """Reusable confirmation popup matching the overlay UI style."""
        def __init__(self):
            self.message = ""
            self.on_confirm = None  # Function() or list of actions

        def show(self, message, confirm_action):
            self.message = message
            self.on_confirm = confirm_action
            renpy.show_screen("cue_confirm_dialog", _layer="cue_layer")

        def hide(self):
            self.message = ""
            self.on_confirm = None
            renpy.hide_screen("cue_confirm_dialog", layer="cue_layer")


    def _cue_confirm_delete_preset(preset_name):
        """Show confirmation dialog for preset deletion."""
        _cue.confirm_dialog.show(
            "Delete preset '{}'?".format(preset_name),
            Function(_cue.markers.delete_preset, preset_name),
        )

    def _cue_confirm_delete_video_preset(preset_name):
        """Show confirmation dialog for video preset deletion."""
        _cue.confirm_dialog.show(
            "Delete video preset '{}'?".format(preset_name),
            Function(_cue.markers.delete_video_preset, preset_name),
        )

    def _cue_maybe_apply_video_preset(preset_name):
        """Apply a video preset, warning if markers would be dropped."""
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

    def _cue_preview_video_preset(preset_name):
        """Preview a random file from a video preset."""
        preset = _cue.markers.get_video_preset(preset_name)
        if preset is None:
            return
        all_files = []
        for pool in preset.get("pools", []):
            all_files.extend(pool.get("files", []))
        resolved = _cue_resolve_files(all_files)
        if resolved:
            f = _random.choice(resolved)
            _cue_preview_sfx(f)

    def _cue_detach_active_video_ts(*args):
        """Detach the active video pool from its preset reference.
        Called by the ✕ button on a preset folder ref in cue_file_list."""
        vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
        if not vid_key:
            return
        entry = _cue.markers.get(vid_key)
        if entry is None:
            return
        _cue.markers._detach_pool(vid_key, _cue.markers.video.target_pool)
        _cue.markers.save_persistent()

    def _cue_detach_pool_at(trigger_key, pool_index):
        """Detach a pool from its preset reference at the given trigger_key
        and pool_index. Called by the ✕ on a preset folder in cue_file_list."""
        _cue.markers._detach_pool(trigger_key, pool_index)
        _cue.markers.save_persistent()


    def _cue_make_tab_action(fn, args_tuple, pi):
        """Build Function(fn, *args_tuple, pi) — appends pi to fixed args.
        Used by cue_pool_tabs and cue_file_list to construct per-row actions
        inside a for loop, where the loop variable must be the last argument."""
        return Function(fn, *(tuple(args_tuple) + (pi,)))

    def _cue_count_file_list_rows(folder_label, folder_children, files):
        """Estimate visible rows in cue_file_list. Used to decide whether
        the viewport scroll wrapper (ymaximum 120) is needed."""
        rows = 0

        if folder_label is not None:
            rows += 1  # folder header
            if _cue.file_tree.expanded_file_refs.get(folder_label, False) and folder_children:
                rows += len(folder_children)
        for f in files:
            rows += 1  # file row or folder-ref header
            if f.endswith("/"):
                if _cue.file_tree.expanded_file_refs.get(f, False):
                    rows += len(_cue_resolve_files([f]))
        return rows
