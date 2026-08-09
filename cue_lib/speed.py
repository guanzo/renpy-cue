# CueVidSpeedResolver -- per-tag speed preferences and variant Movie resolution.
# Wraps every Movie image in a DynamicDisplayable that swaps in speed variants
# without touching the registry entry.

import os
import time as _time
import renpy
import renpy.audio.music as _music
import renpy.config as _config
import renpy.audio.audio as _aaudio
from renpy.display.layout import DynamicDisplayable
from renpy.display.video import Movie
from renpy.display.image import images as _display_images

from cue_lib.state import _cue
from cue_lib.util import (
    _cue_log, _cue_unwrap_displayable, _cue_get_movie_play,
    create_vid_key,
)
from cue_lib.popper import _cue_clear_focus_rect

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Tuple, Type
    from cue_lib._types import MarkerEntry


class SpeedMode:
    SINGLE = "single"
    MULTI = "multi"


class CueVidSpeedResolver:
    def __init__(self):
        self.paths = {}
        self.children = {}
        self.sequence = None
        self.seamless_transition = False
        self._pending_speed = None
        self._pre_pending_speed = None

    def _get_speed_pref(self, tag):
        # type: (str) -> float
        if not tag:
            return _cue.DEFAULT_VIDEO_SPEED
        def _read(entry):
            # type: (MarkerEntry) -> float
            return entry.get("speed_pref", _cue.DEFAULT_VIDEO_SPEED)
        entry = _cue.markers.get(create_vid_key(tag))
        if entry is not None and "speed_pref" in entry:
            return _read(entry)
        best = _cue.DEFAULT_VIDEO_SPEED
        best_len = -1
        for key in self.paths:
            if key.startswith(tag + " ") and len(key) > best_len:
                e = _cue.markers.get(create_vid_key(key))
                if e is not None and "speed_pref" in e:
                    best = _read(e)
                    best_len = len(key)
        return best

    def _set_speed_pref(self, tag, speed):
        # type: (str, float) -> None
        if not tag:
            return
        entry = _cue.markers._get_or_create_entry(create_vid_key(tag))
        entry["speed_pref"] = speed
        _cue.markers.save_persistent()

    def speed_for(self, tag):
        # type: (str) -> float
        return self._get_speed_pref(tag)

    def get_current_speed(self):
        # type: () -> float
        tag = _cue.current_file
        if not tag:
            return _cue.DEFAULT_VIDEO_SPEED
        seq = self.sequence
        if seq is not None and seq.active_tag:
            speeds = seq.speeds_for(tag)
            if speeds:
                si = seq.current_step_index()
                if 0 <= si < len(speeds):
                    return speeds[si]
        return self.speed_for(tag)

    def base_path_for(self, tag):
        # type: (str) -> Optional[str]
        if not tag:
            return None
        if tag in self.paths:
            return self.paths[tag]
        for key, base in self.paths.items():
            if key.startswith(tag + " ") or tag.startswith(key + " "):
                return base
        return _cue.vid_manager.get_video_path()

    def cycle_speed(self, delta):
        # type: (int) -> None
        if self.sequence is not None:
            self.sequence.set_mode(SpeedMode.SINGLE)
        if _cue.top_layer_type != 'movie':
            return
        tag = _cue.current_file
        if not tag:
            return
        base_path = self.base_path_for(tag)
        if not base_path:
            return
        available = self.get_available_speeds(base_path)
        if len(available) <= 1:
            return
        current = self._pending_speed or self._get_speed_pref(tag)
        try:
            idx = available.index(current)
        except ValueError:
            idx = 0
        new_idx = max(0, min(idx + delta, len(available) - 1))
        self.set_speed(available[new_idx])

    def set_speed(self, speed):
        # type: (float) -> None
        if self.sequence is not None:
            self.sequence.set_mode(SpeedMode.SINGLE)
        if _cue.top_layer_type != 'movie':
            return
        tag = _cue.current_file
        if not tag:
            return
        if self.seamless_transition:
            last_requested = self._pending_speed or self._get_speed_pref(tag)
            if last_requested == speed:
                return
            base_path = self.base_path_for(tag)
            if not base_path:
                return
            new_variant = self.variant_path(base_path, speed)
            if not renpy.loadable(new_variant):
                return
            if self._pending_speed is None:
                self._pre_pending_speed = last_requested
            self._pending_speed = speed
            ch = _cue.vid_manager.channel
            if ch and new_variant:
                try:
                    _music.queue(
                        new_variant, channel=ch,
                        loop=True, clear_queue=True)
                    _cue_log("VQ-SEAMLESS queue={} last_req={} new={}".format(
                        new_variant, last_requested, speed))
                except Exception:
                    pass
        else:
            self._set_speed_pref(tag, speed)
        _cue.speed_toast.show(tag)
        renpy.restart_interaction()

    def toggle_seamless(self):
        # type: () -> None
        self.seamless_transition = not self.seamless_transition
        if not self.seamless_transition:
            self._pending_speed = None
            self._pre_pending_speed = None
        renpy.restart_interaction()

    def clear_pending(self):
        # type: () -> None
        self._pending_speed = None
        self._pre_pending_speed = None

    def invalidate(self, tag):
        # type: (str) -> None
        keys_to_pop = [k for k in self.children
                       if (isinstance(k, tuple) and k[0] == tag)]
        for k in keys_to_pop:
            self.children.pop(k, None)

    def resolve(self, st, at, tag, base_path, orig_movie):
        # type: (float, float, str, str, Movie) -> Tuple[Any, Any]
        try:
            speed = self._get_speed_pref(tag)
        except Exception:
            speed = _cue.DEFAULT_VIDEO_SPEED

        def _build_or_cache(cache_key, play_value):
            # type: (Tuple[str, object], object) -> Movie
            cached = self.children.get(cache_key, None)
            if cached is not None:
                return cached
            kwargs = _cue_capture_kwargs(orig_movie)
            kwargs["play"] = play_value
            child = Movie(**kwargs)
            self.children[cache_key] = child
            return child

        # Active speed sequence overrides
        seq = self.sequence
        if seq is not None:
            active = seq.active_tag
            if active and (tag == active or
                           active.startswith(tag + " ") or
                           tag.startswith(active + " ")):
                queue_paths = seq.paths_for(active)
                if queue_paths:
                    return _build_or_cache((tag, "__queue__"), queue_paths), None

        # Seamless transition: hold old Movie until queue flips
        if self._pending_speed is not None:
            pending_variant = self.variant_path(base_path, self._pending_speed)
            try:
                ch = _cue.vid_manager.channel
                now_playing = _music.get_playing(channel=ch) if ch else None
            except Exception:
                now_playing = None
            transitioned = (now_playing and pending_variant
                and os.path.normpath(now_playing) == os.path.normpath(pending_variant))
            if transitioned:
                _cue_log("VQ-SEAMLESS complete, switching to normal resolution")
                speed = self._pending_speed
                self._set_speed_pref(tag, speed)
                self._pending_speed = None
                self._pre_pending_speed = None
            else:
                if self._pre_pending_speed == _cue.DEFAULT_VIDEO_SPEED:
                    return orig_movie, None
                old_variant = self.variant_path(base_path, self._pre_pending_speed)
                if not renpy.loadable(old_variant):
                    return orig_movie, None
                return _build_or_cache((tag, self._pre_pending_speed), old_variant), None

        # Normal speed resolution
        if speed == _cue.DEFAULT_VIDEO_SPEED:
            return orig_movie, None
        variant = self.variant_path(base_path, speed)
        if not renpy.loadable(variant):
            return orig_movie, None
        return _build_or_cache((tag, speed), variant), None

    def wrap_all_movies(self):
        # type: () -> None
        _start = _time.time()
        _count = 0
        for name_tuple, d in list(_display_images.items()):
            if isinstance(d, DynamicDisplayable):
                continue
            unwrapped = _cue_unwrap_displayable(d)
            if not isinstance(unwrapped, Movie):
                continue
            tag = " ".join(name_tuple)
            base_path = _cue_get_movie_play(unwrapped)
            if not base_path:
                continue
            self.paths[tag] = base_path
            renpy.image(name_tuple, DynamicDisplayable(_cue_resolver, tag, base_path, unwrapped))
            _count += 1
        _elapsed = _time.time() - _start
        _cue_log("DynamicDisplayable resolver wrapping done: {} movies in {:.3f}s".format(_count, _elapsed))

    # Variant path utilities
    _VARIANT_PREFIX = "_cue"

    @staticmethod
    def _suffix_variant(speed, ext):
        # type: (float, str) -> str
        return "{cue}{speed:.1f}x{ext}".format(
            cue=CueVidSpeedResolver._VARIANT_PREFIX, speed=speed, ext=ext)

    @staticmethod
    def _parse_variant_speed(filename, base_no_ext, ext):
        # type: (str, str, str) -> Optional[float]
        prefix = base_no_ext + CueVidSpeedResolver._VARIANT_PREFIX
        suffix = "x" + ext
        if not (filename.startswith(prefix) and filename.endswith(suffix)):
            return None
        middle = filename[len(prefix):-len(suffix)]
        try:
            return float(middle)
        except ValueError:
            return None

    @staticmethod
    def _split_ext(path):
        # type: (str) -> Tuple[str, str]
        base, ext = os.path.splitext(path)
        if not ext:
            ext = ".webm"
        return base, ext

    @classmethod
    def variant_path(cls, base_path, speed):
        # type: (Type[CueVidSpeedResolver], str, Any) -> str
        if speed == _cue.DEFAULT_VIDEO_SPEED:
            return base_path
        base, ext = cls._split_ext(base_path)
        return base + cls._suffix_variant(speed, ext)

    @classmethod
    def is_variant_of(cls, path, base_path):
        # type: (Type[CueVidSpeedResolver], str, str) -> bool
        if not path or not base_path:
            return False
        if path == base_path:
            return True
        base, ext = cls._split_ext(base_path)
        sp = cls._parse_variant_speed(path, base, ext)
        return sp is not None

    def get_available_speeds(self, base_path):
        # type: (str) -> List[float]
        speeds = [_cue.DEFAULT_VIDEO_SPEED]
        base_dir = os.path.dirname(os.path.join(_config.gamedir, base_path))
        base_name = os.path.basename(base_path)
        base_no_ext, ext = self._split_ext(base_name)
        try:
            for f in os.listdir(base_dir):
                sp = self._parse_variant_speed(f, base_no_ext, ext)
                if sp is not None and sp != 1.0:
                    if os.path.isfile(os.path.join(base_dir, f)):
                        speeds.append(sp)
        except Exception:
            pass
        speeds.sort()
        return speeds

    @staticmethod
    def preset_speeds():
        # type: () -> List[float]
        return [0.5, 1.5, 2.0]

    def _prune_deleted_speed_from_sequence(self, speed):
        # type: (float) -> None
        if self.sequence is None:
            return
        tag = _cue.current_file
        if not tag:
            return
        entry = _cue.markers.get(create_vid_key(tag))
        if entry is None:
            return
        seq = entry.get("speed_sequence")
        if not seq:
            return
        new_seq = [s for s in seq if s != speed]
        if len(new_seq) == len(seq):
            return
        if new_seq:
            entry["speed_sequence"] = new_seq
        else:
            entry.pop("speed_sequence", None)
        if self.sequence.active_tag:
            self.sequence.start(self.sequence.active_tag)

    def delete_variant(self, base_path, speed):
        # type: (str, float) -> None
        if speed == _cue.DEFAULT_VIDEO_SPEED:
            return
        vpath = self.variant_path(base_path, speed)
        try:
            for _ch_name in _aaudio.channels:
                _playing = _music.get_playing(channel=_ch_name)
                if _playing:
                    _playing_fs = os.path.join(_config.gamedir, _playing)
                    _target_fs = os.path.join(_config.gamedir, vpath)
                    if os.path.normpath(_playing_fs) == os.path.normpath(_target_fs):
                        _music.play(
                            base_path, channel=_ch_name,
                            loop=True, fadeout=0, synchro_start=True)
        except Exception:
            pass
        for tag, base in self.paths.items():
            if base == base_path:
                cur = self._get_speed_pref(tag)
                if cur == speed:
                    self._set_speed_pref(tag, _cue.DEFAULT_VIDEO_SPEED)
        tag = _cue.current_file
        if tag:
            cur = self._get_speed_pref(tag)
            if cur == speed:
                self._set_speed_pref(tag, _cue.DEFAULT_VIDEO_SPEED)
        fspath = os.path.join(_config.gamedir, vpath)
        deleted = False
        for _attempt in range(3):
            try:
                if os.path.exists(fspath):
                    os.remove(fspath)
                deleted = True
                break
            except Exception:
                if _attempt < 2:
                    _time.sleep(0.1)
        if not deleted:
            _cue_log("DELETE-VARIANT: all attempts failed to remove {}".format(fspath))
            return
        for tag, base in self.paths.items():
            if base == base_path:
                self.children.pop((tag, speed), None)
        self._prune_deleted_speed_from_sequence(speed)
        _cue_log("DELETE-VARIANT: removed {} (speed={:.1f}x)".format(vpath, speed))
        _cue.markers.save_persistent()
        renpy.restart_interaction()


