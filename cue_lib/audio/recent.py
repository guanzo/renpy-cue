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

from cue_lib.constants import CUE_RECENT_MAX_ENTRIES
from cue_lib.util import _cue_unwrap_persistent

MYPY = False
if MYPY:
    from typing import Callable


class CueRecentManager(object):
    """Most-recent-first persistent list of heterogeneous used entries.

    expand-state (toggle / on_search_clear) is session-local -- only the
    entries are persisted.  expanded defaults to True whenever the list has
    entries, so a non-empty list shows open until the user collapses it.
    """

    def __init__(self, key, keep):
        # type: (str, Callable[[str, str], bool]) -> None
        self.key = key
        self._keep = keep
        self._entries = []   # type: list
        self.expanded = False

    def load(self):
        """Read persisted entries; expanded defaults to having entries."""
        raw = persistent._cue or {}
        value = raw.get(self.key)
        self._entries = _cue_unwrap_persistent(value) if value is not None else []
        self._entries = [e for e in self._entries
                         if isinstance(e, dict) and "type" in e and "ref" in e]
        self.expanded = bool(self._entries)

    def save(self):
        """Write entries back to persistent (used after record and prune)."""
        if persistent._cue is None:
            persistent._cue = {}
        persistent._cue[self.key] = list(self._entries)

    def record(self, kind, ref):
        # type: (str, str) -> None
        """Mark an attempt to use (kind, ref): move to front, cap, expand."""
        for i, e in enumerate(self._entries):
            if e["type"] == kind and e["ref"] == ref:
                del self._entries[i]
                break
        self._entries.insert(0, {"type": kind, "ref": ref})
        del self._entries[CUE_RECENT_MAX_ENTRIES:]
        self.expanded = True
        self.save()

    def entries(self):
        # type: () -> list
        return list(self._entries)

    def has_entries(self):
        return bool(self._entries)

    def toggle(self):
        self.expanded = not self.expanded

    def on_search_clear(self):
        self.expanded = True

    def prune(self):
        """Drop entries whose ref no longer exists; collapse when empty."""
        self._entries = [e for e in self._entries
                         if self._keep(e["type"], e["ref"])]
        del self._entries[CUE_RECENT_MAX_ENTRIES:]
        self.expanded = bool(self._entries)
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
