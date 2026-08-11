# -*- coding: utf-8 -*-
# CueAutoSpeedGenerator -- procedural speed sequence generation.
#
# Generates "auto" speed sequences by walking through speed-space with
# parameterized drift, intensity, volatility, and center-of-gravity.
# Presets are saved knob values (data, not code paths), and modifiers
# (rest beats, micro-bursts) stack on any preset.
#
# Instantiated at _cue.auto_speed.

import random as _random

import renpy

from cue_lib.state import _cue
from cue_lib.util import _cue_log, create_vid_key


# ==========================================================================
# Module-level helpers (imported into store by cue_z.rpy for screen access)
# ==========================================================================

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
        "surprise":       "Surprise Me",
        None:             "Custom",
    }
    return labels.get(preset_name, preset_name if preset_name else "Custom")


def _cue_auto_preset_description(preset_name):
    # type: (str) -> str
    """One-line description for a preset tooltip."""
    descs = {
        "roller_coaster": "Full slow-fast-slow wave across the entire speed range",
        "build_up":       "Steady climb from slow to fast, then holds at peak",
        "cool_down":      "Starts fast, gently settles back down to slow",
        "slow_groove":    "Stays in the lower speeds with a gentle sway",
        "fast_frenzy":    "High-energy, stays in the upper speeds",
        "tease":          "Mostly slow with sudden, brief spikes of speed",
        "plateau":        "Long, sustained holds at one speed before shifting",
        "random_walk":    "Unpredictable drift with no fixed shape",
        "edge":           "Builds toward peak, drops, builds again -- never quite gets there",
        "anchor":         "Gravitates around a comfortable middle speed",
        "surprise":       "Picks a random vibe each sequence -- expect anything!",
    }
    return descs.get(preset_name, "")


# ==========================================================================

