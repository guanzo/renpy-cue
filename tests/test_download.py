# -*- coding: utf-8 -*-
# Tests for cue_lib.download -- CueDownloader.download_to (policy, redirects,
# chunked stream), _cue_stream_body, and the shared transport (opener UA +
# TLS context).  The network hop and resolver are injected, never touched.

import os
import ssl

import pytest

import cue_lib.download as _dl


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


def _make_dl(fetcher=None, resolver=None):
    dl = _dl.CueDownloader(fetcher=fetcher)
    dl._resolve = resolver if resolver is not None else _public_resolver
    return dl


# ---------------------------------------------------------------------------
# URL policy
# ---------------------------------------------------------------------------


def test_is_private_ip_public():
    assert not _dl._cue_is_private_ip("8.8.8.8")
    assert not _dl._cue_is_private_ip("1.2.3.4")
    assert not _dl._cue_is_private_ip("172.32.0.1")
    assert not _dl._cue_is_private_ip("example.com")
    assert not _dl._cue_is_private_ip("2001:db8::1")


def test_is_private_ip_private():
    assert _dl._cue_is_private_ip("127.0.0.1")
    assert _dl._cue_is_private_ip("10.1.2.3")
    assert _dl._cue_is_private_ip("172.16.0.1")
    assert _dl._cue_is_private_ip("192.168.1.1")
    assert _dl._cue_is_private_ip("169.254.1.1")
    assert _dl._cue_is_private_ip("100.64.0.1")
    assert _dl._cue_is_private_ip("0.0.0.0")
    assert _dl._cue_is_private_ip("::1")
    assert _dl._cue_is_private_ip("fd00::1")
    assert _dl._cue_is_private_ip("fe80::1")


# ---------------------------------------------------------------------------
# _cue_stream_body
# ---------------------------------------------------------------------------


def test_stream_body_writes_and_reports_progress(tmp_path):
    resp = _FakeResponse(200, {"Content-Length": "5"}, b"hello")
    dest = str(tmp_path / "out.bin")
    progress = []
    total, written = _dl._cue_stream_body(resp, dest, progress_cb=lambda t, w: progress.append((t, w)))
    assert (total, written) == (5, 5)
    assert progress == [(5, 5)]
    with open(dest, "rb") as f:
        assert f.read() == b"hello"


def test_stream_body_missing_length_reports_bytes(tmp_path):
    resp = _FakeResponse(200, {}, b"data")
    dest = str(tmp_path / "out.bin")
    progress = []
    total, written = _dl._cue_stream_body(resp, dest, progress_cb=lambda t, w: progress.append((t, w)))
    assert total is None
    assert written == 4
    assert progress == [(None, 4)]


def test_stream_body_cancel_aborts(tmp_path):
    calls = []

    def _cancel():
        calls.append(1)
        raise _dl._CueDownloadCancel()

    resp = _FakeResponse(200, {}, b"data")
    with pytest.raises(_dl._CueDownloadCancel):
        _dl._cue_stream_body(resp, str(tmp_path / "out.bin"), cancel_cb=_cancel)
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# download_to
# ---------------------------------------------------------------------------


def test_download_to_writes_dest(tmp_path):
    fetcher = _fetcher({"https://h.com/pack.zip": _FakeResponse(200, {"Content-Length": "5"}, b"hello")})
    dl = _make_dl(fetcher)
    dest = str(tmp_path / "pack.zip")
    assert dl.download_to("https://h.com/pack.zip", dest) == 5
    with open(dest, "rb") as f:
        assert f.read() == b"hello"


def test_download_to_follows_redirect(tmp_path):
    redirect = _FakeResponse(302, {"Location": "https://h.com/real.zip"})
    final = _FakeResponse(200, {}, b"realdata")
    fetcher = _fetcher({"https://h.com/dl": redirect, "https://h.com/real.zip": final})
    dl = _make_dl(fetcher)
    dest = str(tmp_path / "real.zip")
    assert dl.download_to("https://h.com/dl", dest) == 8
    with open(dest, "rb") as f:
        assert f.read() == b"realdata"


def test_download_to_http_error_raises(tmp_path):
    fetcher = _fetcher({"https://h.com/missing.zip": _FakeResponse(404)})
    dl = _make_dl(fetcher)
    with pytest.raises(_dl._CueDownloadError) as e:
        dl.download_to("https://h.com/missing.zip", str(tmp_path / "x.zip"))
    assert "404" in str(e.value)


def test_download_to_transport_error_raises(tmp_path):
    fetcher = _fetcher({"https://h.com/x.zip": _dl._CueDownloadError("Could not reach URL: down.")})
    dl = _make_dl(fetcher)
    with pytest.raises(_dl._CueDownloadError) as e:
        dl.download_to("https://h.com/x.zip", str(tmp_path / "x.zip"))
    assert "Could not reach URL" in str(e.value)


def test_download_to_blocks_private_redirect(tmp_path):
    redirect = _FakeResponse(302, {"Location": "http://127.0.0.1/evil.zip"})
    fetcher = _fetcher({"https://h.com/dl": redirect})
    dl = _make_dl(fetcher)
    with pytest.raises(_dl._CueDownloadError) as e:
        dl.download_to("https://h.com/dl", str(tmp_path / "x.zip"))
    assert "reachable" in str(e.value)


def test_download_to_blocks_bad_scheme(tmp_path):
    dl = _make_dl()
    with pytest.raises(_dl._CueDownloadError) as e:
        dl.download_to("ftp://h.com/x.zip", str(tmp_path / "x.zip"))
    assert "http" in str(e.value)


# ---------------------------------------------------------------------------
# transport (user agent + TLS context)
# ---------------------------------------------------------------------------


def test_opener_sends_browser_user_agent():
    # CDNs (Discord etc.) 403 urllib's default "Python-urllib" UA, so the
    # shared opener must attach a regular browser UA to every request.
    assert _dl.CUE_DOWNLOAD_USER_AGENT.startswith("Mozilla/5.0")
    assert ("User-Agent", _dl.CUE_DOWNLOAD_USER_AGENT) in _dl._CUE_OPENER.addheaders


def test_https_context_verified_with_certifi(monkeypatch):
    try:
        import certifi as _certifi
    except ImportError:
        pytest.skip("certifi not installed in this test env")

    monkeypatch.setattr(_dl, "_cue_find_cacert", lambda: _certifi.where())
    handler = _dl._cue_https_context()
    assert handler._context.verify_mode == ssl.CERT_REQUIRED


def test_https_context_unverified_without_certifi(monkeypatch):
    # Ren'Py 8.x's bundled python has no default CA paths, and 7.x's urllib2
    # never verified certs -- the fallback must keep downloads working.
    monkeypatch.setattr(_dl, "_cue_find_cacert", lambda: None)
    handler = _dl._cue_https_context()
    assert handler._context.verify_mode == ssl.CERT_NONE
