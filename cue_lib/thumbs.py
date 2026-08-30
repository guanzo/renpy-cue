# cue_lib/thumbs.py -- the scene-thumbnails library: a per-game mapping of
# replay label -> thumbnail fetched at runtime from the mod's release assets,
# with a generic fallback to the marker filepaths captured at marker creation.
#
# The mapping is one merged JSON published with each release
# (cue_thumbs.json); CueThumbManager fetches it once per session on a
# background thread, caches it in the shared tree (data/), and replaces
# the cache only when the remote scraped date is newer.  Regenerating the
# mapping is a scraper job (.local/scripts/scrape_thumbnails.py), not a code
# change.

import os
import tempfile
import threading

import renpy
import renpy.config as _config

from cue_lib.download import CueDownloader
from cue_lib.paths import CuePaths
from cue_lib.sharing.importer_io import _cue_read_json_file
from cue_lib.util import _cue_replace_file

MYPY = False
if MYPY:
    from typing import Any, Dict, Optional  # pyright: ignore[reportUnusedImport]

    from cue_lib.marker_store import CueMarkerStore  # pyright: ignore[reportUnusedImport]

# Published with each release, deliberately versionless: releases/latest/download
# resolves to the latest published asset, never a draft (upload before
# publishing).  Downloaded through the shared CueDownloader, which owns URL
# policy, redirects, and the connect timeout.
CUE_THUMBS_URL = "https://github.com/guanzo/renpy-cue/releases/latest/download/cue_thumbs.json"

# The generic fallback shows a marker's image; videos need a frame extract
# and are skipped.  These are the image extensions the mod ships markers for.
CUE_THUMB_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


class CueThumbManager(object):
    """Resolves a replay label to a thumbnail to render in the Scenes list.

    Lookup order: the mapping entry for the label (cached from the release
    asset), then the first captured image filepath among the label's markers
    (generic fallback), then None -- the page renders a placeholder for that.
    The mapping is fetched once per session on a background thread; the
    fallback map is built lazily on the first miss.
    """

    def __init__(self, paths, marker_store, fetcher=None):
        # type: (CuePaths, CueMarkerStore, Any) -> None
        self._paths = paths
        self._marker_store = marker_store
        self._dl = CueDownloader(fetcher=fetcher)  # tests: inject a fetcher
        self.entries = {}  # type: Dict[str, str]  # replay_id -> thumb
        self._fallbacks = None  # type: Optional[Dict[str, str]]
        self.state = "idle"  # "idle" | "downloading" | "error"
        self.error = ""  # non-empty only when state == "error"
        self._fetched = False  # one download attempt per session
        self._disabled = False  # harness: keep the network out of tests
        self._thread = None  # type: Any

    def _cache_path(self):
        # type: () -> str
        return self._paths.thumbs_cache_path()

    def disable(self):
        # type: () -> None
        """Prevent any download (test harness).  load() still reads a cache."""
        self._disabled = True

    def load(self):
        # type: () -> None
        """(Re)load the cached mapping for the current game.  Safe to call
        repeatedly; no cache (or a game absent from it) falls back to markers."""
        self._fallbacks = None
        sid = getattr(_config, "save_directory", None)
        data = _cue_read_json_file(self._cache_path()) if sid else None
        if isinstance(data, dict):
            games = data.get("games")
            entry = games.get(sid) if isinstance(games, dict) else None
            entries = entry.get("entries") if isinstance(entry, dict) else None
            self.entries = entries if isinstance(entries, dict) else {}
        else:
            self.entries = {}

    def maybe_download(self):
        # type: () -> None
        """Start the background fetch of the merged mapping, once per session.
        No-op while disabled, already fetching, or already attempted this
        session.  Placeholders/marker fallback serve until it lands."""
        if self._disabled or self._fetched or self.state == "downloading":
            return
        self._fetched = True
        self.state = "downloading"
        self.error = ""
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True
        self._thread.start()

    def _run(self):
        # type: () -> None
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix="cue_thumbs_", suffix=".json")
            os.close(fd)
            try:
                cache_path = self._cache_path()
                headers = None
                if os.path.isfile(cache_path):
                    ims = _cue_format_http_date(os.path.getmtime(cache_path))
                    if ims:
                        headers = {"If-Modified-Since": ims}
                written = self._dl.download_to(CUE_THUMBS_URL, tmp_path, headers=headers)
                if written:
                    # 304 (unchanged) leaves the cache alone; a body still goes
                    # through the scraped-date guard before replacing it.
                    remote = _cue_read_json_file(tmp_path)
                    remote_scraped = remote.get("scraped") if isinstance(remote, dict) else None
                    local = _cue_read_json_file(cache_path)
                    local_scraped = local.get("scraped") if isinstance(local, dict) else None
                    if _cue_is_newer(remote_scraped, local_scraped):
                        self._write_cache(tmp_path)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            self.load()
            renpy.restart_interaction()
            self.state = "idle"
        except Exception as err:
            self.state = "error"
            self.error = str(err)

    def _write_cache(self, tmp_path):
        # type: (str) -> None
        d = os.path.dirname(self._cache_path())
        if not os.path.isdir(d):
            os.makedirs(d)
        _cue_replace_file(tmp_path, self._cache_path())

    def thumb_for(self, replay_id):
        # type: (str) -> Optional[str]
        """The thumbnail for a replay label, or None for a placeholder."""
        thumb = self.entries.get(replay_id)
        if thumb:
            return thumb
        if self._fallbacks is None:
            self._fallbacks = self._marker_filepaths()
        return self._fallbacks.get(replay_id)

    def _marker_filepaths(self):
        # type: () -> Dict[str, str]
        """First image marker filepath per replay label, derived from the
        in-memory marker store instead of re-reading every marker JSON from
        disk (the store already loaded them for the effective root)."""
        fallbacks = {}
        markers = self._marker_store._data
        for key in sorted(markers.keys()):
            entry = markers[key]
            if not isinstance(entry, dict):
                continue
            label = entry.get("replay")
            path = entry.get("filepath")
            if not label or not path or label in fallbacks:
                continue
            if path.lower().endswith(CUE_THUMB_IMAGE_EXTS):
                fallbacks[label] = path
        return fallbacks


def _cue_is_newer(remote, local):
    # type: (Optional[str], Optional[str]) -> bool
    """True when the remote has a strictly newer scraped date, or the cache
    is absent (local None).  ISO timestamps compare lexicographically."""
    if not remote:
        return False
    if not local:
        return True
    return remote > local


def _cue_format_http_date(timestamp):
    # type: (Optional[float]) -> Optional[str]
    """Unix timestamp -> HTTP date (GMT) for If-Modified-Since, or None when
    the formatter is unavailable.  The CDN compares it against the asset's
    Last-Modified, so the cache file's mtime doubles as the freshness token."""
    try:
        from email.utils import formatdate as _formatdate

        return _formatdate(timestamp, usegmt=True)
    except Exception:
        return None
