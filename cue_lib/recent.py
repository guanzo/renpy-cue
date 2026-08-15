# -*- coding: utf-8 -*-
# CueRecentManager -- most-recently-used pool items (files, folders, presets).
#
# Installed once at _cue.recent, lives on the NoRollback _cue object.  When
# the user adds a file, folder, or preset to a marker pool in the SFX/video
# editors, the context methods call touch(kind, value) so the last few used
# items are remembered across restarts (per-game, on persistent).  There is
# no UI yet -- the list is written now so a future "recently used" list can
# render and re-add from it unchanged.

from renpy.store import persistent

from cue_lib.constants import CUE_RECENT_MAX
from cue_lib.util import _cue_unwrap_persistent


class CueRecentManager(object):
    """Tracks the pool items the user most recently added, most-recent first.

    Persisted per-game on ``persistent._cue_recent_pool_items`` as a list of
    ``{"kind": ..., "value": ...}`` dicts, capped at CUE_RECENT_MAX.
    """

    _PERSISTENT_KEY = "_cue_recent_pool_items"

    def __init__(self):
        self._items = []

    def load(self):
        # type: () -> None
        """Hydrate from persistent (called once at init, after wiring)."""
        raw = getattr(persistent, self._PERSISTENT_KEY, None)
        self._items = _cue_unwrap_persistent(raw) if raw else []

    def touch(self, kind, value):
        # type: (str, str) -> None
        """Record a used item, deduped and moved to the front, capped at 10."""
        if not value:
            return
        self._items = [
            entry for entry in self._items
            if not (entry.get("kind") == kind and entry.get("value") == value)
        ]
        self._items.insert(0, {"kind": kind, "value": value})
        if len(self._items) > CUE_RECENT_MAX:
            self._items = self._items[:CUE_RECENT_MAX]
        self._save()

    def items(self):
        # type: () -> list
        """Return the recent items, most-recent first."""
        return list(self._items)

    def _save(self):
        setattr(persistent, self._PERSISTENT_KEY, list(self._items))
