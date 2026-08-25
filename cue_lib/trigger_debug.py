# -*- coding: utf-8 -*-
# Marker-accuracy anomaly detection (trigger-debug.log).
#
# Owns the bespoke detection logic so the main trigger dispatch stays lean:
# the stall / stuck-gate / late-fire / missed-marker / play-failed /
# marker-beyond-duration / restart-burst detectors plus the cooldown-limited
# ring-snapshot reporting and the per-video fire-accuracy summary.  The trigger
# engine feeds it per-tick inputs and per-fire results; CueTriggerDebug holds
# the state and the CUE_TD_* thresholds.  Gated on CUE_DEBUG (the master debug
# switch) -- no point detecting when debug logging itself is off.

import time as _time

import cue_lib.constants as _constants  # module ref so CUE_DEBUG stays live (tests flip it)

from cue_lib.logger import _cue_logger
from cue_lib.state import _cue
from cue_lib.util import _cue_log

MYPY = False
if MYPY:
    from typing import List, Optional, Set

# Detection thresholds, tuned above normal jitter (get_pos ~43ms chunks *
# speed, 20fps stretches, ~127ms VQ-START hiccups) so only true anomalies
# trip them.
CUE_TD_LATE_THRESHOLD = 0.15  # marker fired this late past its time
CUE_TD_MISS_TOLERANCE = 0.12  # marker this far past-due yet never fired
CUE_TD_STALL_GAP = 0.5  # tick gap this large while a movie is the top layer
CUE_TD_GATE_CLOSED_GAP = 0.3  # movie on top but no channel this long = stuck gate
CUE_TD_COOLDOWN = 15.0  # min seconds between snapshot dumps (one-liners always log)
# Restart burst: this many played-key clears (video restarts) inside the window
# is abnormal.  Tunable up if short-loop videos false-positive -- a 1s loop
# legitimately clears ~1x/s, a 5s loop ~1x/5s.
CUE_TD_RESTART_WINDOW = 3.0  # restarts inside this window count toward a burst
CUE_TD_RESTART_BURST_N = 5  # this many restarts in the window = burst
CUE_TD_ACCURACY_MAX_FIRES = 500  # cap stored fire deltas per video
# Tick cadence diagnostics: per-second window summary of tick intervals, body
# cost, and the video position-clock rate relative to wall time.  Gated behind
# CUE_TD_DIAG (off unless debugging) -- it never feeds anomaly detection -- and
# bounded to CUE_TD_DIAG_MAX_LINES per session so it can't flood debug.log.
CUE_TD_DIAG = False  # master switch for TICK-DIAG cadence diagnostics
CUE_TD_DIAG_WINDOW = 1.0  # accumulation window per summary line (s)
CUE_TD_DIAG_MAX_LINES = 400  # hard cap on TICK-DIAG lines per session


def _cue_td_missed_times(marker_times, played_keys, effective_elapsed, tolerance):
    # type: (List[float], Set[str], float, float) -> List[float]
    """Marker times that are past-due yet have no fired ts_key in played_keys.

    Run AFTER the fire loop, so any time still pending here was skipped by it
    rather than never reached.  played_keys entries look like
    '<vid_key>@<time>#<count>'; a time matches when a key embeds it, so a
    marker the fire loop dropped (past tolerance without a key being added)
    shows up as missed."""
    missed = []
    for t in marker_times:
        if t > effective_elapsed - tolerance:
            continue
        needle = "@{:.3f}#".format(t)
        if not any(needle in key for key in played_keys):
            missed.append(t)
    return missed


