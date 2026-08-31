# -*- coding: utf-8 -*-
# cue_lib/audio/wav_playable.py -- make WAVs Ren'Py's SDL_mixer backend can play.
#
# SDL_mixer decodes 8-bit and 16-bit PCM WAV natively.  Wider formats (24/32-bit
# integer, 32-bit float) are accepted by play() without error but produce no
# sound, which reads as a silent file (the PLAY-SFX log still prints).  Everything
# we can is rebuilt as 16-bit PCM; the rest is surfaced as unplayable rather than
# left as a silent mystery.
#
# The 16-bit copy is cached in the OS temp dir (tempfile.gettempdir()), outside
# the shared data tree on purpose: SFX/music discovery, backup, and import all
# scan the data tree, so an in-tree cache would leak into every one of them.
#
# Cost model.  ensure_playable() is the play path: after a file has been seen
# once it is a memoized dict hit with no filesystem call, so a native file (the
# common case) costs nothing per play.  Classification is lazy -- a file is
# probed only on its first play, not scanned up front.  Those decisions persist
# in index.json next to the nodes, so a fresh session skips the bulk of a
# library as a fast dict hit.  A converted node cleaned out of temp is rebuilt by
# ensure_playable() -- a single stat for files that need it.

import hashlib
import json
import os
import struct
import tempfile

import renpy.python as _renpy_python

from cue_lib.util import _cue_replace_file, _cue_log, _to_str

MYPY = False
if MYPY:
    from typing import Optional

# Subdir under the OS temp root that holds every converted copy.
CUE_WAV_PLAYABLE_SUBDIR = "renpy_cue"

# Playback classification: native (plays as-is), convert (rebuilt as 16-bit PCM),
# or unplayable (reported with a reason -- compressed codec, corrupt, misnamed).
CUE_WAV_PLAYABLE_NATIVE = "native"  # 8/16-bit PCM int -> passthrough
CUE_WAV_PLAYABLE_CONVERT = "convert"  # wide int or float -> rebuilt as 16-bit
CUE_WAV_PLAYABLE_UNPLAYABLE = "unplayable"  # we can't make it play -> surfaced

# Filename of the persisted classification index, kept in the cache dir next to
# the converted nodes.  A fresh session loads it so warm() skips files it already
# handled instead of re-probing the whole library.
CUE_WAV_PLAYABLE_INDEX = "index.json"


def _byte_str(s):
    # type: (str) -> bytes
    """Coerce ``s`` to the byte type hashlib accepts on this Python.

    Py3 needs ``bytes``; Py2 already has ``str`` (== ``bytes``).
    """
    if isinstance(s, bytes):
        return s
    return s.encode("utf-8")


def _write_wav16(path, channels, rate, data):
    # type: (str, int, int, bytes) -> None
    """Write ``data`` (16-bit PCM) as a standard PCM WAV at ``path``.

    Pure Python.  Ren'Py's bundled interpreter ships no C extensions, and the
    stdlib ``wave`` module line-imports the C-only ``audioop``, so ``wave``
    cannot be loaded inside Ren'Py.  Writing the header by hand is symmetric
    with ``_read_wav``."""
    data_size = len(data)
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * 2, channels * 2, 16)
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + data_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", data_size)
    )
    with open(path, "wb") as f:
        f.write(header)
        f.write(data)