class CueAutoSpeedGenerator(object):
    """Procedural speed sequence generator.

    One walk algorithm. All variety comes from parameter values and
    their interpolation over the course of a sequence."""

    def __init__(self):
        # History
        self.history = []       # list of {'speeds': [...], 'preset': '...'} dicts
        self.max_history = 20

        # ================================================================
        # Tunables -- tweak these to change the feel of generated sequences
        # ================================================================

        # Sequence length in time-units (1 TU = one play of 1.0x video)
        self.min_duration_tu = 8.0
        self.max_duration_tu = 25.0

        # Hold time per rung: how long to linger in time-units.
        # Shorter = snappy transitions. Longer = smooth, sustained holds.
        self.min_hold_tu = 0.8
        self.max_hold_tu = 3.5

        # Max rungs to jump in one step, 0 = no ceiling.
        # When set (1+), caps volatility-driven jumps. When 0, full-range
        # leaps are possible at high volatility. Default: 0 (uncapped).
        self.max_step = 0

        # Momentum: once moving in a direction, keep going for this
        # many steps before the direction can reverse.
        self.momentum_min_steps = 2
        self.momentum_max_steps = 5

        # Chance per step to ignore momentum and drift (adds unpredictability)
        self.momentum_drift_chance = 0.15

        # Max rungs between end of prev sequence and start of next
        self.max_start_delta = 2

        # -- Rest beats --
        # Chance a "phrase" is followed by a brief pause at the slowest speed.
        self.rest_chance = 0.25
        self.min_phrase_tu = 5.0    # min TU between rests
        self.rest_hold_tu = 1.5     # how long the rest lasts

        # -- Micro-bursts --
        # Chance a normal hold is replaced by rapid alternation between
        # two adjacent speeds (like a tremolo / shiver).
        self.micro_burst_chance = 0.06
        self.micro_burst_alternations = 3  # how many back-and-forth swaps

        # ================================================================
        # Presets -- named (drift, intensity, volatility, center) combos
        # ================================================================
        # drift:      -1.0 (trend down) .. +1.0 (trend up)
        # intensity:   0.0 (tiny range) ..  1.0 (full range)
        # volatility:  0.0 (plateau)    ..  1.0 (very twitchy)
        # center:      0.0 (bottom)     ..  1.0 (top of speed range)

        self.presets = {
            "roller_coaster":  dict(drift= 0.0, intensity=1.0, volatility=0.40, center=0.50),
            "build_up":        dict(drift= 0.8, intensity=0.8, volatility=0.15, center=0.20),
            "cool_down":       dict(drift=-0.7, intensity=0.6, volatility=0.15, center=0.50),
            "slow_groove":     dict(drift= 0.0, intensity=0.3, volatility=0.25, center=0.18),
            "fast_frenzy":     dict(drift= 0.0, intensity=0.3, volatility=0.40, center=0.85),
            "tease":           dict(drift= 0.0, intensity=0.8, volatility=0.85, center=0.12),
            "plateau":         dict(drift= 0.0, intensity=0.6, volatility=0.06, center=0.50),
            "random_walk":     dict(drift= 0.0, intensity=1.0, volatility=0.55, center=0.50),
            "edge":            dict(drift= 0.8, intensity=0.9, volatility=0.55, center=0.18),
            "anchor":          dict(drift= 0.0, intensity=0.5, volatility=0.18, center=0.35),
        }

        # Which preset to use when "Surprise me" is selected (random each generation)
        self.surprise_pool = [
            "roller_coaster", "build_up", "cool_down", "slow_groove",
            "fast_frenzy", "tease", "plateau", "random_walk",
            "edge", "anchor",
        ]

        # Currently active preset name (or None for custom/fine-tuned)
        self.active_preset = "roller_coaster"

        # Modifier toggles
        self.rest_beats_enabled = True
        self.micro_bursts_enabled = True

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
        if preset_name in self.presets or preset_name == "surprise":
            self.active_preset = preset_name
            self._regenerate()
            renpy.restart_interaction()

    def toggle_rest_beats(self):
        """Toggle rest-beat modifier."""
        self.rest_beats_enabled = not self.rest_beats_enabled
        self._regenerate()
        renpy.restart_interaction()

    def toggle_micro_bursts(self):
        """Toggle micro-burst modifier."""
        self.micro_bursts_enabled = not self.micro_bursts_enabled
        self._regenerate()
        renpy.restart_interaction()

    def set_length(self, preset_key):
        # type: (str) -> None
        """Set length from a preset key: 'short', 'medium', 'long'."""
        if preset_key == "short":
            self.min_duration_tu = 5.0
            self.max_duration_tu = 12.0
        elif preset_key == "medium":
            self.min_duration_tu = 8.0
            self.max_duration_tu = 25.0
        elif preset_key == "long":
            self.min_duration_tu = 15.0
            self.max_duration_tu = 45.0
        self._regenerate()
        renpy.restart_interaction()

    def get_active_length_key(self):
        # type: () -> str
        """Return 'short', 'medium', or 'long' based on current duration range."""
        avg = (self.min_duration_tu + self.max_duration_tu) / 2.0
        if avg < 15:
            return "short"
        elif avg < 30:
            return "medium"
        else:
            return "long"

    def surprise_me(self):
        """Pick a random preset from the surprise pool and regenerate."""
        self.active_preset = _random.choice(self.surprise_pool)
        self._regenerate()
        renpy.restart_interaction()

    def save_current(self):
        """Save the currently playing sequence to history."""
        tag = _cue.current_file
        if not tag:
            return
        seq = _cue.video_sequence.speeds_for(tag) if _cue.video_sequence else None
        if not seq:
            return
        preset_label = _cue_auto_preset_label(self.active_preset)
        entry = dict(speeds=list(seq), preset=preset_label)
        self.history.insert(0, entry)
        if len(self.history) > self.max_history:
            self.history.pop()
        renpy.restart_interaction()

    def replay_history(self, index):
        # type: (int) -> None
        """Replay a saved sequence from history by writing it into the
        marker entry and starting playback."""
        if index < 0 or index >= len(self.history):
            return
        tag = _cue.current_file
        if not tag:
            return
        saved = self.history[index].get("speeds")
        if not saved:
            return
        entry = _cue.markers._get_or_create_entry(create_vid_key(tag))
        entry["speed_sequence"] = list(saved)
        _cue.markers.save_marker(create_vid_key(tag))
        if _cue.video_sequence:
            _cue.video_sequence.start(tag)
        renpy.restart_interaction()

    def remove_from_history(self, index):
        # type: (int) -> None
        """Remove a single entry from history at the given index."""
        if 0 <= index < len(self.history):
            self.history.pop(index)
            renpy.restart_interaction()

    def clear_history(self):
        """Clear the entire history."""
        self.history = []
        renpy.restart_interaction()

    # ================================================================
    # Generation entry point
    # ================================================================

    def generate(self, available_speeds, prev_sequence=None):
        # type: (list, list) -> list
        """Generate a new speed sequence.

        Args:
            available_speeds: sorted list of speeds from disk variants.
            prev_sequence: the previous sequence (list of floats), used
                           to constrain the start speed for continuity.
        Returns:
            list of floats -- the generated speed sequence.
        """
        if not available_speeds or len(available_speeds) < 2:
            return [available_speeds[0]] * 8 if available_speeds else [1.0]

        n = len(available_speeds)

        # 1. Resolve knobs
        drift, intensity, volatility, center = self._resolve_knobs()

        # 2. Pick target duration
        target_tu = _random.uniform(self.min_duration_tu, self.max_duration_tu)

        # 3. Determine start index (continuity from prev sequence)
        start_idx = self._pick_start_index(n, prev_sequence, available_speeds)

        # 4. Walk
        seq = self._walk(
            available_speeds, n, start_idx,
            drift, intensity, volatility, center,
            target_tu
        )

        # 5. History
        preset_label = _cue_auto_preset_label(self.active_preset)
        h = dict(speeds=list(seq), preset=preset_label)
        self.history.insert(0, h)
        if len(self.history) > self.max_history:
            self.history.pop()

        return seq

    # ================================================================
    # Knob resolution
    # ================================================================

    def _resolve_knobs(self):
        # type: () -> tuple
        """Return (drift, intensity, volatility, center) for the current
        active preset, or custom values when active_preset is None."""
        if self.active_preset and self.active_preset in self.presets:
            p = self.presets[self.active_preset]
            return (p["drift"], p["intensity"], p["volatility"], p["center"])
        # Custom / fine-tuned
        return (self.custom_drift, self.custom_intensity,
                self.custom_volatility, self.custom_center)

    # ================================================================
    # Start-index selection (continuity)
    # ================================================================

    def _pick_start_index(self, n, prev_sequence, available_speeds):
        # type: (int, list, list) -> int
        """Pick a starting speed index, constrained by the previous
        sequence's last speed for continuity."""
        if not prev_sequence or len(prev_sequence) < 1:
            # First sequence: start anywhere in the bottom third
            return _random.randint(0, max(0, n // 3))

        last_speed = prev_sequence[-1]

        # Find the index closest to last_speed
        last_idx = 0
        best_dist = float('inf')
        for i, sp in enumerate(available_speeds):
            dist = abs(sp - last_speed)
            if dist < best_dist:
                best_dist = dist
                last_idx = i

        # Clamp start to within max_start_delta of last_idx
        lo = max(0, last_idx - self.max_start_delta)
        hi = min(n - 1, last_idx + self.max_start_delta)
        if lo >= hi:
            return last_idx
        return _random.randint(lo, hi)

    # ================================================================
    # The walk -- core algorithm
    # ================================================================

    def _walk(self, speeds, n, start_idx, drift, intensity, volatility,
               center, target_tu):
        # type: (list, int, int, float, float, float, float, float) -> list
        """Walk through speed-space and return a list of speed values.

        At each step the walk decides:
        1. How long to hold the current speed (hold_tu -> play count)
        2. Whether to insert a rest beat
        3. Whether to insert a micro-burst instead of a normal hold
        4. Which direction to step next (based on momentum, drift, volatility)
        """
        seq = []
        accumulated_tu = 0.0
        current_idx = start_idx

        # Momentum state
        momentum_dir = 0       # -1, 0, or +1
        momentum_steps_left = 0

        # Rest tracking
        tu_since_last_rest = 0.0

        while accumulated_tu < target_tu:
            sp = speeds[current_idx]

            # -- Determine hold duration --
            hold_tu = _random.uniform(self.min_hold_tu, self.max_hold_tu)
            # Don't overshoot target
            remaining = target_tu - accumulated_tu
            if hold_tu > remaining:
                hold_tu = max(0.3, remaining)

            # -- Micro-burst? --
            if (self.micro_bursts_enabled
                    and _random.random() < self.micro_burst_chance
                    and hold_tu >= 0.5):
                self._emit_micro_burst(seq, speeds, n, current_idx, hold_tu)
            else:
                # -- Normal hold --
                plays = max(1, int(round(sp * hold_tu)))
                for _ in range(plays):
                    seq.append(sp)

            accumulated_tu += hold_tu
            tu_since_last_rest += hold_tu

            # -- Rest beat? --
            if (self.rest_beats_enabled
                    and tu_since_last_rest >= self.min_phrase_tu
                    and _random.random() < self.rest_chance
                    and accumulated_tu < target_tu - self.rest_hold_tu):
                slowest_sp = speeds[0]
                rest_plays = max(1, int(round(slowest_sp * self.rest_hold_tu)))
                for _ in range(rest_plays):
                    seq.append(slowest_sp)
                accumulated_tu += self.rest_hold_tu
                tu_since_last_rest = 0.0

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
                    momentum_steps_left = _random.uniform(self.momentum_min_steps,
                                                           self.momentum_max_steps)

            # -- Step size --
            # Volatility controls jump magnitude:
            #   Low volatility   -> almost always +/-1 (smooth ramp)
            #   High volatility  -> can jump several rungs or full-range
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

    def _emit_micro_burst(self, seq, speeds, n, idx, hold_tu):
        # type: (list, list, int, int, float) -> None
        """Emit a rapid alternation between idx and an adjacent speed
        instead of a normal hold. Feels like a tremolo / shiver."""
        # Pick adjacent speed
        if idx <= 0:
            other_idx = 1
        elif idx >= n - 1:
            other_idx = n - 2
        else:
            other_idx = idx + _random.choice([-1, 1])

        sp_a = speeds[idx]
        sp_b = speeds[other_idx]

        # Alternate back and forth
        burst_pairs = self.micro_burst_alternations
        for _ in range(burst_pairs):
            seq.append(sp_a)
            seq.append(sp_b)

        # End on the original speed
        seq.append(sp_a)

    # ================================================================
    # Lifecycle hooks (called from CueVidSpeedSequence)
    # ================================================================

    def _regenerate(self):
        """Re-generate the sequence now (called when knobs change)."""
        tag = _cue.current_file
        if not tag or not _cue.video_sequence:
            return
        from cue_lib.speed import SpeedMode
        mode = _cue.video_sequence.get_mode(tag)
        if mode != SpeedMode.AUTO:
            return
        base_path = _cue.speed_resolver.base_path_for(tag)
        if not base_path:
            return
        available = _cue.speed_resolver.get_available_speeds(base_path)
        if len(available) < 2:
            return

        prev = _cue.video_sequence.speeds_for(tag)
        new_seq = self.generate(available, prev)
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
        if len(available) < 2:
            return

        prev = _cue.video_sequence.speeds_for(tag)
        new_seq = self.generate(available, prev)
        entry = _cue.markers._get_or_create_entry(create_vid_key(tag))
        entry["speed_sequence"] = new_seq
        _cue.markers.save_marker(create_vid_key(tag))
        _cue.video_sequence.start(tag)
