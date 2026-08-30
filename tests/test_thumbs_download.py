# -*- coding: utf-8 -*-
# Tests for the download path of cue_lib.thumbs -- CueThumbManager fetches the
# merged mapping asset on a background thread (network hop injected), replaces
# the cache only when the remote scraped date is newer, then reloads the
# mapping and pokes the main loop itself.  The marker-filepath fallback is
# unchanged.

import json as _json
import os
import threading

import pytest
import renpy.config as _config

from cue_lib.paths import CuePaths
from cue_lib.thumbs import CueThumbManager, _cue_format_http_date, _cue_is_newer
from tests.fakes import DiskBackedMarkers

GAME_ID = "test_game"
SID = "TestGame-12345"


class _FakeResponse(object):
    def __init__(self, code=200, headers=None, body=b""):
        self.code = code
        self._headers = headers or {}
        self._body = body
        self._pos = 0

    def headers_get(self, name):
        return self._headers.get(name)

    def read(self, size):
        chunk = self._body[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self):
        pass


def _public_resolver(host):
    return [(0, 0, 0, "", ("1.2.3.4", 0))]


def _fetcher(body=None, error=None):
    """A fake network hop: returns body (a merged-asset dict, serialized on
    read) or raises error.  The URL is ignored -- the asset host is fixed."""
    payload = _json.dumps(body).encode("utf-8") if body is not None else b""

    def fetcher(url, timeout, headers=None):
        if error is not None:
            raise error
        return _FakeResponse(200, {"Content-Length": str(len(payload))}, payload)

    return fetcher


def _not_modified_fetcher(body):
    """A conditional-aware hop: answers 304 (content unchanged) when the
    request carries If-Modified-Since, else streams the body -- exactly how
    GitHub's release-asset CDN treats a cache with a fresh-enough mtime."""
    payload = _json.dumps(body).encode("utf-8") if body is not None else b""

    def fetcher(url, timeout, headers=None):
        if headers and "If-Modified-Since" in headers:
            return _FakeResponse(304, {}, b"")
        return _FakeResponse(200, {"Content-Length": str(len(payload))}, payload)

    return fetcher


def _merged(scraped, entries):
    return {"scraped": scraped, "games": {SID: {"game": "T", "install": "T", "entries": entries}}}


@pytest.fixture(autouse=True)
def _mock_config(monkeypatch, tmp_path):
    """Point the mock config's gamedir at a tmp install dir holding the mod."""
    gamedir = str(tmp_path / "game")
    monkeypatch.setattr(_config, "gamedir", gamedir)
    monkeypatch.setattr(_config, "save_directory", SID)
    return gamedir


def _make_manager(tmp_path, fetcher):
    paths = CuePaths(str(tmp_path / "cue_root"), GAME_ID)
    m = CueThumbManager(paths, DiskBackedMarkers(paths), fetcher=fetcher)
    m._dl._resolve = _public_resolver
    return m


def _cache_path(tmp_path):
    return os.path.join(str(tmp_path / "cue_root"), "data", "cue_thumbs.json")


def _write_cache(tmp_path, content):
    path = _cache_path(tmp_path)
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as f:
        f.write(_json.dumps(content))


def _write_marker(root, name, entry):
    path = os.path.join(str(root / "cue_root"), "data", "markers", GAME_ID, name + ".json")
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as f:
        f.write(_json.dumps(entry))


# ---------------------------------------------------------------------------
# maybe_download -- start-once, disabled no-op
# ---------------------------------------------------------------------------


def test_maybe_download_starts_once(tmp_path, _mock_config):
    gate = threading.Event()

    def slow_fetcher(url, timeout):
        gate.wait()
        raise RuntimeError("boom")

    m = _make_manager(tmp_path, slow_fetcher)
    m.maybe_download()
    assert m.state == "downloading"
    m.maybe_download()  # second call while in-flight must not double-start
    assert m.state == "downloading"
    gate.set()
    m._thread.join()
    assert m.state == "error"


def test_maybe_download_disabled_is_noop(tmp_path, _mock_config):
    m = _make_manager(tmp_path, _fetcher(body=_merged("2026-08-29T10:00:00", {"A": "a.png"})))
    m.disable()
    m.maybe_download()
    assert m.state == "idle"
    assert not m._fetched
    assert not os.path.exists(_cache_path(tmp_path))


# ---------------------------------------------------------------------------
# _run -- the worker does the network, the replace decision, and the reload
# ---------------------------------------------------------------------------


def test_run_downloads_and_loads(tmp_path, _mock_config):
    m = _make_manager(tmp_path, _fetcher(body=_merged("2026-08-29T10:00:00", {"Run 1": "images/gallery/run1.png"})))

    m._run()

    assert m.state == "idle"
    assert m.entries == {"Run 1": "images/gallery/run1.png"}
    assert os.path.isfile(_cache_path(tmp_path))


