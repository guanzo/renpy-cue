# -*- coding: utf-8 -*-
# Tests for the pure logic in cue_lib.util -- key helpers, time formatting,
# and persistent unwrapping.  These functions were decoupled from the _cue
# singleton / Ren'Py runtime so they can be tested in isolation.

from cue_lib.util import (
    _cue_clamp_time,
    _cue_format_time,
    _cue_parse_time,
    _cue_speed_label,
    _cue_unwrap_persistent,
    create_dlg_key,
    create_img_key,
    create_loop_key,
    create_vid_key,
    get_key_dialogue,
    get_key_file,
    get_key_prefix,
    is_dlg_key,
    is_img_key,
    is_loop_key,
    is_vid_key,
)


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def test_create_img_key():
    assert create_img_key("bg beach") == "i_bg beach"


def test_create_vid_key():
    assert create_vid_key("anim_envy_bj3") == "v_anim_envy_bj3"


def test_create_loop_key():
    assert create_loop_key("file") == "l_file"


def test_create_loop_key_empty_file_for_global_pool():
    assert create_loop_key("") == "l_"


def test_create_dlg_key():
    assert create_dlg_key(("file", "dialogue")) == "d_file__dialogue"


def test_is_key_type_checks():
    assert is_img_key("i_bg")
    assert not is_img_key("v_anim")
    assert is_vid_key("v_anim")
    assert not is_vid_key("i_bg")
    assert is_dlg_key("d_file__dlg")
    assert not is_dlg_key("i_bg")
    assert is_loop_key("l_file")
    assert not is_loop_key("d_file__dlg")


def test_get_key_file_strips_prefix():
    assert get_key_file("i_bg beach") == "bg beach"
    assert get_key_file("v_movie") == "movie"
    assert get_key_file("l_file") == "file"


def test_get_key_file_dialogue_strips_text():
    assert get_key_file("d_file__dialogue") == "file"
    # Legacy | separator
    assert get_key_file("d_file|dialogue") == "file"


def test_get_key_dialogue():
    assert get_key_dialogue("d_file__dialogue") == "dialogue"
    # Legacy | separator
    assert get_key_dialogue("d_file|dialogue") == "dialogue"


def test_get_key_dialogue_without_separator_returns_empty():
    assert get_key_dialogue("d_plain") == ""
    assert get_key_dialogue("i_bg") == ""


def test_get_key_prefix():
    assert get_key_prefix("i_bg") == "i_"
    assert get_key_prefix("v_anim") == "v_"
    assert get_key_prefix("d_file__dlg") == "d_"
    assert get_key_prefix("l_file") == "l_"


# ---------------------------------------------------------------------------
# Time clamping
# ---------------------------------------------------------------------------

def test_clamp_time_within_range():
    assert _cue_clamp_time(5.0, 10.0) == 5.0


def test_clamp_time_below_zero():
    assert _cue_clamp_time(-5.0, 10.0) == 0.0


def test_clamp_time_above_duration():
    assert _cue_clamp_time(15.0, 10.0) == 10.0


def test_clamp_time_zero_duration_keeps_positive_time():
    assert _cue_clamp_time(5.0, 0.0) == 5.0


def test_clamp_time_negative_duration_clamps_below():
    assert _cue_clamp_time(-5.0, -3.0) == 0.0


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------

def test_format_time_none():
    assert _cue_format_time(None) == "00:00.00"


def test_format_time_negative():
    assert _cue_format_time(-1.0) == "00:00.00"


def test_format_time_zero():
    assert _cue_format_time(0.0) == "00:00.00"


def test_format_time_minutes_and_centiseconds():
    assert _cue_format_time(65.5) == "01:05.50"


def test_format_time_under_an_hour():
    assert _cue_format_time(3599.5) == "59:59.50"


def test_format_time_over_an_hour():
    assert _cue_format_time(3723.5) == "01:02:03.50"


def test_format_time_centiseconds_truncate_like_int_cast():
    # 0.99 is not exactly representable in binary floats; the centisecond
    # fraction uses int() truncation, matching the game's formatting.
    assert _cue_format_time(3599.99) == "59:59.98"


def test_format_time_exactly_one_hour():
    assert _cue_format_time(3600.0) == "01:00:00.00"


# ---------------------------------------------------------------------------
# Speed labels
# ---------------------------------------------------------------------------

def test_speed_label():
    assert _cue_speed_label(1.0) == "1.0x"
    assert _cue_speed_label(1.5) == "1.5x"
    assert _cue_speed_label(0.5) == "0.5x"
    assert _cue_speed_label(2.0) == "2.0x"


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

def test_parse_time_none():
    assert _cue_parse_time(None) is None


def test_parse_time_empty_string():
    assert _cue_parse_time("") is None
    assert _cue_parse_time("   ") is None


def test_parse_time_raw_float():
    assert _cue_parse_time("90.5") == 90.5


def test_parse_time_raw_float_with_whitespace():
    assert _cue_parse_time("  90.5  ") == 90.5


def test_parse_time_negative_number_rejected():
    assert _cue_parse_time("-5") is None


def test_parse_time_minutes_seconds():
    assert _cue_parse_time("01:23.45") == 83.45


def test_parse_time_hours_minutes_seconds():
    assert _cue_parse_time("01:02:03.45") == 3723.45


def test_parse_time_comma_decimal_separator():
    assert _cue_parse_time("1:23,45") == 83.45


def test_parse_time_garbage_returns_none():
    assert _cue_parse_time("abc") is None
    assert _cue_parse_time("::") is None


# ---------------------------------------------------------------------------
# Persistent unwrapping
# ---------------------------------------------------------------------------

def test_unwrap_persistent_plain_dict():
    assert _cue_unwrap_persistent({"a": 1}) == {"a": 1}


def test_unwrap_persistent_nested():
    data = {"a": {"b": [1, {"c": 2}], "d": set([3, 4])}}
    assert _cue_unwrap_persistent(data) == {"a": {"b": [1, {"c": 2}], "d": set([3, 4])}}


def test_unwrap_persistent_list_like():
    assert _cue_unwrap_persistent([1, [2, 3]]) == [1, [2, 3]]
    assert _cue_unwrap_persistent((1, 2)) == [1, 2]


def test_unwrap_persistent_set_like():
    result = _cue_unwrap_persistent(set([1, 2, 3]))
    assert isinstance(result, set)
    assert result == set([1, 2, 3])


def test_unwrap_persistent_strings_untouched():
    assert _cue_unwrap_persistent("hello") == "hello"


def test_unwrap_persistent_scalars_untouched():
    assert _cue_unwrap_persistent(42) == 42
    assert _cue_unwrap_persistent(None) is None
    assert _cue_unwrap_persistent(3.14) == 3.14


def test_unwrap_persistent_duck_typed_mapping():
    class FakeDict(object):
        def __init__(self):
            self._data = {"x": 1, "y": [2]}

        def items(self):
            return self._data.items()

        def keys(self):
            return self._data.keys()

    result = _cue_unwrap_persistent(FakeDict())
    assert type(result) is dict
    assert result == {"x": 1, "y": [2]}