class CueVidSpeedSequence:
    def __init__(self, resolver):
        self.resolver = resolver
        self.active_tag = None
        self.last_playing = None
        self.last_elapsed = 0.0
        self.play_count = 0
        self._step_index = -1

    def speeds_for(self, tag):
        # type: (str) -> Optional[List[float]]
        if not tag:
            return None
        entry = _cue.markers.get(create_vid_key(tag))
        if entry is None:
            return None
        seq = entry.get("speed_sequence")
        if not seq:
            return None
        return seq

    def current_step_index(self):
        # type: () -> int
        return self._step_index

    def speeds_grouped(self, tag):
        # type: (str) -> Optional[List[Tuple[float, int, int]]]
        seq = self.speeds_for(tag)
        if not seq:
            return None
        groups = []
        i = 0
        while i < len(seq):
            sp = seq[i]
            start = i
            count = 1
            i += 1
            while i < len(seq) and seq[i] == sp:
                count += 1
                i += 1
            groups.append((sp, count, start))
        return groups

    def contains(self, speed):
        # type: (float) -> bool
        seq = self.speeds_for(_cue.current_file)
        if not seq:
            return False
        for s in seq:
            if s == speed:
                return True
        return False

    def _get_entry(self, tag):
        # type: (str) -> Any
        if not tag:
            return None
        return _cue.markers._get_or_create_entry(create_vid_key(tag))

    def append_speed(self, speed):
        # type: (float) -> None
        tag = _cue.current_file
        if not tag:
            return
        entry = self._get_entry(tag)
        if entry is None:
            return
        seq = entry.setdefault("speed_sequence", [])
        seq.append(speed)
        _cue_log("VQ-APPEND tag={} speed={} seq={}".format(tag, speed, seq))
        if len(seq) >= 1:
            self.start(tag)
        _cue.markers.save_persistent()
        renpy.restart_interaction()

    def remove_at(self, index):
        # type: (int) -> None
        tag = _cue.current_file
        if not tag:
            return
        entry = _cue.markers.get(create_vid_key(tag))
        if entry is None:
            return
        seq = entry.get("speed_sequence")
        if not seq or not (0 <= index < len(seq)):
            return
        seq.pop(index)
        if not seq:
            entry.pop("speed_sequence", None)
        _cue.markers.save_persistent()
        if self.active_tag == tag:
            self.start(tag)
        else:
            renpy.restart_interaction()

    def move(self, index, delta):
        # type: (int, int) -> None
        tag = _cue.current_file
        if not tag:
            return
        entry = _cue.markers.get(create_vid_key(tag))
        if entry is None:
            return
        seq = entry.get("speed_sequence")
        if not seq:
            return
        new_index = index + delta
        if new_index < 0 or new_index >= len(seq):
            return
        seq[index], seq[new_index] = seq[new_index], seq[index]
        _cue.markers.save_persistent()
        if self.active_tag == tag:
            self.start(tag)
        else:
            renpy.restart_interaction()

    def clear_sequence(self, tag=None):
        # type: (Optional[str]) -> None
        if tag is None:
            tag = _cue.current_file
        if not tag:
            return
        entry = _cue.markers.get(create_vid_key(tag))
        if entry is not None and "speed_sequence" in entry:
            del entry["speed_sequence"]
            _cue.markers.save_persistent()
        self.cancel()
        renpy.restart_interaction()

    def get_mode(self, tag=None):
        # type: (Optional[str]) -> str
        if tag is None:
            tag = _cue.current_file
        if not tag:
            return SpeedMode.SINGLE
        entry = _cue.markers.get(create_vid_key(tag))
        if entry is None:
            return SpeedMode.SINGLE
        return entry.get("speed_mode", SpeedMode.SINGLE)

    def set_mode(self, mode, tag=None):
        # type: (str, Optional[str]) -> None
        if tag is None:
            tag = _cue.current_file
        if not tag or mode not in (SpeedMode.SINGLE, SpeedMode.MULTI):
            return
        entry = self._get_entry(tag)
        if entry is None:
            return
        entry["speed_mode"] = mode
        _cue.markers.save_persistent()
        if mode == SpeedMode.MULTI:
            self.start(tag)
        else:
            self.cancel()
            renpy.restart_interaction()

    def paths_for(self, tag):
        # type: (str) -> Optional[List[str]]
        speeds = self.speeds_for(tag)
        base_path = self.resolver.base_path_for(tag)
        if not speeds or not base_path:
            return None
        paths = []
        for sp in speeds:
            if sp == _cue.DEFAULT_VIDEO_SPEED:
                paths.append(base_path)
            else:
                vpath = self.resolver.variant_path(base_path, sp)
                if renpy.loadable(vpath):
                    paths.append(vpath)
        if len(paths) < 1:
            return None
        return paths

    def start(self, tag):
        # type: (str) -> None
        paths = self.paths_for(tag)
        if not paths:
            _cue_log("VQ-NOSTART tag={} paths={}".format(tag, paths is not None))
            self.active_tag = None
            return
        self.resolver.invalidate(tag)
        self.active_tag = tag
        self.play_count = 0
        self._step_index = 0
        try:
            ch = _cue.vid_manager.channel
            self.last_playing = _music.get_playing(channel=ch) if ch else None
        except Exception:
            self.last_playing = None
        self.last_elapsed = 0.0
        _cue_log("VQ-START tag={} paths={}".format(tag, ",".join(paths)))
        renpy.restart_interaction()

    def handle(self, tag):
        # type: (str) -> None
        old_tag = self.active_tag
        speeds = self.speeds_for(tag)
        if speeds and self.get_mode(tag) == SpeedMode.MULTI:
            if not old_tag or old_tag != tag:
                self.start(tag)
        elif old_tag:
            self.active_tag = None
            if _cue.top_layer_type != 'movie':
                ch = _cue.vid_manager.channel
                if ch:
                    try:
                        _music.stop(channel=ch, fadeout=0)
                    except Exception:
                        pass

    def cancel(self):
        # type: () -> None
        self.active_tag = None

    def tick(self):
        # type: () -> None
        if not self.active_tag or not _cue.vid_manager.channel:
            return
        try:
            ch = _cue.vid_manager.channel
            now_playing = _music.get_playing(channel=ch)
            now_elapsed = _music.get_pos(channel=ch) or 0.0
        except Exception:
            now_playing = None
            now_elapsed = 0.0
        is_wrap_around = now_playing and now_elapsed < 0.2 and self.last_elapsed - now_elapsed > 0.2
        is_new_play = (now_playing != self.last_playing or is_wrap_around)
        if is_new_play:
            if self.play_count > 0:
                seq = self.speeds_for(self.active_tag)
                if seq:
                    self._step_index = (self._step_index + 1) % len(seq)
            self.play_count += 1
            _cue_log("VQ-PLAY #{} step={} file={}".format(
                self.play_count, self._step_index,
                now_playing.rsplit("/", 1)[-1] if now_playing else now_playing))
            renpy.restart_interaction()
        self.last_playing = now_playing
        self.last_elapsed = now_elapsed


