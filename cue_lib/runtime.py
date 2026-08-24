# -*- coding: utf-8 -*-
# Runtime drivers -- overlay show/hide, context detection, tick engine.
# Extracted from cue_z.rpy Section 3 (init python: free functions).

import random as _random
import renpy
import renpy.audio.music as _music
import renpy.audio.audio as _aaudio
import time as _time

from cue_lib.constants import CuePage
from cue_lib.logger import _cue_logger
from cue_lib.marker_store import _cue_migrate_intensity_hooks
from cue_lib.markers import _cue_load_scalars_from_persistent
from cue_lib.state import _cue
from cue_lib.ui.displayables import CueVideoMarkerTimeline
from cue_lib.util import (
    _cue_log,
    _cue_unwrap_displayable,
    _cue_get_movie_play,
    create_img_key,
    create_vid_key,
    create_dlg_key,
)

MYPY = False
if MYPY:
    from typing import Any, Optional, Tuple  # pyright: ignore[reportUnusedImport]


# Dedup set for the TOP-LAYER-UNKNOWN debug log (which displayables have
# already been reported). Module-level so a duplicate sighting stays silent.
_cue_logged_unknown_displayables = set()

# Slow lane: work that doesn't need the 20ms tick cadence runs at most every
# CUE_SLOW_TICK_INTERVAL seconds.
CUE_SLOW_TICK_INTERVAL = 0.25
_cue_slow_tick_last = 0.0

# Quick cross-fade duration for exclusive cut-in sweeps.
CUE_EXCLUSIVE_FADE = 0.1


# --------------------------------------------------------------------------
# Visibility
# --------------------------------------------------------------------------


def _cue_toggle_overlay():
    # type: () -> None
    if _cue.is_overlay_visible:
        _cue_hide_overlay()
    else:
        _cue_show_overlay()


def _cue_set_page(page):
    # type: (int) -> None
    """Switch the overlay sidebar to the given page.

    Clicking the page that is already open is a no-op.
    """
    if _cue.overlay_active_page == page:
        return
    if page == CuePage.SETTINGS:
        _cue.settings.prepare_for_page()
    elif page == CuePage.IMPORT:
        _cue.importer.scan()
        _cue.exporter.refresh()

    _cue.overlay_active_page = page


def _cue_toggle_video_mute():
    # type: () -> None
    if not _cue.current_file:
        return
    vid_key = create_vid_key(_cue.current_file)
    entry = _cue.markers.get(vid_key, {})
    if not entry:
        return
    video_file_muted = not entry.get("video_file_muted", False)
    entry["video_file_muted"] = video_file_muted
    _cue.markers.save_marker(vid_key)
    ch = _cue.vid_manager.channel
    if ch:
        _music.set_volume(0.0 if video_file_muted else 1.0, delay=0, channel=ch)
    renpy.restart_interaction()


def _cue_toggle_intensity_flag(flag_key):
    # type: (str) -> None
    """Toggle one per-video intensity flag (enabled, sfx_levels, volume,
    frequency).  Absent fields read as on, so the first toggle turns the
    flag off."""
    if not _cue.current_file:
        return
    vid_key = create_vid_key(_cue.current_file)
    entry = _cue.markers.get(vid_key, {})
    if not entry:
        return
    flags = entry.setdefault("intensity", {})
    flags[flag_key] = not flags.get(flag_key, True)
    _cue.markers.save_marker(vid_key)
    renpy.restart_interaction()


def _cue_show_overlay():
    # type: () -> None
    _cue.is_overlay_visible = True
    if not _cue.sfx.library.files:
        _cue.sfx.library.scan()
    if not _cue.music.user_music.files:
        _cue.music.user_music.scan()
    _cue.sfx.warm_cache()

    _cue_refresh_context()
    _cue.music.library.maybe_rebuild()
    _cue.sfx.library.maybe_rebuild()
    _cue.video_editor.refresh()

    renpy.show_screen("cue_overlay", _layer="cue_layer")
    renpy.restart_interaction()


