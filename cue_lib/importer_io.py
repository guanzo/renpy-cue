# -*- coding: utf-8 -*-
# cue_lib/importer_io.py -- import/export .zip format.
#
# An import is a .zip mirroring the shared-root layout plus a manifest.json
# recording the packed files.  This module owns the pure logic (category
# mapping, game_id matching, manifest build/validate) and the filesystem ops
# (zip build/extract, merge copy).  It imports only stdlib + cue_lib helpers
# -- never runtime or state -- so managers can use it without import cycles.

import hashlib as _hashlib
import json as _json
import os
import re as _re
import shutil as _shutil
import tempfile as _tempfile
import zipfile as _zipfile

from cue_lib.backup import CUE_BAK_DIR, _safe_extract_path
from cue_lib.constants import (
    CUE_HASH_TRUNC_LEN,
    CUE_MUSIC_GAME_TAG,
    CUE_MUSIC_PREFIX,
    CUE_MUSIC_USER_TAG,
    CUE_IMPORT_CATEGORY_ORDER,
    CUE_IMPORT_FORMAT_VERSION,
    CUE_IMPORT_MANIFEST_NAME,
    CUE_VID_KEY_PREFIX,
    CueImportCategory,
    CueImportMatch,
)
from cue_lib.paths import CuePaths
from cue_lib.util import _cue_log, _cue_replace_file, _to_str

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]

# --------------------------------------------------------------------------
# Category mapping -- path prefix -> CueImportCategory.  Single source of
# the mapping; used by export enumeration, the merge filter, and import
# validation.  More-specific prefixes first (they don't overlap today, but
# order keeps it robust if a prefix becomes a prefix of another).
# --------------------------------------------------------------------------

_CUE_CATEGORY_PREFIX = [
    (CueImportCategory.PRESETS, "data/presets/"),
    (CueImportCategory.MARKERS, "data/markers/"),
    (CueImportCategory.SFX, "audio/"),
    (CueImportCategory.MUSIC, "music/"),
    (CueImportCategory.SPEED_VARIANTS, "video/"),
]

# Manifest key holding the import format version.  Single source for the
# build/validate pair in this module.
_CUE_MANIFEST_FORMAT_KEY = "format_version"

# User-supplied manifest fields are silently truncated to these lengths on
# export -- a long title shouldn't balloon the manifest or the row UI.
_CUE_MAX_NAME_LEN = 60
_CUE_MAX_AUTHOR_LEN = 40
_CUE_MAX_DESC_LEN = 300


def _cue_import_category(path):
    # type: (str) -> int
    """Map a zip-relative path to its CueImportCategory (UNKNOWN if it
    falls outside the 5 exportable categories)."""
    for cat, prefix in _CUE_CATEGORY_PREFIX:
        if path.startswith(prefix):
            return cat
    return CueImportCategory.UNKNOWN


# --------------------------------------------------------------------------
# game_id matching -- three levels, always surfaced as a guess when heuristic
# --------------------------------------------------------------------------

def _cue_digit_strip_normalize(game_id):
    # type: (str) -> str
    """Lower + drop separators + drop trailing digits.  Catches no-hyphen
    variance like 'MyGame123' vs 'MyGame456' (deliberately disjoint from the
    hyphen-prefix check; no per-token digit strip, which would blur tokens)."""
    s = _to_str(game_id or "").lower()
    for sep in ("-", "_", ".", " "):
        s = s.replace(sep, "")
    return s.rstrip("0123456789")


def _cue_import_match(game_id, manifest_game_id):
    # type: (str, str) -> Tuple[int, str]
    """Match an import's manifest game_id against the current game.

    Returns (CueImportMatch.*, reason).  Only exact/raw/token matches are
    AUTO; every heuristic lands CONFIRM with a why, and anything else is
    MISMATCH -- heuristics are always surfaced as a guess, never auto-remapped.
    """
    if game_id == manifest_game_id:
        return (CueImportMatch.AUTO, "")

    raw_a = [t for t in _to_str(game_id).split("-") if t]
    raw_b = [t for t in _to_str(manifest_game_id).split("-") if t]
    tokens_a = [t.lower() for t in raw_a]
    tokens_b = [t.lower() for t in raw_b]
    if tokens_a == tokens_b:
        return (CueImportMatch.AUTO, "")

    common = 0
    for a, b in zip(tokens_a, tokens_b):
        if a == b:
            common += 1
        else:
            break
    if common >= 1:
        # Show the original-case prefix so the guess reads like the game name.
        return (CueImportMatch.CONFIRM,
                "both share prefix '{}'".format("-".join(raw_a[:common])))

    if (_cue_digit_strip_normalize(game_id) ==
            _cue_digit_strip_normalize(manifest_game_id)):
        return (CueImportMatch.CONFIRM,
                "the names match once version numbers are dropped")

    return (CueImportMatch.MISMATCH, "no shared identifier")


