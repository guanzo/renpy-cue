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
from renpy.display.video import (
    default_play_callback as _default_play_callback,  # pyright: ignore[reportAttributeAccessIssue]
)
from renpy.display.image import images as _display_images

from cue_lib.constants import CUE_DEFAULT_VIDEO_SPEED, CUE_AUTO_SPEED_MIN_VARIANTS
from cue_lib.state import _cue
from cue_lib.util import (
    _cue_log, _cue_unwrap_displayable, _cue_get_movie_play,
    _cue_atl_child_displayables,
    create_vid_key,
)

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Tuple, Type
    from cue_lib._types import MarkerEntry
    from cue_lib.marker_store import CueMarkerStore  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.video import CueVideoManager  # pyright: ignore[reportUnusedImport]
    from cue_lib.video.auto_speed import CueAutoSpeedGenerator  # pyright: ignore[reportUnusedImport]
    from cue_lib.paths import CuePaths  # pyright: ignore[reportUnusedImport]
    from cue_lib.state import CueContext  # pyright: ignore[reportUnusedImport]

# Toast display duration in seconds (includes 0.6s hold + 0.5s fade-out).
CUE_TOAST_DURATION = 4.1

# Shorter duration used when a seamless speed transition completes.
CUE_TOAST_DURATION_SEAMLESS = 1.6

# Fade-out split points for the toast transform in cue_ui_overlay.rpy.
CUE_TOAST_FADE_DURATION = 0.5
CUE_TOAST_FADE_OFFSET = 0.6

# Minimum number of speed variants required before auto / multi-speed
# sequences activate.  Fewer than this is pointless.
CUE_MULTI_SPEED_MIN_VARIANTS = 2


class CueSpeedMode(object):
    SINGLE = "single"
    MULTI = "multi"
    AUTO = "auto"