def _cue_full_reload():
    # type: () -> None
    """Reload every in-memory layer from the current effective root.

    Markers reload from the effective root (load_persistent reads
    paths.marker_dir, which follows an active import), so activating an
    import serves the package's markers instead of the live tree's.

    Idempotent: safe to call at boot, on import activate/deactivate, and after
    a restore.  Every step re-derives state from disk or the effective paths --
    none accumulates -- so any number of calls converges to the same state.
    Ends with a context refresh so the trigger drivers resolve pools against
    the freshly loaded data."""
    _cue.markers.load_persistent()
    # One-time migration: rewrite any legacy folder-hooked pools the freshly
    # loaded markers contain to explicit igroup/ilevel_id.  Idempotent --
    # hooked pools have empty files after migration, so a re-run is a no-op.
    # Runs on every reload (boot, import activate/deactivate, post-restore)
    # so a mid-session reload can never persist the legacy form.
    _cue_migrate_intensity_hooks(_cue.marker_store, _cue.intensity._load())
    _cue_load_scalars_from_persistent()
    _cue.markers.reload_presets()
    _cue.music.reload_presets()

    _cue.sfx.library.scan()
    _cue.music.user_music.scan()
    _cue.music.game_music.scan()
    _cue.sfx.warm_cache()
    _cue.sfx.library._recent.load()  # pyright: ignore[reportOptionalMemberAccess]
    _cue.music._recent.load()

    _cue.sfx.library.maybe_rebuild()
    _cue.music.library.maybe_rebuild()
    _cue.undo.reset()
    _cue.video_editor.refresh()

    _cue_refresh_context()


def _cue_hide_overlay():
    # type: () -> None
    _cue.is_overlay_visible = False
    # The marker timeline outlives the overlay (built once as a class
    # singleton), so a hide mid-drag would otherwise leave a stale in-flight
    # drag on the next show.
    CueVideoMarkerTimeline.reset_timeline_drag()
    renpy.hide_screen("cue_overlay", layer="cue_layer")


# --------------------------------------------------------------------------
# Context Detection
# --------------------------------------------------------------------------


def _cue_refresh_context():
    # type: () -> None
    try:
        _cue_refresh_context_impl()
    except Exception as exc:
        _cue_logger.log_error("REFRESH-CTX-ERR {}".format(repr(exc)))


def _cue_refresh_context_impl():
    # type: () -> None
    old_file = _cue.current_file
    old_channel = _cue.vid_manager.channel
    old_layer_type = _cue.top_layer_type

    if renpy.get_screen("say") is None:
        _cue.ctx.current_dialogue = ""
        _cue.ctx.prev_dialogue = ""

    top_name, top_type, top_d = _cue_get_top_layer()
    if top_name is None:
        return

    _cue.ctx.current_file = top_name
    _cue.ctx.top_layer_type = top_type
    _cue.ctx.top_displayable = top_d
    # The scene batch has now landed, so current_file is the settled scene --
    # the right moment to stamp key_after for any music that just played.
    _cue.music.capture_display()
    _cue_refresh_channel(displayable=top_d)
    _cue_log_context()

    changed = ""
    img_key = None
    dlg_key = None

    if _cue.current_file != old_file:
        changed += " file:{}->{}".format(old_file, _cue.current_file)
        if _cue.current_file:
            img_key = create_img_key(_cue.current_file)

        _cue.music.play_custom_music()
        _cue.trigger.loop_states = {}
        _cue.trigger.played_video_keys.clear()
        _cue.trigger._prev_eff_elapsed = -1.0
        if _cue.is_overlay_visible:
            _cue.video_editor.refresh()
        _cue.video_sequence.handle(_cue.current_file)
        _cue.speed_resolver.clear_pending()

    if _cue.vid_manager.channel != old_channel:
        changed += " ch:{}->{}".format(old_channel, _cue.vid_manager.channel)

    if _cue.current_dialogue != _cue.prev_dialogue:
        changed += " dlg:{}->{}".format(
            _cue.prev_dialogue[:20] if _cue.prev_dialogue else "(null)",
            _cue.current_dialogue[:20] if _cue.current_dialogue else "(null)",
        )
        if _cue.current_dialogue:
            dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue))

    if _cue.top_layer_type != old_layer_type:
        changed += " type:{}->{}".format(old_layer_type, _cue.top_layer_type)

    if changed:
        _cue_log("CTX-CHANGE{}".format(changed))
        _cue.trigger.fire_context(img_key, dlg_key)
        renpy.restart_interaction()

    if _cue.ctx._shake_just_happened:
        _cue.ctx._shake_just_happened = False
        if _cue.current_file:
            shake_key = create_img_key(_cue.current_file)
            if shake_key != img_key:
                _cue.trigger.fire_context(shake_key, only_shake_pools=True)


