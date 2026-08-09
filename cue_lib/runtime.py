# Runtime drivers — overlay show/hide, context detection, tick engine, SFX playback.
# Extracted from cue_z.rpy Section 3 (init python: free functions).

import os
import random as _random
import time as _time
import renpy
import renpy.audio.music as _music
import renpy.audio.audio as _aaudio

from cue_lib.state import _cue
from cue_lib.util import (
    _cue_log, _cue_unwrap_displayable, _cue_get_movie_play,
    _cue_resolve_files, _cue_pick_file, _cue_format_time,
    create_img_key, create_dlg_key,
    is_vid_key, is_img_key, is_dlg_key,
    get_key_file, get_key_dialogue,
)

MYPY = False
if MYPY:
    from typing import Optional
    from cue_lib._types import MarkerEntry, PoolDict, VideoPoolDict


# --------------------------------------------------------------------------
# Visibility
# --------------------------------------------------------------------------

def _cue_TEST():
    _cue_log("TESTTTTTT")

def _cue_toggle_overlay():
    if _cue.is_overlay_visible:
        _cue_hide_overlay()
    else:
        _cue_show_overlay()

def _cue_toggle_active():
    _cue.trigger.active = not _cue.trigger.active
    _cue.markers.save_persistent()

def _cue_toggle_shake_trigger():
    if not _cue.current_file:
        return
    shake_key = create_img_key(_cue.current_file)
    pool = _cue.markers._ensure_pool(shake_key, _cue.markers._img_target)
    pool["trigger_on_shake"] = not pool.get("trigger_on_shake", False)
    _cue.markers.save_persistent()

def _cue_show_overlay():
    _cue.is_overlay_visible = True
    if not _cue.available_files:
        _cue_scan_audio()
    _cue.file_tree.rebuild_tree()
    _cue_refresh_context()
    _cue.video_editor.refresh()
    renpy.show_screen("cue_overlay", _layer="cue_layer")
    renpy.restart_interaction()

def _cue_hide_overlay():
    _cue.is_overlay_visible = False
    _cue.markers.save_persistent()
    renpy.hide_screen("cue_overlay", layer="cue_layer")


# --------------------------------------------------------------------------
# Context Detection
# --------------------------------------------------------------------------

def _cue_refresh_context():
    _cue.current_replay = renpy.store._in_replay
    old_file = _cue.current_file
    old_channel = _cue.vid_manager.channel
    old_layer_type = _cue.top_layer_type

    if renpy.get_screen("say") is None:
        _cue.current_dialogue = ""
        _cue.prev_dialogue = ""

    top_name, top_type, top_d = _cue_get_top_layer()
    if top_name is None:
        return

    _cue.current_file = top_name
    _cue.top_layer_type = top_type
    _cue.top_displayable = top_d
    _cue_refresh_channel(displayable=top_d)
    _cue.file_tree.rebuild_tree()
    _cue_log_context()

    changed = ""
    img_key = None
    dlg_key = None

    if _cue.current_file != old_file:
        changed += " file:{}->{}".format(old_file, _cue.current_file)
        if _cue.current_file:
            img_key = create_img_key(_cue.current_file)
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
        changed += " dlg:{}->{}".format(_cue.prev_dialogue[:20] if _cue.prev_dialogue else "",
            _cue.current_dialogue[:20] if _cue.current_dialogue else "")
        if _cue.current_dialogue:
            dlg_key = create_dlg_key((_cue.current_file, _cue.current_dialogue))

    if _cue.top_layer_type != old_layer_type:
        changed += " type:{}->{}".format(old_layer_type, _cue.top_layer_type)

    if changed:
        _cue_log("CTX-CHANGE{}".format(changed))
        _cue.trigger.fire_context(img_key, dlg_key)
        renpy.restart_interaction()

    if _cue._shake_just_happened:
        _cue._shake_just_happened = False
        if _cue.current_file:
            shake_key = create_img_key(_cue.current_file)
            if shake_key != img_key:
                _cue.trigger.fire_context(shake_key, only_shake_pools=True)


