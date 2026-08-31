# -*- coding: utf-8 -*-
# cue_lib/importer_io.py -- import/export .zip format.
#
# An import is a .zip mirroring the shared-root layout plus a manifest.json
# recording the packed files.  This module owns the pure logic (category
# mapping, game_id matching, manifest build/validate) and the filesystem ops
# (zip build/extract, merge copy).  It imports only stdlib + cue_lib helpers
# -- never runtime or state -- so managers can use it without import cycles.

import copy as _copy
import hashlib as _hashlib
import json as _json
import os
import re as _re
import shutil as _shutil
import tempfile as _tempfile
import zipfile as _zipfile

from cue_lib.backup import CUE_BAK_DIR, _safe_extract_path
from cue_lib.constants import (
    CUE_AUDIO_EXTS,
    CUE_EXTERNAL_HASH_LEN,
    CUE_HASH_TRUNC_LEN,
    CUE_MUSIC_GAME_TAG,
    CUE_MUSIC_PREFIX,
    CUE_MUSIC_USER_TAG,
    CUE_IMPORT_CATEGORY_ORDER,
    CUE_IMPORT_MANIFEST_NAME,
    CUE_INTENSITY_PRESET_TYPE,
    CUE_VID_KEY_PREFIX,
    CUE_SHARED_KEY_MUSIC_FOLDERS,
    CUE_SHARED_KEY_SFX_FOLDERS,
    CueImportCategory,
    CueImportMatch,
)
from cue_lib.paths import CuePaths, CUE_THUMBS_CACHE_NAME
from cue_lib.util import (
    _cue_is_abs_path,
    _cue_is_variant_of,
    _cue_log,
    _cue_replace_file,
    _cue_variant_base_name,
    _to_str,
)

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]

# Import format version, bumped only on breaking format changes (not the mod
# version).  The importer rejects an import whose format is NEWER than this.
CUE_IMPORT_FORMAT_VERSION = 1

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

# Extension allow-list per category.  An entry under a known prefix but
# carrying a foreign extension is not cue content: it is skipped at extract
# and merge, and never enumerated for export, so a manifest can't list a file
# the import will drop.  Media dirs keep their audio/video extensions; markers
# and presets are JSON.
_CUE_VIDEO_EXTS = (".webm", ".mp4", ".mkv", ".ogv", ".avi")
_CUE_CATEGORY_EXTS = {
    CueImportCategory.MARKERS: (".json",),
    CueImportCategory.PRESETS: (".json",),
    CueImportCategory.SFX: CUE_AUDIO_EXTS,
    CueImportCategory.MUSIC: CUE_AUDIO_EXTS,
    CueImportCategory.SPEED_VARIANTS: _CUE_VIDEO_EXTS,
}


def _cue_import_category(path):
    # type: (str) -> int
    """Map a zip-relative path to its CueImportCategory (UNKNOWN if it
    falls outside the 5 exportable categories)."""
    for cat, prefix in _CUE_CATEGORY_PREFIX:
        if path.startswith(prefix):
            return cat
    return CueImportCategory.UNKNOWN


def _cue_known_content(path):
    # type: (str) -> bool
    """True when path is recognizable cue content: under one of the 5 category
    prefixes and carrying that category's extension (case-insensitive)."""
    exts = _CUE_CATEGORY_EXTS.get(_cue_import_category(path))
    return exts is not None and path.lower().endswith(exts)


def _cue_thumbs_cache_rel():
    # type: () -> str
    """Zip-relative path of the scene-thumbnail mapping file.  Runtime data
    that rides exports so an import (and its preview) shows dev-selected scene
    thumbnails instead of the marker-filepath fallback; never a user-facing
    category."""
    return "data/" + CUE_THUMBS_CACHE_NAME


