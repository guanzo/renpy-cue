# -*- coding: utf-8 -*-
"""Tests for cue_lib.logger's runtime error safety net."""

import os
import sys

import traceback as _traceback

import cue_lib.logger as _logger_mod
from cue_lib.paths import CUE_MOD_DIRNAME


def _raise_here():
    raise ValueError("boom")


def _cue_frame():
    return _traceback.FrameSummary("cue_lib/ui/foo.rpy", 1, "_cue_fn", line="line")


def test_touches_mod_false_for_foreign_traceback():
    try:
        _raise_here()
    except ValueError:
        tb = sys.exc_info()[2]
    assert _logger_mod._cue_traceback_touches_mod(tb) is False


def test_touches_mod_true_for_cue_frame(monkeypatch):
    monkeypatch.setattr(_traceback, "extract_tb", lambda tb: [_cue_frame()])
    assert _logger_mod._cue_traceback_touches_mod(object()) is True


def test_install_sets_callable_handler():
    _logger_mod._cue_install_exception_handler()
    assert callable(_logger_mod._config.exception_handler)


def test_handler_passes_foreign_error_to_renpy():
    _logger_mod._cue_install_exception_handler()
    handler = _logger_mod._config.exception_handler
    try:
        _raise_here()
    except ValueError as exc:
        result = handler(exc, sys.exc_info()[2])
    assert result is False


def test_handler_swallows_cue_error(monkeypatch):
    monkeypatch.setattr(_traceback, "extract_tb", lambda tb: [_cue_frame()])
    _logger_mod._cue_install_exception_handler()
    handler = _logger_mod._config.exception_handler
    try:
        _raise_here()
    except ValueError as exc:
        result = handler(exc, sys.exc_info()[2])
    assert result is True


def test_handler_defers_to_previous_handler(monkeypatch):
    calls = []

    def previous(exc, tb):
        calls.append(exc)
        return True

    monkeypatch.setattr(_logger_mod._config, "exception_handler", previous)
    _logger_mod._cue_install_exception_handler()
    handler = _logger_mod._config.exception_handler
    try:
        _raise_here()
    except ValueError as exc:
        result = handler(exc, sys.exc_info()[2])
        captured = exc
    assert result is True
    assert calls == [captured]


def test_handler_swallows_cue_error_despite_previous(monkeypatch):
    monkeypatch.setattr(_traceback, "extract_tb", lambda tb: [_cue_frame()])

    def previous(exc, tb):
        return False

    monkeypatch.setattr(_logger_mod._config, "exception_handler", previous)
    _logger_mod._cue_install_exception_handler()
    handler = _logger_mod._config.exception_handler
    try:
        _raise_here()
    except ValueError as exc:
        result = handler(exc, sys.exc_info()[2])
    assert result is True


def test_handler_does_not_swallow_in_debug(monkeypatch):
    from cue_lib import constants as _constants

    monkeypatch.setattr(_constants, "CUE_DEBUG", True)
    monkeypatch.setattr(_traceback, "extract_tb", lambda tb: [_cue_frame()])
    _logger_mod._cue_install_exception_handler()
    handler = _logger_mod._config.exception_handler
    try:
        _raise_here()
    except ValueError as exc:
        result = handler(exc, sys.exc_info()[2])
    assert result is False


def test_handler_survives_failing_previous(monkeypatch):
    monkeypatch.setattr(_traceback, "extract_tb", lambda tb: [])

    def previous(exc, tb):
        raise RuntimeError("previous handler broke")

    monkeypatch.setattr(_logger_mod._config, "exception_handler", previous)
    _logger_mod._cue_install_exception_handler()
    handler = _logger_mod._config.exception_handler
    try:
        _raise_here()
    except ValueError as exc:
        result = handler(exc, sys.exc_info()[2])
    assert result is True


def test_handler_survives_own_failure(monkeypatch):
    # A traceback filter that throws must not crash the game: swallow.
    def _boom_extract(tb):
        raise RuntimeError("extract failed")

    monkeypatch.setattr(_traceback, "extract_tb", _boom_extract)
    _logger_mod._cue_install_exception_handler()
    handler = _logger_mod._config.exception_handler
    try:
        _raise_here()
    except ValueError as exc:
        result = handler(exc, sys.exc_info()[2])
    assert result is True


def test_log_error_writes_to_error_log(monkeypatch, tmp_path):
    from cue_lib import state as _state
    from cue_lib.paths import CuePaths

    monkeypatch.setattr(_logger_mod._config, "gamedir", str(tmp_path))
    paths = CuePaths(str(tmp_path / "cue_root"), game_id="test_game")
    monkeypatch.setattr(_state._cue, "paths", paths)

    _logger_mod._cue_logger.clear_error()
    _logger_mod._cue_logger.log_error("sentinel error")

    log_path = os.path.join(str(tmp_path), CUE_MOD_DIRNAME, "error.log")
    with open(log_path) as f:
        content = f.read()
    assert "sentinel error" in content