class CueVidSpeedResolver(object):
    def __init__(self, ctx, store, vid_manager, video_sequence, speed_toast, paths):
        # type: (CueContext, CueMarkerStore, CueVideoManager, CueVidSpeedSequence, CueSpeedToast, CuePaths) -> None
        self._store = store
        self._vid_manager = vid_manager
        self._ctx = ctx
        self._video_sequence = video_sequence
        self._speed_toast = speed_toast
        self._paths = paths
        self.paths = {}
        self.children = {}
        self.seamless_transition = False
        self._pending_speed = None
        self._pre_pending_speed = None

    def _get_speed_pref(self, tag):
        # type: (str) -> float
        if not tag:
            return CUE_DEFAULT_VIDEO_SPEED
        def _read(entry):
            # type: (MarkerEntry) -> float
            return entry.get("single_speed_pref", CUE_DEFAULT_VIDEO_SPEED)
        entry = self._store.get(create_vid_key(tag))
        if entry is not None and "single_speed_pref" in entry:
            return _read(entry)
        best = CUE_DEFAULT_VIDEO_SPEED
        best_len = -1
        for key in self.paths:
            if key.startswith(tag + " ") and len(key) > best_len:
                e = self._store.get(create_vid_key(key))
                if e is not None and "single_speed_pref" in e:
                    best = _read(e)
                    best_len = len(key)
        return best

    def _set_speed_pref(self, tag, speed):
        # type: (str, float) -> None
        if not tag:
            return
        entry = self._store._get_or_create_entry(create_vid_key(tag))
        entry["single_speed_pref"] = speed
        self._store.save_marker(create_vid_key(tag))

    def speed_for(self, tag):
        # type: (str) -> float
        return self._get_speed_pref(tag)

    def get_current_speed(self):
        # type: () -> float
        tag = self._ctx.current_file
        if not tag:
            return CUE_DEFAULT_VIDEO_SPEED
        seq = self._video_sequence
        if seq is not None and seq.active_tag:
            speeds = seq.speeds_for(tag)
            if speeds:
                si = seq.current_step_index()
                if 0 <= si < len(speeds):
                    return speeds[si]
        return self.speed_for(tag)

    def active_speeds(self, tag):
        # type: (str) -> Optional[List[float]]
        """Distinct speeds the current mode plays, for intensity banding.

        MULTI/AUTO both drive playback through speeds_for() -- the stored
        custom sequence for MULTI, the in-memory generated sequence for
        AUTO -- so its distinct values are the variant set, an O(1) read
        that avoids re-scanning the video directory
        (auto_speed.enabled_speeds lists the dir every call).  SINGLE-mode
        videos have no variants -> None (no intensity)."""
        mode = self._video_sequence.get_mode(tag)
        if mode in (CueSpeedMode.MULTI, CueSpeedMode.AUTO):
            seq = self._video_sequence.speeds_for(tag)
            if seq:
                return sorted(set(seq))
        return None

    def base_path_for(self, tag):
        # type: (str) -> Optional[str]
        if not tag:
            return None
        if tag in self.paths:
            return self.paths[tag]
        for key, base in self.paths.items():
            if key.startswith(tag + " ") or tag.startswith(key + " "):
                return base
        raw = self._vid_manager.get_video_path()
        if raw:
            # raw may be a speed variant (e.g. in shared_dir).
            # Resolve back to the original base path from self.paths.
            for _key, _base in self.paths.items():
                if self.is_variant_of(raw, _base):
                    return _base
        return raw

    def cycle_speed(self, delta):
        # type: (int) -> None
        self._video_sequence.set_mode(CueSpeedMode.SINGLE)
        if self._ctx.top_layer_type != 'movie':
            return
        tag = self._ctx.current_file
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
        self._video_sequence.set_mode(CueSpeedMode.SINGLE)
        if self._ctx.top_layer_type != 'movie':
            return
        tag = self._ctx.current_file
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
            ch = self._vid_manager.channel
            if ch and new_variant:
                try:
                    _music.queue(
                        new_variant, channel=ch,
                        loop=True, clear_queue=True)
                    _cue_log("VQ-SEAMLESS queue={} last_req={} new={}".format(
                        new_variant, last_requested, speed))
                except Exception:
                    _cue_log("SET-SPEED: queue failed for {}".format(new_variant))
        else:
            self._set_speed_pref(tag, speed)
        self._speed_toast.show(tag)
        renpy.restart_interaction()

    def toggle_seamless(self):
        # type: () -> None
        self.seamless_transition = not self.seamless_transition
        persistent._cue["seamless_transition"] = self.seamless_transition
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
        seq = self._video_sequence
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
                ch = self._vid_manager.channel
                now_playing = _music.get_playing(channel=ch) if ch else None
            except Exception:
                _cue_log("SPEED-RESOLVE: get_playing failed")
                now_playing = None
            transitioned = (now_playing and pending_variant
                and os.path.normpath(now_playing) == os.path.normpath(pending_variant))

            if transitioned:
                _cue_log("VQ-SEAMLESS complete tag={} speed={}".format(
                    tag, self._pending_speed))
                self._set_speed_pref(tag, self._pending_speed)
                self._pending_speed = None
                self._pre_pending_speed = None
                self._speed_toast.show(tag, duration=CUE_TOAST_DURATION_SEAMLESS)
                renpy.restart_interaction()
                
            # Always return the stable Movie during seamless pending --
            # the channel is being driven by music.queue(), not by the
            # Movie's play parameter.
            return self._movie_for(tag, base_path, orig_movie), None

        # -- Non-seamless path: return a Movie whose play matches the
        #    current speed preference.  Different speeds get different
        #    Movie objects so Ren'Py detects the identity change and
        #    restarts playback with the new variant file.
        if not self.seamless_transition:
            speed = self._get_speed_pref(tag)
            if speed == CUE_DEFAULT_VIDEO_SPEED:
                return self._movie_for(tag, base_path, orig_movie), None
            
            cache_key = (tag, speed)
            cached = self.children.get(cache_key, None)

            if cached is not None:
                return cached, None
            variant = self.variant_path(base_path, speed)

            if not os.path.exists(variant):
                return self._movie_for(tag, base_path, orig_movie), None
            
            kwargs = _cue_capture_kwargs(orig_movie)
            kwargs["play"] = variant
            child = Movie(**kwargs)
            self.children[cache_key] = child
            return child, None

        # Seamless idle: stable Movie identity, channel plays whatever
        # file was last queued or set.
        return self._movie_for(tag, base_path, orig_movie), None

    def wrap_all_movies(self):
        # type: () -> None
        _start = _time.time()
        _count = 0

        # First pass: Find all Movies
        for name_tuple, d in list(_display_images.items()):
            # Skip only our own wrappers; a game DynamicDisplayable whose
            # rendered child is a Movie should still be wrapped.
            if isinstance(d, CueDynamicDisplayable):
                continue
            unwrapped = _cue_unwrap_displayable(d)
            if not isinstance(unwrapped, Movie):
                continue
            tag = " ".join(name_tuple)
            base_path = _cue_get_movie_play(unwrapped)
            if not base_path:
                continue
            self.paths[tag] = base_path
            renpy.image(name_tuple, CueDynamicDisplayable(_cue_resolver, tag, base_path, unwrapped))
            _count += 1

        # Second pass: ATL images ("bg <name> movie") display a wrapped
        # Movie child. They aren't Movies themselves, but base_path_for()
        # must resolve their tag for channel detection. Child names are
        # resolved against self.paths, which the first pass fully
        # populated, so this is independent of registry order.
        _atl_count = 0
        for name_tuple, d in list(_display_images.items()):
            if isinstance(d, CueDynamicDisplayable):
                continue
            children = _cue_atl_child_displayables(d)
            if not children:
                continue
            for child in children:
                if isinstance(child, Movie):
                    base_path = _cue_get_movie_play(child)
                else:
                    name = getattr(child, "name", None)
                    if name is None and isinstance(child, str):
                        name = child
                    if name is None:
                        continue
                    if not isinstance(name, tuple):
                        name = tuple(name.split())
                    base_path = self.paths.get(" ".join(name))
                if base_path:
                    tag = " ".join(name_tuple)
                    if tag not in self.paths:
                        self.paths[tag] = base_path
                        _atl_count += 1
                    break
        _elapsed = _time.time() - _start
        _cue_log("DynamicDisplayable resolver wrapping done: {} movies (+{} atl) in {:.3f}s".format(
            _count, _atl_count, _elapsed))

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

    def variant_path(self, base_path, speed):
        # type: (str, Any) -> str
        """Return the absolute filesystem path for a speed variant.

        At 1.0x the original file is returned (as an absolute path).
        Other speeds go into ``shared_dir/video/<game_id>/`` so the
        game directory is never modified.
        """
        if speed == CUE_DEFAULT_VIDEO_SPEED:
            if os.path.isabs(base_path):
                return os.path.normpath(base_path).replace("\\", "/")
            return os.path.normpath(os.path.join(_config.gamedir, base_path)).replace("\\", "/")
        base_name = os.path.basename(base_path)
        base, ext = self._split_ext(base_name)
        filename = base + self._suffix_variant(speed, ext)
        return os.path.join(self._paths.video_dir, filename).replace("\\", "/")

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
        speeds = [CUE_DEFAULT_VIDEO_SPEED]
        if not base_path:
            return speeds
        base_name = os.path.basename(base_path)
        base_no_ext, ext = self._split_ext(base_name)
        try:
            video_dir = self._paths.video_dir
            for f in os.listdir(video_dir):
                sp = self._parse_variant_speed(f, base_no_ext, ext)
                if sp is not None and sp != CUE_DEFAULT_VIDEO_SPEED:
                    if os.path.isfile(os.path.join(video_dir, f)):
                        speeds.append(sp)
        except Exception:
            _cue_log("SPEED-LIST: os.listdir failed for {}".format(self._paths.video_dir))
        speeds.sort()
        return speeds

    @staticmethod
    def preset_speeds():
        # type: () -> List[float]
        return [0.5, 1.5, 2.0]

    def _prune_deleted_speed_from_sequence(self, speed):
        # type: (float) -> bool
        """Remove `speed` from the current file's multi_speed_sequence.
        Returns True if the sequence was modified."""
        tag = self._ctx.current_file
        if not tag:
            return False
        entry = self._store.get(create_vid_key(tag))
        if entry is None:
            return False
        seq = entry.get("multi_speed_sequence")
        if not seq:
            return False
        new_seq = [s for s in seq if s != speed]
        if len(new_seq) == len(seq):
            return False
        if new_seq:
            entry["multi_speed_sequence"] = new_seq
        else:
            entry.pop("multi_speed_sequence", None)
        if self._video_sequence.active_tag:
            self._video_sequence.start(self._video_sequence.active_tag)
        return True

    def delete_variant(self, base_path, speed):
        # type: (str, float) -> None
        if speed == CUE_DEFAULT_VIDEO_SPEED:
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
            _cue_log("DELETE-VARIANT: channel stop failed for {}".format(vpath))
        for tag, base in self.paths.items():
            if base == base_path:
                cur = self._get_speed_pref(tag)
                if cur == speed:
                    self._set_speed_pref(tag, CUE_DEFAULT_VIDEO_SPEED)
        tag = self._ctx.current_file
        if tag:
            cur = self._get_speed_pref(tag)
            if cur == speed:
                self._set_speed_pref(tag, CUE_DEFAULT_VIDEO_SPEED)
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
        if self._prune_deleted_speed_from_sequence(speed):
            tag = self._ctx.current_file
            if tag:
                self._store.save_marker(create_vid_key(tag))
        _cue_log("DELETE-VARIANT: removed {} (speed={:.1f}x)".format(vpath, speed))
        renpy.restart_interaction()


