# -*- coding: utf-8 -*-
# Runtime drivers -- overlay show/hide, context detection, tick engine, SFX playback.
# Extracted from cue_z.rpy Section 3 (init python: free functions).

import os as _os
import random as _random
import renpy
import renpy.audio.music as _music
import renpy.audio.audio as _aaudio

from renpy.store import persistent
from cue_lib.constants import CUE_SFX_CHANNEL_COUNT
from cue_lib.db import CueDatabase
from cue_lib.paths import CuePaths
from cue_lib.state import _cue, CuePage
from cue_lib.util import (
    _cue_log, _cue_ui_refresh, _cue_unwrap_displayable, _cue_get_movie_play,
    _cue_resolve_files, _cue_pick_file,
    create_img_key, create_vid_key, create_dlg_key,
    is_vid_key, is_img_key, is_dlg_key,
    get_key_file, get_key_dialogue,
)

MYPY = False
if MYPY:
    from typing import Any, List, Optional, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import MarkerEntry, PoolDict, VideoPoolDict  # pyright: ignore[reportUnusedImport]


# --------------------------------------------------------------------------
# Visibility
# --------------------------------------------------------------------------

def _cue_toggle_overlay():
    # type: () -> None
    if _cue.is_overlay_visible:
        _cue_hide_overlay()
    else:
        _cue_show_overlay()

def _cue_toggle_active():
    # type: () -> None
    _cue.trigger.active = not _cue.trigger.active
    persistent._cue["triggers_active"] = _cue.trigger.active

def _cue_toggle_exclusive_row():
    # type: () -> None
    _cue.is_exclusive_row_visible = not _cue.is_exclusive_row_visible
    persistent._cue["exclusive_row_visible"] = _cue.is_exclusive_row_visible

def _cue_set_page(page):
    # type: (int) -> None
    """Switch the overlay sidebar to the given page.

    Clicking the page that is already open is a no-op.
    """
    if _cue.overlay_active_page == page:
        return
    if page == CuePage.SETTINGS:
        _cue.setup_dir_text = _cue.paths.root
        _cue.shared_dir_error = ""
        _cue.shared_dir_success = ""
    _cue.overlay_active_page = page

@_cue_ui_refresh
def _cue_confirm_shared_dir():
    # type: () -> None
    """Validate and persist the Shared Dir input from the Settings page.

    The dir is created up front (throwaway CueDatabase) so uncreatable paths
    fail here instead of at next launch; the live db is untouched -- the new
    dir takes effect after restart.  The choice is written as a pointer file
    in the platform-default dir, so all games on this machine pick it up.
    """
    _cue.shared_dir_success = ""

    text = (_cue.setup_dir_text or "").strip()
    if not text:
        _cue.shared_dir_error = "Path cannot be empty."
        return
    path = _os.path.abspath(_os.path.normpath(_os.path.expanduser(text))).replace("\\", "/")

    try:
        probe_db = CueDatabase(CuePaths(path, getattr(renpy.config, "save_directory")))
        probe_db.open()
    except Exception as exc:
        _cue.shared_dir_error = "Could not create that directory."
        _cue_log("SHARED-DIR: open failed for {}: {}".format(path, exc))
        return

    try:
        CuePaths.save_root(path)
    except Exception as exc:
        _cue.shared_dir_error = "Could not save the directory setting."
        _cue_log("SHARED-DIR: pointer write failed for {}: {}".format(path, exc))
        return

    _cue.shared_dir_error = ""
    _cue.setup_dir_text = path
    _cue.shared_dir_success = ("Success. If you have any data in the old dir, "
                               "move it to the new dir and relaunch.")

def _cue_toggle_shake_trigger():
    # type: () -> None
    if not _cue.current_file:
        return
    shake_key = create_img_key(_cue.current_file)
    pool = _cue.markers._ensure_pool(shake_key, _cue.markers._img_target)
    resolved = _cue.markers.resolve_pool(pool)
    pool["trigger_on_shake"] = not resolved.trigger_on_shake
    _cue.markers.save_marker(shake_key)

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

def _cue_show_overlay():
    # type: () -> None
    _cue.is_overlay_visible = True
    if not _cue.available_files:
        _cue_scan_audio()
    _cue.file_tree.rebuild_tree()
    _cue_refresh_context()
    _cue.video_editor.refresh()
    renpy.show_screen("cue_overlay", _layer="cue_layer")
    renpy.restart_interaction()

def _cue_reload_presets():
    # type: () -> None
    """Re-read shared presets from disk (picks up changes from other games)."""
    _cue.markers.reload_presets()

def _cue_hide_overlay():
    # type: () -> None
    _cue.is_overlay_visible = False
    renpy.hide_screen("cue_overlay", layer="cue_layer")


