# -*- coding: utf-8 -*-
# CueVideoManager -- per-video playback state and control.
# Instantiated once at _cue.vid_manager, lives on the NoRollback _cue object.

import renpy.audio.music as _music

from cue_lib.constants import CUE_RESTART_JUMP_SECONDS
from cue_lib.util import _cue_log, _cue_format_time, _cue_clamp_time

MYPY = False
if MYPY:
    from typing import Optional
    from cue_lib.state import CueContext  # pyright: ignore[reportUnusedImport]

# Minimum non-zero seek target to avoid sending 0.0 to the audio backend
# (which would be interpreted as "no target" and defeat auto-pause).
CUE_SEEK_MIN_TARGET = 0.001

# Cap on the SFX-fire breadcrumb trail logged for playhead/marker-sync checks.
CUE_SFX_BREADCRUMB_MAX = 256


def _cue_is_video_restart(prev_elapsed, curr_elapsed, duration):
    # type: (float, float, float) -> bool
    """True when the movie channel restarted (looped, or seeked-to-start).

    Ren'Py can't seek backward mid-clock, so a backward jump is the restart
    signal.  Anchor on duration (near-end -> near-start) when known; fall back
    to the fixed jump for short/unknown clips so a restart is never missed."""
    if curr_elapsed >= prev_elapsed:
        return False
    if duration and duration > 0:
        if prev_elapsed > duration * 0.6 and curr_elapsed < duration * 0.4:
            return True
    return prev_elapsed - curr_elapsed > CUE_RESTART_JUMP_SECONDS