class CueWavPlayable(_renpy_python.NoRollback):
    """Makes WAVs playable in Ren'Py, converting undecodable widths to 16-bit.

    ``ensure_playable(path)`` is the play-time entry point; ``refresh(path)`` is
    the scan-time one that rebuilds when the source changed; ``unplayable()``
    reports any file that could not be made playable, with a short reason.
    Best-effort -- a failure degrades to the original path so playback is never
    blocked by the converter."""

    def __init__(self, temp_root=None):
        # type: (Optional[str]) -> None
        self._cache_root = self._make_cache_root(temp_root)
        self._decision = {}  # path -> CUE_WAV_PLAYABLE_* state; read on play (no I/O)
        self._stamp = {}  # path -> (size, mtime) recorded at last probe/refresh
        self._reason = {}  # path -> short reason, only for unplayable files
        self._load_index()

    def _make_cache_root(self, temp_root):
        # type: (Optional[str]) -> str
        """The cache directory.  ``temp_root`` is injected for tests; the default
        is the OS temp dir plus a dedicated subdir.  If it can't be created we
        fall back to a path that won't exist, so ensure_playable just returns the
        original (a silent play, but no crash)."""
        base = temp_root if temp_root is not None else tempfile.gettempdir()
        path = os.path.join(base, CUE_WAV_PLAYABLE_SUBDIR).replace("\\", "/")
        try:
            if not os.path.isdir(path):
                os.makedirs(path)
        except Exception:
            _cue_log("WAV-PLAYABLE: cache dir unavailable at {}".format(path))
        return path

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def ensure_playable(self, path):
        # type: (str) -> str
        """Return a path Ren'Py can play for ``path``.

        Memoized by path: a file is classified once (first sight), then the
        decision is a dict hit with no filesystem call, so common native playback
        is free.  A converted node that was cleaned out of temp is rebuilt here --
        the one stat per play that files needing conversion pay.  Unplayable files
        pass through so Ren'Py can still try; they were reported at classification
        time."""
        if path not in self._decision:
            self._probe(path)
        if self._decision[path] == CUE_WAV_PLAYABLE_CONVERT:
            return self._ensure_node(path)
        return path

    def refresh(self, path):
        # type: (str) -> str
        """Probe ``path`` and rebuild its 16-bit copy if the source changed.

        Lazy: called on demand, not on a scan.  An unchanged file keeps its
        decision and node; a changed source is re-probed and its node rebuilt,
        so a swapped-in file is never served as a stale conversion."""
        st = self._stat(path)
        if st is None:
            self._decision.pop(path, None)
            self._stamp.pop(path, None)
            self._reason.pop(path, None)
            return path
        stamp = (st.st_size, st.st_mtime)
        if path in self._stamp and self._stamp[path] == stamp:
            # unchanged -- keep the decision, just top up a node that vanished
            if self._decision.get(path) == CUE_WAV_PLAYABLE_CONVERT:
                return self._ensure_node(path)
            return path
        state, reason = self._classify(path)
        self._stamp[path] = stamp
        self._record(path, state, reason)
        if state == CUE_WAV_PLAYABLE_CONVERT:
            # source changed -- rebuild unconditionally, not the existence-checked
            # path used for play-time top-ups, so the node reflects the new source
            node = self._cache_node(path)
            if not self._convert(path, node):
                self._record(path, CUE_WAV_PLAYABLE_UNPLAYABLE, "failed to convert")
                return path
            return node
        return path

    def unplayable(self):
        # type: () -> dict
        """{path: reason} for every WAV that can't be made playable, for UI."""
        out = {}
        for p, state in self._decision.items():
            if state == CUE_WAV_PLAYABLE_UNPLAYABLE:
                out[p] = self._reason[p]
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _probe(self, path):
        # type: (str) -> None
        """One-time lazy sighting on the play path: classify the header and record
        the decision.  Ensures a file first played before any scan still works."""
        st = self._stat(path)
        state, reason = self._classify(path)
        self._stamp[path] = (st.st_size, st.st_mtime) if st else None
        self._record(path, state, reason)
        self._save_index()  # first sighting at play time is persisted too

    def _ensure_node(self, path):
        # type: (str) -> str
        """Return the converted node for a CONVERT file, rebuilding if the temp
        copy vanished.  If the rebuild fails the file is re-recorded as unplayable
        and the original path is returned."""
        node = self._cache_node(path)
        if os.path.exists(node) or self._convert(path, node):
            return node
        self._record(path, CUE_WAV_PLAYABLE_UNPLAYABLE, "failed to convert")
        return path

    def _record(self, path, state, reason):
        # type: (str, str, str) -> None
        """Store a path's classification and, when unplayable, its reason.

        A path transition *into* UNPLAYABLE is logged once; a guard prevents a
        repeated play-path retry from spamming the log.  Leaving UNPLAYABLE clears
        the reason."""
        was = self._decision.get(path)
        self._decision[path] = state
        if state == CUE_WAV_PLAYABLE_UNPLAYABLE:
            self._reason[path] = reason
            if was != CUE_WAV_PLAYABLE_UNPLAYABLE:
                _cue_log("WAV-PLAYABLE: {} unplayable: {}".format(path, reason))
        else:
            self._reason.pop(path, None)

    def _index_path(self):
        # type: () -> str
        return os.path.join(self._cache_root, CUE_WAV_PLAYABLE_INDEX).replace("\\", "/")

    def _load_index(self):
        # type: () -> None
        """Load decisions/reasons persisted by a prior session.  A missing or
        corrupt index leaves the maps empty (a full reprobe today) -- it never
        crashes startup."""
        path = self._index_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            decision = data.get("decision")
            reasons = data.get("reasons")
            if isinstance(decision, dict):
                # _to_str keeps keys as str on py2 (json yields unicode there)
                self._decision = {_to_str(k): v for k, v in decision.items()}
            if isinstance(reasons, dict):
                self._reason = {_to_str(k): v for k, v in reasons.items()}
        except Exception:
            _cue_log("WAV-PLAYABLE: index load failed at {}".format(path))

    def _save_index(self):
        # type: () -> None
        """Persist decisions/reasons atomically (temp file + replace) so a
        concurrent reader never sees a partial file.  Best-effort: a write
        failure logs and is ignored -- classification still works this session."""
        path = self._index_path()
        tmp = path + ".tmp"
        data = {"version": 1, "decision": self._decision, "reasons": self._reason}
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, sort_keys=True)
            _cue_replace_file(tmp, path)
        except Exception as exc:
            _cue_log("WAV-PLAYABLE: index save failed at {}: {}".format(path, exc))

    def _stat(self, path):
        # type: (str) -> Optional[os.stat_result]
        """os.stat for ``path``, or None on failure (unreadable/gone)."""
        try:
            return os.stat(path)
        except Exception:
            return None

    def _classify(self, path):
        # type: (str) -> tuple
        """Classify a WAV by codec and width -> (state, reason).

        NATIVE for 8/16-bit int; CONVERT for any PCM int wider than 16-bit (the
        top 2 bytes/sample survive as a 16-bit value) and 32-bit float; UNPLAYABLE
        for compressed codecs, corrupt or misnamed WAVs, with a short reason.
        Reads the real format tag because wave gives the same sampwidth for int and
        float and refuses to open float at all.  Non-WAV containers (ogg/mp3/opus)
        are left alone -- the codec decodes those, so they are not our concern."""
        if self._wav_magic(path) is False:
            return CUE_WAV_PLAYABLE_NATIVE, ""
        meta = self._read_wav(path)
        if meta is None:
            return CUE_WAV_PLAYABLE_UNPLAYABLE, "not a valid WAV"
        tag, sw = meta["tag"], meta["sw"]
        if tag == 1:
            if sw in (1, 2):
                return CUE_WAV_PLAYABLE_NATIVE, ""
            if sw >= 3:
                return CUE_WAV_PLAYABLE_CONVERT, ""
            return CUE_WAV_PLAYABLE_UNPLAYABLE, "invalid sample width {}".format(sw)
        if tag == 3 and sw == 4:
            return CUE_WAV_PLAYABLE_CONVERT, ""
        return CUE_WAV_PLAYABLE_UNPLAYABLE, self._format_reason(tag, sw)

    def _format_reason(self, tag, sw):
        # type: (int, int) -> str
        """Short reason for an unsupported format, shown where unplayable files
        are surfaced.  Fine to be loose -- surfaced as a hint, not an error."""
        if tag == 2:
            return "ADPCM"
        if tag == 6:
            return "A-law"
        if tag == 7:
            return "mu-law"
        return "unsupported format tag {}".format(tag)

    def _wav_magic(self, path):
        # type: (str) -> Optional[bool]
        """True if path is a WAV container (RIFF....WAVE), False if it is not
        (ogg/mp3/opus or a non-audio file), None if it can't be opened.  Lets
        classification ignore non-WAV files instead of flagging them."""
        try:
            f = open(path, "rb")
            try:
                head = f.read(12)
            finally:
                f.close()
        except Exception:
            return None
        if len(head) < 12:
            return False
        return head[0:4] == b"RIFF" and head[8:12] == b"WAVE"

    def _read_wav(self, path):
        # type: (str) -> Optional[dict]
        """Parse a WAV header down to the data chunk.

        Returns tag (codec, extensible resolved), sample-width bytes, channels,
        rate, and the data chunk's offset/size -- or None when the file isn't a
        parseable WAV.  Reads chunk headers only (no data), so classification is
        cheap.  Needed because the stdlib ``wave`` module hides the format tag and
        outright refuses non-PCM (float) files."""
        try:
            f = open(path, "rb")
        except Exception:
            return None
        try:
            if f.read(4) != b"RIFF":
                return None
            f.seek(4, 1)
            if f.read(4) != b"WAVE":
                return None
            meta = None
            while True:
                head = f.read(8)
                if len(head) < 8:
                    return None
                ckid = head[0:4]
                size = struct.unpack("<I", head[4:8])[0]
                if size > 0x7FFFFFFF:
                    return None
                if ckid == b"fmt ":
                    body = f.read(size)
                    if len(body) < 16:
                        return None
                    tag = struct.unpack("<H", body[0:2])[0]
                    if tag == 0xFFFE:
                        # WAVE_FORMAT_EXTENSIBLE: real codec is the sub-format GUID
                        tag = struct.unpack("<I", body[24:28])[0] if len(body) >= 28 else 0
                    meta = {
                        "tag": tag,
                        "channels": struct.unpack("<H", body[2:4])[0],
                        "rate": struct.unpack("<I", body[4:8])[0],
                        "sw": struct.unpack("<H", body[14:16])[0] // 8,
                        "offset": None,
                        "size": 0,
                    }
                elif ckid == b"data":
                    if meta is None:
                        return None
                    meta["offset"] = f.tell()
                    meta["size"] = size
                    return meta
                else:
                    f.seek(size, 1)
                if size & 1:
                    f.seek(1, 1)
        except Exception:
            return None
        finally:
            f.close()
        return None

    def _cache_node(self, path):
        # type: (str) -> str
        """Cached-copy path for ``path``.  Keyed by abs path so two sources with
        the same name (across games) never collide; a replaced source reuses the
        node but refresh() rebuilds it, so no stale conversion is served after a
        scan."""
        digest = hashlib.md5(_byte_str(os.path.abspath(path))).hexdigest()
        return os.path.join(self._cache_root, digest + ".wav").replace("\\", "/")

    def _convert(self, src, dst):
        # type: (str, str) -> bool
        """Rebuild the WAV at ``dst`` as 16-bit PCM.  Called only for files
        classified CONVERT (PCM int wider than 16-bit, or 32-bit float).

        Writes to a temp file then atomically replaces ``dst`` so a concurrent
        reader never sees a partial file.  True on success; False (with a log)
        when the source can't be read or written, so the caller records the file
        as unplayable and falls back to the original path."""
        meta = self._read_wav(src)
        if meta is None:
            _cue_log("WAV-PLAYABLE: cannot parse {}".format(src))
            return False
        try:
            f = open(src, "rb")
            try:
                f.seek(meta["offset"])
                raw = bytearray(f.read(meta["size"]))
            finally:
                f.close()
        except Exception as exc:
            _cue_log("WAV-PLAYABLE: read {} failed: {}".format(src, exc))
            return False
        tag, sw = meta["tag"], meta["sw"]
        if tag == 1:
            # integer PCM: the top 2 bytes of each sw-byte sample are the 16-bit value
            if sw < 3:
                return True  # already 16-bit or smaller; nothing to convert
            conv = self._int_to_16(raw, sw)
        elif tag == 3:
            try:
                conv = self._float_to_16(raw)
            except Exception as exc:
                _cue_log("WAV-PLAYABLE: float decode {} failed: {}".format(src, exc))
                return False
        else:
            _cue_log("WAV-PLAYABLE: {} unsupported format tag {}".format(src, tag))
            return False
        tmp = dst + ".tmp"
        try:
            _write_wav16(tmp, meta["channels"], meta["rate"], bytes(conv))
            _cue_replace_file(tmp, dst)
        except Exception as exc:
            _cue_log("WAV-PLAYABLE: write {} failed: {}".format(dst, exc))
            return False
        return True

    def _int_to_16(self, raw, sw):
        # type: (bytearray, int) -> bytearray
        """Drop the low (sw-2) bytes of each sw-byte little-endian sample, keeping
        the top 16 bits (and sign).  Uniform across 24/32-bit int."""
        step = sw
        n = len(raw) // step
        out = bytearray(n * 2)
        for j in range(n):
            base = j * step
            out[j * 2] = raw[base + step - 2]
            out[j * 2 + 1] = raw[base + step - 1]
        return out

    def _float_to_16(self, raw):
        # type: (bytearray) -> bytearray
        """Decode 32-bit float samples, clamp to [-1, 1] and scale to int16."""
        if len(raw) % 4:
            raise ValueError("float32 data not 4-byte aligned")
        n = len(raw) // 4
        samples = struct.unpack("<{}f".format(n), raw)
        out = bytearray(n * 2)
        for i in range(n):
            f = samples[i]
            if f < -1.0:
                f = -1.0
            elif f > 1.0:
                f = 1.0
            v = int(f * 32767.0)
            if v < -32768:
                v = -32768
            elif v > 32767:
                v = 32767
            out[i * 2] = v & 0xFF
            out[i * 2 + 1] = (v >> 8) & 0xFF
        return out