def _cue_log_context():
    vpath = _cue.vid_manager.get_video_path()
    vname = vpath.rsplit("/", 1)[-1] if vpath else "(none)"
    playing = "?"
    if _cue.vid_manager.channel:
        try:
            playing = "1" if _music.is_playing(channel=_cue.vid_manager.channel) else "0"
        except Exception:
            pass
    top_name, top_type, _unused = _cue_get_top_layer()
    if top_type:
        ctx_type = top_type
    elif _cue.vid_manager.channel is not None and playing == "1":
        ctx_type = "video"
    else:
        ctx_type = "none"
    _cue_log("CTX-DUMP ctx={} type={} video={} ch={} playing={} dlg=\"{}\"".format(
        _cue.current_file or "(none)", ctx_type, vname,
        _cue.vid_manager.channel or "(none)", playing,
        _cue.current_dialogue[:60] if _cue.current_dialogue else "(none)"))


def _cue_play_pool(entry, key, pool, pool_index, file=None, avoid_repeats=True):
    # type: (Optional[MarkerEntry], str, PoolDict, int, Optional[str], bool) -> Optional[str]
    resolved = _cue.markers.resolve_pool(pool)
    files = _cue_resolve_files(resolved.files)
    if not files:
        return None
    f = file if file is not None else _cue_pick_file(files, avoid_repeats=avoid_repeats)
    vol = _cue.volume.get_effective(entry, key, pool_index=pool_index)
    return _cue_play_sfx(f, key, volume=vol)


# --------------------------------------------------------------------------
# Image / Movie Detection (master layer scene list)
# --------------------------------------------------------------------------

def _cue_get_top_layer():
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
            if dedup_key not in _cue._logged_unknown_displayables:
                _cue._logged_unknown_displayables.add(dedup_key)
                _cue_log("TOP-LAYER-UNKNOWN name={} d_class={}".format(
                    name, d.__class__.__name__))
        return name, "image", d
    except Exception as exc:
        _cue_log("TOP-LAYER-ERR {}".format(repr(exc)))
        return None, None, None


# --------------------------------------------------------------------------
# Channel Detection
# --------------------------------------------------------------------------

def _cue_refresh_channel(displayable=None):
    if _cue.vid_manager.refreshing:
        return
    _cue.vid_manager.refreshing = True
    try:
        video_exts = (".webm", ".mp4", ".mkv", ".avi", ".ogv", ".mpeg", ".mpg")
        old_ch = _cue.vid_manager.channel

        def _apply_channel(ch_name, ch_obj=None):
            fps = 30
            if ch_obj is not None:
                for attr in ('framerate', 'fps', 'frame_rate'):
                    try:
                        val = getattr(ch_obj, attr, None)
                        if callable(val):
                            val = val()
                        if val is not None and val > 0:
                            fps = int(round(val))
                            break
                    except Exception:
                        pass
            if old_ch != ch_name:
                _cue.vid_manager.reset(ch_name)
                _cue.vid_manager.set_fps(fps)
                _cue.video_editor.refresh()

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
                    pass
        except Exception:
            pass

        if candidates:
            import renpy.display.video as _video
            if displayable is not None and isinstance(displayable, _video.Movie):
                _cue_get_movie_play(displayable)
                target_path = _cue.speed_resolver.base_path_for(_cue.current_file)
                if target_path:
                    for ch_name, ch_obj, path in candidates:
                        if path == target_path or _cue.speed_resolver.is_variant_of(path, target_path):
                            _apply_channel(ch_name, ch_obj)
                            return
                _cue.vid_manager.channel = None
            else:
                ch_name, ch_obj, _ = candidates[0]
                _apply_channel(ch_name, ch_obj)
        else:
            _cue.vid_manager.channel = None
    finally:
        _cue.vid_manager.refreshing = False