# --------------------------------------------------------------------------
# contents grouping / filtering
# --------------------------------------------------------------------------

def _cue_group_contents(contents):
    # type: (List[str]) -> Dict[int, List[str]]
    """Group import contents by category."""
    grouped = {}
    for rel in contents:
        cat = _cue_import_category(rel)
        grouped.setdefault(cat, []).append(rel)
    return grouped


def _cue_category_counts(contents):
    # type: (List[str]) -> Dict[int, int]
    """{category: file count} for the 5 categories actually present.  A
    category with no files is absent -- the UI greys it out."""
    grouped = _cue_group_contents(contents)
    counts = {}
    for cat in CUE_IMPORT_CATEGORY_ORDER:
        files = grouped.get(cat, [])
        if files:
            counts[cat] = len(files)
    return counts


def _cue_empty_categories(contents):
    # type: (List[str]) -> List[int]
    """Categories (of the 5) absent from contents."""
    grouped = _cue_group_contents(contents)
    return [cat for cat in CUE_IMPORT_CATEGORY_ORDER if cat not in grouped]


def _cue_filter_contents(contents, checked_categories):
    # type: (List[str], Any) -> List[str]
    """Keep only the files whose category is in checked_categories.  Anything
    outside the 5 (UNKNOWN) is never kept."""
    checked = set(checked_categories)
    return [rel for rel in contents if _cue_import_category(rel) in checked]


# --------------------------------------------------------------------------
# manifest build / validate / load
# --------------------------------------------------------------------------

def _cue_build_manifest(game_id, name, author, description, contents):
    # type: (str, str, str, str, List[str]) -> dict
    return {
        _CUE_MANIFEST_FORMAT_KEY: CUE_IMPORT_FORMAT_VERSION,
        "game_id": game_id,
        "name": (name or "")[:_CUE_MAX_NAME_LEN],
        "author": (author or "")[:_CUE_MAX_AUTHOR_LEN],
        "description": (description or "")[:_CUE_MAX_DESC_LEN],
        "contents": sorted(contents),
    }


def _cue_validate_manifest(manifest, zip_names):
    # type: (Any, Any) -> Tuple[bool, str]
    """Hard gates only: is this a usable import?  A newer format version is
    rejected outright; a malformed or absent contents list means it isn't a
    import.  Listed files absent from the zip are NOT a refusal -- they are
    reported separately via _cue_missing_files for a warn-and-confirm."""
    if not isinstance(manifest, dict):
        return (False, "This is not a renpy_cue import.")
    fmt = manifest.get(_CUE_MANIFEST_FORMAT_KEY)
    if not isinstance(fmt, int):
        return (False, "This is not a renpy_cue import.")
    if fmt > CUE_IMPORT_FORMAT_VERSION:
        return (False, "This was made with a newer renpy_cue and can't be "
                       "imported yet.")
    if not isinstance(manifest.get("contents"), list):
        return (False, "This is not a renpy_cue import.")
    return (True, "")


def _cue_missing_files(manifest, zip_names):
    # type: (Any, Any) -> List[str]
    """Listed content paths absent from the zip, in manifest order.  Empty
    when the manifest is malformed or every listed file is present."""
    if not isinstance(manifest, dict):
        return []
    contents = manifest.get("contents")
    if not isinstance(contents, list):
        return []
    return [rel for rel in contents if rel not in zip_names]


def _cue_load_manifest(imp_dir):
    # type: (str) -> Any
    """Read + parse {imp_dir}/manifest.json; None on any error."""
    path = os.path.join(imp_dir, CUE_IMPORT_MANIFEST_NAME)
    try:
        with open(path, "r") as f:
            data = _json.load(f)
    except Exception as e:
        _cue_log("IMPORT: failed to read manifest {}: {}".format(path, e))
        return None
    return data if isinstance(data, dict) else None


