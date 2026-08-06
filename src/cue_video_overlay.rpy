###############################################################################
# Video speed overlay — uses renpy.show() on the master layer to swap the
# Movie displayable for a speed variant. Re-applied at every interaction
# boundary via start_interact_callback, so rollback is handled automatically.
# Variants must be generated via the Video Editor before they appear.
#
# Persistence: speed_pref is stored in the v: marker entry for the video.
###############################################################################

init -999 python:
    import os as _os

    # ------------------------------------------------------------------
    # Naming / disk helpers
    # ------------------------------------------------------------------

    def _cue_speed_variant_path(base_path, speed):
        """Build the virtual path for a speed variant.
        Example: 'movies/ep1.webm' + 1.5 -> 'movies/ep1.1.50x.webm'"""
        base, ext = _os.path.splitext(base_path)
        if not ext:
            ext = ".webm"
        return "{}.{:.1f}x{}".format(base, speed, ext)

    def _cue_get_available_speeds(base_path):
        """Return sorted list of speeds that have variant files on disk.
        Always includes 1.0 (the original)."""
        speeds = [1.0]
        base_dir = _os.path.dirname(_os.path.join(renpy.config.gamedir, base_path))
        base_name = _os.path.basename(base_path)
        base_no_ext, ext = _os.path.splitext(base_name)
        if not ext:
            ext = ".webm"
        try:
            for f in _os.listdir(base_dir):
                if f.startswith(base_no_ext + ".") and f.endswith("x" + ext):
                    # Extract speed from "{basename}.{speed}x{ext}"
                    middle = f[len(base_no_ext) + 1:-len("x" + ext)]
                    try:
                        sp = float(middle)
                        if 0.25 <= sp <= 4.0 and abs(sp - 1.0) > 0.05:
                            if _os.path.isfile(_os.path.join(base_dir, f)):
                                speeds.append(sp)
                    except ValueError:
                        pass
        except Exception:
            pass
        speeds.sort()
        _cue_log("SPEED-OVERLAY: available speeds for '{}' -> {}".format(
            base_name, speeds))
        return speeds

    # ------------------------------------------------------------------
    # Runtime display swap (via renpy.show on the master layer)
    # ------------------------------------------------------------------

    def _cue_resolve_path(base_path, speed):
        """Return the path to use for a given speed.
        Falls back to base_path if the variant doesn't exist."""
        if abs(speed - 1.0) < 0.05:
            return base_path
        variant = _cue_speed_variant_path(base_path, speed)
        if renpy.loadable(variant):
            return variant
        return base_path

    def _cue_apply_speed(tag):
        """Show the Movie displayable at the current speed on the master layer.
        Called on video detect and on every speed change.
        Must be called during an interaction (uses renpy.show)."""
        base_path = _cue._dynamic_tags.get(tag)
        if not base_path:
            return
        path = _cue_resolve_path(base_path, _cue._speed_pref)
        renpy.show(tag, what=renpy.display.video.Movie(play=[path]))

    # ------------------------------------------------------------------
    # Speed preference (stored in v: marker entry)
    # ------------------------------------------------------------------

    def _cue_read_speed_pref():
        """Read speed_pref from the current video's v: marker entry.
        Falls back to 1.0 if no preference is saved or the variant is missing."""
        vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
        if not vid_key:
            return None
        entry = _cue.markers.get(vid_key, {})
        pref = entry.get("speed_pref", None)
        if pref is None:
            return None
        try:
            pref = float(pref)
        except (ValueError, TypeError):
            return 1.0
        if pref < 0.25 or pref > 4.0:
            return 1.0
        # Verify the variant actually exists
        if abs(pref - 1.0) > 0.05:
            base_path = _cue._dynamic_tags.get(_cue.current_file)
            if base_path:
                variant_vpath = _cue_speed_variant_path(base_path, pref)
                if not renpy.loadable(variant_vpath):
                    return 1.0
        return pref

    def _cue_save_speed_pref(speed):
        """Save speed_pref to the current video's v: marker entry."""
        vid_key = create_vid_key(_cue.current_file) if _cue.current_file else ""
        if not vid_key:
            return
        entry = _cue.markers.setdefault(vid_key, {"timestamps": []})
        entry["speed_pref"] = speed
        _cue.markers.save_persistent()

    # ------------------------------------------------------------------
    # Speed control (called from UI buttons and key bindings)
    # ------------------------------------------------------------------

    def _cue_set_speed(speed):
        """Set the playback speed for the current video.
        Updates the saved preference and swaps the displayable on master."""
        if _cue.top_layer_type != 'movie':
            return
        tag = _cue.current_file
        if not tag:
            return
        _cue._speed_pref = speed
        _cue_save_speed_pref(speed)
        _cue_apply_speed(tag)
        renpy.restart_interaction()
        _cue_log("SPEED-OVERLAY: set speed {:.1f}x for '{}'".format(
            speed, tag))

    def _cue_cycle_speed(delta):
        """Cycle to the next/previous available speed (wrapping).
        delta = 1 for next, -1 for previous."""
        if _cue.top_layer_type != 'movie':
            return
        tag = _cue.current_file
        if not tag:
            return
        base_path = _cue._dynamic_tags.get(tag)
        if not base_path:
            return
        available = _cue_get_available_speeds(base_path)
        if len(available) <= 1:
            return
        current = _cue._speed_pref
        try:
            idx = available.index(current)
        except ValueError:
            idx = 0
        new_idx = (idx + delta) % len(available)
        _cue_set_speed(available[new_idx])

    # ------------------------------------------------------------------
    # Hook: called when a new video is detected
    # ------------------------------------------------------------------

    def _cue_on_video_detected(tag, base_path):
        """Called from _cue_refresh_context when a video appears on the
        master layer. Stores the base path and loads the saved speed pref,
        then swaps the displayable on the master layer."""
        _cue._dynamic_tags[tag] = base_path
        speed_pref = _cue_read_speed_pref()
        _cue_log(f'{speed_pref=}')
        
        if speed_pref is None:
            return
        _cue._speed_pref = speed_pref

        _cue_apply_speed(tag)
        _cue_log("SPEED-OVERLAY: video '{}' detected, speed_pref={:.1f}".format(
            tag, _cue._speed_pref))

    # ------------------------------------------------------------------
    # User speed presets (for the Video Editor preset buttons)
    # ------------------------------------------------------------------

    def _cue_get_user_speeds():
        """Return list of user-added speed presets from persistent storage."""
        try:
            data = getattr(_cue.markers, '_data', None)
            if data is not None:
                stored = data.get("video_overlay_user_speeds", None)
                if stored is not None:
                    return python_list([float(s) for s in stored])
        except Exception:
            pass
        return python_list([])

    def _cue_add_user_speed(speed):
        """Add a custom speed to the user presets list and persist."""
        speed = round(max(0.25, min(4.0, speed)), 2)
        current = _cue_get_user_speeds()
        if speed not in current and abs(speed - 1.0) > 0.05:
            current.append(speed)
            current.sort()
            try:
                _cue.markers._data["video_overlay_user_speeds"] = list(current)
                _cue.markers.save_persistent()
            except Exception:
                pass
        renpy.restart_interaction()

    def _cue_remove_user_speed(speed):
        """Remove a custom speed from the user presets list and persist."""
        current = _cue_get_user_speeds()
        filtered = python_list([s for s in current if abs(s - speed) > 0.05])
        try:
            _cue.markers._data["video_overlay_user_speeds"] = list(filtered)
            _cue.markers.save_persistent()
        except Exception:
            pass
        renpy.restart_interaction()

    def _cue_get_preset_speeds():
        """Return combined hardcoded + user speed presets (no 1.0)."""
        defaults = python_list([1.5, 2.0, 2.5])
        combined = list(defaults)
        for s in _cue_get_user_speeds():
            if s not in combined:
                combined.append(s)
        combined.sort()
        return python_list(combined)

    def _cue_get_active_speeds_for_current():
        """Return speeds that have variant files on disk for the current video.
        Always includes 1.0. Used by the speed toggle UI.
        Uses the stored base path so variant detection still works even after
        renpy.show() has replaced the Movie displayable."""
        tag = _cue.current_file
        base_path = _cue._dynamic_tags.get(tag) if tag else None
        if not base_path:
            return python_list([1.0])
        return python_list(_cue_get_available_speeds(base_path))

