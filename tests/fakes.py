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