def _cue_log_context():
    # type: () -> None
    vpath = _cue.vid_manager.get_video_path()
    vname = vpath.rsplit("/", 1)[-1] if vpath else "(none)"
    playing = "?"
    if _cue.vid_manager.channel:
        try:
            playing = "1" if _music.is_playing(channel=_cue.vid_manager.channel) else "0"
        except Exception:
            _cue_log("LOG-CONTEXT: is_playing probe failed")
    _, top_type, _unused = _cue_get_top_layer()
    if top_type:
        ctx_type = top_type
    elif _cue.vid_manager.channel is not None and playing == "1":
        ctx_type = "video"
    else:
        ctx_type = "none"
    _cue_log(
        "CTX-DUMP ctx={} type={} video={} ch={} playing={} dlg=\"{}\"".format(
            _cue.current_file or "(none)",
            ctx_type,
            vname,
            _cue.vid_manager.channel or "(none)",
            playing,
            _cue.current_dialogue[:60] if _cue.current_dialogue else "(none)",
        )
    )


# --------------------------------------------------------------------------
# Image / Movie Detection (master layer scene list)
# --------------------------------------------------------------------------


def _cue_get_top_layer():
    # type: () -> Tuple[Optional[str], Optional[str], Any]
    try:
        tags = renpy.get_showing_tags(layer="master")
        if not tags:
            return None, None, None
        layers = renpy.game.context().scene_lists.layers.get("master", [])
        if not layers:
            return None, None, None
        name = layers[-1].tag
        if not name:
            return None, None, None
        entry = layers[-1]
        d = _cue_unwrap_displayable(entry.displayable)
        name = " ".join(entry.name) if entry.name else name
        import renpy.display.video as _video
        import renpy.display.im as _im

        if isinstance(d, _video.Movie):
            return name, "movie", d
        if isinstance(d, _im.Image):
            return name, "image", d
        if d is not None:
            dedup_key = (name, d.__class__.__name__)
            if dedup_key not in _cue_logged_unknown_displayables:
                _cue_logged_unknown_displayables.add(dedup_key)
                _cue_log("TOP-LAYER-UNKNOWN name={} d_class={}".format(name, d.__class__.__name__))
        return name, "image", d
    except Exception as exc:
        _cue_logger.log_error("TOP-LAYER-ERR {}".format(repr(exc)))
        return None, None, None


# --------------------------------------------------------------------------
# Channel Detection
# --------------------------------------------------------------------------


def _cue_refresh_channel(displayable=None):
    # type: (Any) -> None
    if _cue.vid_manager.refreshing:
        return
    _cue.vid_manager.refreshing = True
    try:
        old_ch = _cue.vid_manager.channel

        candidates = []
        try:
            for ch_name in _aaudio.channels:
                try:
                    ch = _aaudio.channels.get(ch_name)
                    if ch is None or not getattr(ch, 'movie', False):
                        continue
                    path = _music.get_playing(channel=ch_name)
                    dur = _music.get_duration(channel=ch_name)
                    if path and dur > 0:
                        candidates.append((ch_name, ch, path))
                except Exception:
                    _cue_log("REFRESH-CHANNEL: scan failed for {}".format(ch_name))
        except Exception:
            _cue_log("REFRESH-CHANNEL: outer scan failed")

        if candidates:
            import renpy.display.video as _video

            if displayable is not None and isinstance(displayable, _video.Movie):
                _cue_get_movie_play(displayable)
                target_path = _cue.speed_resolver.base_path_for(_cue.current_file)
                if target_path:
                    for ch_name, ch_obj, path in candidates:
                        if path == target_path or _cue.speed_resolver.is_variant_of(path, target_path):
                            _cue_apply_channel(ch_name, ch_obj, old_ch)
                            return
                _cue.vid_manager.channel = None
            else:
                ch_name, ch_obj, _ = candidates[0]
                _cue_apply_channel(ch_name, ch_obj, old_ch)
        else:
            _cue.vid_manager.channel = None
    finally:
        _cue.vid_manager.refreshing = False