# --------------------------------------------------------------------------
# Context Detection
# --------------------------------------------------------------------------

def _cue_refresh_context():
    # type: () -> None
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
    # The scene batch has now landed, so current_file is the settled scene --
    # the right moment to stamp key_after for any music that just played.
    _cue.music_manager.capture_display()
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
        changed += " dlg:{}->{}".format(_cue.prev_dialogue[:20] if _cue.prev_dialogue else "(null)",
            _cue.current_dialogue[:20] if _cue.current_dialogue else "(null)")
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
    f = file if file is not None else _cue_pick_file(files, avoid_repeats=avoid_repeats)  # type: Any
    vol = _cue.volume.get_effective(entry, key, pool_index=pool_index)
    return _cue_play_sfx(f, key, volume=vol)


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
    # type: (Any) -> None
    if _cue.vid_manager.refreshing:
        return
    _cue.vid_manager.refreshing = True
    try:
        old_ch = _cue.vid_manager.channel

        def _apply_channel(ch_name, ch_obj=None):
            # type: (str, Any) -> None
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
    # type: () -> None
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
    # type: (str) -> None
    preset = _cue.markers.get_preset(preset_name)
    if preset is None:
        return
    files = _cue_resolve_files(preset.get("files", []))
    if files:
        f = _random.choice(files)
        _cue_preview_sfx(f)


def _cue_preview_folder(folder_path, volume=1.0):
    # type: (str, float) -> None
    """Preview a random file from an SFX Library folder."""
    files = _cue_resolve_files([folder_path])
    if files:
        f = _random.choice(files)
        _cue_preview_sfx(f, volume=volume)


def _cue_preview_video_preset(preset_name):
    # type: (str) -> None
    """Preview a random file from a video preset (across all pools)."""
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


# --------------------------------------------------------------------------
# SFX Playback
# --------------------------------------------------------------------------

def _cue_preview_sfx(filename, volume=1.0):
    # type: (str, float) -> None
    prev_ch = _cue._preview_channel
    if prev_ch is not None and _music.is_playing(channel=prev_ch):
        _music.stop(channel=prev_ch, fadeout=0)
    _cue._preview_channel = _cue_play_sfx(filename, "preview", volume=volume)


def _cue_play_sfx(filename, source="", volume=1.0):
    # type: (str, str, float) -> Optional[str]

    # Apply +-10% volume jitter for natural variation
    MAX_JITTER = 0.1
    jitter = _random.uniform(1.0 - MAX_JITTER, 1.0 + MAX_JITTER)
    volume = volume * jitter

    base_dir = _cue.paths.audio_dir
    if not base_dir.endswith("/"):
        base_dir = base_dir + "/"
    full_path = base_dir + filename

    target_ch = None
    for i in range(1, CUE_SFX_CHANNEL_COUNT + 1):
        ch_name = "_cue_{}".format(i)
        if not _music.is_playing(channel=ch_name):
            target_ch = ch_name
            break

    if target_ch is None:
        idx = _cue._cue_next_sfx_channel
        target_ch = "_cue_{}".format(idx + 1)
        _cue._cue_next_sfx_channel = (idx + 1) % CUE_SFX_CHANNEL_COUNT
    else:
        ch_num = int(target_ch.split("_")[-1])
        _cue._cue_next_sfx_channel = ch_num % CUE_SFX_CHANNEL_COUNT

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

        _cue_log("PLAY-SFX file={} src={} ch={} jitter={} vol={:.2f}".format(
            filename.rsplit("/", 1)[-1], source, target_ch, jitter, volume))

        return target_ch
    except Exception:
        _cue_log("PLAY-SFX: exception during playback of {}".format(full_path))
        return None


# Quick cross-fade duration for exclusive cut-in sweeps.
CUE_EXCLUSIVE_FADE = 0.1


def _cue_fade_out_sfx(exclude_channels=None):
    # type: (Optional[List[str]]) -> int
    """Quickly fade out every SFX playing on the shared _cue_ channels,
    except the channels in exclude_channels (same-group friends).
    Returns the number of channels faded."""
    excluded = set(exclude_channels) if exclude_channels else set()
    faded = 0
    for i in range(1, CUE_SFX_CHANNEL_COUNT + 1):
        ch_name = "_cue_{}".format(i)
        if ch_name in excluded:
            continue
        if _music.is_playing(channel=ch_name):
            _music.stop(channel=ch_name, fadeout=CUE_EXCLUSIVE_FADE)
            faded += 1
    return faded


# Re-export _cue_scan_audio from util for backward-compat in overlay
from cue_lib.util import _cue_scan_audio
