# -*- coding: utf-8 -*-
# CueAutoSpeedGenerator -- procedural speed sequence generation.
#
# Each preset has a macro rhythm / phase structure that directly encodes
# its intended shape.  Randomization changes the details (hold durations,
# exact peak / bottom rungs, climb eagerness) without destroying the
# recognisable identity of the preset.
#
# The legacy _walk algorithm is kept for the "custom" fine-tune mode
# (active_preset is None).
#
# Instantiated at _cue.auto_speed.

import random as _random

import renpy

from cue_lib.constants import CUE_DEFAULT_VIDEO_SPEED, CUE_MIN_SPEEDS_FOR_SEQUENCE
from cue_lib.state import _cue
from cue_lib.util import create_vid_key, _cue_log, _cue_speed_label

MYPY = False
if MYPY:
    from typing import List


# ==========================================================================
# Module-level helpers (imported into store by cue_z.rpy for screen access)
# ==========================================================================

# Minimum number of speed variants required for Auto Speed mode.
# Fewer than this and the generator can't produce meaningful variety.
CUE_AUTO_SPEED_MIN_VARIANTS = 4

def _cue_auto_preset_label(preset_name):
    # type: (str) -> str
    """Human-readable label for a preset key."""
    labels = {
        "roller_coaster": "Roller Coaster",
        "build_up":       "Building Up",
        "cool_down":      "Winding Down",
        "slow_groove":    "Slow Groove",
        "fast_frenzy":    "Fast Frenzy",
        "tease":          "Tease",
        "plateau":        "Plateau",
        "random_walk":    "Random Walk",
        "edge":           "Edge",
        "anchor":         "Anchor",
        "pulse":          "Pulse",
        "surprise":       "Surprise Me",
        None:             "Custom",
    }
    return labels.get(preset_name, preset_name if preset_name else "Custom")


def _cue_auto_preset_description(preset_name):
    # type: (str) -> str
    """One-line description for a preset tooltip."""
    descs = {
        "roller_coaster": "Sweeps back and forth across the full speed range",
        "build_up":       "Stair-steps upward from slow to fast, then holds at peak",
        "cool_down":      "Stair-steps downward from fast to slow and settles",
        "slow_groove":    "Lingers in the lower speeds with a gentle, lazy sway",
        "fast_frenzy":    "High-energy, stays fast with frequent quick changes",
        "tease":          "Mostly slow with sudden, brief spikes of speed",
        "plateau":        "Long, sustained holds at one speed, then jumps to another",
        "random_walk":    "Unpredictable drift with no fixed direction or shape",
        "edge":           "Climbs toward peak, then drops suddenly -- never quite gets there",
        "anchor":         "Gravitates around a comfortable speed with small wobbles",
        "pulse":          "Steady repetitive beat — alternates around a central speed",
        "surprise":       "Picks a random rhythm each sequence -- expect anything!",
    }
    return descs.get(preset_name, "")


# ==========================================================================
# Generator dispatch -- maps preset name to method name on the class
# ==========================================================================

_GEN_METHODS = {
    "roller_coaster": "_gen_wave",
    "build_up":       "_gen_climb",
    "cool_down":      "_gen_descend",
    "slow_groove":    "_gen_low_sway",
    "fast_frenzy":    "_gen_high_jitter",
    "tease":          "_gen_spike",
    "plateau":        "_gen_plateau",
    "random_walk":    "_gen_random_walk",
    "edge":           "_gen_edge",
    "anchor":         "_gen_anchor",
    "pulse":          "_gen_pulse",
}


# ==========================================================================