class CueSpeedToast:
    def __init__(self):
        self.toast_speeds = None
        self.toast_current = None
        self.toast_tag = None
        self.toast_timestamp = 0.0

    def show(self, tag):
        # type: (str) -> None
        resolver = _cue.speed_resolver
        base_path = resolver.base_path_for(tag)
        if not base_path:
            return
        speeds = resolver.get_available_speeds(base_path)
        if len(speeds) <= 1:
            return
        renpy.hide_screen("cue_speed_toast", layer="cue_layer")
        self.toast_speeds = speeds
        self.toast_current = resolver._get_speed_pref(tag)
        self.toast_tag = tag
        self.toast_timestamp = _time.time()
        renpy.show_screen("cue_speed_toast", _layer="cue_layer")

    def clear(self):
        # type: () -> None
        renpy.hide_screen("cue_speed_toast", layer="cue_layer")
        self.toast_speeds = None


# ==========================================================================
# Module-level wrappers (must be module-level for DynamicDisplayable pickling)
# ==========================================================================

def _cue_resolver(st, at, tag, base_path, orig_movie):
    # type: (float, float, str, str, Movie) -> Tuple[Any, Any]
    """DynamicDisplayable callback. Delegates through this module-level
    function so Ren'Py can pickle it by name reference."""
    return _cue.speed_resolver.resolve(st, at, tag, base_path, orig_movie)