class CueTriggerDebug(object):
    """Anomaly detection for video marker accuracy.

    The engine calls tick() once per frame (stall + stuck-gate + restart
    cadence), note_fire() after each successful marker fire, note_failed_fire()
    after a reached marker that produced no sound, and end_fire_loop() after the
    fire pass (missed markers, beyond-duration, accuracy flush).  Every detector
    logs a TD-ANOMALY one-liner to debug.log; a ring snapshot to trigger-debug.log
    lands at most once per cooldown.
    """

    def __init__(self):
        self._last_dump = 0.0
        self._last_tick_wall = 0.0
        self._gate_closed_since = 0.0  # 0 open, >0 timing a closure, -1 already reported
        self._late_deltas = []  # late-fire deltas collected since the last report
        # Per-video fire-accuracy bucket (mean / p95 / late count), flushed on
        # file change or when the movie layer drops.
        self._acc_file = None  # type: Optional[str]
        self._acc_deltas = []  # type: List[float]
        self._acc_late = 0
        # (file, mt) markers already flagged as beyond the video's duration.
        self._beyond_reported = set()  # type: Set[tuple]
        # Restart-burst state: recent restart wall-times + report-once-per-episode.
        self._restarts = []  # type: List[float]
        self._restart_burst_armed = False
        # Tick cadence diagnostics (TICK-DIAG windowed summary).
        self._diag_lines = 0
        self._diag_win_start = 0.0  # wall time the current window started
        self._diag_ticks = 0  # ticks seen in this window
        self._diag_int_n = 0  # valid tick intervals in this window
        self._diag_int_min = 1e9
        self._diag_int_sum = 0.0
        self._diag_int_max = 0.0
        self._diag_body_max = 0.0  # worst tick-body wall cost this window
        self._diag_last_pos = None  # get_elapsed at the previous rate sample
        self._diag_last_rate_wall = 0.0
        self._diag_rate_dp_sum = 0.0  # window-summed get_elapsed advance
        self._diag_rate_dw_sum = 0.0  # window-summed wall advance
        self._diag_skips = 0  # invalidated rate samples (wrap / new play / seek jump)

    def tick(self, now, current_file, top_layer_type, channel):
        # type: (float, str, str, Optional[str]) -> None
        """Stall + stuck-gate checks plus tick-cadence accumulation, once per
        engine frame.  When the movie layer drops, flush the accuracy bucket
        the fire loop no longer runs to close out."""
        if not _constants.CUE_DEBUG:
            return
        if CUE_TD_DIAG and not self._diag_win_start:
            self._diag_win_start = now
        if self._last_tick_wall:
            _interval = now - self._last_tick_wall
            if CUE_TD_DIAG and _interval < 1.0:  # ignore long gaps (focus loss, scene switch)
                self._diag_int_n += 1
                if _interval < self._diag_int_min:
                    self._diag_int_min = _interval
                if _interval > self._diag_int_max:
                    self._diag_int_max = _interval
                self._diag_int_sum += _interval
            if top_layer_type == 'movie' and _interval > CUE_TD_STALL_GAP:
                self.report("stall", "gap={:.2f} vid={}".format(_interval, current_file))
        self._last_tick_wall = now
        if CUE_TD_DIAG:
            self._diag_ticks += 1

        # Gate-closed: a movie is the top layer but the video manager has no
        # channel, so _tick_video early-returns and no markers can fire.  A
        # short window is normal (the tick where the channel is being set);
        # persisting past the gap means the gate is stuck.
        if top_layer_type == 'movie' and not channel:
            if self._gate_closed_since == 0.0:
                self._gate_closed_since = now
            elif self._gate_closed_since > 0.0 and now - self._gate_closed_since > CUE_TD_GATE_CLOSED_GAP:
                self.report("gate-closed", "since={:.2f}s vid={}".format(now - self._gate_closed_since, current_file))
                self._gate_closed_since = -1.0  # reported once; re-arm when the gate re-opens
        elif self._gate_closed_since != 0.0:
            self._gate_closed_since = 0.0

        if top_layer_type != 'movie':
            self._flush_accuracy()

    def tick_end(self, t0):
        # type: (float) -> None
        """Close out an engine frame: tick-body wall cost, video clock-rate
        sample, and the per-second TICK-DIAG window summary."""
        if not _constants.CUE_DEBUG:
            return
        if not CUE_TD_DIAG:
            return
        _body = _time.time() - t0
        if _body > self._diag_body_max:
            self._diag_body_max = _body
        self._sample_rate()
        self._emit_summary()

    def _sample_rate(self):
        # type: () -> None
        """Per-frame get_elapsed/wall deltas while a video is the top layer.
        get_pos advances in ~43ms audio-buffer chunks, so per-sample ratios are
        biased (jumps ~1.7x, flats skipped).  Window-summed averages cancel
        that, so the rate is read at summary time as dp_sum/dw_sum."""
        if _cue.top_layer_type != 'movie':
            return
        try:
            _pos = _cue.vid_manager.get_elapsed()
        except Exception:
            return
        _now = _time.time()
        if self._diag_last_pos is None or not self._diag_last_rate_wall:
            self._diag_last_pos = _pos
            self._diag_last_rate_wall = _now
            return
        _dp = _pos - self._diag_last_pos
        _dw = _now - self._diag_last_rate_wall
        self._diag_last_pos = _pos
        self._diag_last_rate_wall = _now
        if _dw <= 0.0 or _dw > 1.0:
            self._diag_skips += 1
            return
        if _dp < 0.0 or _dp > 0.5:  # wrap / new play / seek jump
            self._diag_skips += 1
            return
        self._diag_rate_dp_sum += _dp
        self._diag_rate_dw_sum += _dw

    def _emit_summary(self):
        # type: () -> None
        """Emit the accumulated TICK-DIAG window once it spans a second, then
        reset the accumulators for the next window."""
        if not CUE_TD_DIAG:
            return
        if self._diag_lines >= CUE_TD_DIAG_MAX_LINES:
            return
        if not self._diag_win_start:
            return
        if _time.time() - self._diag_win_start < CUE_TD_DIAG_WINDOW:
            return
        _int_mean = (self._diag_int_sum / self._diag_int_n) if self._diag_int_n else 0.0
        _rate = (self._diag_rate_dp_sum / self._diag_rate_dw_sum) if self._diag_rate_dw_sum else 0.0
        _sp = 0.0
        try:
            _sp = _cue.speed_resolver.get_current_speed() or 0.0
        except Exception:
            _sp = 0.0
        _rnorm = (_rate / _sp) if _sp else 0.0
        _video = ""
        try:
            _vp = _cue.vid_manager.get_video_path()
            if _vp:
                _video = _vp.rsplit("/", 1)[-1]
        except Exception:
            _video = ""
        _cue_log(
            "TICK-DIAG n={} int={:.1f}/{:.1f}/{:.1f}ms body={:.2f}ms "
            "rate={:.3f} sp={:.2f} rnorm={:.3f} skip={} video={}".format(
                self._diag_ticks,
                self._diag_int_min * 1000.0,
                _int_mean * 1000.0,
                self._diag_int_max * 1000.0,
                self._diag_body_max * 1000.0,
                _rate,
                _sp,
                _rnorm,
                self._diag_skips,
                _video or "-",
            )
        )
        self._diag_lines += 1
        self._diag_win_start = 0.0
        self._diag_ticks = 0
        self._diag_int_n = 0
        self._diag_int_min = 1e9
        self._diag_int_sum = 0.0
        self._diag_int_max = 0.0
        self._diag_body_max = 0.0
        self._diag_rate_dp_sum = 0.0
        self._diag_rate_dw_sum = 0.0
        self._diag_skips = 0

    def note_fire(self, t, effective_elapsed, current_file):
        # type: (float, float, str) -> None
        """Record a marker that fired successfully.  Accumulates the delta into
        the current video's accuracy bucket; deltas over the late threshold also
        feed the late-fire report at the end of the fire loop."""
        if not _constants.CUE_DEBUG:
            return
        delta = effective_elapsed - t
        if current_file != self._acc_file:
            self._flush_accuracy()
            self._acc_file = current_file
            self._acc_deltas = []
            self._acc_late = 0
        if len(self._acc_deltas) < CUE_TD_ACCURACY_MAX_FIRES:
            self._acc_deltas.append(delta)
        if delta > CUE_TD_LATE_THRESHOLD:
            self._acc_late += 1
            self._late_deltas.append(round(delta, 3))

    def note_failed_fire(self, t, effective_elapsed, current_file):
        # type: (float, float, str) -> None
        """Record a marker that was REACHED but whose playback produced nothing
        (empty intensity folder, or a play_sfx exception).  The engine marks it
        as fired so it doesn't retry; this surfaces the accuracy signal once."""
        if not _constants.CUE_DEBUG:
            return
        self.report("play-failed", "vid={} mt={:.3f} delta={:+.3f}".format(current_file, t, effective_elapsed - t))

    def note_restart(self):
        # type: () -> None
        """Record a video restart (played-key clear in the engine).  Flags a
        restart burst -- more restarts than loop cadence explains -- once per
        episode."""
        if not _constants.CUE_DEBUG:
            return
        _now = _time.time()
        self._restarts.append(_now)
        while self._restarts and _now - self._restarts[0] > CUE_TD_RESTART_WINDOW:
            self._restarts.pop(0)
        if len(self._restarts) >= CUE_TD_RESTART_BURST_N:
            if not self._restart_burst_armed:
                self._restart_burst_armed = True
                self.report(
                    "restart-burst", "count={} in {:.1f}s".format(len(self._restarts), _now - self._restarts[0])
                )
        else:
            self._restart_burst_armed = False

    def _flush_accuracy(self):
        # type: () -> None
        """Emit the per-video fire-accuracy summary (mean / p95 / late count)
        and reset the bucket."""
        if not self._acc_deltas:
            return
        _n = len(self._acc_deltas)
        _sorted = sorted(self._acc_deltas)
        _mean = sum(_sorted) / _n
        _idx = max(0, min(_n - 1, int(_n * 0.95) - 1))
        _cue_log(
            "TD-ACCURACY vid={} fires={} mean={:+.0f}ms p95={:+.0f}ms late={}/{}".format(
                self._acc_file or "-", _n, _mean * 1000.0, _sorted[_idx] * 1000.0, self._acc_late, _n
            )
        )
        self._acc_file = None
        self._acc_deltas = []
        self._acc_late = 0

    def end_fire_loop(self, current_file, effective_elapsed, played_keys, markers, preview_count):
        # type: (str, float, Set[str], List[dict], int) -> None
        """Post-loop check: markers skipped entirely (missed) or fired late,
        reported once.  base_times counts only the video's own markers --
        previews are transient and excluded.  Also flags markers set beyond the
        video's duration (can never fire -- config error, not an anomaly)."""
        if not _constants.CUE_DEBUG:
            return
        base_times = []
        for pool_entry in markers[: len(markers) - preview_count]:
            if "time" in pool_entry:
                base_times.append(pool_entry["time"])
        missed = _cue_td_missed_times(base_times, played_keys, effective_elapsed, CUE_TD_MISS_TOLERANCE)
        if self._late_deltas or missed:
            self.report(
                "late" if self._late_deltas else "missed",
                "vid={} mt={} delta={} eff={:.3f}".format(
                    current_file,
                    self._late_deltas if self._late_deltas else missed,
                    self._late_deltas if self._late_deltas else "n/a",
                    effective_elapsed,
                ),
            )
            self._late_deltas = []  # reported once per fire-loop episode
        self._note_beyond_duration(current_file, base_times)

    def _note_beyond_duration(self, current_file, marker_times):
        # type: (str, List[float]) -> None
        """Flag markers whose time exceeds the video duration -- they can never
        fire.  Reported once per (file, mt); a recurring 'missed' on a marker
        past its video's end is this, not a runtime skip."""
        try:
            duration = _cue.vid_manager.get_duration()
        except Exception:
            return
        if not duration:
            return
        for t in marker_times:
            if t > duration:
                key = (current_file, t)
                if key in self._beyond_reported:
                    continue
                self._beyond_reported.add(key)
                self.report("marker-beyond-duration", "vid={} mt={:.3f} dur={:.3f}".format(current_file, t, duration))

    def report(self, kind, details):
        # type: (str, str) -> None
        """Record an anomaly: always a TD-ANOMALY one-liner to debug.log, plus
        a ring snapshot to trigger-debug.log at most once per cooldown."""
        if not _constants.CUE_DEBUG:
            return
        now = _time.time()
        line = "TD-ANOMALY type={} {} t={:.2f}".format(kind, details, now)
        _cue_log(line)
        if now - self._last_dump >= CUE_TD_COOLDOWN:
            self._last_dump = now
            _cue_logger.snapshot_debug(line)