def _cue_is_cache_arc(rel):
    # type: (str) -> bool
    """True when rel is the scene-thumbnail mapping cache file."""
    return rel == _cue_thumbs_cache_rel()


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
        return (CueImportMatch.CONFIRM, "both share prefix '{}'".format("-".join(raw_a[:common])))

    if _cue_digit_strip_normalize(game_id) == _cue_digit_strip_normalize(manifest_game_id):
        return (CueImportMatch.CONFIRM, "the names match once version numbers are dropped")

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


def _cue_build_manifest(game_id, name, author, description, contents, replays=None):
    # type: (str, str, str, str, List[str], Optional[List[dict]]) -> dict
    return {
        _CUE_MANIFEST_FORMAT_KEY: CUE_IMPORT_FORMAT_VERSION,
        "game_id": game_id,
        "name": (name or "")[:_CUE_MAX_NAME_LEN],
        "author": (author or "")[:_CUE_MAX_AUTHOR_LEN],
        "description": (description or "")[:_CUE_MAX_DESC_LEN],
        "contents": sorted(contents),
        "replays": replays or [],
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
        return (False, "This was made with a newer renpy_cue and can't be imported yet.")
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
    # Py2: manifest rels are unicode (json), zip names are str bytes.  Coerce
    # both so a non-ASCII filename present in the zip isn't falsely missing.
    zip_set = set(_to_str(n) for n in zip_names)
    return [rel for rel in contents if _to_str(rel) not in zip_set]


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
            return set(info.filename for info in zf.infolist() if not info.filename.endswith("/"))
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
    Non-cue files (foreign extensions under a category prefix) are skipped --
    export only ships content the import can consume.  Tolerates a missing
    dir (yields nothing)."""
    arcnames = []
    try:
        base = os.path.relpath(src_dir, root).replace("\\", "/")
        base = base.rstrip("/") + "/"
        for dirpath, _dirs, filenames in os.walk(src_dir):
            for name in filenames:
                rel = os.path.relpath(os.path.join(dirpath, name), src_dir).replace("\\", "/")
                arcname = base + rel
                if not _cue_known_content(arcname):
                    continue
                arcnames.append(arcname)
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
    """Backward-compat wrapper: the per-category asset map for a replay
    export.  External (e:) refs are dropped -- see _cue_replay_assets_full
    for the dropped-file count."""
    per_cat, _ext = _cue_replay_assets_full(root, game_id, replay_labels)
    return per_cat


def _cue_replay_assets_full(root, game_id, replay_labels):
    # type: (str, str, List[str]) -> Tuple[Dict[int, List[str]], int]
    """Replay-scoped export content + the count of external (e:) refs dropped.

    {category: [arcname]} for every marker whose replay field is in
    replay_labels, plus the files those markers reference: SFX pool files
    (audio-relative on disk; folder refs expanded to the files under them),
    My Music entries, and presets named on their pools.  A marker never edited
    inside a replay has no replay field and belongs to no replay.  Game-music
    refs and untagged game-relative refs are dropped -- the recipient's copy
    has its own.  External (e:) refs are dropped too (their files live outside
    the shared tree and can't be packed); the count lets the exporter warn.

    Video markers (v_ key) pull the speed variants of the movie they belong
    to, resolved from the base-movie path captured on the marker at creation
    (entry["filepath"]) -- a replay-scoped export never ships every movie in
    the video/<game_id>/ tree.  A video marker saved before filepaths were
    captured has no filepath; one of those anywhere in scope falls back to the
    whole variant tree, since its movie can't be identified (the recipient
    only gets the variants, never the game's own base movie)."""
    paths = CuePaths(root, game_id)
    labels = set(replay_labels)
    result = {}
    video_bases = set()  # type: Set[str]
    has_unmapped_video = False
    external_refs = set()  # type: Set[str]

    try:
        names = sorted(os.listdir(paths.marker_dir))
    except Exception:
        return result, 0

    for name in names:
        if not name.endswith(".json"):
            continue
        entry = _cue_read_json_file(os.path.join(paths.marker_dir, name))
        if not isinstance(entry, dict):
            continue
        if entry.get("replay") not in labels:
            continue
        if name.startswith(CUE_VID_KEY_PREFIX):
            fp = entry.get("filepath")
            if fp:
                video_bases.add(fp)
            else:
                has_unmapped_video = True

        _cue_add_asset(result, CueImportCategory.MARKERS, "data/markers/{}/{}".format(game_id, name))
        pools = list(entry.get("pools") or []) + list(entry.get("timestamps") or [])

        for pool in pools:
            if not isinstance(pool, dict):
                continue
            for ref in pool.get("files") or []:
                if _cue_is_abs_path(ref):
                    external_refs.add(ref)
                else:
                    _cue_add_referenced_asset(root, result, _cue_audio_rel(ref))
            if pool.get("preset"):
                for rel in _cue_preset_files(root, pool["preset"]):
                    _cue_add_asset(result, CueImportCategory.PRESETS, rel)
            if pool.get("igroup"):
                _cue_igroup_assets(root, result, pool["igroup"]["name"])

        for ref in entry.get("files") or []:
            _cue_add_referenced_asset(root, result, _cue_audio_rel(ref))

        for song in entry.get("music") or []:
            if hasattr(song, "startswith") and _cue_is_abs_path(song):
                external_refs.add(song)
            else:
                rel = _cue_music_rel(song)
                if rel:
                    _cue_add_referenced_asset(root, result, rel)
    if has_unmapped_video:
        # A video marker in scope predates filepath capture; its movie can't
        # be identified, so ship the whole variant tree (old behavior).
        for rel in _cue_collect_tree(root, paths.video_dir):
            _cue_add_asset(result, CueImportCategory.SPEED_VARIANTS, rel)
    elif video_bases:
        # Normalize marker filepaths to their base movie (a marker may have
        # captured a variant path), then keep only matching variants.
        bases = set(_cue_variant_base_name(os.path.basename(b)) for b in video_bases)
        for rel in _cue_collect_tree(root, paths.video_dir):
            for base_name in bases:
                if _cue_is_variant_of(rel, base_name):
                    _cue_add_asset(result, CueImportCategory.SPEED_VARIANTS, rel)
                    break
    # Per-replay metadata subdirs ride with their replay: the cast file
    # (replays/<label>.json) and the default-music trigger log
    # (music_triggers/<label>.json).  Both are marker-dir children, not
    # markers, and travel only for the selected replays.
    for label in sorted(labels):
        _cue_add_marker_subdir_asset(result, root, game_id, "replays", label)
        _cue_add_marker_subdir_asset(result, root, game_id, "music_triggers", label)
    return result, len(external_refs)


def _cue_manifest_replays(root, game_id, contents):
    # type: (str, str, List[str]) -> List[dict]
    """[{"replay": label, "marker_count": count}] for the replay-tagged
    marker files among contents, sorted by label.  Only markers actually
    packed count -- a Specific-Replays export lists just the replays whose
    markers made it into the zip.  A marker never edited inside a replay has
    no replay field and is omitted."""
    prefix = "data/markers/{}/".format(game_id)
    counts = {}
    for rel in contents:
        if not rel.startswith(prefix) or not rel.endswith(".json"):
            continue
        # Only direct children of the marker dir are markers; the replays/
        # and music_triggers/ subdirs hold per-replay metadata, not scenes.
        if "/" in rel[len(prefix) :]:
            continue
        entry = _cue_read_json_file(os.path.join(root, rel))
        if not isinstance(entry, dict):
            continue
        label = entry.get("replay")
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    return [{"replay": label, "marker_count": counts[label]} for label in sorted(counts)]


def _cue_add_asset(result, cat, rel):
    # type: (Dict[int, List[str]], int, str) -> None
    files = result.setdefault(cat, [])
    if rel not in files:
        files.append(rel)


def _cue_marker_subdir_rel(game_id, subdir, label):
    # type: (str, str, str) -> str
    """Rel arcname of a per-replay metadata file (cast, music trigger)."""
    return "data/markers/{}/{}/{}.json".format(game_id, subdir, label)


def _cue_add_marker_subdir_asset(result, root, game_id, subdir, label):
    # type: (Dict[int, List[str]], str, str, str, str) -> None
    """Add a per-replay metadata file to the export when it exists on disk."""
    rel = _cue_marker_subdir_rel(game_id, subdir, label)
    if os.path.isfile(os.path.join(root, rel.replace("/", os.sep))):
        _cue_add_asset(result, CueImportCategory.MARKERS, rel)


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
        song = song[len(CUE_MUSIC_USER_TAG) :]
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


# --------------------------------------------------------------------------
# external bake -- turn absolute external media refs into portable content
# --------------------------------------------------------------------------


def _cue_utf8_byte(text):
    # type: (str) -> bytes
    """Coerce a str/unicode path to bytes for hashing (py2/py3 safe)."""
    if isinstance(text, bytes):
        return text
    return text.encode("utf-8")


def _cue_breadcrumb(abs_root):
    # type: (str) -> str
    """Display basename of an external source root (empty -> 'External')."""
    base = abs_root.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return base if base else "External"


def _cue_source_root(abs_ref, extra_roots):
    # type: (str, List[str]) -> Tuple[Optional[str], str]
    """(source_root, rel) when abs_ref sits under one of extra_roots.

    abs_ref is the stored bare absolute ref (optionally a folder ref with a
    trailing '/').  Returns the longest matching root with the ref's remainder
    as rel (rel keeps a trailing '/' for a folder ref); (None, '') if it
    matches no root."""
    ref = abs_ref.replace("\\", "/")
    best = None  # type: Optional[str]
    for root in extra_roots:
        r = root.replace("\\", "/").rstrip("/")
        if ref == r or ref.startswith(r + "/"):
            if best is None or len(r) > len(best):
                best = r
    if best is None:
        return None, ""
    if ref == best:
        return best, ""
    return best, ref[len(best) + 1 :]


def _cue_collect_external_refs(data):
    # type: (Dict[str, Any]) -> List[Tuple[Tuple[Any, ...], str]]
    """All absolute external media refs in a marker dict, as (loc_path, ref).

    loc_path is a tuple of keys/indices tracing from data to the ref so it can
    be swapped in place on rewrite.  Covers the SFX pool files, the entry's own
    files, and its music list -- the refs the exporter used to drop."""
    out = []  # type: List[Tuple[Tuple[Any, ...], str]]
    for pi, pool in enumerate(data.get("pools") or []):
        if not isinstance(pool, dict):
            continue
        for fi, ref in enumerate(pool.get("files") or []):
            if hasattr(ref, "startswith") and _cue_is_abs_path(ref):
                out.append((("pools", pi, "files", fi), ref))
    for fi, ref in enumerate(data.get("files") or []):
        if hasattr(ref, "startswith") and _cue_is_abs_path(ref):
            out.append((("files", fi), ref))
    for mi, song in enumerate(data.get("music") or []):
        if hasattr(song, "startswith") and _cue_is_abs_path(song):
            out.append((("music", mi), song))
    return out


def _cue_rewrite_marker(data, swaps):
    # type: (Dict[str, Any], List[Tuple[Tuple[Any, ...], str, str]]) -> Dict[str, Any]
    """A shallow copy of data with each swap's ref text replaced in place.

    swaps are (loc_path, old_ref, new_ref); loc_path traces to the ref within
    data.  The original dict is never mutated."""
    result = _copy.deepcopy(data)
    for loc, _old, new in swaps:
        node = result
        for key in loc[:-1]:
            node = node[key]
        node[loc[-1]] = new
    return result


def _cue_walk_abs(abs_folder, source_root):
    # type: (str, str) -> List[str]
    """Every file under abs_folder as a '/'-separated rel path from
    source_root.  Tolerates a missing folder (yields nothing)."""
    rels = []
    if not os.path.isdir(abs_folder):
        return rels
    for dirpath, _dirs, filenames in os.walk(abs_folder):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rels.append(os.path.relpath(full, source_root).replace("\\", "/"))
    return rels


def _cue_ref_category(loc):
    # type: (Tuple[Any, ...]) -> int
    """CueImportCategory a marker ref location belongs to."""
    return CueImportCategory.MUSIC if (loc and loc[0] == "music") else CueImportCategory.SFX


def _cue_external_roots(config_path):
    # type: (str) -> List[str]
    """The user's configured external Music/SFX folder roots, in config order.

    These absolute paths are the candidate source roots a marker's abs ref must
    sit under for the export to bake it.  Missing or unreadable config yields
    [] (nothing to bake)."""
    try:
        with open(config_path, "r") as fh:
            config = _to_str(_json.load(fh))
    except Exception:
        return []
    out = []
    for key in (CUE_SHARED_KEY_MUSIC_FOLDERS, CUE_SHARED_KEY_SFX_FOLDERS):
        val = config.get(key)
        if isinstance(val, list):
            out.extend(str(v) for v in val)
    return out


def _cue_external_bake(root, game_id, marker_arcnames, extra_roots, allowed):
    # type: (str, str, List[str], List[str], Set[int]) -> Tuple[List[str], Dict[str, str], Dict[str, Any]]
    """Bake absolute external media refs referenced by marker JSONs into the
    export bundle as portable relative refs.

    marker_arcnames are the in-scope marker arcs (data/markers/<gid>/x.json);
    extra_roots the configured external Music/SFX folder roots; allowed the set
    of CueImportCategory being exported (baking honors category checkboxes).

    Returns (add_contents, overrides, rewrites):
      * add_contents -- arcnames to append to the zip contents
        (audio/_external/<ns>/<rel> and music/_external/<ns>/<rel>).
      * overrides -- {arcname: abs_source_path} telling the zip builder to copy
        from the external file rather than <root>/<arcname>.
      * rewrites -- {marker_arcname: rewritten-dict} for markers whose abs refs
        were swapped for baked-relative refs (re-serialized on zip write).

    A baked source missing on disk is dropped from the override map but its
    arcname stays in add_contents, so the importer's missing-file flow flags
    it (warn-and-proceed).  Only marker-level refs are baked -- SFX pool files,
    entry files, entry music."""
    if not marker_arcnames or not extra_roots:
        return [], {}, {}
    if CueImportCategory.MARKERS not in allowed:
        return [], {}, {}
    markers = [a for a in marker_arcnames if a.endswith(".json")]
    if not markers:
        return [], {}, {}

    # source_root -> {"files": {rel: abs_path}}
    sources = {}  # type: Dict[str, Dict[str, Any]]
    found_by_marker = {}  # type: Dict[str, List[Tuple[Tuple[Any, ...], str]]]
    data_by_marker = {}  # type: Dict[str, Dict[str, Any]]

    for arc in markers:
        data = _cue_read_json_file(os.path.join(root, arc.replace("/", os.sep)))
        if not isinstance(data, dict):
            continue
        found = [f for f in _cue_collect_external_refs(data) if _cue_ref_category(f[0]) in allowed]
        if not found:
            continue
        found_by_marker[arc] = found
        data_by_marker[arc] = data
        for loc, ref in found:
            sroot, rel = _cue_source_root(ref, extra_roots)
            if sroot is None:
                continue
            src = sources.setdefault(sroot, {"files": {}})
            # A folder ref is flagged by the original abs ref's trailing '/'
            # (the derived rel can be "" when the ref is the whole root), not
            # by rel.endswith("/").
            if ref.endswith("/"):
                for frel in _cue_walk_abs(sroot + "/" + rel, sroot):
                    src["files"][frel] = sroot + "/" + frel
            else:
                src["files"][rel] = sroot + "/" + rel

    if not sources:
        return [], {}, {}

    # Per-source namespace: SHA1 over sorted (rel + bytes) of the baked files.
    for sroot, src in sources.items():
        h = _hashlib.sha1()
        for rel in sorted(src["files"]):
            h.update(_cue_utf8_byte(rel) + b"\x00")
            try:
                with open(src["files"][rel].replace("/", os.sep), "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
            except Exception:
                pass
        src["ns"] = "_external/" + _cue_breadcrumb(sroot) + "-" + h.hexdigest()[:CUE_EXTERNAL_HASH_LEN]

    add_contents = []  # type: List[str]
    overrides = {}  # type: Dict[str, str]
    rewrites = {}  # type: Dict[str, Any]

    for arc, found in found_by_marker.items():
        swaps = []  # type: List[Tuple[Tuple[Any, ...], str, str]]
        for loc, ref in found:
            sroot, rel = _cue_source_root(ref, extra_roots)
            if sroot is None:
                continue
            src = sources[sroot]
            ns = src["ns"]
            is_music = loc[0] == "music"
            prefix = "music/" if is_music else "audio/"
            # SFX refs are stored audio-dir-relative (pool refs index the flat
            # list) so _cue_audio_rel adds the audio/ prefix on import; music
            # refs carry the music/ prefix in stored form, so it is baked in.
            if is_music:
                new_ref = "u:" + prefix + ns + "/" + rel
            else:
                new_ref = ns + "/" + rel
            swaps.append((loc, ref, new_ref))
            if ref.endswith("/"):
                for frel, fabs in src["files"].items():
                    if not frel.startswith(rel):
                        continue
                    farc = prefix + ns + "/" + frel
                    if farc not in overrides:
                        overrides[farc] = fabs
                        add_contents.append(farc)
            else:
                arcname = prefix + ns + "/" + rel
                if arcname not in overrides:
                    overrides[arcname] = sroot + "/" + rel
                    add_contents.append(arcname)
        if swaps:
            rewrites[arc] = _cue_rewrite_marker(data_by_marker[arc], swaps)

    return add_contents, overrides, rewrites


def _cue_preset_rel(subdir, preset_name):
    # type: (str, str) -> str
    """Rel path of a stored preset file named preset_name -- mirrors
    db._preset_path's on-disk naming ({safe}_{sha1:8}.json) so every consumer
    resolves the same file the db writes."""
    safe = preset_name.replace("/", "_").replace("\\", "_")
    digest = _hashlib.sha1(preset_name.encode("utf-8")).hexdigest()[:CUE_HASH_TRUNC_LEN]
    return "data/presets/{}/{}_{}.json".format(subdir, safe, digest)


def _cue_preset_files(root, preset_name):
    # type: (str, str) -> List[str]
    """Rel path(s) of the stored preset file named preset_name, across the
    audio/video/music preset dirs.  Mirrors db._preset_path's on-disk naming
    ({safe}_{sha1:8}.json) so referenced presets resolve exactly."""
    found = []
    for sub in ("audio", "video", "music"):
        rel = _cue_preset_rel(sub, preset_name)
        if os.path.isfile(os.path.join(root, rel.replace("/", os.sep))):
            found.append(rel)
    return found


def _cue_igroup_assets(root, result, igroup_name):
    # type: (str, Dict[int, List[str]], str) -> None
    """Add the intensity group named igroup_name and every file it references.

    A pool hooks an igroup by name (store-time the pool's ``files`` is cleared
    and its ``igroup`` dict is set).  The group is a shared preset JSON
    under data/presets/intensity/; each level's folders/direct refs are
    audio-dir-relative, the same shape as a marker pool's ``files``.  The WHOLE
    group travels -- every level, not just the pinned one -- so the recipient
    can re-run speed banding for the level a playback lands on.  A group that
    has been deleted (no JSON on disk) is skipped: nothing to bring."""
    rel = _cue_preset_rel(CUE_INTENSITY_PRESET_TYPE, igroup_name)
    fpath = _safe_extract_path(root, rel)
    if fpath is None or not os.path.isfile(fpath):
        return
    _cue_add_asset(result, CueImportCategory.PRESETS, rel)
    data = _cue_read_json_file(fpath)
    if not isinstance(data, dict):
        return
    for level in data.get("levels") or []:
        if not isinstance(level, dict):
            continue
        for ref in level.get("files") or []:
            _cue_add_referenced_asset(root, result, _cue_audio_rel(ref))


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


def _cue_build_import_zip(
    root, game_id, name, author, description, contents, zip_path, progress=None, overrides=None, rewrites=None
):
    # type: (str, str, str, str, str, List[str], str, Optional[Any], Optional[Dict[str, str]], Optional[Dict[str, Any]]) -> int
    """Write an import zip at zip_path: manifest.json + each content file
    (arcname = its shared-root-relative path).  Writes a temp file first, then
    moves it over zip_path.  Returns the number of content files packed.  When
    progress is given, it is called as progress(written_bytes, total_bytes)
    after each file; total is pre-computed over the files that exist.

    overrides maps an arcname to an absolute source path -- used for baked
    external files that live outside the shared root.  rewrites maps an arcname
    to a dict that is serialized as the zip entry instead of copying the file
    (markers whose external refs were rewritten)."""
    manifest = _cue_build_manifest(
        game_id, name, author, description, contents, _cue_manifest_replays(root, game_id, contents)
    )
    tmp_path = zip_path + ".tmp"
    count = 0
    total = 0
    if progress is not None:
        for rel in contents:
            if rewrites is not None and rel in rewrites:
                total += len(_json.dumps(rewrites[rel], sort_keys=True))
                continue
            src = _cue_zip_source(root, rel, overrides)
            if src is None or not os.path.isfile(src):
                continue
            total += os.path.getsize(src)
    with _zipfile.ZipFile(tmp_path, "w", _zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(CUE_IMPORT_MANIFEST_NAME, _json.dumps(manifest, sort_keys=True, indent=2))
        written = 0
        for rel in contents:
            if rewrites is not None and rel in rewrites:
                data = _json.dumps(rewrites[rel], sort_keys=True, indent=2)
                zf.writestr(rel, data)
                count += 1
                if progress is not None:
                    written += len(data)
                    progress(written, total)
                continue
            src = _cue_zip_source(root, rel, overrides)
            if src is None or not os.path.isfile(src):
                _cue_log("EXPORT: missing {}, skipping".format(rel))
                continue
            zf.write(src, rel)
            count += 1
            if progress is not None:
                written += os.path.getsize(src)
                progress(written, total)
    _cue_replace_file(tmp_path, zip_path)
    return count


def _cue_zip_source(root, rel, overrides):
    # type: (str, str, Optional[Dict[str, str]]) -> Optional[str]
    """Absolute source path to copy for a zip arcname: an overridden baked
    external file, else <root>/<rel> (None if the path is unsafe)."""
    if overrides is not None and rel in overrides:
        return overrides[rel]
    return _safe_extract_path(root, rel)


def _cue_extract_import_zip(zip_path, out_dir, progress=None):
    # type: (str, str, Optional[Any]) -> int
    """Extract the zip's cue content under out_dir: the manifest plus every
    file under a known category prefix with a recognized extension.  Dir
    entries, parent-traversal names, and unexpected files (stray .exe, foreign
    extensions) are skipped.  Returns the file count.  When progress is given
    it is called as progress(written_bytes, total_bytes) after each file;
    total is the sum of uncompressed sizes of the entries that pass the
    filters."""
    count = 0
    total = 0
    with _zipfile.ZipFile(zip_path, "r") as zf:
        infos = []
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            if name != CUE_IMPORT_MANIFEST_NAME and not _cue_known_content(name) and not _cue_is_cache_arc(name):
                _cue_log("IMPORT: skipped unexpected file: {}".format(name))
                continue
            infos.append(info)
        if progress is not None:
            total = sum(info.file_size for info in infos)
        written = 0
        for info in infos:
            name = info.filename
            dest = _safe_extract_path(out_dir, name)
            if dest is None:
                _cue_log("IMPORT: blocked unsafe path: {}".format(name))
                continue
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


def _cue_extract_zip_to(zip_path, out_dir, progress=None, unwrap_root=False):
    # type: (str, str, Optional[Any], bool) -> int
    """Extract every entry of a zip into out_dir, no content filtering.

    Unlike _cue_extract_import_zip this keeps all files -- used to unpack a
    plain archive (the curated SFX pack) into a drop folder.  Traversal names
    are skipped via _safe_extract_path.  Returns the file count; when progress
    is given it fires as progress(written_bytes, total_bytes) after each file.
    unwrap_root=True drops a single top-level directory that every file entry
    shares (an archive-wrapper dir) so its contents land directly in out_dir;
    a mixed archive is left untouched."""
    count = 0
    with _zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        # py2-compatible dir test: ZipInfo.is_dir() is py3.6+ only.
        names = [info.filename for info in infos if not info.filename.endswith("/")]
        unwrap_prefix = None  # type: Optional[str]
        if unwrap_root and names:
            top = names[0].split("/", 1)[0]
            if top and all(name.split("/", 1)[0] == top for name in names):
                unwrap_prefix = top + "/"
        total = 0
        if progress is not None:
            total = sum(info.file_size for info in infos if not info.filename.endswith("/"))
        written = 0
        for info in infos:
            name = info.filename
            if name.endswith("/"):
                continue
            if unwrap_prefix is not None and name.startswith(unwrap_prefix):
                name = name[len(unwrap_prefix) :]
            dest = _safe_extract_path(out_dir, name)
            if dest is None:
                _cue_log("EXTRACT: blocked unsafe path: {}".format(name))
                continue
            parent = os.path.dirname(dest)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            with zf.open(info) as src_f:
                with open(dest, "wb") as dst_f:
                    _shutil.copyfileobj(src_f, dst_f)
            count += 1
            if progress is not None:
                written += info.file_size
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
    """The cue content whose destination under root already exists -- drives
    the merge dialog's overwrite summary.  Non-cue paths are never counted."""
    out = []
    for rel in contents:
        if not _cue_known_content(rel) and not _cue_is_cache_arc(rel):
            continue
        dest = _safe_extract_path(root, rel)
        if dest is not None and os.path.isfile(dest):
            out.append(rel)
    return out


def _cue_merge_files(root, src_root, contents):
    # type: (str, str, List[str]) -> int
    """Copy each cue content file from src_root (the extracted import) into
    root.  Non-cue paths are skipped.  An existing destination is first moved
    to {root}/data_bak/{rel} as a safety net.  Copy, not rename, so the import
    stays intact for re-extract recovery.  Returns the number of files merged."""
    count = 0
    for rel in contents:
        if not _cue_known_content(rel) and not _cue_is_cache_arc(rel):
            continue
        src = _safe_extract_path(src_root, rel)
        if src is None or not os.path.isfile(src):
            continue
        dst = _safe_extract_path(root, rel)
        if dst is None:
            continue
        if os.path.isfile(dst):
            bak = _safe_extract_path(os.path.join(root, CUE_BAK_DIR), rel)
            if bak is None:
                continue
            parent = os.path.dirname(bak)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            _cue_replace_file(dst, bak)
        _cue_copy_file(src, dst)
        count += 1
    return count
