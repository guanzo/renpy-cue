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


class FakeExclusive(object):
    """Resolved exclusive-config stand-in: the start/hold/group attributes
    trigger.py branches on."""

    def __init__(self, start=0, hold=False, group=0):
        self.start = start
        self.hold = hold
        self.group = group


class FakeResolvedPool(object):
    """Resolved-pool stand-in carrying every attribute consumers read:
    volume (volume.py), files/frequency/trigger_on_shake/exclusive (trigger.py).

    resolve_pool defaults mirror the real store: volume 1.0 (identity),
    frequency CueLoopFrequency.NORMAL, exclusive a default FakeExclusive."""

    def __init__(self, files=None, volume=1.0, frequency=1, trigger_on_shake=False, exclusive=None):
        self.files = files if files is not None else []
        self.volume = volume
        self.frequency = frequency
        self.trigger_on_shake = trigger_on_shake
        self.exclusive = exclusive if exclusive is not None else FakeExclusive()


class FakeMarkerStore(object):
    """Data-store stand-in for the entry/pool surface volume.py and trigger.py
    consume.

    Mirrors CueMarkerStore's narrow read/write contract -- get / save_marker /
    resolve_pool -- with plain dict storage, so volume math and trigger
    dispatch can be tested without a real CueDatabase.  resolve_pool builds a
    FakeResolvedPool straight from the pool dict (preset fallback is the real
    store's job; tests drive the resolved values by putting them on the pool).
    """

    def __init__(self, data=None):
        self._data = data if data is not None else {}
        self.saved_keys = []

    def get(self, key, default=None):
        return self._data.get(key, default)

    def save_marker(self, key):
        self.saved_keys.append(key)

    def resolve_pool(self, pool):
        excl = pool.get("exclusive", {})
        if not isinstance(excl, dict):
            excl = {}
        return FakeResolvedPool(
            files=pool.get("files", []),
            volume=pool.get("volume", 1.0),
            frequency=pool.get("frequency", 1),
            trigger_on_shake=pool.get("trigger_on_shake", False),
            exclusive=FakeExclusive(
                start=excl.get("start", 0),
                hold=excl.get("hold", False),
                group=excl.get("group", 0)))


class FakeVideoContext(object):
    """Stand-in for CueVideoContext: carries target_pool (volume.adjust_video)
    and the get_markers() list (_tick_video)."""

    def __init__(self, target_pool=0, markers=None):
        self.target_pool = target_pool
        self.markers = markers if markers is not None else []

    def get_markers(self):
        return self.markers


class FakeLoopContext(object):
    """Stand-in for the loop context's get_delay(frequency) seam."""

    def __init__(self, delay=2.1):
        self.delay = delay

    def get_delay(self, frequency):
        return self.delay


class FakeMarkers(object):
    """Coordinator stand-in exposing the `video` and `loop` seams the trigger
    engine and volume manager dereference (markers.video.target_pool /
    markers.video.get_markers / markers.loop.get_delay).  All attributes are
    mutable so tests drive the seams directly."""

    def __init__(self, target_pool=0, markers=None, loop_delay=2.1):
        self.video = FakeVideoContext(target_pool, markers)
        self.loop = FakeLoopContext(loop_delay)


class FakeRepeater(object):
    """Repeater stand-in for the two flags + preview-pool computation
    _tick_video reads."""

    def __init__(self, dialog_visible=False, preview_sfx_enabled=False, preview_pools=None):
        self.dialog_visible = dialog_visible
        self.preview_sfx_enabled = preview_sfx_enabled
        self.preview_pools = preview_pools if preview_pools is not None else []

    def compute_preview_pools(self):
        return self.preview_pools


class FakeSpeedResolver(object):
    """Speed-resolver stand-in: get_current_speed() returns the configured rate
    (multiplier on marker reference time, 1.0 = unsped)."""

    def __init__(self, speed=1.0):
        self.speed = speed

    def get_current_speed(self):
        return self.speed


class FakeVidManager(object):
    """Video-manager stand-in for the tick surface (channel / get_elapsed /
    last_elapsed) plus the duration seam markers.py reads.  last_elapsed is
    written by the engine each tick."""

    def __init__(self, channel="cue_vid", elapsed=0.0, duration=0.0):
        self.channel = channel
        self._elapsed = elapsed
        self.last_elapsed = 0
        self.duration = duration

    def get_elapsed(self):
        return self._elapsed

    def get_duration(self):
        return self.duration


class FakeSfxManager(object):
    """SFX-library stand-in for the folder-ref expansion surface markers.py
    reads: the files list + disabled_files set."""

    def __init__(self, files=None, disabled_files=None):
        self.files = files if files is not None else []
        self.disabled_files = disabled_files if disabled_files is not None else set()