def _cue_capture_kwargs(movie):
    # type: (Any) -> Dict[str, Any]
    """Capture constructor kwargs from a Movie object."""
    kwargs = {
        "channel": movie.channel,
        "loop": movie.loop,
        "size": movie.size,
        "side_mask": getattr(movie, "side_mask", False),
        "mask": getattr(movie, "mask", None),
        "mask_channel": getattr(movie, "mask_channel", None),
        "image": getattr(movie, "image", None),
        "start_image": getattr(movie, "start_image", None),
        "play_callback": getattr(movie, "play_callback", None),
    }
    if hasattr(movie, "group"):
        kwargs["group"] = movie.group
    return kwargs


# ==========================================================================
# Sequence button popup actions
# ==========================================================================

def _cue_seq_btn_hovered(index):
    # type: (int) -> None
    _cue._seq_popup_index = index

def _cue_seq_popup_dismiss():
    # type: () -> None
    _cue_clear_focus_rect("seq_btn")
    _cue._seq_popup_index = -1

def _cue_seq_delete():
    # type: () -> None
    idx = getattr(_cue, '_seq_popup_index', -1)
    if idx < 0:
        return
    _cue_seq_popup_dismiss()
    _cue.video_sequence.remove_at(idx)

def _cue_seq_move_left():
    # type: () -> None
    idx = getattr(_cue, '_seq_popup_index', -1)
    if idx < 1:
        return
    _cue_seq_popup_dismiss()
    _cue.video_sequence.move(idx, -1)

def _cue_seq_move_right():
    # type: () -> None
    idx = getattr(_cue, '_seq_popup_index', -1)
    if idx < 0:
        return
    _cue_seq_popup_dismiss()
    _cue.video_sequence.move(idx, 1)
