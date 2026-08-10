# -*- coding: utf-8 -*-
# CueVidSpeedResolver -- per-tag speed preferences and variant Movie resolution.
# Wraps every Movie image in a DynamicDisplayable that swaps in speed variants
# without touching the registry entry.

import os
import time as _time
import renpy
import renpy.audio.music as _music
import renpy.config as _config
import renpy.audio.audio as _aaudio
from renpy.store import persistent
from renpy.display.layout import DynamicDisplayable
from renpy.display.video import Movie
from renpy.display.video import default_play_callback as _default_play_callback
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


class SpeedMode(object):
    SINGLE = "single"
    MULTI = "multi"
    SMART = "smart"


class CueVidSpeedResolver(object):
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
        _cue.markers.save_marker(create_vid_key(tag))

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
        raw = _cue.vid_manager.get_video_path()
        if raw:
            # raw may be a speed variant (e.g. in shared_dir).
            # Resolve back to the original base path from self.paths.
            for _key, _base in self.paths.items():
                if self.is_variant_of(raw, _base):
                    return _base
        return raw

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
            if not os.path.exists(new_variant):
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
        persistent._cue_seamless_transition = self.seamless_transition
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
                       if k == tag or (isinstance(k, tuple) and k[0] == tag)]
        for k in keys_to_pop:
            self.children.pop(k, None)

    def _movie_for(self, tag, base_path, orig_movie):
        # type: (str, str, Movie) -> Movie
        """Return (or create) the single Movie instance for *tag*.

        The same object is returned every frame -- no identity change,
        no ``update_playing()`` restart, no render cold-start during
        speed switches.  Speed changes are handled by
        ``music.queue()`` on the channel, not by swapping Movie objects.
        """
        cached = self.children.get(tag, None)
        if cached is not None:
            return cached
        kwargs = _cue_capture_kwargs(orig_movie)
        kwargs["play"] = base_path
        if kwargs.get("play_callback", None) is None:
            kwargs["play_callback"] = _cue_seamless_play_callback
        # 8.x: group_texture bridges the decoder cold-start on speed
        # changes.  No-op on 7.x (swallowed by **properties).
        if hasattr(Movie, "group"):
            kwargs["group"] = tag
        child = Movie(**kwargs)
        self.children[tag] = child
        _cue_log("VQ-MOVIE-CREATE tag={} ch={}".format(tag, child.channel))
        return child

    def resolve(self, st, at, tag, base_path, orig_movie):
        # type: (float, float, str, str, Movie) -> Tuple[Any, Any]

        # Active speed sequence overrides
        seq = self.sequence
        if seq is not None:
            active = seq.active_tag
            if active and (tag == active or
                           active.startswith(tag + " ") or
                           tag.startswith(active + " ")):
                queue_paths = seq.paths_for(active)
                if queue_paths:
                    cached = self.children.get((tag, "__queue__"), None)
                    if cached is not None:
                        return cached, None
                    kwargs = _cue_capture_kwargs(orig_movie)
                    kwargs["play"] = queue_paths
                    kwargs["play_callback"] = None
                    child = Movie(**kwargs)
                    self.children[(tag, "__queue__")] = child
                    return child, None

        # Seamless transition: wait for queue flip, but always return
        # the same Movie object so the display tree never changes.
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
                _cue_log("VQ-SEAMLESS complete tag={} speed={}".format(
                    tag, self._pending_speed))
                self._set_speed_pref(tag, self._pending_speed)
                self._pending_speed = None
                self._pre_pending_speed = None
                _cue.speed_toast.show(tag, duration=1.6)
                renpy.restart_interaction()

        # Always return the same Movie -- the channel produces frames
        # for whichever file is currently playing.
        return self._movie_for(tag, base_path, orig_movie), None

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
        """Return the absolute filesystem path for a speed variant.

        At 1.0x the original file is returned (as an absolute path).
        Other speeds go into ``shared_dir/video/<game_id>/`` so the
        game directory is never modified.
        """
        if speed == _cue.DEFAULT_VIDEO_SPEED:
            if os.path.isabs(base_path):
                return os.path.normpath(base_path).replace("\\", "/")
            return os.path.normpath(os.path.join(_config.gamedir, base_path)).replace("\\", "/")
        base_name = os.path.basename(base_path)
        base, ext = cls._split_ext(base_name)
        filename = base + cls._suffix_variant(speed, ext)
        return os.path.join(_cue.db.video_dir, filename).replace("\\", "/")

    @classmethod
    def is_variant_of(cls, path, base_path):
        # type: (Type[CueVidSpeedResolver], str, str) -> bool
        if not path or not base_path:
            return False
        # Compare basenames because the variant may live in the shared
        # video dir while base_path is a game-relative vpath.
        path_name = os.path.basename(path)
        base_name = os.path.basename(base_path)
        if path_name == base_name:
            return True
        base, ext = cls._split_ext(base_name)
        sp = cls._parse_variant_speed(path_name, base, ext)
        return sp is not None

    def get_available_speeds(self, base_path):
        # type: (str) -> List[float]
        speeds = [_cue.DEFAULT_VIDEO_SPEED]
        if not base_path:
            return speeds
        base_name = os.path.basename(base_path)
        base_no_ext, ext = self._split_ext(base_name)
        try:
            video_dir = _cue.db.video_dir
            for f in os.listdir(video_dir):
                sp = self._parse_variant_speed(f, base_no_ext, ext)
                if sp is not None and sp != 1.0:
                    if os.path.isfile(os.path.join(video_dir, f)):
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
                    if os.path.normpath(_playing_fs) == os.path.normpath(vpath):
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
        fspath = vpath  # already absolute from variant_path()
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
        _cue.markers.save_all()
        renpy.restart_interaction()