def _cue_zip_file_names(zip_path):
    # type: (str) -> Set[str]
    """Every file in an import zip as a '/' relative name (dirs excluded).
    Empty set if the archive can't be read -- validation then reports the
    import as missing files."""
    try:
        with _zipfile.ZipFile(zip_path, "r") as zf:
            return set(
                info.filename for info in zf.infolist()
                if not info.filename.endswith("/"))
    except Exception:
        return set()


def _cue_sanitize_filename(name):
    # type: (str) -> str
    """Sanitize an export filename: strip path separators and chars illegal on
    Windows.  Falls back to 'cue_import' if nothing survives."""
    safe = _to_str(name or "").replace("/", "_").replace("\\", "_")
    safe = _re.sub(r"[^A-Za-z0-9 ._-]", "", safe)
    return safe.strip(" ._-") or "cue_import"


# --------------------------------------------------------------------------
# import file enumeration
# --------------------------------------------------------------------------

def _cue_collect_tree(root, src_dir):
    # type: (str, str) -> List[str]
    """All files under src_dir as root-relative arcnames ('/' separated).
    Tolerates a missing dir (yields nothing)."""
    arcnames = []
    try:
        base = os.path.relpath(src_dir, root).replace("\\", "/")
        base = base.rstrip("/") + "/"
        for dirpath, _dirs, filenames in os.walk(src_dir):
            for name in filenames:
                rel = os.path.relpath(
                    os.path.join(dirpath, name), src_dir).replace("\\", "/")
                arcnames.append(base + rel)
    except Exception as e:
        _cue_log("IMPORT: enumerate failed for {}: {}".format(src_dir, e))
    return arcnames


def _cue_enumerate_import_files(root, game_id):
    # type: (str, str) -> Dict[int, List[str]]
    """{category: [arcname]} for every file in the 5 exportable source dirs
    under root (this game's namespaces only).  Empty categories are absent."""
    paths = CuePaths(root, game_id)
    sources = (
        (CueImportCategory.MARKERS, paths.marker_dir),
        (CueImportCategory.SFX, paths.audio_dir),
        (CueImportCategory.MUSIC, paths.music_dir),
        (CueImportCategory.SPEED_VARIANTS, paths.video_dir),
        (CueImportCategory.PRESETS, paths.presets_dir),
    )
    result = {}
    for cat, src_dir in sources:
        files = _cue_collect_tree(root, src_dir)
        if files:
            result[cat] = files
    return result


# --------------------------------------------------------------------------
# replay-scoped export -- markers for a replay + the files they reference
# --------------------------------------------------------------------------

def _cue_replay_assets(root, game_id, replay_labels):
    # type: (str, str, List[str]) -> Dict[int, List[str]]
    """{category: [arcname]} for every marker whose replay field is in
    replay_labels, plus the files those markers reference: SFX pool files
    (audio-relative on disk; folder refs expanded to the files under them),
    My Music entries, and presets named on their pools.  A marker never edited
    inside a replay has no replay field and belongs to no replay.  Game-music
    refs and untagged game-relative refs are dropped -- the recipient's copy
    has its own.  A marker file that can't be parsed is skipped.

    A replay whose markers include any video marker (v_ key) also pulls the
    whole video/<game_id>/ tree: the base movie path is runtime state, not
    stored on markers, so the variant files can't be mapped per-marker -- the
    entire set goes (the recipient only gets the variants, never the game's
    own base movie)."""
    paths = CuePaths(root, game_id)
    labels = set(replay_labels)
    result = {}
    has_video = False

    try:
        names = sorted(os.listdir(paths.marker_dir))
    except Exception:
        return result

    for name in names:
        if not name.endswith(".json"):
            continue
        entry = _cue_read_json_file(os.path.join(paths.marker_dir, name))
        if not isinstance(entry, dict):
            continue
        if entry.get("replay") not in labels:
            continue
        if name.startswith(CUE_VID_KEY_PREFIX):
            has_video = True

        _cue_add_asset(result, CueImportCategory.MARKERS,
                       "data/markers/{}/{}".format(game_id, name))
        pools = list(entry.get("pools") or []) + list(entry.get("timestamps") or [])

        for pool in pools:
            if not isinstance(pool, dict):
                continue
            for ref in pool.get("files") or []:
                _cue_add_referenced_asset(root, result, _cue_audio_rel(ref))
            if pool.get("preset"):
                for rel in _cue_preset_files(root, pool["preset"]):
                    _cue_add_asset(result, CueImportCategory.PRESETS, rel)

        for ref in entry.get("files") or []:
            _cue_add_referenced_asset(root, result, _cue_audio_rel(ref))

        for song in entry.get("music") or []:
            rel = _cue_music_rel(song)
            if rel:
                _cue_add_referenced_asset(root, result, rel)
    if has_video:
        for rel in _cue_collect_tree(root, paths.video_dir):
            _cue_add_asset(result, CueImportCategory.SPEED_VARIANTS, rel)
    return result