def test_run_keeps_fresher_cache(tmp_path, _mock_config):
    _write_cache(tmp_path, _merged("2026-08-29T12:00:00", {"A": "a.png"}))
    m = _make_manager(tmp_path, _fetcher(body=_merged("2026-08-29T10:00:00", {"A": "b.png"})))

    m._run()

    # Remote is older -- the cache keeps its own (newer) entries.
    assert m.entries == {"A": "a.png"}


def test_run_replaces_staler_cache(tmp_path, _mock_config):
    _write_cache(tmp_path, _merged("2026-08-29T10:00:00", {"A": "a.png"}))
    m = _make_manager(tmp_path, _fetcher(body=_merged("2026-08-29T12:00:00", {"A": "b.png"})))

    m._run()

    assert m.entries == {"A": "b.png"}


def test_run_error_keeps_cache(tmp_path, _mock_config):
    _write_cache(tmp_path, _merged("2026-08-29T10:00:00", {"A": "a.png"}))
    m = _make_manager(tmp_path, _fetcher(error=RuntimeError("offline")))

    m._run()
    assert m.state == "error"
    assert m.error

    # The cache is untouched and still serves.
    m.load()
    assert m.entries == {"A": "a.png"}


def test_run_error_falls_back_to_marker(tmp_path, _mock_config):
    # No cache at all; the download fails -- the marker filepath still serves.
    _write_marker(tmp_path, "a", {"replay": "Run 1", "filepath": "images/bg/beach.png"})
    m = _make_manager(tmp_path, _fetcher(error=RuntimeError("offline")))

    m._run()
    assert m.state == "error"
    assert m.thumb_for("Run 1") == "images/bg/beach.png"


def test_maybe_download_end_to_end_thread(tmp_path, _mock_config):
    m = _make_manager(tmp_path, _fetcher(body=_merged("2026-08-29T10:00:00", {"Run 1": "images/gallery/run1.png"})))

    m.maybe_download()
    deadline = 5.0
    while m.state == "downloading" and deadline > 0:
        import time as _time

        _time.sleep(0.01)
        deadline -= 0.01
    assert m.state == "idle"
    assert m.entries == {"Run 1": "images/gallery/run1.png"}


# ---------------------------------------------------------------------------
# conditional GET -- If-Modified-Since against the cache mtime
# ---------------------------------------------------------------------------


def test_run_304_keeps_cache_when_unchanged(tmp_path, _mock_config):
    _write_cache(tmp_path, _merged("2026-08-29T10:00:00", {"A": "a.png"}))
    # The CDN answers 304 (content unchanged) because the cache exists and
    # its mtime backs the If-Modified-Since header -- even a newer remote
    # body is never fetched.
    m = _make_manager(tmp_path, _not_modified_fetcher(body=_merged("2026-08-29T12:00:00", {"A": "b.png"})))

    m._run()

    assert m.entries == {"A": "a.png"}


def test_run_no_cache_bypasses_conditional(tmp_path, _mock_config):
    # No cache yet -> no If-Modified-Since header -> the CDN streams the body.
    m = _make_manager(tmp_path, _not_modified_fetcher(body=_merged("2026-08-29T10:00:00", {"Run 1": "a.png"})))

    m._run()

    assert m.entries == {"Run 1": "a.png"}


def test_cue_format_http_date_is_gmt_rfc_1123():
    import calendar as _calendar
    import time as _time

    ts = _calendar.timegm(_time.strptime("2026-08-29 12:34:56", "%Y-%m-%d %H:%M:%S"))
    out = _cue_format_http_date(ts)
    # RFC 1123 GMT date, the exact shape a CDN's Last-Modified comparison needs.
    assert out == "Sat, 29 Aug 2026 12:34:56 GMT"
    parsed = _calendar.timegm(_time.strptime(out[:-4], "%a, %d %b %Y %H:%M:%S"))
    assert parsed == ts
    # A missing mtime must not crash the conditional path.
    assert isinstance(_cue_format_http_date(None), str)


# ---------------------------------------------------------------------------
# _cue_is_newer -- the replace decision
# ---------------------------------------------------------------------------


def test_cue_is_newer():
    assert _cue_is_newer(None, "2026-08-29T10:00:00") is False  # no remote date
    assert _cue_is_newer("2026-08-29T10:00:00", None) is True  # no cache yet
    assert _cue_is_newer("2026-08-29T12:00:00", "2026-08-29T10:00:00") is True
    assert _cue_is_newer("2026-08-29T09:00:00", "2026-08-29T10:00:00") is False
    assert _cue_is_newer("2026-08-29T10:00:00", "2026-08-29T10:00:00") is False
