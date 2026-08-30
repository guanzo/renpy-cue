# -*- coding: utf-8 -*-
# CueRecentManager -- the "Recently Used" list backing the SFX library row
# (and, later, the music library).
#
# Entries are heterogeneous: {"type": "file"|"folder"|"preset", "ref": <str>},
# stored most-recent-first under persistent._cue[<key>].  "type" differs by
# library (music has no presets); "ref" is opaque to this manager -- the keep
# callable injected at construction decides prune-time existence, so one
# manager serves both the SFX and music libraries.

from renpy.store import persistent
import renpy.python as _renpy_python

from cue_lib.constants import CUE_MUSIC_GAME_TAG, CUE_MUSIC_USER_TAG
from cue_lib.util import _cue_is_abs_path, _cue_unwrap_persistent

# Maximum entries in a "Recently Used" list.
CUE_RECENT_MAX_ENTRIES = 8

MYPY = False
if MYPY:
    from typing import Callable
    from cue_lib.audio.tree.music_tree import CueMusicTree


class CueRecentManager(_renpy_python.NoRollback):
    """Most-recent-first persistent list of heterogeneous used entries.

    Both the entries and the expand-state (toggle) are persisted, under
    <key> and <key>_expanded.  The list opens only when the user toggles it;
    recording a use or loading persisted entries never auto-expands.  prune
    only collapses a list that has been emptied of valid refs.
    """

    def __init__(self, key, keep):
        # type: (str, Callable[[str, str], bool]) -> None
        self.key = key
        self._expanded_key = key + "_expanded"
        self._keep = keep
        self._entries = []  # type: list
        self.expanded = False

    def load(self):
        """Read persisted entries and expand state, then drop stale refs.

        The keep callable checks existence against current scan state, so load
        must run after the relevant files are populated.  Loading is always a
        hydrate-then-prune; stale refs are removed and an emptied list
        collapses (see prune)."""
        raw = persistent._cue or {}
        value = raw.get(self.key)
        self._entries = _cue_unwrap_persistent(value) if value is not None else []
        self._entries = [e for e in self._entries if isinstance(e, dict) and "type" in e and "ref" in e]
        expanded = raw.get(self._expanded_key)
        if isinstance(expanded, bool):
            self.expanded = expanded
        self.prune()

    def save(self):
        """Write entries and expand state back to persistent."""
        if persistent._cue is None:
            persistent._cue = {}
        persistent._cue[self.key] = list(self._entries)
        persistent._cue[self._expanded_key] = self.expanded

    def record(self, kind, ref):
        # type: (str, str) -> None
        """Mark an attempt to use (kind, ref): move to front, cap."""
        for i, e in enumerate(self._entries):
            if e["type"] == kind and e["ref"] == ref:
                del self._entries[i]
                break
        self._entries.insert(0, {"type": kind, "ref": ref})
        del self._entries[CUE_RECENT_MAX_ENTRIES:]
        self.save()

    def entries(self):
        # type: () -> list
        return list(self._entries)

    def has_entries(self):
        return bool(self._entries)

    def toggle(self):
        self.expanded = not self.expanded
        self.save()

    def prune(self):
        """Drop entries whose ref no longer exists; collapse when empty."""
        self._entries = [e for e in self._entries if self._keep(e["type"], e["ref"])]
        del self._entries[CUE_RECENT_MAX_ENTRIES:]
        if not self._entries:
            self.expanded = False
        self.save()


def _cue_keep_sfx(kind, ref, sfx_files, preset_names):
    # type: (str, str, list, list) -> bool
    """Existence check for SFX-library refs: files are exact members, folders
    are prefixes of at least one file, presets are preset names.  Unknown
    kinds are never kept."""
    if kind == "file":
        return ref in sfx_files
    if kind == "folder":
        return any(f.startswith(ref) for f in sfx_files)
    if kind == "preset":
        return ref in preset_names
    return False


def _cue_music_ref_tag(ref):
    # type: (str) -> tuple
    """Split a stored music ref into (tag, path); tag is None if untagged.

    Mirrors CueMusicManager._split_ref_tag so recent.py can stay independent
    of the music manager.  External refs are bare absolute paths (no tag);
    the caller detects them via _cue_is_abs_path."""
    for tag in (CUE_MUSIC_USER_TAG, CUE_MUSIC_GAME_TAG):
        if ref.startswith(tag):
            return tag, ref[len(tag) :]
    return None, ref


def _cue_keep_music(kind, ref, library):
    # type: (str, str, CueMusicTree) -> bool
    """Existence check for music refs: files are exact members of the tagged
    source's files, folders are prefixes of at least one file there.  An
    untagged legacy ref matches either source, and an external (bare absolute)
    ref matches the external source.  Unknown kinds are never kept."""
    tag, path = _cue_music_ref_tag(ref)
    if tag == CUE_MUSIC_USER_TAG:
        files = library.user_files
    elif tag == CUE_MUSIC_GAME_TAG:
        files = library.game_files
    elif _cue_is_abs_path(path):
        files = library.external_files
    else:
        files = library.user_files + library.game_files
    if kind == "file":
        return path in files
    if kind == "folder":
        return any(f.startswith(path) for f in files)
    return False