class CueAutoSpeedGenerator(object):
    """Procedural speed sequence generator."""

    def __init__(self):
        # ================================================================
        # Tunables -- tweak these to change the feel of generated sequences
        # ================================================================

        # Sequence length in time-units (1 TU = one play of 1.0x video)
        self.min_duration_tu = 20.0
        self.max_duration_tu = 30.0

        # Hold time per rung: how long to linger in time-units.
        # Shorter = snappy transitions. Longer = smooth, sustained holds.
        self.min_hold_tu = 0.4
        self.max_hold_tu = 1.5

        # Max rungs to jump in one step, 0 = no ceiling.
        # Used only by the legacy _walk (custom mode).
        self.max_step = 0

        # Momentum: once moving in a direction, keep going for this
        # many steps before the direction can reverse.
        # Used only by the legacy _walk (custom mode).
        self.momentum_min_steps = 2
        self.momentum_max_steps = 5

        # Chance per step to ignore momentum and drift (adds unpredictability).
        # Used only by the legacy _walk (custom mode).
        self.momentum_drift_chance = 0.15

        # Which preset to use when "Surprise me" is selected (random each generation)
        self.surprise_pool = list(_GEN_METHODS.keys())

        # Currently active preset name (or None for custom/fine-tuned)
        self.active_preset = "roller_coaster"

        # Whether the user chose "surprise" — if True, re-randomize on each loop
        self.is_surprise_mode = False

        # ================================================================
        # Fine-tune overrides (only used when active_preset is None)
        # ================================================================
        self.custom_drift = 0.0
        self.custom_intensity = 0.7
        self.custom_volatility = 0.4
        self.custom_center = 0.5

    # ================================================================
    # Public API -- called from screen actions
    # ================================================================

    def select_preset(self, preset_name):
        # type: (str) -> None
        """Pick a named preset. Persists immediately."""
        if preset_name == "surprise":
            self.surprise_me()
        elif preset_name in _GEN_METHODS:
            self.active_preset = preset_name
            self.is_surprise_mode = False
            self._regenerate()
            renpy.restart_interaction()

    def surprise_me(self):
        """Pick a random preset from the surprise pool and regenerate."""
        self.is_surprise_mode = True
        self.active_preset = _random.choice(self.surprise_pool)
        self._regenerate()
        renpy.restart_interaction()

    # ================================================================
    # Generation entry point
    # ================================================================

    def generate(self, available_speeds):
        # type: (list) -> list
        """Generate a new speed sequence.

        Each preset picks its own starting rung.  No continuity is
        enforced between successive sequences.
        """
        if not available_speeds or len(available_speeds) < CUE_AUTO_SPEED_MIN_VARIANTS:
            return [available_speeds[0]] * 8 if available_speeds else [CUE_DEFAULT_VIDEO_SPEED]

        n = len(available_speeds)
        target_tu = _random.uniform(self.min_duration_tu, self.max_duration_tu)

        method_name = _GEN_METHODS.get(self.active_preset)
        if method_name:
            gen = getattr(self, method_name)
            seq = gen(available_speeds, n, target_tu)
        else:
            # Custom / fine-tuned -- use legacy walk
            seq = self._walk(
                available_speeds, n,
                self.custom_drift, self.custom_intensity,
                self.custom_volatility, self.custom_center,
                target_tu
            )

        # -- Debug: log the grouped sequence --
        runs = []
        i = 0
        while i < len(seq):
            sp = seq[i]
            count = 1
            i += 1
            while i < len(seq) and seq[i] == sp:
                count += 1
                i += 1
            runs.append((sp, count))

        parts = [_cue_speed_label(sp) + "x" + str(cnt) for sp, cnt in runs]
        actual_tu = sum(cnt / sp for sp, cnt in runs)
        preset = self.active_preset if self.active_preset else "custom"
        rung_labels = ", ".join(_cue_speed_label(s) for s in available_speeds)
        vid_dur = getattr(self, '_video_duration', 0) or 0

        _cue_log(
            "[{}] {} rungs({}) | vid {:.1f}s | target {:.1f} TU"
            " | actual {:.1f} TU | {} holds\n"
            "    {}".format(
                preset, n, rung_labels, vid_dur, target_tu, actual_tu,
                len(runs), " -> ".join(parts)
            )
        )

        return seq

    # ================================================================
    # Shared helper -- emit a hold at a given speed index
    # ================================================================

    @staticmethod
    def _emit_hold(seq, speeds, idx, hold_tu):
        # type: (list, list, int, float) -> float
        """Append speed values to seq for a hold at rung idx lasting
        hold_tu time-units.  Returns the actual TU emitted (plays / sp)."""
        sp = speeds[idx]
        plays = max(1, int(round(sp * hold_tu)))
        for _ in range(plays):
            seq.append(sp)
        return float(plays) / sp

    def _take_hold(self, seq, speeds, idx, remaining_tu, scale=1.0, max_real_s=10.0):
        # type: (list, list, int, float, float, float) -> float
        """Emit a single hold at rung idx and return the actual TU used.

        hold_tu = random in [min_hold_tu*scale, max_hold_tu*scale],
        clamped to remaining_tu.  Returns actual TU from _emit_hold."""
        hold_tu = _random.uniform(
            self.min_hold_tu * scale,
            self.max_hold_tu * scale
        )
        if hold_tu > remaining_tu:
            hold_tu = remaining_tu

        # Cap real time per hold.
        if (hasattr(self, '_video_duration')
                and self._video_duration > 0):
            max_tu = max_real_s / self._video_duration
            if hold_tu > max_tu:
                hold_tu = max_tu

        return self._emit_hold(seq, speeds, idx, hold_tu)


    def _should_stay(self, stay_count, stay_prob, max_stays=2):
        # type: (int, float, int) -> bool
        """Return True if we should stay on the current rung."""
        if stay_count >= max_stays:
            return False
        return _random.random() < stay_prob

    # ================================================================
    # Per-preset generators
    #
    # Each generator receives (speeds, n, start_idx, target_tu).
    #   speeds      -- sorted list of available speed floats
    #   n           -- len(speeds), the number of rungs
    #   start_idx   -- continuity-aware suggested start index (0..n-1)
    #   target_tu   -- total time-units to fill
    #
    # Presets that need a specific starting region override start_idx.
    # Presets that benefit from continuity (wave, plateau, random_walk)
    # use it, clamped to their valid range.
    # ================================================================

    # ----------------------------------------------------------------
    # Roller Coaster -- explicit bottom <-> top sweeps
    # ----------------------------------------------------------------

    def _gen_wave(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Roller Coaster: 3-6 humps with peaks in the top fourth and
        valleys in the bottom fourth.  Starts and ends near the bottom."""
        seq = []
        tu = 0.0
        idx = 0

        # Slow start at the bottom.
        tu += self._take_hold(seq, speeds, idx, target_tu, scale=1.3)

        # Regions (top / bottom fourth).
        peak_lo = n - max(1, n // 4)
        peak_hi = n - 1
        valley_lo = 0
        valley_hi = max(0, n // 4)

        # How many humps?
        min_humps = 3
        max_humps = 6
        num_humps = _random.randint(min_humps, max_humps)

        # Plan peak / valley pairs ahead so the last valley lands near
        # the start (within 1 rung of 0).
        peaks = []
        valleys = []
        for _i in range(num_humps):
            peak = _random.randint(peak_lo, peak_hi)
            v_hi = min(valley_hi, peak - 3)
            if v_hi < valley_lo:
                v_hi = valley_lo
            valley = _random.randint(valley_lo, v_hi)
            peaks.append(peak)
            valleys.append(valley)

        # Force the final valley within 1 rung of 0.
        valleys[-1] = _random.randint(0, min(1, valley_hi))

        min_stride = max(1, (n - 1) // 6)
        _CLIMB_STYLES = (0.3, 0.6, 1)
        _DESCEND_STYLES = (0.3, 0.6)

        last_climb = None
        last_descend = None

        for i in range(num_humps):
            peak = peaks[i]
            valley = valleys[i]

            if i == 0:
                # First climb is always the slowest for a gradual start.
                climb_scale = max(_CLIMB_STYLES)
            else:
                climb_scale = _random.choice(_CLIMB_STYLES)
                while climb_scale == last_climb:
                    climb_scale = _random.choice(_CLIMB_STYLES)
            last_climb = climb_scale

            descend_scale = _random.choice(_DESCEND_STYLES)
            while descend_scale == last_descend:
                descend_scale = _random.choice(_DESCEND_STYLES)
            last_descend = descend_scale

            # -- Climb (fresh stride per step) --
            rung = idx
            # Thin hump: big strides, few steps.  Wide hump: small strides,
            # many steps (one rung at a time).
            if _random.random() < 0.45:
                _stride_lo = 1
                _stride_hi = max(1, (n - 1) // 5)
            else:
                _stride_lo = min_stride
                _stride_hi = max(min_stride, (n - 1) // 2)
            while rung < peak:
                stride = _random.randint(_stride_lo, _stride_hi)
                rung = min(rung + stride, peak)
                if target_tu - tu <= 0.1:
                    break
                tu += self._take_hold(seq, speeds, rung, target_tu - tu,
                                      scale=climb_scale)
            if tu >= target_tu:
                break
            if rung != peak:
                tu += self._take_hold(seq, speeds, peak,
                                      target_tu - tu, scale=0.4)
            if tu >= target_tu:
                break

            # -- Descend (same width as the climb) --
            rung = peak
            while rung > valley:
                stride = _random.randint(_stride_lo, _stride_hi)
                rung = max(rung - stride, valley)
                if target_tu - tu <= 0.1:
                    break
                tu += self._take_hold(seq, speeds, rung, target_tu - tu,
                                      scale=descend_scale)
            if tu >= target_tu:
                break
            if rung != valley:
                tu += self._take_hold(seq, speeds, valley,
                                      target_tu - tu, scale=0.4)

            idx = valley

        return seq

    # ----------------------------------------------------------------
    # Build Up -- guaranteed low -> peak climb, then hold
    # ----------------------------------------------------------------

    def _gen_climb(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Build Up: 40-60% of the budget spent climbing, rest at peak."""
        seq = []
        tu = 0.0

        idx = _random.randint(0, n // 2)
        peak = n - 1

        # Build the list of rungs we'll visit during the climb.
        stride = _random.randint(1, max(1, (n - 1) // 4))
        climb_rungs = list(range(idx + stride, peak + 1, stride))
        if not climb_rungs or climb_rungs[-1] != peak:
            climb_rungs.append(peak)

        # 40-60% of the budget goes to the climb phase.
        climb_budget = target_tu * _random.uniform(0.4, 0.6)
        per_rung = climb_budget / max(len(climb_rungs), 1)
        avg_hold = (self.min_hold_tu + self.max_hold_tu) / 2.0
        climb_scale = max(0.3, per_rung / max(avg_hold, 0.1))

        for rung in climb_rungs:
            remaining = target_tu - tu
            if remaining <= 0.1:
                break
            tu += self._take_hold(seq, speeds, rung, remaining, scale=climb_scale)

        # -- Peak phase: wiggle with remaining budget --
        idx = peak
        while tu < target_tu:
            tu += self._take_hold(seq, speeds, idx, target_tu - tu, scale=1.2)
            r = _random.random()
            if r < 0.35:
                idx = max(peak - 1, idx - 1)
            elif r < 0.70:
                idx = min(peak, idx + 1)
            idx = max(peak - 1, min(peak, idx))
        return seq

    # ----------------------------------------------------------------
    # Cool Down -- guaranteed high -> low descent, then settle
    # ----------------------------------------------------------------

    def _gen_descend(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Cool Down: 40-60% of the budget spent descending, rest at bottom."""
        seq = []
        tu = 0.0

        idx = _random.randint(n // 2, n - 1)
        bottom = 0

        # Build the list of rungs we'll visit during the descent.
        stride = _random.randint(1, max(1, (n - 1) // 4))
        descend_rungs = list(range(idx - stride, bottom - 1, -stride))
        if not descend_rungs or descend_rungs[-1] != bottom:
            descend_rungs.append(bottom)

        descend_budget = target_tu * _random.uniform(0.4, 0.6)
        per_rung = descend_budget / max(len(descend_rungs), 1)
        avg_hold = (self.min_hold_tu + self.max_hold_tu) / 2.0
        descend_scale = max(0.3, per_rung / max(avg_hold, 0.1))

        for rung in descend_rungs:
            remaining = target_tu - tu
            if remaining <= 0.1:
                break
            tu += self._take_hold(seq, speeds, rung, remaining, scale=descend_scale)

        # -- Bottom phase: wiggle with remaining budget --
        idx = bottom
        while tu < target_tu:
            tu += self._take_hold(seq, speeds, idx, target_tu - tu, scale=1.2)
            r = _random.random()
            if r < 0.35:
                idx = min(bottom + 1, idx + 1)
            elif r < 0.70:
                idx = max(bottom, idx - 1)
            idx = max(bottom, min(bottom + 1, idx))
        return seq

    # ----------------------------------------------------------------
    # Slow Groove -- lower rungs, lazy sway
    # ----------------------------------------------------------------

    def _gen_low_sway(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Slow Groove: lazy sway in the lower speeds, never reaches high."""
        seq = []
        tu = 0.0

        idx = _random.randint(0, n // 2)
        max_rung = _random.randint(1, n // 2)
        stay_count = 0

        while tu < target_tu:
            remaining = target_tu - tu
            tu += self._take_hold(seq, speeds, idx, remaining, scale=1.1)

            if tu >= target_tu:
                break

            if self._should_stay(stay_count, 0.35):
                stay_count += 1
            elif _random.random() < 0.54:
                idx = min(idx + 1, max_rung)
                stay_count = 0
            else:
                idx = max(idx - 1, 0)
                stay_count = 0
        return seq

    # ----------------------------------------------------------------
    # Fast Frenzy -- upper rungs, short holds, frequent changes
    # ----------------------------------------------------------------

    def _gen_high_jitter(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Fast Frenzy: high-energy upper speeds with quick changes."""
        seq = []
        tu = 0.0

        # Explicitly start high
        hi_min = n // 2
        idx = _random.randint(hi_min, n - 1)
        stay_count = 0

        while tu < target_tu:
            remaining = target_tu - tu
            # Short holds for rapid change feel
            tu += self._take_hold(seq, speeds, idx, remaining, scale=0.5)

            if tu >= target_tu:
                break

            if self._should_stay(stay_count, 0.12):
                stay_count += 1
            else:
                r = _random.random()
                if r < 0.068:
                    idx = min(idx + 2, n - 1)
                elif r < 0.136:
                    idx = max(idx - 2, hi_min)
                elif r < 0.568:
                    idx = min(idx + 1, n - 1)
                else:
                    idx = max(idx - 1, hi_min)
                stay_count = 0
        return seq

    # ----------------------------------------------------------------
    # Tease -- mostly slow, rare sharp spikes with enforced cooldown
    # ----------------------------------------------------------------

    def _gen_spike(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Tease: baseline in the lowest fourth, sharp spikes into the
        top third.  Guarantees at least 3 spikes, then lets probability
        drive additional spikes."""
        seq = []
        tu = 0.0

        # Baseline: lowest fourth.  Spike: top third.
        base_hi = max(0, n // 4)
        spike_lo = n - max(1, n // 3)
        spike_rungs = list(range(spike_lo, n))
        if not spike_rungs:
            spike_rungs = [n - 1]

        idx = _random.randint(0, base_hi)
        spike_hold = _random.uniform(0.3, 0.8)
        cooldown_tu = _random.uniform(1.5, 4.0)
        tu_since_spike = cooldown_tu
        min_spikes = 5
        spike_chance = _random.uniform(0.10, 0.25)
        spike_count = 0
        stay_count = 0

        while tu < target_tu:
            remaining = target_tu - tu

            # Force a spike if we haven't hit the minimum and we're
            # running out of room (each spike needs spike_hold + cooldown).
            spikes_needed = max(0, min_spikes - spike_count)
            force_spike = (spikes_needed > 0
                           and tu_since_spike >= cooldown_tu
                           and remaining <= spikes_needed * (spike_hold + cooldown_tu + 0.5))

            if ((tu_since_spike >= cooldown_tu
                    and (_random.random() < spike_chance or force_spike))
                    and spike_rungs):
                spike_idx = _random.choice(spike_rungs)
                spike_tu = min(spike_hold, remaining)
                if spike_tu > 0:
                    tu += self._emit_hold(seq, speeds, spike_idx, spike_tu)
                    tu_since_spike = 0.0
                    spike_count += 1
                    idx = _random.randint(0, base_hi)
                    stay_count = 0
                if tu >= target_tu:
                    break

            hold_tu = self._take_hold(seq, speeds, idx, remaining, scale=1.1)
            tu += hold_tu
            tu_since_spike += hold_tu

            if tu >= target_tu:
                break

            # Baseline sway: stay at most twice, then forced move.
            if self._should_stay(stay_count, 0.50):
                stay_count += 1
            elif _random.random() < 0.60:
                idx = min(idx + 1, base_hi)
                stay_count = 0
            else:
                idx = max(idx - 1, 0)
                stay_count = 0
        return seq

    # ----------------------------------------------------------------
    # Plateau -- very long holds, deliberate jumps
    # ----------------------------------------------------------------

    def _gen_plateau(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Plateau: long sustained holds, then deliberate jumps."""
        seq = []
        tu = 0.0

        idx = _random.randint(0, n - 1)
        last_idx = -1  # previous rung, to avoid immediate reversal
        plateau_scale = _random.uniform(2, 5)

        while tu < target_tu:
            remaining = target_tu - tu
            tu += self._take_hold(seq, speeds, idx, remaining, scale=plateau_scale, max_real_s=20.0)

            if tu >= target_tu:
                break

            # Collect valid jumps ordered by preference (larger first).
            # Exclude jumping straight back where we just came from.
            candidates = []
            for jump in (2, -2, 1, -1):
                target = idx + jump
                if 0 <= target <= n - 1 and target != last_idx:
                    candidates.append(target)

            if candidates:
                last_idx = idx
                # Usually take the biggest available jump.
                idx = candidates[0] if _random.random() < 0.7 else _random.choice(candidates)
            else:
                # Only option is to reverse — allow it.
                last_idx = idx
                idx = idx - 1 if idx > 0 else idx + 1
        return seq

    # ----------------------------------------------------------------
    # Random Walk -- no macro structure, pure drift
    # ----------------------------------------------------------------

    def _gen_random_walk(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Random Walk: unpredictable drift with no fixed shape."""
        seq = []
        tu = 0.0

        idx = _random.randint(0, n - 1)
        stay_count = 0

        while tu < target_tu:
            remaining = target_tu - tu
            tu += self._take_hold(seq, speeds, idx, remaining)

            if tu >= target_tu:
                break

            if self._should_stay(stay_count, 0.40):
                stay_count += 1
            else:
                r = _random.random()
                if r < 0.417:
                    idx = min(idx + 1, n - 1)
                elif r < 0.833:
                    idx = max(idx - 1, 0)
                elif r < 0.916:
                    idx = min(idx + 2, n - 1)
                else:
                    idx = max(idx - 2, 0)
                stay_count = 0
        return seq

    # ----------------------------------------------------------------
    # Edge -- repeated climb toward near-top, then drop
    # ----------------------------------------------------------------

    def _gen_edge(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Edge: climbs toward peak, drops, climbs again -- never reaches top."""
        seq = []
        tu = 0.0

        # Explicitly start low
        idx = _random.randint(0, n // 2)
        # Never visit the topmost rung
        max_rung = max(1, n - 2) if n >= 3 else 0
        # Small chance to drop one rung before max_rung (adds tension)
        early_drop_chance = _random.uniform(0.0, 0.12)

        while tu < target_tu:
            remaining = target_tu - tu
            tu += self._take_hold(seq, speeds, idx, remaining)

            if tu >= target_tu:
                break

            if idx < max_rung:
                # Optional early stumble
                if (_random.random() < early_drop_chance
                        and idx > n // 2):
                    idx -= 1
                else:
                    idx += 1
            else:
                # At near-top -- drop into the bottom fourth.
                idx = _random.randint(0, max(0, n // 4))
        return seq

    # ----------------------------------------------------------------
    # Anchor -- strong mean reversion around a middle rung
    # ----------------------------------------------------------------

    def _gen_anchor(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Anchor: gravitates around a comfortable middle speed with
        strong return-to-center behaviour."""
        seq = []
        tu = 0.0

        # Pick anchor in middle range, start at it
        anchor_rung = _random.randint(
            max(1, n // 3),
            min(n - 2, 2 * n // 3)
        )
        idx = anchor_rung
        max_drift = _random.randint(1, min(2, max(1, n // 2)))
        stay_count = 0

        while tu < target_tu:
            remaining = target_tu - tu
            tu += self._take_hold(seq, speeds, idx, remaining)

            if tu >= target_tu:
                break

            dist = idx - anchor_rung

            if dist <= -2:
                up_p = 0.70
                down_p = 0.05
            elif dist <= -1:
                up_p = 0.45
                down_p = 0.15
            elif dist >= 2:
                up_p = 0.05
                down_p = 0.70
            elif dist >= 1:
                up_p = 0.15
                down_p = 0.45
            else:
                up_p = 0.30
                down_p = 0.25

            stay_prob = 1.0 - up_p - down_p
            if self._should_stay(stay_count, stay_prob):
                stay_count += 1
            elif _random.random() < up_p / max(up_p + down_p, 0.01):
                idx = min(idx + 1, anchor_rung + max_drift)
                stay_count = 0
            else:
                idx = max(idx - 1, anchor_rung - max_drift)
                stay_count = 0

            idx = max(anchor_rung - max_drift, min(anchor_rung + max_drift, idx))
        return seq

    # ----------------------------------------------------------------
    # Pulse -- steady beat alternating around a center
    # ----------------------------------------------------------------

    def _gen_pulse(self, speeds, n, target_tu):
        # type: (list, int, float) -> list
        """Pulse: steady repetitive beat around a central speed."""
        seq = []
        tu = 0.0

        # Pick a centre rung in the middle third.
        lo = max(1, n // 3)
        hi = min(n - 2, 2 * n // 3)
        if lo > hi:
            lo = hi = n // 2
        center = _random.randint(lo, hi)
        idx = center

        # Beat length: short snappy holds for the hypnotic feel.
        beat_scale = _random.uniform(0.4, 0.7)

        while tu < target_tu:
            tu += self._take_hold(seq, speeds, idx, target_tu - tu,
                                  scale=beat_scale)
            if tu >= target_tu:
                break

            # Alternate: off-centre returns to centre, centre steps away.
            if idx == center:
                # 50% +1, rest spread evenly.
                step = _random.choice([1, 1, 1, -1, 2, -2])
                idx = max(0, min(n - 1, center + step))
            else:
                idx = center
        return seq

    # ================================================================
    # Legacy walk -- used only for custom / fine-tune mode
    # ================================================================

    def _walk(self, speeds, n, drift, intensity, volatility,
               center, target_tu):
        # type: (list, int, float, float, float, float, float) -> List[float]
        """Legacy walk algorithm for custom / fine-tune mode."""
        seq = []
        accumulated_tu = 0.0
        current_idx = _random.randint(0, n - 1)

        # Momentum state
        momentum_dir = 0       # -1, 0, or +1
        momentum_steps_left = 0

        while accumulated_tu < target_tu:
            hold_tu = _random.uniform(self.min_hold_tu, self.max_hold_tu)
            remaining = target_tu - accumulated_tu
            if hold_tu > remaining:
                hold_tu = remaining

            accumulated_tu += self._emit_hold(seq, speeds, current_idx, hold_tu)

            if accumulated_tu >= target_tu:
                break

            # -- Decide next direction --
            direction = self._pick_direction(
                current_idx, n, drift, intensity, volatility, center,
                momentum_dir, momentum_steps_left
            )

            # Update momentum tracking
            if direction != 0:
                if direction == momentum_dir and momentum_steps_left > 0:
                    momentum_steps_left -= 1
                else:
                    momentum_dir = direction
                    momentum_steps_left = int(_random.uniform(
                        self.momentum_min_steps, self.momentum_max_steps))

            # -- Step size --
            step = direction
            if direction != 0:
                roll = _random.random()
                if roll < volatility * 0.10 and n >= 4:
                    # Full-range leap: slowest<->fastest
                    if direction > 0:
                        step = (n - 1) - current_idx
                    else:
                        step = 0 - current_idx
                elif roll < volatility * 0.30 and n >= 3:
                    # Big jump: 2-3 rungs
                    step = direction * min(3, n - 1)
                elif roll < volatility * 0.55:
                    # Moderate jump: 2 rungs
                    step = direction * 2
                # else: +/-1 (adjacent -- the default)

            # Apply max_step ceiling (0 = uncapped)
            if self.max_step > 0:
                step = max(-self.max_step, min(self.max_step, step))

            # Apply step (clamped to valid range)
            current_idx = max(0, min(n - 1, current_idx + step))

        return seq

    def _pick_direction(self, idx, n, drift, intensity, volatility, center,
                        momentum_dir, momentum_steps_left):
        # type: (int, int, float, float, float, float, int, int) -> int
        """Decide the next direction: -1, 0, or +1."""
        # Chance to stay put (stay chance increases at edges)
        stay_chance = 0.30
        if idx <= 0:
            stay_chance = 0.15  # don't get stuck at bottom
        elif idx >= n - 1:
            stay_chance = 0.15  # don't get stuck at top

        if _random.random() < stay_chance:
            return 0

        # If momentum is still active, keep going
        if momentum_steps_left > 0 and momentum_dir != 0:
            # Small chance to defy momentum (drift chance)
            if _random.random() < self.momentum_drift_chance:
                pass  # fall through to normal decision
            else:
                return momentum_dir

        # -- Normal direction decision --

        # Effective range: how far from center the walk is allowed to go
        half_range = (intensity * (n - 1)) / 2.0
        target_lo = center * (n - 1) - half_range
        target_hi = center * (n - 1) + half_range

        # If we're outside the target band, bias back toward center
        if idx > target_hi + 0.5:
            # Above target range -- bias down
            up_weight = max(0.0, 0.3 + drift * 0.15)
            down_weight = 0.7 - drift * 0.15
            return self._weighted_pick(up_weight, down_weight)

        if idx < target_lo - 0.5:
            # Below target range -- bias up
            up_weight = 0.7 + drift * 0.15
            down_weight = max(0.0, 0.3 - drift * 0.15)
            return self._weighted_pick(up_weight, down_weight)

        # Within target band -- follow drift with volatility
        up_bias = 0.5 + drift * 0.35
        down_bias = 0.5 - drift * 0.35

        # Volatility scales the randomness of direction choice
        # Low volatility -> direction is stable (mostly follows drift)
        # High volatility -> direction is erratic
        up_weight = up_bias * (1.0 - volatility * 0.6) + volatility * 0.3
        down_weight = down_bias * (1.0 - volatility * 0.6) + volatility * 0.3

        return self._weighted_pick(up_weight, down_weight)

    def _weighted_pick(self, up_weight, down_weight):
        # type: (float, float) -> int
        """Pick -1, 0, or +1 based on weighted probabilities."""
        total = up_weight + down_weight
        if total <= 0:
            return 0

        r = _random.random() * total
        if r < up_weight:
            return 1
        else:
            return -1

    # ================================================================
    # Lifecycle hooks (called from CueVidSpeedSequence)
    # ================================================================

    def _regenerate(self):
        """Re-generate the sequence now (called when knobs change)."""
        tag = _cue.current_file
        if not tag or not _cue.video_sequence:
            return
        from cue_lib.speed import CueSpeedMode
        mode = _cue.video_sequence.get_mode(tag)
        if mode != CueSpeedMode.AUTO:
            return
        base_path = _cue.speed_resolver.base_path_for(tag)
        if not base_path:
            return
        available = _cue.speed_resolver.get_available_speeds(base_path)
        if len(available) < CUE_MIN_SPEEDS_FOR_SEQUENCE:
            return

        self._video_duration = _cue.vid_manager.get_duration()
        new_seq = self.generate(available)
        entry = _cue.markers._get_or_create_entry(create_vid_key(tag))
        entry["speed_sequence"] = new_seq
        _cue.markers.save_marker(create_vid_key(tag))
        _cue.video_sequence.start(tag)

    def on_wrap_around(self):
        """Called when an AUTO sequence finishes a full cycle.
        Generates a fresh sequence and restarts playback."""
        tag = _cue.current_file
        if not tag:
            return
        base_path = _cue.speed_resolver.base_path_for(tag)
        if not base_path:
            return
        available = _cue.speed_resolver.get_available_speeds(base_path)
        if len(available) < CUE_MIN_SPEEDS_FOR_SEQUENCE:
            return

        # Surprise mode: pick a new random preset each loop
        if self.is_surprise_mode:
            self.active_preset = _random.choice(self.surprise_pool)

        self._video_duration = _cue.vid_manager.get_duration()
        new_seq = self.generate(available)
        entry = _cue.markers._get_or_create_entry(create_vid_key(tag))
        entry["speed_sequence"] = new_seq
        _cue.markers.save_marker(create_vid_key(tag))
        _cue.video_sequence.start(tag)