def _cue_replay_labels(root, game_id):
    # type: (str, str) -> List[Tuple[str, int]]
    """[(replay label, marker count)] for every replay that has markers,
    sorted by label.  A marker never edited inside a replay has no replay
    field and is not counted.  Labels are used as opaque keys, so str vs
    unicode (Py2) needs no coercion."""
    paths = CuePaths(root, game_id)
    counts = {}
    try:
        names = sorted(os.listdir(paths.marker_dir))
    except Exception:
        return []

    for name in names:
        if not name.endswith(".json"):
            continue
        entry = _cue_read_json_file(os.path.join(paths.marker_dir, name))
        if not isinstance(entry, dict):
            continue
        label = entry.get("replay")
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
        
    return sorted(counts.items())


def _cue_add_asset(result, cat, rel):
    # type: (Dict[int, List[str]], int, str) -> None
    files = result.setdefault(cat, [])
    if rel not in files:
        files.append(rel)


def _cue_audio_rel(ref):
    # type: (str) -> str
    """A stored pool file ref -> a root-relative arcname.

    Pool refs are stored audio-dir-relative (g1/s.ogg; folder refs keep a
    trailing '/') because they index the SFX manager's flat file list, so they
    need the audio/ prefix to resolve in the shared root.  A ref that already
    carries a category prefix passes through untouched."""
    if _cue_import_category(ref) != CueImportCategory.UNKNOWN:
        return ref
    return "audio/" + ref


def _cue_music_rel(song):
    # type: (str) -> Optional[str]
    """Map a stored music ref to a shareable root-relative path, or None.

    Stored refs are source-tagged: 'u:' My Music (shareable -- lives under the
    shared music/ dir) vs 'g:' Game Music (dropped -- the recipient has their
    own copy of the game's music).  An untagged legacy ref passes through when
    it already points under music/; anything else (game-relative paths) is
    dropped."""
    if not hasattr(song, "startswith"):
        return None
    if song.startswith(CUE_MUSIC_GAME_TAG):
        return None
    if song.startswith(CUE_MUSIC_USER_TAG):
        song = song[len(CUE_MUSIC_USER_TAG):]
    if song.startswith(CUE_MUSIC_PREFIX):
        return song
    return None


def _cue_add_referenced_asset(root, result, ref):
    # type: (str, Dict[int, List[str]], str) -> None
    """Add one marker file ref: a direct rel path, or a folder ref (trailing
    '/') expanded to every file on disk under it.  Unknown-prefix refs
    (game music and the like) are dropped -- not shareable content."""
    cat = _cue_import_category(ref)
    if cat == CueImportCategory.UNKNOWN:
        return
    if ref.endswith("/"):
        for rel in _cue_collect_tree(root, os.path.join(root, ref)):
            _cue_add_asset(result, cat, rel)
    else:
        _cue_add_asset(result, cat, ref)


def _cue_preset_files(root, preset_name):
    # type: (str, str) -> List[str]
    """Rel path(s) of the stored preset file named preset_name, across the
    audio/video/music preset dirs.  Mirrors db._preset_path's on-disk naming
    ({safe}_{sha1:8}.json) so referenced presets resolve exactly."""
    safe = preset_name.replace("/", "_").replace("\\", "_")
    digest = _hashlib.sha1(preset_name.encode("utf-8")).hexdigest()[:CUE_HASH_TRUNC_LEN]
    fname = "{}_{}.json".format(safe, digest)
    found = []
    for sub in ("audio", "video", "music"):
        rel = "data/presets/{}/{}".format(sub, fname)
        if os.path.isfile(os.path.join(root, rel.replace("/", os.sep))):
            found.append(rel)
    return found