class CueVideoManager(object):
    """Per-video playback state and control.
    Tracks the movie channel that's currently playing.
    Methods act on self.channel (the movie channel this state tracks),
    which _cue_refresh_channel keeps in sync."""

    def __init__(self, ctx, channel=None):
        # type: (CueContext, Optional[str]) -> None
        self._ctx = ctx
        self.reset(channel)

    # --- Playback control ---

    def reset(self, channel=None):
        # type: (Optional[str]) -> None
        """Reinitialize playback state (video changed).
        Keeps the current channel unless a new one is given."""
        self.channel = channel
        self.paused = False
        self.refreshing = False
        self.fps = 30
        self.last_elapsed = 0.0
        # One-shot "fresh video" signal: set here, consumed (cleared) by
        # poll_restart().  Uses a flag, not <0.0> last_elapsed, because a tick
        # reading elapsed=0 writes last_elapsed=0 back and would otherwise
        # re-trigger the reset next tick.
        self.is_reset_pending = True
        # Per-frame "video restarted" verdict -- the single source of truth the
        # speed sequence and SFX trigger both read so they act on the SAME tick.
        self.is_restart = False
        self.time_offset = 0.0
        self.step_target = 0.0
        self.pause_target = 0.0
        self.pause_origin = 0.0
        self.total_offset = 0.0  # deprecated, kept for attribute compatibility
        self.sfx_breadcrumbs = []  # file-frac (0..1) where each SFX fired, for sync debug

    def set_fps(self, fps):
        # type: (int) -> None
        """Apply the detected video framerate."""
        self.fps = fps

    def reset_pause(self):
        # type: () -> None
        """Clear the paused flag without touching playback (after load)."""
        self.paused = False

    def get_elapsed(self):
        # type: () -> float
        """Get current playback position (real pos + virtual offset)."""
        if not self.channel:
            return 0.0
        try:
            pos = _music.get_pos(channel=self.channel)
            if pos is not None:
                return max(0.0, pos + self.time_offset)
        except Exception:
            _cue_log("VIDEO: get_pos failed on {}".format(self.channel))
        return 0.0

    def get_duration(self):
        # type: () -> float
        """Get total duration of the current video in seconds.
        Returns 0.0 when the channel is unavailable or duration cannot
        be queried."""
        if not self.channel:
            return 0.0
        try:
            dur = _music.get_duration(channel=self.channel)
            if dur is not None and dur > 0:
                return dur
        except Exception:
            _cue_log("VIDEO: get_duration failed on {}".format(self.channel))
        return 0.0

    def record_sfx_breadcrumb(self, frac):
        # type: (float) -> None
        """Stamp a timeline breadcrumb at the file-frac where an SFX fired.

        Debug aid for playhead/marker-sync checks: CueVideoTimeline renders the
        trail as static ticks so they can be compared against the moving playhead.
        Clamped to [0,1]; drops the oldest beyond CUE_SFX_BREADCRUMB_MAX."""
        if frac < 0.0:
            frac = 0.0
        elif frac > 1.0:
            frac = 1.0
        self.sfx_breadcrumbs.append(frac)
        if len(self.sfx_breadcrumbs) > CUE_SFX_BREADCRUMB_MAX:
            del self.sfx_breadcrumbs[0]

    def clear_sfx_breadcrumbs(self):
        # type: () -> None
        """Drop the SFX-fire breadcrumb trail (on each video loop restart)."""
        self.sfx_breadcrumbs = []

    def poll_restart(self):
        # type: () -> bool
        """Detect a video restart/loop once per frame -- the single source of
        truth for "the video just restarted."

        Both the speed sequence and the SFX trigger read self.is_restart to
        advance the step and re-arm markers on the SAME tick.  Computed here
        from one last_elapsed so the two can never drift apart (previously
        each kept its own tracker; a sequence start() reset one but not the
        other, so a restart was detected on different ticks and the first
        marker fired the wrong level)."""
        elapsed = self.get_elapsed()
        dur = self.get_duration()
        fresh = self.is_reset_pending
        self.is_reset_pending = False
        back = self.last_elapsed > 0 and _cue_is_video_restart(self.last_elapsed, elapsed, dur)
        self.is_restart = fresh or back
        self.last_elapsed = elapsed
        return self.is_restart

    def get_video_path(self):
        # type: () -> Optional[str]
        """Get the filepath of the currently playing video."""
        if not self.channel:
            return None
        try:
            return _music.get_playing(channel=self.channel)
        except Exception:
            _cue_log("VIDEO-PATH: get_playing failed on {}".format(self.channel))
            return None

    def toggle_pause(self):
        # type: () -> None
        """Toggle pause on the active video channel."""
        if not self.channel:
            return
        self.time_offset = 0.0
        try:
            currently_paused = _music.get_pause(channel=self.channel)
            new_state = not currently_paused
            _music.set_pause(new_state, channel=self.channel)
            self.paused = new_state
            if new_state:  # Just paused -- save origin
                self.pause_origin = _music.get_pos(channel=self.channel) or 0.0
                self.total_offset = 0.0
                _cue_log("pause: origin={:.3f}".format(self.pause_origin))
            else:  # Just unpaused
                self.total_offset = 0.0
                _cue_log("unpause: reset offset")
        except Exception:
            # Fallback: use volume as pseudo-pause
            if not self.paused:
                _music.set_volume(0.0, delay=0, channel=self.channel)
                self.paused = True
            else:
                _music.set_volume(1.0, delay=0, channel=self.channel)
                self.paused = False

    def seek_to(self, target_time):
        # type: (float) -> None
        """Seek to an absolute timestamp and pause there.
        Forward (target >= current pos): pause, set step_target, unpause.
        The tick auto-pauses when pos reaches the target -- no restart.
        Backward (target < current pos): restart from 0 with pause_target."""
        if not self.channel:
            return
        dur = _music.get_duration(channel=self.channel) or 0.0
        if dur <= 0:
            return
        target = _cue_clamp_time(target_time, dur)
        current_pos = _music.get_pos(channel=self.channel) or 0.0
        # Reset offset tracking for the absolute target
        self.pause_origin = target
        self.total_offset = 0.0
        self.time_offset = 0.0
        self.pause_target = 0.0
        if target >= current_pos:
            # Forward seek: pause, set step target, unpause.
            if not self.paused:
                _music.set_pause(True, channel=self.channel)
                self.paused = True
            self.step_target = max(CUE_SEEK_MIN_TARGET, target)
            _music.set_pause(False, channel=self.channel)
        else:
            # Backward seek: restart from 0 with pause_target.
            filepath = _music.get_playing(channel=self.channel)
            if not filepath:
                return
            self.step_target = 0.0
            self.pause_target = max(CUE_SEEK_MIN_TARGET, target)
            _music.stop(channel=self.channel, fadeout=0)
            _music.play(filepath, channel=self.channel, loop=True)

    # --- Tick hooks ---

    def poll_autopause(self):
        # type: () -> None
        """Tick hook: auto-re-pause when a seek target is reached."""
        if not self.channel or self._ctx.top_layer_type != 'movie':
            return
        try:
            pos = _music.get_pos(channel=self.channel)
        except Exception:
            _cue_log("AUTOPAUSE: get_pos failed on {}".format(self.channel))
            return
        has_pos = pos is not None
        if has_pos and self.pause_target > 0 and pos >= self.pause_target:
            _music.set_pause(True, channel=self.channel)
            self.pause_target = 0.0
            self.paused = True
            self.time_offset = 0.0
        if has_pos and self.step_target > 0 and pos >= self.step_target:
            _music.set_pause(True, channel=self.channel)
            self.step_target = 0.0
            self.paused = True
            self.time_offset = 0.0

    def sync_paused(self):
        # type: () -> None
        """Mirror the channel's real pause state (UI play/pause buttons)."""
        if not self.channel:
            return
        try:
            self.paused = _music.get_pause(channel=self.channel)
        except Exception:
            _cue_log("SYNC-PAUSED: get_pause failed on {}".format(self.channel))

    # --- Label getters (zero-arg callables for CueSelfUpdatingLabel) ---

    def time_label(self):
        # type: () -> str
        """Return 'elapsed / duration' formatted for the live time display."""
        if self._ctx.top_layer_type != 'movie':
            return "--:--.-- / --:--.--"
        e = self.get_elapsed()
        d = self.get_duration()
        return "{} / {}".format(_cue_format_time(e), _cue_format_time(d))

    def frame_label(self):
        # type: () -> str
        """Return 'frame / total' formatted for the live frame display."""
        if self._ctx.top_layer_type != 'movie':
            return "---/---"
        e = self.get_elapsed()
        d = self.get_duration()
        fps = max(1, self.fps)
        return "{}/{}".format(int(e * fps), int(d * fps))
