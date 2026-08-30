# -*- coding: utf-8 -*-
# CueSyncManager -- perceptual audio-sync calibration (Settings > Audio Sync).
# Runs a wall-clock-driven metronome that cycles three tempo stages -- slow,
# medium, fast, then repeats.  Each stage sweeps the playhead across the whole
# bar and fires CUE_SYNC_BEATS_PER_STAGE clicks, one on each of the timeline's
# equidistant markers; a full cycle does 9 clicks (3 per stage).
#
# The calibration value `sync_lead` shifts each click EARLIER than its beat
# (the playhead crossing its marker), so the user tunes it until clicks are
# HEARD on the visual pops -- output latency varies per speaker / headphones.
# The video marker trigger reads the same lead.  The playhead itself is a pure
# ramp independent of click timing: it always traverses the bar start to end
# and only restarts at the bar's real end.  Instantiated once at _cue.sync,
# lives on the NoRollback _cue object.

import renpy
import renpy.audio.music as _music
import renpy.python as _renpy_python

from cue_lib.constants import CUE_SHARED_KEY_AUDIO_SYNC_LEAD
from cue_lib.db import CueDatabase
from cue_lib.trigger.helpers import CUE_SFX_AUDIBLE_LEAD

# Dedicated channel for the metronome click -- never collides with _cue_ SFX.
CUE_SYNC_CHANNEL = "cue_sync"

# Gamedir-relative path to the metronome click.  ~0.8s long; the slow stage
# leaves it room to finish, fast overlaps into a quick roll (intended).
CUE_SYNC_CLICK = "renpy_cue/cue_lib/assets/metronome.mp3"

# Tempo stages: seconds per beat, slow -> medium -> fast, then repeat.
CUE_SYNC_STAGE_INTERVALS = (1.0, 0.6, 0.4)
CUE_SYNC_STAGE_LABELS = ("Slow", "Medium", "Fast")

# Clicks per stage -- matches the 3 equidistant markers the timeline draws.
CUE_SYNC_BEATS_PER_STAGE = 3

# Marker positions across one stage's sweep, inset from both ends so the marks
# are equidistant from each other AND from the edges: with N beats the sweep
# spans N+1 equal intervals, the k-th beat sits at (k+1)/(N+1), and the playhead
# keeps traveling past the last marker to the bar's real end before restarting.
# Derived from BEATS_PER_STAGE so the timeline and the click schedule can't
# drift apart.
CUE_SYNC_MARKER_FRACS = tuple(float(i + 1) / (CUE_SYNC_BEATS_PER_STAGE + 1) for i in range(CUE_SYNC_BEATS_PER_STAGE))


class CueSyncManager(_renpy_python.NoRollback):
    """Three-stage beat clock for the Audio Sync calibration sweep."""

    # Upper bound (seconds) for the audible-lead calibration.  Referenced by
    # set_sync_lead (clamp) and the slider's range.
    LEAD_MAX = 0.5

    def __init__(self, db):
        # type: (CueDatabase) -> None
        self._db = db
        # Calibration follows the user across games (shared config), loaded up
        # front so the metronome and video trigger have it from the first frame.
        self.sync_lead = float(db.load_shared_config().get(CUE_SHARED_KEY_AUDIO_SYNC_LEAD, CUE_SFX_AUDIBLE_LEAD))
        self.is_running = False
        self.stage_intervals = CUE_SYNC_STAGE_INTERVALS
        self._stage_idx = 0
        self._beat_idx = 0  # clicks the current stage has fired so far
        self._stage_t0 = 0.0  # wall-clock when the current stage's sweep was at 0

    def set_sync_lead(self, seconds):
        # type: (float) -> None
        """Clamp the calibration into [0, LEAD_MAX] and persist it to shared
        config.  The metronome and the video marker trigger both read it."""
        seconds = max(0.0, min(self.LEAD_MAX, seconds))
        self.sync_lead = seconds
        self._db.update_shared_config({CUE_SHARED_KEY_AUDIO_SYNC_LEAD: seconds})

    def start(self):
        # type: () -> None
        """Begin the sweep at the slow stage.  The sweep is a pure wall-clock
        ramp that restarts only when it reaches the bar's right end."""
        now = renpy.display.core.get_time()
        self.is_running = True
        self._stage_idx = 0
        self._beat_idx = 0
        self._stage_t0 = now

    def stop(self):
        # type: () -> None
        """Halt the sweep and cut any pending click."""
        self.is_running = False
        try:
            _music.stop(channel=CUE_SYNC_CHANNEL, fadeout=0)
        except Exception:
            pass

    def current_interval(self):
        # type: () -> float
        """Seconds per beat for the active stage."""
        return self.stage_intervals[self._stage_idx]

    def stage_label(self):
        # type: () -> str
        """Name of the active stage (Slow / Medium / Fast)."""
        return CUE_SYNC_STAGE_LABELS[self._stage_idx]

    def stage_duration(self):
        # type: () -> float
        """Total sweep length for the active stage.  One extra interval past
        the last marker so the playhead reaches the bar's real end before the
        stage restarts."""
        return self.current_interval() * (CUE_SYNC_BEATS_PER_STAGE + 1)

    def phase(self, now):
        # type: (float) -> float
        """0..1 sweep position across the whole stage (left edge to right
        edge).  Pure wall-clock -- independent of when clicks fire -- so the
        playhead always traverses the bar start to end before restarting.
        Valid only while running."""
        if not self.is_running:
            return 0.0
        return max(0.0, min(1.0, (now - self._stage_t0) / self.stage_duration()))

    def tick(self, now):
        # type: (float) -> None
        """Fire the click for a beat at `beat_time - sync_lead`, and roll the
        stage over once the sweep reaches the bar's end.  Neither the clicks
        nor the lead touches the playhead; the sweep restarts purely on
        wall-clock."""
        if not self.is_running:
            return
        interval = self.current_interval()
        offset = self.sync_lead

        # A click is scheduled for each beat, lead-shifted EARLY so the audio
        # lands on the pop after output latency.  Beat k fires in the stage's
        # (k+1)-th interval, i.e. at phase (k+1)/(N+1).
        if self._beat_idx < CUE_SYNC_BEATS_PER_STAGE:
            click_at = self._stage_t0 + (self._beat_idx + 1) * interval - offset
            if now >= click_at:
                self._play_click()
                self._beat_idx += 1

        # Roll to the next stage when the sweep has fully crossed the bar,
        # regardless of whether every click has fired.
        if now >= self._stage_t0 + self.stage_duration():
            self._stage_t0 += self.stage_duration()
            self._beat_idx = 0
            self._stage_idx = (self._stage_idx + 1) % len(self.stage_intervals)

    def _play_click(self):
        # type: () -> None
        _music.play(CUE_SYNC_CLICK, channel=CUE_SYNC_CHANNEL, loop=False)