def _cue_read_json_file(path):
    # type: (str) -> Any
    """Parse a JSON file to a dict; None on any error."""
    try:
        with open(path, "r") as f:
            data = _json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------
# zip build / extract
# --------------------------------------------------------------------------

def _cue_build_import_zip(root, game_id, name, author, description,
                           contents, zip_path, progress=None):
    # type: (str, str, str, str, str, List[str], str, Optional[Any]) -> int
    """Write an import zip at zip_path: manifest.json + each content file
    (arcname = its shared-root-relative path).  Writes a temp file first, then
    moves it over zip_path.  Returns the number of content files packed.  When
    progress is given, it is called as progress(written_bytes, total_bytes)
    after each file; total is pre-computed over the files that exist."""
    manifest = _cue_build_manifest(game_id, name, author, description, contents)
    tmp_path = zip_path + ".tmp"
    count = 0
    total = 0
    if progress is not None:
        for rel in contents:
            src = _safe_extract_path(root, rel)
            if os.path.isfile(src):
                total += os.path.getsize(src)
    with _zipfile.ZipFile(tmp_path, "w", _zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(CUE_IMPORT_MANIFEST_NAME,
                    _json.dumps(manifest, sort_keys=True, indent=2))
        written = 0
        for rel in contents:
            src = _safe_extract_path(root, rel)
            if not os.path.isfile(src):
                _cue_log("EXPORT: missing {}, skipping".format(src))
                continue
            zf.write(src, rel)
            count += 1
            if progress is not None:
                written += os.path.getsize(src)
                progress(written, total)
    _cue_replace_file(tmp_path, zip_path)
    return count


def _cue_extract_import_zip(zip_path, out_dir, progress=None):
    # type: (str, str, Optional[Any]) -> int
    """Extract every file in the zip under out_dir (dir entries skipped,
    parent traversal dropped).  Returns the file count.  When progress is
    given it is called as progress(written_bytes, total_bytes) after each
    file; total is the sum of uncompressed file sizes."""
    count = 0
    total = 0
    with _zipfile.ZipFile(zip_path, "r") as zf:
        if progress is not None:
            total = sum(info.file_size for info in zf.infolist()
                        if not info.filename.endswith("/"))
        written = 0
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            dest = _safe_extract_path(out_dir, name)
            parent = os.path.dirname(dest)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            with zf.open(info) as src_f:
                with open(dest, "wb") as dst_f:
                    _shutil.copyfileobj(src_f, dst_f)
            written += info.file_size
            count += 1
            if progress is not None:
                progress(written, total)
    return count


# --------------------------------------------------------------------------
# merge -- copy selected import files into a live root, data_bak safety net
# --------------------------------------------------------------------------

def _cue_copy_file(src, dst):
    # type: (str, str) -> None
    """Copy src to dst atomically (temp in the dst dir, then replace)."""
    parent = os.path.dirname(dst)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    fd, tmp = _tempfile.mkstemp(dir=parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out_f:
            with open(src, "rb") as in_f:
                _shutil.copyfileobj(in_f, out_f)
        _cue_replace_file(tmp, dst)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise


def _cue_merge_overwrites(root, contents):
    # type: (str, List[str]) -> List[str]
    """The contents whose destination under root already exists -- drives the
    merge dialog's overwrite summary."""
    return [rel for rel in contents
            if os.path.isfile(_safe_extract_path(root, rel))]


def _cue_merge_files(root, src_root, contents):
    # type: (str, str, List[str]) -> int
    """Copy each content file from src_root (the extracted import) into root.
    An existing destination is first moved to {root}/data_bak/{rel} as a
    safety net.  Copy, not rename, so the import stays intact for re-extract
    recovery.  Returns the number of files merged."""
    count = 0
    for rel in contents:
        src = _safe_extract_path(src_root, rel)
        if not os.path.isfile(src):
            continue
        dst = _safe_extract_path(root, rel)
        if os.path.isfile(dst):
            bak = _safe_extract_path(os.path.join(root, CUE_BAK_DIR), rel)
            parent = os.path.dirname(bak)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            _cue_replace_file(dst, bak)
        _cue_copy_file(src, dst)
        count += 1
    return count
