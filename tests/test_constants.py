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
    assert constants.CUE_DEFAULT_VIDEO_SPEED > 0


def test_auto_speed_thresholds_are_ordered():
    assert constants.CUE_AUTO_SPEED_MIN_VARIANTS >= 1
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


def test_package_category_enum_has_five_categories_plus_unknown():
    cats = constants.CueImportCategory
    five = [cats.MARKERS, cats.SFX, cats.MUSIC, cats.SPEED_VARIANTS, cats.PRESETS]
    assert len(set(five)) == 5
    assert cats.UNKNOWN not in five


def test_package_category_order_matches_enum_and_excludes_unknown():
    order = constants.CUE_IMPORT_CATEGORY_ORDER
    cats = constants.CueImportCategory
    assert len(order) == len(set(order)) == 5
    assert cats.UNKNOWN not in order
    # Every enum category is listed exactly once.
    assert set(order) == {cats.MARKERS, cats.SFX, cats.MUSIC, cats.SPEED_VARIANTS, cats.PRESETS}


def test_package_category_labels_cover_every_ordered_category():
    labels = constants.CUE_IMPORT_CATEGORY_LABELS
    assert set(labels.keys()) == set(constants.CUE_IMPORT_CATEGORY_ORDER)
    for cat in constants.CUE_IMPORT_CATEGORY_ORDER:
        assert labels[cat]


def test_package_match_levels_are_distinct():
    m = constants.CueImportMatch
    assert len({m.AUTO, m.CONFIRM, m.MISMATCH}) == 3
