# -*- coding: utf-8 -*-
# Regression: a video loop restart must advance the speed sequence step on the
# SAME tick the video trigger re-arms its markers, so the first marker of a
# re-armed loop fires the CURRENT level, not the previous one.
#
# Both the sequence and the trigger now read the restart verdict from a single
# source of truth -- CueVideoManager.poll_restart() (vm.is_restart) -- computed
# once per frame from one last_elapsed, so the two can never drift apart.  The
# sequence no longer detects the restart from raw get_pos() against its own
# tracker (which a start() could zero independently and desync).
#
# Root cause: each detector kept its own last_elapsed; a sequence start()
# reset one but not the other, so on the restart tick the sequence said
# not-a-restart while the trigger's stale position said backward-jump.  The
# marker then resolved against the previous level.
import os
import types

import renpy.audio.music as _music

from cue_lib.paths import CuePaths
from cue_lib.video.speed import CueVidSpeedSequence
from cue_lib.video.video import CueVideoManager


def _drive(seq, reg, f, pos):
    reg["playing"] = f
    reg["position"] = pos
    seq._vid_manager.poll_restart()
    seq.tick()


def _seq(tmp_path, speed_pair, dur=2.0):
    """A 2-step MULTI sequence over tmp variant files, started at step 0."""
    video_dir = str(tmp_path / "video" / "g")
    os.makedirs(video_dir)
    base = str(tmp_path / "base.webm")
    open(base, "w").close()
    paths = CuePaths(str(tmp_path), game_id="g")
    # Create the variant files before start() so paths_for() finds them.
    open(os.path.join(video_dir, "base_cue0.7x.webm"), "w").close()
    open(os.path.join(video_dir, "base_cue1.3x.webm"), "w").close()
    ctx = types.SimpleNamespace(current_file="scene", top_layer_type="movie")
    _entry = {"speed_mode": "multi", "multi_speed_sequence": list(speed_pair)}
    store = types.SimpleNamespace(get=lambda k, d=None: _entry, _get_or_create_entry=lambda k: _entry)
    vid = CueVideoManager(ctx, channel="video")
    seq = CueVidSpeedSequence(ctx, store, vid)

    def path_for(sp):
        return os.path.join(video_dir, "base_cue%.1fx.webm" % sp)

    seq._speed_resolver = types.SimpleNamespace(
        base_path_for=lambda t: base,
        variant_path=lambda b, sp: os.path.join(video_dir, "base_cue%.1fx.webm" % sp),
        invalidate=lambda tag: None,
    )
    _music._registry["video"] = {"duration": dur}
    seq.start("scene")  # step 0
    return seq, path_for(0.7), path_for(1.3)


def test_seq_advances_on_coarse_pos_wrap(tmp_path):
    """A coarse-pos wrap (get_pos lands >= 0.2s, get_playing lags) must advance
    the step on the wrap tick itself, not one tick later."""
    seq, A, B = _seq(tmp_path, (0.7, 1.3))
    reg = _music._registry["video"]
    _drive(seq, reg, A, 0.50)  # A -> step 0
    _drive(seq, reg, A, 2.90)  # A end -> step 0
    assert seq._step_index == 0
    _drive(seq, reg, B, 0.05)  # A->B -> step 1
    assert seq._step_index == 1
    _drive(seq, reg, B, 2.90)  # B end -> step 1
    assert seq._step_index == 1

    # Coarse wrap into A: get_pos resets to 0.35, get_playing still reports B.
    # Backward jump (2.90 - 0.35 > 0.3) must advance step NOW, matching the
    # trigger's restart detection on the same tick.
    _drive(seq, reg, B, 0.35)
    assert seq._step_index == 0, "step must advance on the coarse wrap tick, got %d" % seq._step_index


