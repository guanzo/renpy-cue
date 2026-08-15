# -*- coding: utf-8 -*-
from typing import Optional

# Shared test doubles for cue_lib managers.
#
# The marker context classes receive their data manager through the
# constructor and only call a narrow, dict-like surface on it (get / pop /
# __delitem__ / _db_save_marker).  FakeManager provides that surface in
# isolation, so context logic can be tested headlessly without the real
# CueMarkerManager (which is wired to _cue and Ren'Py).

class FakeManager(object):
    """Dict-like stand-in for CueMarkerManager's data-facing surface."""

    def __init__(self, data=None):
        # type: (Optional[dict]) -> None
        self._data = data if data is not None else {}
        self.saved_keys = []
        self._img_target = 0
        self._dlg_target = 0
        self._loop_target = 0

    def get(self, key, default=None):
        return self._data.get(key, default)

    def pop(self, key, default=None):
        return self._data.pop(key, default)

    def __delitem__(self, key):
        del self._data[key]

    def _db_save_marker(self, key):
        self.saved_keys.append(key)


class FakeDb(object):
    """Shared-config db stand-in for managers that persist via the db.

    Mirrors the real CueDatabase's shared-config surface only: keybinds and
    music read it via load_shared_config(); writes are recorded in `saved`
    (list of the dicts passed to update_shared_config).
    """

    def __init__(self):
        self.shared = {}   # type: dict
        self.saved = []    # type: list

    def load_shared_config(self):
        return self.shared

    def update_shared_config(self, data):
        self.saved.append(data)


class _ResolvedPool(object):
    """Minimal resolved-pool stand-in: only the `.volume` attribute is read by
    volume.py.  The real ResolvedPool also carries files/frequency/exclusive."""

    def __init__(self, volume):
        self.volume = volume


class FakeMarkerStore(object):
    """Data-store stand-in for the entry/pool surface volume.py consumes.

    Mirrors CueMarkerStore's narrow read/write contract -- get / save_marker /
    resolve_pool -- with plain dict storage, so volume math can be tested
    without a real CueDatabase.  resolve_pool echoes the pool's stored volume
    (preset fallback is the real store's job; volume tests only need the
    resolved value to be controllable).
    """

    def __init__(self, data=None):
        self._data = data if data is not None else {}
        self.saved_keys = []

    def get(self, key, default=None):
        return self._data.get(key, default)

    def save_marker(self, key):
        self.saved_keys.append(key)

    def resolve_pool(self, pool):
        return _ResolvedPool(pool.get("volume", 1.0))


class FakeVideoContext(object):
    """Stand-in for CueVideoContext: carries the target_pool attribute that
    adjust_video reads off `markers.video`."""

    def __init__(self, target_pool=0):
        self.target_pool = target_pool


class FakeMarkers(object):
    """Coordinator stand-in exposing the `video` seam adjust_video reads.
    Holds no data logic itself -- only the attribute path the volume manager
    dereferences (markers.video.target_pool)."""

    def __init__(self, target_pool=0):
        self.video = FakeVideoContext(target_pool)
