# -*- coding: utf-8 -*-
import os
import time
from typing import Optional

# Shared test doubles for cue_lib managers.
#
# The marker context classes receive their data manager through the
# constructor and only call a narrow, dict-like surface on it (get / pop /
# __delitem__ / _db_save_marker).  FakeManager provides that surface in
# isolation, so context logic can be tested headlessly without the real
# CueMarkerManager (which is wired to _cue and Ren'Py).

class FakeCtx(object):
    """Minimal _ctx stand-in carrying the seam the video context reads:
    current_file (for the real _key / add_folder guard)."""

    def __init__(self, current_file=None):
        self.current_file = current_file


class FakeManager(object):
    """Dict-like stand-in for CueMarkerManager's data-facing surface.

    Also exposes the narrow mutator surface the video context's per-pool edit
    primitives call (_get_or_create_entry / _detach_pool /
    _detach_folder_ref_in_files) plus the sfx/vid seams _add_file_to_pool and
    add_file dereference, so context logic runs headlessly without the real
    manager (which is wired to _cue and Ren'Py)."""

    def __init__(self, data=None, current_file=None):
        # type: (Optional[dict], Optional[str]) -> None
        self._data = data if data is not None else {}
        self.saved_keys = []
        self._img_target = 0
        self._dlg_target = 0
        self._loop_target = 0
        self._ctx = FakeCtx(current_file)
        self._sfx_manager = FakeSfxManager()
        self._vid_manager = FakeVidManager()
        self._presets = {}   # type: dict

    def get(self, key, default=None):
        return self._data.get(key, default)

    def pop(self, key, default=None):
        return self._data.pop(key, default)

    def __delitem__(self, key):
        del self._data[key]

    def _db_save_marker(self, key):
        self.saved_keys.append(key)

    def _get_or_create_entry(self, trigger_key):
        entry = self._data.get(trigger_key)
        if entry is None:
            entry = {"pools": []}
            self._data[trigger_key] = entry
        return entry

    def _detach_pool(self, trigger_key, pool_index):
        entry = self._data.get(trigger_key)
        if entry is None:
            return False
        pools = entry.get("pools")
        if not pools or pool_index >= len(pools):
            return False
        pool = pools[pool_index]
        if "preset" not in pool:
            return False
        preset_name = pool.pop("preset")
        preset = self._presets.get(preset_name, {})
        pool["files"] = list(preset.get("files", []))
        pool["volume"] = preset.get("volume", 1.0)
        return True

    def _detach_folder_ref_in_files(self, files, file_index, child_file):
        folder_ref = files[file_index]
        if not folder_ref.endswith("/"):
            return
        resolved = []
        for f in self._sfx_manager.files:
            if f.startswith(folder_ref) and f not in self._sfx_manager.disabled_files and f not in resolved:
                resolved.append(f)
        if child_file in resolved:
            resolved.remove(child_file)
        files[file_index:file_index + 1] = resolved

    def resolve_pool(self, pool):
        # type: (dict) -> FakeResolvedPool
        defaults = self._presets.get(pool["preset"], {}) if "preset" in pool else {}
        files = pool.get("files", defaults.get("files", []))
        volume = pool.get("volume", defaults.get("volume", 1.0))
        return FakeResolvedPool(files=list(files), volume=volume)


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
    """Stand-in for CueVideoContext: carries target_pool.
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


# ---------------------------------------------------------------------------
# ffmpeg / video-editor doubles
# ---------------------------------------------------------------------------

class FakeProc(object):
    """Fake subprocess.Popen return value for ffmpeg/ffprobe tests.

    communicate() returns out_bytes (decoded downstream); returncode is
    settable; poll() returns poll_result (None = still running, an int =
    exited). kill()/wait() record their calls so _kill_proc paths can assert.
    timeout_error simulates a hung process: communicate() blocks until
    kill() is called -- mirrors a real process unblocking on SIGKILL, so the
    _cue_run_proc hang guard can reap it.
    """

    def __init__(self, out_bytes=b"", returncode=0, poll_result=None,
                 timeout_error=False):
        self.out_bytes = out_bytes
        self.returncode = returncode
        self.poll_result = poll_result
        self.pid = 1234
        self.killed = False
        self.waited = False
        self.timeout_error = timeout_error
        self.stdout = None
        self.stderr = None

    def communicate(self):
        if self.timeout_error:
            while not self.killed:
                time.sleep(0.002)
        return self.out_bytes, None

    def poll(self):
        return self.poll_result

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self):
        self.waited = True
        return self.returncode


class FakeThread(object):
    """Captures a threading.Thread target without running it.  start() just
    records; the probe/swap worker bodies never execute in tests."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs if kwargs is not None else {}
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True


class FakeFFmpeg(object):
    """FFmpeg-backend stand-in for the video editor: the flag + method surface
    check_prerequisites / refresh / _warm_tools dereference."""

    def __init__(self, available=True, ffprobe_ok=True, has_audio=True, cache=-1):
        self._ffmpeg_cache = cache
        self.available = available
        self.ffprobe_ok = ffprobe_ok
        self.has_audio = has_audio

    def ffmpeg_available(self):
        self._ffmpeg_cache = 1 if self.available else 0
        return self.available

    def ffprobe_available(self):
        return self.ffprobe_ok

    def load_encoders(self):
        pass

    def probe_has_audio(self, fspath):
        return self.has_audio


class FakeVidPathManager(object):
    """Video-manager stand-in for the editor's current-video surface:
    get_video_path() + the channel seam the queue's _start_next reads."""

    def __init__(self, vpath="", channel="cue_vid"):
        self._vpath = vpath
        self.channel = channel

    def get_video_path(self):
        return self._vpath


class FakePathsVideo(object):
    """Paths stand-in for the editor/queue: in_game_base_dir + video_dir."""

    def __init__(self, video_dir):
        self.video_dir = video_dir
        self.in_game_base_dir = "renpy_cue"


class FakeVidSpeedResolver(object):
    """Speed-resolver stand-in for the editor's create() path: base_path_for /
    variant_path / _split_ext, driven by a configured base tag."""

    def __init__(self, base=None):
        self.base = base

    def base_path_for(self, tag):
        return self.base

    def variant_path(self, base_path, speed):
        _b, _e = os.path.splitext(base_path)
        return _b + "__cue_{:.1f}x{}".format(speed, _e)

    def _split_ext(self, path):
        return os.path.splitext(path)
