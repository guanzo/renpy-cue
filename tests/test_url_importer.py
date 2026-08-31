# -*- coding: utf-8 -*-
# Tests for cue_lib.sharing.url_importer -- CueUrlImporter: URL policy (scheme,
# credentials, private hosts), the download worker (chunked read, redirects,
# cancel), naming/collision, and the size/duration formatters.

import os

import pytest

import cue_lib.download as _download
import cue_lib.sharing.url_importer as _url
from cue_lib.sharing.url_importer import CueUrlImporter
from cue_lib.util import _cue_format_duration, _cue_format_size


# ---------------------------------------------------------------------------
# pure formatters
# ---------------------------------------------------------------------------


def test_format_size_units():
    assert _cue_format_size(0) == "0 B"
    assert _cue_format_size(1023) == "1023 B"
    assert _cue_format_size(1024) == "1.0 KB"
    assert _cue_format_size(1536) == "1.5 KB"
    assert _cue_format_size(1024 * 1024) == "1.0 MB"
    assert _cue_format_size(int(29.5 * 1024 * 1024)) == "29.5 MB"
    assert _cue_format_size(1024**3) == "1.0 GB"
    assert _cue_format_size(None) == "0 B"


def test_format_duration():
    assert _cue_format_duration(0) == "00:00"
    assert _cue_format_duration(37) == "00:37"
    assert _cue_format_duration(97) == "01:37"
    assert _cue_format_duration(3600) == "01:00:00"
    assert _cue_format_duration(-5) == "00:00"
    assert _cue_format_duration(None) == "00:00"


# ---------------------------------------------------------------------------
# manager fixtures
# ---------------------------------------------------------------------------


class _FakeImporter(object):
    def __init__(self, imports_dir):
        self._paths = type("_Paths", (object,), {"imports_dir": imports_dir})()
        self.scan_calls = 0

    def scan(self):
        self.scan_calls += 1


class _FakeThread(object):
    """Records the worker body without running it -- tests drive it
    synchronously via the url_threads _join helper."""

    def __init__(self, target=None, args=()):
        self.target = target
        self.args = args
        self.daemon = False
        self.started = False
        self.joined = False

    def start(self):
        self.started = True


@pytest.fixture
def url_threads(monkeypatch):
    """Patch Thread with a recording factory; _join() runs every recorded
    worker body inline once, synchronously."""
    created = []

    def _factory(**kw):
        t = _FakeThread(**kw)
        created.append(t)
        return t

    monkeypatch.setattr(_url.threading, "Thread", _factory)

    def _join():
        for t in created:
            if t.started and not t.joined:
                t.joined = True
                t.target(*t.args)

    return created, _join