class CueVidSpeedSequence(object):
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
        _cue.markers.save_marker(create_vid_key(tag))
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
        _cue.markers.save_marker(create_vid_key(tag))
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
        _cue.markers.save_marker(create_vid_key(tag))
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
            _cue.markers.save_marker(create_vid_key(tag))
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
        if not tag or mode not in (SpeedMode.SINGLE, SpeedMode.MULTI, SpeedMode.SMART):
            return
        entry = self._get_entry(tag)
        if entry is None:
            return
        entry["speed_mode"] = mode
        _cue.markers.save_marker(create_vid_key(tag))
        if mode == SpeedMode.MULTI:
            self.start(tag)
        elif mode == SpeedMode.SMART:
            self._start_smart(tag)
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
            vpath = self.resolver.variant_path(base_path, sp)
            # variant_path returns absolute FS paths; 1.0x points to
            # the original file, other speeds point into shared_dir.
            if os.path.exists(vpath):
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
        mode = self.get_mode(tag)
        speeds = self.speeds_for(tag)
        if speeds and mode in (SpeedMode.MULTI, SpeedMode.AUTO):
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
                    new_index = (self._step_index + 1) % len(seq)
                    # AUTO mode: wrap-around triggers regeneration
                    if (self.get_mode(self.active_tag) == SpeedMode.AUTO
                            and new_index == 0
                            and hasattr(_cue, 'auto_speed')):
                        _cue.auto_speed.on_wrap_around()
                    else:
                        self._step_index = new_index
            self.play_count += 1
            _cue_log("VQ-PLAY #{} step={} file={}".format(
                self.play_count, self._step_index,
                now_playing.rsplit("/", 1)[-1] if now_playing else now_playing))
            renpy.restart_interaction()
        self.last_playing = now_playing
        self.last_elapsed = now_elapsed

    def _start_auto(self, tag):
        # type: (str) -> None
        """Generate a fresh auto sequence and start playback."""
        if not hasattr(_cue, 'auto_speed'):
            self.start(tag)
            return
        base_path = self.resolver.base_path_for(tag)
        if not base_path:
            return
        available = self.resolver.get_available_speeds(base_path)
        if len(available) < 2:
            return
        new_seq = _cue.auto_speed.generate(available, None)
        entry = _cue.markers._get_or_create_entry(create_vid_key(tag))
        entry["speed_sequence"] = new_seq
        _cue.markers.save_persistent()
        self.start(tag)


class CueSpeedToast(object):
    def __init__(self):
        self.toast_speeds = None
        self.toast_current = None
        self.toast_tag = None
        self.toast_timestamp = 0.0
        self.toast_duration = 4.1

    def show(self, tag, duration=4.1):
        # type: (str, float) -> None
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
        self.toast_duration = duration
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


def _cue_seamless_play_callback(old, new):
    # type: (Any, Any) -> None
    """Skip the redundant ``music.play()`` restart during seamless speed
    switches.  The queued file is already playing on the channel by the
    time ``update_playing()`` notices the Movie identity change; calling
    ``default_play_callback`` would tear down the running decoder and
    re-open it, causing a visible stutter."""
    try:
        ch = new.channel
        now = _music.get_playing(channel=ch)
        # Only skip for single-speed mode (string _play).  Sequence mode
        # (list _play) needs music.play() to start the new path list.
        if now and new._play and not isinstance(new._play, list):
            if os.path.normpath(now) == os.path.normpath(new._play):
                return
    except Exception:
        pass
    _default_play_callback(old, new)


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
