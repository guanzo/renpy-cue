# -*- coding: utf-8 -*-
# Music stored-ref resolution: split source tags ("u:"/"g:"), resolve a ref to
# a playable path, and expand folder refs against the music library caches.
# Pure functions over the library -- no state, so callers pass what they need.

from cue_lib.constants import CUE_MUSIC_GAME_TAG, CUE_MUSIC_PREFIX, CUE_MUSIC_USER_TAG
from cue_lib.util import _cue_expand_folder_ref, _cue_is_abs_path

MYPY = False
if MYPY:
    from typing import List, Optional, Tuple
    from cue_lib.paths import CuePaths
    from cue_lib.audio.tree.music_tree import CueMusicTree


def _cue_split_ref_tag(ref):
    # type: (str) -> Tuple[Optional[str], str]
    """Split a stored ref into (tag, path); tag is None if untagged.

    External refs carry no tag -- they are bare absolute paths, recognised
    by _cue_is_abs_path at the call sites that need to distinguish them."""
    if ref.startswith(CUE_MUSIC_USER_TAG):
        return CUE_MUSIC_USER_TAG, ref[len(CUE_MUSIC_USER_TAG) :]
    if ref.startswith(CUE_MUSIC_GAME_TAG):
        return CUE_MUSIC_GAME_TAG, ref[len(CUE_MUSIC_GAME_TAG) :]
    return None, ref


def _cue_ref_path(ref):
    # type: (str) -> str
    """Stored ref without its source tag, for display."""
    return _cue_split_ref_tag(ref)[1]


def _cue_resolve_music_path(paths, stored):
    # type: (CuePaths, str) -> str
    """Turn a stored music entry into a playable path.

    Ref sources are resolved by tag: "u:" (My Music) is root-relative
    under the shared music dir, "g:" (Game Music) is game-relative and
    plays directly.  A bare absolute path is an external ref and plays
    as-is.  No disk probing -- every ref is tagged or absolute, and the
    last branch is a non-probing fallback for stray legacy data."""
    tag, path = _cue_split_ref_tag(stored)
    if tag == CUE_MUSIC_USER_TAG:
        if path.startswith(CUE_MUSIC_PREFIX):
            path = path[len(CUE_MUSIC_PREFIX) :]
        return paths.music_dir + path
    if tag == CUE_MUSIC_GAME_TAG:
        return path
    if _cue_is_abs_path(stored):
        # External payload is already absolute.
        return stored
    # Untagged relative -- legacy only; default to the My Music layout.
    if path.startswith(CUE_MUSIC_PREFIX):
        path = path[len(CUE_MUSIC_PREFIX) :]
    return paths.music_dir + path


def _cue_resolve_music_files(library, files):
    # type: (CueMusicTree, List[str]) -> List[str]
    """Expand folder refs (trailing '/') to matching available files.

    A tagged ref ("u:" My Music / "g:" Game Music) expands only against
    that cache; an untagged legacy ref expands against both.  Direct refs
    pass through unchanged; results are deduped."""
    result = []
    for item in files:
        if item.endswith("/"):
            _cue_resolve_folder_ref(library, item, result)
        elif item not in result:
            result.append(item)
    return result


def _cue_resolve_folder_ref(library, folder_ref, result):
    # type: (CueMusicTree, str, List[str]) -> None
    """Expand a single folder ref into concrete stored-form file paths."""
    tag, ref = _cue_split_ref_tag(folder_ref)
    if tag == CUE_MUSIC_USER_TAG:
        _cue_expand_folder_into(result, library.user_files, ref, CUE_MUSIC_USER_TAG)
    elif tag == CUE_MUSIC_GAME_TAG:
        _cue_expand_folder_into(result, library.game_files, ref, CUE_MUSIC_GAME_TAG)
    elif _cue_is_abs_path(folder_ref):
        # External folder: no tag, expand the absolute path under the
        # external payload list (which holds bare absolute paths).
        for f in _cue_expand_folder_ref(library.external_files, ref):
            if f not in result:
                result.append(f)
    else:
        # Legacy untagged ref -- ambiguous, match both caches (tagged so
        # every expanded child is stored-form).
        _cue_expand_folder_into(result, library.user_files, ref, CUE_MUSIC_USER_TAG)
        _cue_expand_folder_into(result, library.game_files, ref, CUE_MUSIC_GAME_TAG)


def _cue_expand_folder_into(result, files, ref, tag):
    # type: (List[str], List[str], str, str) -> None
    """Append the files under `ref` in `files`, each tagged as stored-form."""
    for f in _cue_expand_folder_ref(files, ref):
        expanded = tag + f
        if expanded not in result:
            result.append(expanded)