class _FakeResponse(object):
    def __init__(self, code=200, headers=None, body=b"", on_read=None):
        self.code = code
        self._headers = headers or {}
        self._body = body
        self._pos = 0
        self._on_read = on_read
        self.closed = False

    def headers_get(self, name):
        return self._headers.get(name)

    def read(self, size):
        if self._on_read is not None:
            self._on_read(self)
        chunk = self._body[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


def _public_resolver(host):
    # Every host resolves to a public address unless a test overrides.
    return [(0, 0, 0, "", ("1.2.3.4", 0))]


def _fetcher(responses, default_code=404):
    """responses: url -> _FakeResponse (returned) or Exception (raised)."""

    def fetcher(url, timeout):
        if url in responses:
            item = responses[url]
            if isinstance(item, Exception):
                raise item
            return item
        return _FakeResponse(default_code)

    return fetcher


def _make_mgr(tmp_path, resolver=None):
    imports_dir = os.path.join(str(tmp_path), "imports")
    importer = _FakeImporter(imports_dir)
    mgr = CueUrlImporter(importer)
    mgr._dl._resolve = resolver if resolver is not None else _public_resolver
    return mgr, importer


def _run(url_threads, mgr, url):
    mgr.url = url
    mgr.import_url()
    _created, _join = url_threads
    _join()


# ---------------------------------------------------------------------------
# input validation (main thread, before any network)
# ---------------------------------------------------------------------------


def test_import_url_empty_url(tmp_path, url_threads):
    mgr, _imp = _make_mgr(tmp_path)
    _run(url_threads, mgr, "  ")
    assert mgr.download_error == "Enter a URL first."
    assert not mgr.is_downloading


def test_rejects_bad_scheme(tmp_path, url_threads):
    mgr, _imp = _make_mgr(tmp_path)
    _run(url_threads, mgr, "ftp://host.com/x.zip")
    assert "http" in mgr.download_error
    assert not mgr.is_downloading


def test_rejects_credentials(tmp_path, url_threads):
    mgr, _imp = _make_mgr(tmp_path)
    _run(url_threads, mgr, "https://user:pass@host.com/x.zip")
    assert "credentials" in mgr.download_error
    assert not mgr.is_downloading


def test_rejects_private_literal_host(tmp_path, url_threads):
    mgr, _imp = _make_mgr(tmp_path)
    _run(url_threads, mgr, "https://127.0.0.1/x.zip")
    assert "reachable" in mgr.download_error
    assert not mgr.is_downloading


def test_rejects_private_resolved_host(tmp_path, url_threads):
    def _resolver(host):
        return [(0, 0, 0, "", ("192.168.1.5", 0))]

    mgr, _imp = _make_mgr(tmp_path, resolver=_resolver)
    _run(url_threads, mgr, "https://internal.example/x.zip")
    assert "reachable" in mgr.download_error
    assert not mgr.is_downloading


def test_check_url_syntax():
    mgr, _imp = _make_mgr(".")
    assert mgr._dl.check_url("https://h.com/x.zip") is None
    assert "http" in mgr._dl.check_url("ftp://h.com/x.zip")
    assert "credentials" in mgr._dl.check_url("https://u:p@h.com/x.zip")
    assert "host" in mgr._dl.check_url("https:///x.zip")


# ---------------------------------------------------------------------------
# download worker
# ---------------------------------------------------------------------------


def test_download_success(tmp_path, url_threads):
    imports_dir = os.path.join(str(tmp_path), "imports")
    importer = _FakeImporter(imports_dir)
    resp = _FakeResponse(200, {"Content-Length": "5"}, b"hello")
    fetcher = _fetcher({"https://h.com/pack.zip": resp})
    mgr = CueUrlImporter(importer, fetcher=fetcher)
    mgr._dl._resolve = _public_resolver
    _run(url_threads, mgr, "https://h.com/pack.zip")

    assert not mgr.is_downloading
    assert mgr.download_status == "Downloaded pack.zip. (5 B)"
    assert mgr.download_total == 5
    assert mgr.download_done == 5
    assert mgr.url == ""
    assert importer.scan_calls == 1
    with open(os.path.join(imports_dir, "pack.zip"), "rb") as f:
        assert f.read() == b"hello"


def test_download_appends_zip_extension(tmp_path, url_threads):
    imports_dir = os.path.join(str(tmp_path), "imports")
    importer = _FakeImporter(imports_dir)
    fetcher = _fetcher({"https://h.com/download": _FakeResponse(200, {}, b"zipdata")})
    mgr = CueUrlImporter(importer, fetcher=fetcher)
    mgr._dl._resolve = _public_resolver
    _run(url_threads, mgr, "https://h.com/download")
    assert os.path.isfile(os.path.join(imports_dir, "download.zip"))


def test_collision_dedupes(tmp_path, url_threads):
    imports_dir = os.path.join(str(tmp_path), "imports")
    os.makedirs(imports_dir)
    open(os.path.join(imports_dir, "pack.zip"), "w").close()
    importer = _FakeImporter(imports_dir)
    fetcher = _fetcher({"https://h.com/pack.zip": _FakeResponse(200, {}, b"x")})
    mgr = CueUrlImporter(importer, fetcher=fetcher)
    mgr._dl._resolve = _public_resolver
    _run(url_threads, mgr, "https://h.com/pack.zip")
    assert os.path.isfile(os.path.join(imports_dir, "pack (2).zip"))
    assert mgr.download_status.startswith("Downloaded pack (2).zip")


def test_download_404(tmp_path, url_threads):
    imports_dir = os.path.join(str(tmp_path), "imports")
    importer = _FakeImporter(imports_dir)
    fetcher = _fetcher({"https://h.com/missing.zip": _FakeResponse(404)})
    mgr = CueUrlImporter(importer, fetcher=fetcher)
    mgr._dl._resolve = _public_resolver
    _run(url_threads, mgr, "https://h.com/missing.zip")
    assert "404" in mgr.download_error
    assert not mgr.is_downloading
    assert importer.scan_calls == 0


def test_connect_failure(tmp_path, url_threads):
    imports_dir = os.path.join(str(tmp_path), "imports")
    importer = _FakeImporter(imports_dir)
    fetcher = _fetcher({"https://h.com/x.zip": _download._CueDownloadError("Could not reach URL: down.")})
    mgr = CueUrlImporter(importer, fetcher=fetcher)
    mgr._dl._resolve = _public_resolver
    _run(url_threads, mgr, "https://h.com/x.zip")
    assert "Could not reach URL" in mgr.download_error
    assert not mgr.is_downloading


def test_follows_redirect(tmp_path, url_threads):
    imports_dir = os.path.join(str(tmp_path), "imports")
    importer = _FakeImporter(imports_dir)
    redirect = _FakeResponse(302, {"Location": "https://h.com/real.zip"})
    final = _FakeResponse(200, {}, b"realdata")
    fetcher = _fetcher({"https://h.com/dl": redirect, "https://h.com/real.zip": final})
    mgr = CueUrlImporter(importer, fetcher=fetcher)
    mgr._dl._resolve = _public_resolver
    _run(url_threads, mgr, "https://h.com/dl")
    assert os.path.isfile(os.path.join(imports_dir, "real.zip"))
    assert mgr.download_status.startswith("Downloaded real.zip")


def test_redirect_to_private_blocked(tmp_path, url_threads):
    imports_dir = os.path.join(str(tmp_path), "imports")
    importer = _FakeImporter(imports_dir)
    redirect = _FakeResponse(302, {"Location": "http://127.0.0.1/evil.zip"})
    fetcher = _fetcher({"https://h.com/dl": redirect})
    mgr = CueUrlImporter(importer, fetcher=fetcher)
    mgr._dl._resolve = _public_resolver
    _run(url_threads, mgr, "https://h.com/dl")
    assert "reachable" in mgr.download_error
    assert not mgr.is_downloading


def test_redirect_without_location(tmp_path, url_threads):
    imports_dir = os.path.join(str(tmp_path), "imports")
    importer = _FakeImporter(imports_dir)
    fetcher = _fetcher({"https://h.com/dl": _FakeResponse(302, {})})
    mgr = CueUrlImporter(importer, fetcher=fetcher)
    mgr._dl._resolve = _public_resolver
    _run(url_threads, mgr, "https://h.com/dl")
    assert "Location" in mgr.download_error
    assert not mgr.is_downloading


def test_cancel_deletes_partial(tmp_path, url_threads):
    imports_dir = os.path.join(str(tmp_path), "imports")
    importer = _FakeImporter(imports_dir)
    body = b"x" * (1024 * 1024)
    state = {"reads": 0}

    def _on_read(resp):
        state["reads"] += 1
        if state["reads"] == 1:
            mgr.cancel_requested = True

    resp = _FakeResponse(200, {"Content-Length": str(len(body))}, body=body, on_read=_on_read)
    fetcher = _fetcher({"https://h.com/big.zip": resp})
    mgr = CueUrlImporter(importer, fetcher=fetcher)
    mgr._dl._resolve = _public_resolver
    _run(url_threads, mgr, "https://h.com/big.zip")

    assert mgr.download_status == "Cancelled."
    assert not mgr.is_downloading
    assert not os.path.exists(os.path.join(imports_dir, "big.zip"))
    assert not os.path.exists(os.path.join(imports_dir, "big.zip.tmp"))
    assert importer.scan_calls == 0


def test_unknown_total(tmp_path, url_threads):
    imports_dir = os.path.join(str(tmp_path), "imports")
    importer = _FakeImporter(imports_dir)
    fetcher = _fetcher({"https://h.com/x.zip": _FakeResponse(200, {}, b"data")})
    mgr = CueUrlImporter(importer, fetcher=fetcher)
    mgr._dl._resolve = _public_resolver
    _run(url_threads, mgr, "https://h.com/x.zip")
    assert mgr.download_total is None
    assert mgr.download_done == 4
    assert mgr.download_status.startswith("Downloaded x.zip")


# ---------------------------------------------------------------------------
# misc state helpers
# ---------------------------------------------------------------------------


def test_import_url_noop_while_downloading(tmp_path, url_threads):
    mgr, _imp = _make_mgr(tmp_path)
    mgr.is_downloading = True
    mgr.url = "https://h.com/x.zip"
    mgr.import_url()
    created, _join = url_threads
    assert created == []
    assert not mgr.download_error


def test_cancel_noop_when_idle(tmp_path):
    mgr, _imp = _make_mgr(tmp_path)
    mgr.cancel_requested = False
    mgr.cancel()
    assert not mgr.cancel_requested


def test_download_duration_zero_when_idle(tmp_path):
    mgr, _imp = _make_mgr(tmp_path)
    assert mgr.download_duration() == 0.0


def test_name_from_url():
    mgr, _imp = _make_mgr(".")
    assert mgr._name_from_url("https://h.com/dir/pack.zip") == "pack.zip"
    assert mgr._name_from_url("https://h.com/download") == "download.zip"
    assert mgr._name_from_url("https://h.com/") == "cue_import.zip"
    assert mgr._name_from_url("https://h.com/my%20pack.zip") == "my pack.zip"