def _cue_apply_channel(ch_name, ch_obj, old_ch):
    # type: (str, Any, Optional[str]) -> None
    fps = 30
    if ch_obj is not None:
        for attr in ('framerate', 'fps', 'frame_rate'):
            try:
                val = getattr(ch_obj, attr, None)  # type: Any
                if callable(val):
                    val = val()
                if val is not None and val > 0:
                    fps = int(round(val))
                    break
            except Exception:
                _cue_log("APPLY-CHANNEL: attr {} probe failed".format(attr))
    if old_ch != ch_name:
        _cue.vid_manager.reset(ch_name)
        _cue.vid_manager.set_fps(fps)
        _cue.video_editor.refresh()

    # Re-apply video mute state from marker data
    if _cue.current_file:
        vid_key = create_vid_key(_cue.current_file)
        entry = _cue.markers.get(vid_key, {})
        if entry and entry.get("video_file_muted", False):
            _music.set_volume(0.0, delay=0, channel=ch_name)


# --------------------------------------------------------------------------
# SFX Trigger Engine (Tick)
# --------------------------------------------------------------------------


def _cue_tick_trigger():
    # type: () -> None
    # Runs at 50 Hz from a screen timer.  Guard the whole body so a bad edge
    # in any collaborator logs and continues instead of wedging the mod every
    # frame (mirrors _cue_get_top_layer).
    try:
        _cue_tick_trigger_impl()
    except Exception as exc:
        _cue_logger.log_error("TICK-ERR {}".format(repr(exc)))


def _cue_tick_trigger_impl():
    # type: () -> None
    _t0 = _time.time()

    if _cue.current_file is not None:
        top_name, top_type, __ = _cue_get_top_layer()
        if top_name != _cue.current_file or top_type != _cue.top_layer_type:
            _cue_refresh_context()

    if _cue.top_layer_type == 'movie':
        _cue_refresh_channel(displayable=_cue.ctx.top_displayable)

    _cue.vid_manager.sync_paused()
    _cue.vid_manager.poll_autopause()
    _cue.video_sequence.tick()
    _cue.trigger.tick(_cue.current_file, _cue.top_layer_type or "")
    # Tick cadence + body-cost measurement live in the trigger-debug module.
    _cue.trigger._td.tick_end(_t0)

    # Slow lane: work that doesn't need the 20ms cadence runs at most every
    # 0.25s -- search-bar rebuilds and anything else deferred here.
    global _cue_slow_tick_last
    is_slow_tick = _time.time() - _cue_slow_tick_last >= CUE_SLOW_TICK_INTERVAL
    if is_slow_tick:
        _cue_slow_tick_last = _time.time()

        _cue.volume.flush_pending_saves()
        _cue_logger.flush()

        if _cue.video_editor.job_queue.has_pending:
            _cue.video_editor.job_queue.poll()

        # Background .rpa extraction completes here (not gated on processing:
        # extraction happens before a job exists).
        _cue.video_editor.poll_extract()

        for _m in (_cue.sfx.library, _cue.music.library):
            _m.maybe_rebuild()


def _cue_preview_music_preset(preset_name):
    # type: (str) -> None
    """Preview a random song from a music preset."""
    preset = _cue.music.get_preset(preset_name)
    if preset is None:
        return
    files = _cue.music.preset_display_files(preset)
    if files:
        f = _random.choice(files)
        _cue.music.library.preview(f)
