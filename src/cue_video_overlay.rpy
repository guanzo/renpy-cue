###############################################################################
# Shared video utilities used by the speed resolver and video editor.
###############################################################################

init -999 python:
    import os as _os
    import time as _time

    # ------------------------------------------------------------------
    # Variant path helpers (used by resolver + UI)
    # ------------------------------------------------------------------

    def _cue_speed_variant_path(base_path, speed):
        """Build the virtual path for a speed variant.
        Example: 'movies/ep1.webm' + 1.5 -> 'movies/ep1.1.5x.webm'"""
        base, ext = _os.path.splitext(base_path)
        if not ext:
            ext = ".webm"
        return "{}.{:.1f}x{}".format(base, speed, ext)

    def _cue_is_speed_variant_of(path, base_path):
        """True if path is base_path itself or a speed variant of it
        (movies/ep1.webm -> movies/ep1.2.0x.webm)."""
        if not path or not base_path:
            return False
        if path == base_path:
            return True
        base, ext = _os.path.splitext(base_path)
        if not ext:
            ext = ".webm"
        if not (path.startswith(base + ".") and path.endswith("x" + ext)):
            return False
        middle = path[len(base) + 1:-len("x" + ext)]
        try:
            sp = float(middle)
        except ValueError:
            return False
        return 0.25 <= sp <= 4.0

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
        return speeds

    # ------------------------------------------------------------------
    # Speed presets (used by Video Editor UI)
    # ------------------------------------------------------------------

    def _cue_get_preset_speeds():
        """Return hardcoded speed presets (no 1.0)."""
        return python_list([0.5, 1.5, 2.0])

    def _cue_delete_speed_variant(base_path, speed):
        """Delete a speed variant file from disk. If the variant is currently
        playing, switches to the 1.0x original first so the file handle is
        released before deletion."""
        if abs(speed - 1.0) < 0.05:
            return  # cannot delete the original

        vpath = _cue_speed_variant_path(base_path, speed)

        # If this variant is currently playing, switch to the 1.0x
        # original first.  This releases the file handle so the delete
        # won't fail with a lock error on Windows.
        try:
            import renpy.audio.audio as _aaudio
            for _ch_name in _aaudio.channels:
                _playing = renpy.music.get_playing(channel=_ch_name)
                if _playing:
                    _playing_fs = _os.path.join(renpy.config.gamedir, _playing)
                    _target_fs = _os.path.join(renpy.config.gamedir, vpath)
                    if _os.path.normpath(_playing_fs) == _os.path.normpath(_target_fs):
                        # Switch to the original 1.0x file — stops the
                        # variant and releases its file handle.
                        renpy.music.play(
                            base_path,
                            channel=_ch_name,
                            loop=True,  # video channels always loop
                            fadeout=0,
                            synchro_start=True,
                        )
        except Exception:
            pass

        # Update speed prefs before deleting so the resolver falls back
        # to 1.0x on the next interaction.
        for tag, bp in _cue.resolver_paths.items():
            if bp == base_path:
                key = _cue_resolver_key_for(tag)
                cur = _cue.speed_prefs.get(key, 1.0)
                if abs(cur - speed) < 0.05:
                    _cue.speed_prefs[key] = 1.0

        tag = _cue.current_file
        if tag:
            key = _cue_resolver_key_for(tag)
            cur = _cue.speed_prefs.get(key, 1.0)
            if abs(cur - speed) < 0.05:
                _cue.speed_prefs[key] = 1.0

        # Now delete the variant file with a few retries in case the
        # file handle takes a moment to release (Windows especially).
        fspath = _os.path.join(renpy.config.gamedir, vpath)
        deleted = False
        for _attempt in range(4):
            try:
                if _os.path.exists(fspath):
                    _os.remove(fspath)
                deleted = True
                break
            except Exception:
                if _attempt < 3:
                    _time.sleep(0.5)

        if not deleted:
            _cue_log("DELETE-VARIANT: all attempts failed to remove {}".format(fspath))
            return

        # Clear resolver cache entries for tags that use this base_path
        # so stale variant Movies aren't reused.
        for tag, bp in _cue.resolver_paths.items():
            if bp == base_path:
                _cue.resolver_children.pop((tag, speed), None)

        _cue_log("DELETE-VARIANT: removed {} (speed={:.1f}x)".format(vpath, speed))
        renpy.restart_interaction()
