# -*- coding: utf-8 -*-
# Tests for cue_lib.constants -- value sanity and backward compat.

from cue_lib import constants


def test_key_prefixes_have_expected_values():
    assert constants.CUE_IMG_KEY_PREFIX == "i_"
    assert constants.CUE_VID_KEY_PREFIX == "v_"
    assert constants.CUE_DLG_KEY_PREFIX == "d_"
    assert constants.CUE_LOOP_KEY_PREFIX == "l_"


def test_key_prefixes_are_distinct():
    prefixes = [
        constants.CUE_IMG_KEY_PREFIX,
        constants.CUE_VID_KEY_PREFIX,
        constants.CUE_DLG_KEY_PREFIX,
        constants.CUE_LOOP_KEY_PREFIX,
    ]
    assert len(set(prefixes)) == 4


def test_audio_and_video_tuning_values_are_sane():
    assert constants.CUE_SFX_CHANNEL_COUNT >= 1
    assert constants.CUE_MAX_INTERP_FPS > 0
    assert constants.CUE_DEFAULT_VIDEO_SPEED > 0


def test_multi_speed_thresholds_are_ordered():
    assert constants.CUE_MULTI_SPEED_MIN_VARIANTS >= 1
    assert constants.CUE_AUTO_SPEED_MIN_VARIANTS >= constants.CUE_MULTI_SPEED_MIN_VARIANTS
    assert constants.CUE_AUTO_SPEED_IDEAL_VARIANTS >= constants.CUE_AUTO_SPEED_MIN_VARIANTS


def test_keymap_names_are_distinct():
    names = [
        constants.CUE_KEYMAP_TOGGLE_OVERLAY,
        constants.CUE_KEYMAP_QUIT_RELAUNCH,
        constants.CUE_KEYMAP_COPY_CONTEXT,
        constants.CUE_KEYMAP_PASTE_CONTEXT,
        constants.CUE_KEYMAP_TOGGLE_SFX_ACTIVE,
        constants.CUE_KEYMAP_PAUSE,
        constants.CUE_KEYMAP_UNDO,
        constants.CUE_KEYMAP_REDO,
        constants.CUE_KEYMAP_SPEED_UP,
        constants.CUE_KEYMAP_SPEED_DOWN,
        constants.CUE_KEYMAP_TOGGLE_SFX_LIBRARY,
        constants.CUE_KEYMAP_TARGET_VIDEO,
        constants.CUE_KEYMAP_TARGET_IMAGE,
        constants.CUE_KEYMAP_TARGET_DIALOGUE,
        constants.CUE_KEYMAP_TARGET_LOOP,
    ]
    assert len(set(names)) == len(names)