class CueVidSpeedSequence(object):
    def __init__(self, ctx, store, vid_manager):
        # type: (CueContext, CueMarkerStore, CueVideoManager) -> None
        self._ctx = ctx
        self._store = store
        self._vid_manager = vid_manager
        # The resolver and auto_speed both take this sequence in their own
        # constructors, so they are late-bound via bind() in cue_z.rpy.
        self._speed_resolver = None  # type: Optional[CueVidSpeedResolver]
        self._auto_speed = None  # type: Optional[CueAutoSpeedGenerator]
        self.active_tag = None
        self.last_playing = None
        self.last_elapsed = 0.0
        self.play_count = 0
        self._step_index = -1
        # Generated AUTO sequences live here only, never in the stored
        # multi_speed_sequence (which holds the user's custom MULTI sequence).
        self._auto_sequences = {}

    def bind(self, speed_resolver, auto_speed):
        # type: (CueVidSpeedResolver, CueAutoSpeedGenerator) -> None
        """Late-bind the two cyclic collaborators (construction cycle)."""
        self._speed_resolver = speed_resolver
        self._auto_speed = auto_speed

    def speeds_for(self, tag):
        # type: (str) -> Optional[List[float]]
        if not tag:
            return None
        # AUTO generation is in-memory only; the stored multi_speed_sequence is
        # the custom MULTI sequence, which AUTO must never read or overwrite.
        if self.get_mode(tag) == CueSpeedMode.AUTO:
            seq = self._auto_sequences.get(tag)
            if seq:
                return seq
            return None
        entry = self._store.get(create_vid_key(tag))
        if entry is None:
            return None
        seq = entry.get("multi_speed_sequence")
        if not seq:
            return None
        return seq

    def set_auto_sequence(self, tag, seq):
        # type: (str, List[float]) -> None
        """Remember a generated AUTO sequence in memory only.

        Never write AUTO sequences to the stored multi_speed_sequence, or
        switching MULTI -> AUTO would clobber the user's custom sequence.
        In-memory means they reset on quit, which is fine -- AUTO
        regenerates on every entry."""
        if not tag or not seq:
            return
        self._auto_sequences[tag] = list(seq)

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
        seq = self.speeds_for(self._ctx.current_file)
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
        return self._store._get_or_create_entry(create_vid_key(tag))

    def get_disabled_auto_speeds(self, tag):
        # type: (str) -> set
        """Return the set of speeds disabled for auto-speed generation."""
        if not tag:
            return set()
        entry = self._store.get(create_vid_key(tag))
        if entry is None:
            return set()
        _stored = entry.get("disabled_auto_speeds", None)
        return set(_stored) if _stored else set()

    def set_disabled_auto_speeds(self, tag, speeds):
        # type: (str, set) -> None
        """Persist the set of disabled auto speeds for a video."""
        if not tag:
            return
        entry = self._get_entry(tag)
        if entry is None:
            return
        if speeds:
            entry["disabled_auto_speeds"] = list(speeds)
        else:
            entry.pop("disabled_auto_speeds", None)
        self._store.save_marker(create_vid_key(tag))

    def append_speed(self, speed):
        # type: (float) -> None
        tag = self._ctx.current_file
        if not tag:
            return
        entry = self._get_entry(tag)
        if entry is None:
            return
        seq = entry.setdefault("multi_speed_sequence", [])
        seq.append(speed)
        _cue_log("VQ-APPEND tag={} speed={} seq={}".format(tag, speed, seq))
        if len(seq) >= CUE_MULTI_SPEED_MIN_VARIANTS:
            self.start(tag)
        self._store.save_marker(create_vid_key(tag))
        renpy.restart_interaction()

    def remove_at(self, index):
        # type: (int) -> None
        tag = self._ctx.current_file
        if not tag:
            return
        entry = self._store.get(create_vid_key(tag))
        if entry is None:
            return
        seq = entry.get("multi_speed_sequence")
        if not seq or not (0 <= index < len(seq)):
            return
        seq.pop(index)
        if not seq:
            entry.pop("multi_speed_sequence", None)
        self._store.save_marker(create_vid_key(tag))
        if self.active_tag == tag:
            self.start(tag)
        else:
            renpy.restart_interaction()

    def move(self, index, delta):
        # type: (int, int) -> None
        tag = self._ctx.current_file
        if not tag:
            return
        entry = self._store.get(create_vid_key(tag))
        if entry is None:
            return
        seq = entry.get("multi_speed_sequence")
        if not seq:
            return
        new_index = index + delta
        if new_index < 0 or new_index >= len(seq):
            return
        seq[index], seq[new_index] = seq[new_index], seq[index]
        self._store.save_marker(create_vid_key(tag))
        if self.active_tag == tag:
            self.start(tag)
        else:
            renpy.restart_interaction()

    def clear_sequence(self, tag=None):
        # type: (Optional[str]) -> None
        if tag is None:
            tag = self._ctx.current_file
        if not tag:
            return
        entry = self._store.get(create_vid_key(tag))
        if entry is not None and "multi_speed_sequence" in entry:
            del entry["multi_speed_sequence"]
            self._store.save_marker(create_vid_key(tag))
        self.cancel()
        renpy.restart_interaction()

    def get_mode(self, tag=None):
        # type: (Optional[str]) -> str
        if tag is None:
            tag = self._ctx.current_file
        if not tag:
            return CueSpeedMode.SINGLE
        entry = self._store.get(create_vid_key(tag))
        if entry is None:
            return CueSpeedMode.SINGLE
        return entry.get("speed_mode", CueSpeedMode.SINGLE)

    def set_mode(self, mode, tag=None):
        # type: (str, Optional[str]) -> None
        if tag is None:
            tag = self._ctx.current_file
        if not tag or mode not in (CueSpeedMode.SINGLE, CueSpeedMode.MULTI, CueSpeedMode.AUTO):
            return
        entry = self._get_entry(tag)
        if entry is None:
            return
        entry["speed_mode"] = mode
        self._store.save_marker(create_vid_key(tag))
        if mode == CueSpeedMode.MULTI:
            self.start(tag)
        elif mode == CueSpeedMode.AUTO:
            self.start_auto(tag)
        else:
            self.cancel()
            renpy.restart_interaction()

    def paths_for(self, tag):
        # type: (str) -> Optional[List[str]]
        speeds = self.speeds_for(tag)
        if self._speed_resolver is None:
            return None
        base_path = self._speed_resolver.base_path_for(tag)
        if not speeds or not base_path:
            return None
        paths = []
        for sp in speeds:
            vpath = self._speed_resolver.variant_path(base_path, sp)
            # variant_path returns absolute FS paths; 1.0x points to
            # the original file, other speeds point into shared_dir.
            if os.path.exists(vpath):
                paths.append(vpath)
        if len(paths) < 1:
            return None
        return paths

    def start(self, tag):
        # type: (str) -> None
        if self._speed_resolver is None:
            return
        paths = self.paths_for(tag)
        if not paths:
            _cue_log("VQ-NOSTART tag={} paths={}".format(tag, paths is not None))
            self.active_tag = None
            return
        self._speed_resolver.invalidate(tag)
        self.active_tag = tag
        self.play_count = 0
        self._step_index = 0

        try:
            ch = self._vid_manager.channel
            now = _music.get_playing(channel=ch) if ch else None
        except Exception:
            _cue_log("SPEED-START: get_playing failed")
            now = None

        # If the new queue's first file is the same file already on the
        # channel, tick() will never see now_playing change and the first
        # play is invisible -- play_count stays 0, _step_index lags by 1.
        # Force last_playing to None so tick() always detects the first
        # play after a start().
        _first = paths[0] if paths else None
        if now and _first and os.path.normpath(now) == os.path.normpath(_first):
            self.last_playing = None
            self.last_elapsed = -1.0
        else:
            self.last_playing = now
            self.last_elapsed = 0.0

        _cue_log("VQ-START tag={} paths=[{}]".format(
            tag, "][".join(os.path.basename(p) for p in paths)))
        
        renpy.restart_interaction()

    def handle(self, tag):
        # type: (str) -> None
        old_tag = self.active_tag
        mode = self.get_mode(tag)
        if mode == CueSpeedMode.AUTO:
            # AUTO keeps no stored sequence (it's in-memory), so the
            # speeds gate can't decide whether to start -- start_auto has
            # its own variant guard and handles a no-op internally.
            if not old_tag or old_tag != tag:
                self.start_auto(tag)
        else:
            speeds = self.speeds_for(tag)
            if speeds and mode == CueSpeedMode.MULTI:
                if not old_tag or old_tag != tag:
                    self.start(tag)
            elif old_tag:
                self.active_tag = None
                if self._ctx.top_layer_type != 'movie':
                    ch = self._vid_manager.channel
                    if ch:
                        try:
                            _music.stop(channel=ch, fadeout=0)
                        except Exception:
                            _cue_log("SPEED-HANDLE: stop failed on {}".format(ch))

    def cancel(self):
        # type: () -> None
        self.active_tag = None

    def tick(self):
        # type: () -> None
        if not self.active_tag or not self._vid_manager.channel:
            return
        try:
            ch = self._vid_manager.channel
            now_playing = _music.get_playing(channel=ch)
            now_elapsed = _music.get_pos(channel=ch) or 0.0
        except Exception:
            _cue_log("SPEED-TICK: playback query failed")
            now_playing = None
            now_elapsed = 0.0

        is_wrap_around = now_playing and now_elapsed < 0.2 and self.last_elapsed - now_elapsed > 0.2
        is_new_play = (now_playing != self.last_playing or is_wrap_around)
        if is_new_play:
            _old_step = self._step_index
            if self.play_count > 0:
                seq = self.speeds_for(self.active_tag)
                if seq:
                    new_index = (self._step_index + 1) % len(seq)
                    # AUTO mode: wrap-around triggers regeneration
                    if (self.get_mode(self.active_tag) == CueSpeedMode.AUTO
                            and new_index == 0
                            and self._auto_speed is not None):
                        self._auto_speed.on_wrap_around()
                        # on_wrap_around() calls start() which resets all
                        # tick state -- bail out so we don't overwrite it
                        return
                    else:
                        self._step_index = new_index
            self.play_count += 1

            # _cue_log(
            #     "VQ-PLAY #{} step={}->{} wrap={} file={}".format(
            #         self.play_count, _old_step, self._step_index,
            #         1 if is_wrap_around else 0,
            #         os.path.basename(now_playing) if now_playing else "-"))
            
        self._debug_verify_step(now_playing)
        self.last_playing = now_playing
        self.last_elapsed = now_elapsed

    def start_auto(self, tag):
        # type: (str) -> None
        """Generate a fresh auto sequence and start playback."""
        if self._auto_speed is None:
            self.start(tag)
            return
        if self._speed_resolver is None:
            return

        # The preset is stored per-video in the marker entry; restore it now
        # so generation and the UI highlight reflect this video's selection.
        self._auto_speed.load_preset(tag)
        base_path = self._speed_resolver.base_path_for(tag)
        if not base_path:
            return
        
        available = self._auto_speed.enabled_speeds
        
        if len(available) < CUE_AUTO_SPEED_MIN_VARIANTS:
            return

        new_seq = self._auto_speed.generate(available)
        self.set_auto_sequence(tag, new_seq)
        self.start(tag)

    def _debug_verify_step(self, now_playing):
        # type: (Optional[str]) -> None
        """Log a warning if the tracked step index disagrees with the file
        actually playing on the channel.  Rate-limited to one log per step
        to avoid flooding during fast timer ticks."""
        if now_playing is None:
            return
        _tag = self.active_tag
        if not _tag:
            return
        _seq = self.speeds_for(_tag)
        if not _seq:
            return
        if self._speed_resolver is None:
            return
        _base = self._speed_resolver.base_path_for(_tag)
        if not _base:
            return
        
        _now_name = os.path.basename(now_playing)
        _matches = []
        
        for _i, _sp in enumerate(_seq):
            _vp = self._speed_resolver.variant_path(_base, _sp)
            if os.path.basename(_vp) == _now_name:
                _matches.append(str(_i))

        if not _matches:
            return
        
        if str(self._step_index) in _matches:
            return
        
        # Rate-limit: one log per (step, file) pair
        _key = "{}|{}".format(self._step_index, _now_name)
        if getattr(self, '_last_desync_key', None) == _key:
            return
        self._last_desync_key = _key
        _cue_log(
            "VQ-DESYNC step={} playing_matches=[{}] file={}".format(
                self._step_index, ",".join(_matches), _now_name))