def test_seq_coarse_wrap_keeps_fine_wrap(tmp_path):
    """A clean wrap (get_pos lands < 0.2s) still advances the step."""
    seq, A, B = _seq(tmp_path, (0.7, 1.3))
    reg = _music._registry["video"]
    _drive(seq, reg, A, 0.50)
    _drive(seq, reg, A, 2.90)
    _drive(seq, reg, B, 0.05)
    _drive(seq, reg, B, 2.90)
    assert seq._step_index == 1
    _drive(seq, reg, A, 0.08)  # clean wrap: pos < 0.2, file change too
    assert seq._step_index == 0


def test_seq_no_false_wrap_on_forward_progress(tmp_path):
    """Normal forward playback must not look like a wrap."""
    seq, A, B = _seq(tmp_path, (0.7, 1.3))
    reg = _music._registry["video"]
    _drive(seq, reg, A, 0.50)
    _drive(seq, reg, A, 2.90)
    assert seq._step_index == 0, "forward progress within a segment must not wrap"


def test_seq_anchor_catches_small_backward_jump(tmp_path):
    """A restart whose backward gap is under the fixed threshold is still
    detected when the jump is near-end -> near-start of a short clip (the
    duration anchor, used in addition to the fixed-jump fallback)."""
    seq, A, B = _seq(tmp_path, (0.7, 1.3), dur=1.0)
    reg = _music._registry["video"]
    _drive(seq, reg, A, 0.50)
    _drive(seq, reg, A, 0.65)
    assert seq._step_index == 0
    # gap is 0.30 (not > 0.3), but prev=0.65 is late in a 1.0s clip and
    # curr=0.35 is early -- the duration anchor must advance the step.
    _drive(seq, reg, A, 0.35)
    assert seq._step_index == 1, "duration anchor must advance the step"


def test_seq_anchor_rejects_mid_clip_jitter(tmp_path):
    """A backward jitter in the MIDDLE of a clip (not near the end) must not be
    treated as a restart: neither the duration anchor nor the fixed fallback
    can fire, so the step stays put."""
    seq, A, B = _seq(tmp_path, (0.7, 1.3), dur=2.0)
    reg = _music._registry["video"]
    _drive(seq, reg, A, 0.50)
    _drive(seq, reg, A, 0.90)
    assert seq._step_index == 0
    # 0.90 -> 0.75 is a backward jump of 0.15 (sub-threshold) and neither is
    # near the end/start of the clip, so the step must NOT advance.
    _drive(seq, reg, A, 0.75)
    assert seq._step_index == 0, "mid-clip jitter must not advance the step"


def test_seq_heals_mis_synced_step(tmp_path):
    """After a restart advances the step, the next non-restart tick re-syncs it
    to the file actually playing -- file-match is authoritative, so a mis-synced
    step is corrected within one tick."""
    seq, A, B = _seq(tmp_path, (0.7, 1.3), dur=1.0)
    reg = _music._registry["video"]
    _drive(seq, reg, A, 0.50)
    _drive(seq, reg, A, 0.65)
    assert seq._step_index == 0
    # Anchor restart (near-end -> near-start of a 1.0s clip) advances the step,
    # even though the playing file is still A.
    _drive(seq, reg, A, 0.35)
    assert seq._step_index == 1
    # No restart on the next tick; file-match re-syncs the step to A (index 0).
    _drive(seq, reg, A, 0.45)
    assert seq._step_index == 0, "file-match must re-sync the step"


def test_poll_restart_is_single_verdict(tmp_path):
    """vm.is_restart must be computed once per frame and consumed by both the
    sequence and the trigger -- not recomputed by each with its own tracker."""
    seq, A, B = _seq(tmp_path, (0.7, 1.3))
    reg = _music._registry["video"]
    _drive(seq, reg, A, 0.50)
    _drive(seq, reg, A, 2.90)
    assert seq._step_index == 0
    # A wrap: poll_restart flags is_restart=True, and it must remain True for
    # this whole frame so both consumers see the same verdict.
    reg["position"] = 0.05
    assert seq._vid_manager.poll_restart() is True
    assert seq._vid_manager.is_restart is True
