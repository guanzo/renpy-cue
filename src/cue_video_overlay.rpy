###############################################################################
# Shared video utilities used by the speed resolver and video editor.
###############################################################################

init -999 python:
    import os as _os

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