class CueSpeedToast(object):
    def __init__(self):
        self.toast_speeds = None
        self.toast_tag = None
        self.toast_timestamp = 0.0
        self.toast_duration = CUE_TOAST_DURATION

    def show(self, tag, duration=CUE_TOAST_DURATION):
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

class CueDynamicDisplayable(DynamicDisplayable):
    """Marker subclass for the speed wrappers we register.  wrap_all_movies()
    skips only these, letting the game's own DynamicDisplayables (whose
    rendered child may be a Movie) through the unwrap path."""

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
        _cue_log("SEAMLESS-CB: callback failed")
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
# Create tab delete actions
# ==========================================================================

def _cue_create_select_speed(speed):
    # type: (float) -> None
    # Select a created speed for deletion. Clicking the selected speed
    # again deselects it. Scoped to the current video so switching videos
    # can't leave a stale selection that deletes the wrong file.
    sel = getattr(_cue, '_create_delete_speed', None)
    if sel is not None and sel[0] == _cue.current_file and sel[1] == speed:
        _cue._create_delete_speed = None
    else:
        _cue._create_delete_speed = (_cue.current_file, speed)
    renpy.restart_interaction()

def _cue_create_delete_sel():
    # type: () -> Optional[float]
    sel = getattr(_cue, '_create_delete_speed', None)
    if sel is None or sel[0] != _cue.current_file:
        return None
    return sel[1]

def _cue_create_delete_speed():
    # type: () -> None
    sel = getattr(_cue, '_create_delete_speed', None)
    if sel is None or sel[0] != _cue.current_file:
        return
    tag, speed = sel
    _cue._create_delete_speed = None
    if speed == CUE_DEFAULT_VIDEO_SPEED:
        renpy.restart_interaction()
        return
    base_path = _cue.speed_resolver.base_path_for(tag)
    if base_path:
        _cue.speed_resolver.delete_variant(base_path, speed)
    renpy.restart_interaction()