# --------------------------------------------------------------------------
# SFX Trigger Engine (Tick)
# --------------------------------------------------------------------------

def _cue_tick_trigger():
    if _cue.current_file is not None:
        top_name, top_type, __ = _cue_get_top_layer()
        if top_name != _cue.current_file or top_type != _cue.top_layer_type:
            _cue_refresh_context()
    if _cue.top_layer_type == 'movie':
        _cue_refresh_channel(displayable=_cue.top_displayable)
    _cue.vid_manager.sync_paused()
    if _cue.video_editor.processing:
        _cue.video_editor.job_queue.poll()
    _cue.vid_manager.poll_autopause()
    _cue.video_sequence.tick()
    _cue.trigger.tick(_cue.current_file, _cue.top_layer_type or "")


def _cue_preview_preset(preset_name):
    preset = _cue.markers.get_preset(preset_name)
    if preset is None:
        return
    files = _cue_resolve_files(preset.get("files", []))
    if files:
        f = _random.choice(files)
        _cue_preview_sfx(f)


# --------------------------------------------------------------------------
# SFX Playback
# --------------------------------------------------------------------------

def _cue_preview_sfx(filename, volume=1.0):
    prev_ch = _cue._preview_channel
    if prev_ch is not None and _music.is_playing(channel=prev_ch):
        _music.stop(channel=prev_ch, fadeout=0)
    _cue._preview_channel = _cue_play_sfx(filename, "preview", volume=volume)


def _cue_play_sfx(filename, source="", volume=1.0):
    base_dir = _cue.audio_dir
    if not base_dir.endswith("/"):
        base_dir = base_dir + "/"
    full_path = base_dir + filename

    target_ch = None
    for i in range(1, 9):
        ch_name = "_cue_{}".format(i)
        if not _music.is_playing(channel=ch_name):
            target_ch = ch_name
            break

    if target_ch is None:
        idx = _cue._cue_next_sfx_channel
        target_ch = "_cue_{}".format(idx + 1)
        _cue._cue_next_sfx_channel = (idx + 1) % 8
    else:
        ch_num = int(target_ch.split("_")[-1])
        _cue._cue_next_sfx_channel = ch_num % 8

    try:
        curr_file = _cue.current_file
        warn = None
        if is_vid_key(source):
            expected_vid = get_key_file(source)
            if expected_vid and curr_file and expected_vid != curr_file:
                warn = "expected vid={} actual vid={}".format(expected_vid, curr_file)
        elif is_img_key(source):
            expected_img = get_key_file(source)
            if expected_img and curr_file and expected_img != curr_file:
                warn = "expected img={} actual img={}".format(expected_img, curr_file)
        elif is_dlg_key(source):
            expected_img = get_key_file(source)
            expected_dlg = get_key_dialogue(source)
            cur_dlg = (_cue.current_dialogue or "")[:40]
            if expected_img != curr_file or expected_dlg != cur_dlg:
                warn = "expected img={}|{} actual img={}|{}".format(
                    expected_img, expected_dlg, curr_file, cur_dlg)
        if warn:
            _cue_log("WARN CTX-MISMATCH file={} src={} {}".format(
                filename.rsplit("/", 1)[-1], source, warn))

        if _cue._has_relative_volume:
            _music.play(full_path, channel=target_ch, loop=False, relative_volume=volume)
        else:
            _music.play(full_path, channel=target_ch, loop=False)
            _music.set_volume(volume, delay=0, channel=target_ch)

        _cue_log("PLAY-SFX file={} src={} ch={} vol={:.2f}".format(
            filename.rsplit("/", 1)[-1], source, target_ch, volume))

        return target_ch
    except Exception:
        return None


# Re-export _cue_scan_audio from util for backward-compat in overlay
from cue_lib.util import _cue_scan_audio
