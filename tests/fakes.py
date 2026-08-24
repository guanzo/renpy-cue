# -*- coding: utf-8 -*-
import os
import time
import types
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
        self._ctx = FakeCtx(current_file)
        self._sfx_manager = FakeSfxManager()
        self._vid_manager = FakeVidManager()
        self._presets = {}  # type: dict
        self.added_files = []  # type: list
        self.stamped_presets = []  # type: list

    def get(self, key, default=None):
        return self._data.get(key, default)

    def pop(self, key, default=None):
        return self._data.pop(key, default)

    def __delitem__(self, key):
        del self._data[key]

    def _db_save_marker(self, key):
        self.saved_keys.append(key)

    def _get_or_create_entry(self, marker_key):
        entry = self._data.get(marker_key)
        if entry is None:
            entry = {"pools": []}
            self._data[marker_key] = entry
        return entry

    def _add_file_to_pool(self, key, filename, pool_index):
        self.added_files.append((key, filename, pool_index))

    def _ensure_pool(self, key, pool_index):
        entry = self._get_or_create_entry(key)
        while len(entry["pools"]) <= pool_index:
            entry["pools"].append({"files": []})
        return entry["pools"][pool_index]

    def _stamp_preset(self, key, preset_name, pool_index):
        self.stamped_presets.append((key, preset_name, pool_index))

    def _detach_pool(self, marker_key, pool_index):
        entry = self._data.get(marker_key)
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
        files[file_index : file_index + 1] = resolved

    def resolve_pool(self, pool):
        # type: (dict) -> FakeResolvedPool
        defaults = self._presets.get(pool["preset"], {}) if "preset" in pool else {}
        files = pool.get("files", defaults.get("files", []))
        volume = pool.get("volume", defaults.get("volume", 1.0))
        trigger_on_shake = pool.get("trigger_on_shake", defaults.get("trigger_on_shake", False))
        return FakeResolvedPool(files=list(files), volume=volume, trigger_on_shake=trigger_on_shake)


class FakeDb(object):
    """Shared-config db stand-in for managers that persist via the db.

    Mirrors the real CueDatabase's shared-config surface only: keybinds and
    music read it via load_shared_config(); writes are recorded in `saved`
    (list of the dicts passed to update_shared_config).
    """

    def __init__(self):
        self.shared = {}  # type: dict
        self.saved = []  # type: list

    def load_shared_config(self):
        return self.shared

    def update_shared_config(self, data):
        self.saved.append(data)

    def save_shared_config(self, data):
        self.shared = data
        self.saved.append(data)


class FakeRecent(object):
    """Recent-manager stand-in: records record() calls as (kind, ref) tuples."""

    def __init__(self):
        self.calls = []

    def record(self, kind, ref):
        self.calls.append((kind, ref))


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
    frequency CueLoopFrequency.MEDIUM, exclusive a default FakeExclusive."""

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
                start=excl.get("start", 0), hold=excl.get("hold", False), group=excl.get("group", 0)
            ),
        )


class FakeVideoContext(object):
    """Stand-in for CueVideoContext: carries active_pool, the get_markers()
    list (_tick_video), and the repeater's selection / drag seams."""

    def __init__(self, active_pool=0, markers=None, selected=None):
        self.active_pool = active_pool
        self.markers = markers if markers is not None else []
        self.selected = selected if selected is not None else set()
        self.drag_calls = 0

    def get_markers(self):
        return self.markers

    def get_selected(self):
        return self.selected

    def finalize_drag(self):
        self.drag_calls += 1


class FakeLoopContext(object):
    """Stand-in for the loop context's get_delay(frequency) seam."""

    def __init__(self, delay=2.1):
        self.delay = delay

    def get_delay(self, frequency):
        return self.delay


class FakeMarkers(object):
    """Coordinator stand-in exposing the `video` and `loop` seams the trigger
    engine and volume manager dereference (markers.video.active_pool /
    markers.video.get_markers / markers.loop.get_delay).  All attributes are
    mutable so tests drive the seams directly."""

    def __init__(self, active_pool=0, markers=None, loop_delay=2.1):
        self.video = FakeVideoContext(active_pool, markers)
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
    (multiplier on marker reference time, 1.0 = unsped).  banding_speeds returns
    the configured variant set (None = no intensity)."""

    def __init__(self, speed=1.0, variants=None):
        self.speed = speed
        self.variants = variants

    def get_current_speed(self):
        return self.speed

    def banding_speeds(self, tag):
        return self.variants

    def invalidate_speed_cache(self):
        pass


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
    reads: the library.files list + library.disabled_files set.

    The real CueSfxManager owns a CueSfxLibraryTree as ``library``, so
    consumers read sfx_manager.library.files.  Tests keep writing
    mgr._sfx_manager.files / .disabled_files / ._recent directly -- those
    forward to the nested library, as do scan_calls / rebuild_calls."""

    def __init__(self, files=None, disabled_files=None):
        self.library = types.SimpleNamespace(
            files=files if files is not None else [],
            disabled_files=disabled_files if disabled_files is not None else set(),
            _recent=None,  # type: Optional[FakeRecent]  # set by recording tests
            scan_calls=0,
            rebuild_calls=0,
        )
        self.library.scan = self._scan
        self.library.maybe_rebuild = self._maybe_rebuild

    def _scan(self):
        self.library.scan_calls += 1

    def _maybe_rebuild(self):
        self.library.rebuild_calls += 1

    def warm_cache(self):
        """No-op: the real manager pre-generates 24->16 cache on a thread."""
        pass

    @property
    def files(self):
        return self.library.files

    @files.setter
    def files(self, value):
        self.library.files = value

    @property
    def disabled_files(self):
        return self.library.disabled_files

    @disabled_files.setter
    def disabled_files(self, value):
        self.library.disabled_files = value

    @property
    def _recent(self):
        return self.library._recent

    @_recent.setter
    def _recent(self, value):
        self.library._recent = value

    @property
    def scan_calls(self):
        return self.library.scan_calls

    @property
    def rebuild_calls(self):
        return self.library.rebuild_calls


class FakeTrigger(object):
    """Trigger-engine stand-in for the loop_states dict loop clear() pops."""

    def __init__(self, loop_states=None):
        self.loop_states = loop_states if loop_states is not None else {}
        self.active = True


class FakeVideoEditor(object):
    """Video-editor stand-in for the scalar fan-out: MODE_INTERPOLATE +
    encode_mode/remove_audio attributes, refresh() no-op."""

    MODE_INTERPOLATE = 0

    def __init__(self, encode_mode=MODE_INTERPOLATE, remove_audio=True):
        self.encode_mode = encode_mode
        self.remove_audio = remove_audio
        self.refresh_calls = 0

    def refresh(self):
        self.refresh_calls += 1


class FakeUndo(object):
    """Undo-manager stand-in for _apply_restore's reset() call."""

    def __init__(self):
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1


# ---------------------------------------------------------------------------
# runtime / audio driver cue-graph
# ---------------------------------------------------------------------------


def make_runtime_cue(root="", audio_dir=""):
    """Full _cue stand-in for runtime.py and audio-driver tests.

    A real Cue() instance supplies ctx plus the current_file/current_dialogue/
    prev_dialogue/top_layer_type read-through properties; every manager slot
    is a recording stand-in.  Call side effects land in ``cue.calls`` as
    {"manager.method": [(args, kwargs), ...]}.  Stateful managers carry the
    attributes the drivers read (sfx files, trigger loop_states, vid channel)
    so tests can drive branches directly.
    """
    from cue_lib.state import Cue
    from cue_lib.settings import CueSettings

    cue = Cue()
    cue.paths = types.SimpleNamespace(root=root, original_root=root, audio_dir=audio_dir)
    cue.settings = CueSettings()
    cue.calls = {}
    cue.ensured_pools = []

    def _rec(manager, name):
        def _record(*args, **kwargs):
            cue.calls.setdefault(manager + "." + name, []).append((args, kwargs))

        return _record

    def _ns(manager, methods):
        ns = types.SimpleNamespace()
        for m in methods:
            setattr(ns, m, _rec(manager, m))
        return ns

    # markers -- get/ensure_pool/resolve_pool carry state and returns
    def _ensure_pool(key, target):
        pool = {"time": 0.0, "files": []}
        cue.ensured_pools.append(pool)
        cue.calls.setdefault("markers._ensure_pool", []).append(((key, target), {}))
        return pool

    cue.markers = types.SimpleNamespace(
        image=types.SimpleNamespace(active_pool=0),
        get=_rec("markers", "get"),
        save_marker=_rec("markers", "save_marker"),
        get_preset=_rec("markers", "get_preset"),
        get_video_preset=_rec("markers", "get_video_preset"),
        reload_presets=_rec("markers", "reload_presets"),
        load_persistent=_rec("markers", "load_persistent"),
        _ensure_pool=_ensure_pool,
        resolve_pool=lambda pool: types.SimpleNamespace(trigger_on_shake=False),
    )

    # trigger -- mutable state the context/tick drivers read and reset
    cue.trigger = types.SimpleNamespace(
        active=True,
        loop_states={},
        played_video_keys=set(),
        last_played=[],
        _prev_eff_elapsed=-1.0,
        fire_context=_rec("trigger", "fire_context"),
        tick=_rec("trigger", "tick"),
    )

    # vid_manager -- channel + flags + driver methods.  reset() mirrors the
    # real CueVideoManager.reset: it records AND adopts the channel (runtime's
    # _apply_channel relies on reset to update _cue.vid_manager.channel).
    def _reset_vid(channel=None):
        cue.calls.setdefault("vid_manager.reset", []).append(((channel,), {}))
        cue.vid_manager.channel = channel

    cue.vid_manager = types.SimpleNamespace(
        channel=None,
        refreshing=False,
        get_video_path=lambda: None,
        reset=_reset_vid,
        set_fps=_rec("vid_manager", "set_fps"),
        sync_paused=_rec("vid_manager", "sync_paused"),
        poll_autopause=_rec("vid_manager", "poll_autopause"),
    )

    # sfx_manager -- library subtree holds the tree state (_cue_resolve_files
    # reads library.files/disabled_files; _cue_full_reload drives library
    # scan/_recent/maybe_rebuild), the manager itself the playback channel
    # state.  Rec keys stay "sfx_manager.X" so call assertions don't change.
    cue.sfx = types.SimpleNamespace(
        _next_sfx_channel=0,
        _preview_channel=None,
        warm_cache=lambda: None,
        library=types.SimpleNamespace(
            files=[],
            disabled_files=set(),
            _recent=types.SimpleNamespace(load=_rec("sfx_manager._recent", "load")),
            scan=_rec("sfx_manager", "scan"),
            rebuild_tree=_rec("sfx_manager", "rebuild_tree"),
            maybe_rebuild=_rec("sfx_manager", "maybe_rebuild"),
        ),
    )

    # music -- user_music/game_music subtrees + driver methods
    cue.music = types.SimpleNamespace(
        user_music=types.SimpleNamespace(
            files=[], scan=_rec("music.user_music", "scan"), maybe_rebuild=_rec("music.user_music", "maybe_rebuild")
        ),
        game_music=types.SimpleNamespace(
            scan=_rec("music.game_music", "scan"), maybe_rebuild=_rec("music.game_music", "maybe_rebuild")
        ),
        _recent=types.SimpleNamespace(load=_rec("music._recent", "load")),
        capture_display=_rec("music", "capture_display"),
        play_custom_music=_rec("music", "play_custom_music"),
        play_untracked=_rec("music", "play_untracked"),
        reload_presets=_rec("music", "reload_presets"),
        _resolve_music_path=lambda filename: filename,
        library=types.SimpleNamespace(
            rebuild_tree=_rec("music.library", "rebuild_tree"), maybe_rebuild=_rec("music.library", "maybe_rebuild")
        ),
    )

    # video_editor -- job_queue.has_pending gates job_queue.poll
    cue.video_editor = types.SimpleNamespace(
        MODE_INTERPOLATE=0,
        processing=False,
        job_queue=types.SimpleNamespace(has_pending=False, poll=_rec("video_editor.job_queue", "poll")),
        refresh=_rec("video_editor", "refresh"),
        poll_extract=_rec("video_editor", "poll_extract"),
    )

    # undo -- _cue_full_reload re-seeds the undo baseline on every reload
    cue.undo = types.SimpleNamespace(reset=_rec("undo", "reset"))

    # db -- shared-config surface read/written by _cue_load_scalars_from_persistent
    cue.db = types.SimpleNamespace(load_shared_config=lambda: {}, save_shared_config=_rec("db", "save_shared_config"))

    cue.volume = types.SimpleNamespace(
        get_effective=lambda entry, key, pool_index: 1.0, flush_pending_saves=_rec("volume", "flush_pending_saves")
    )
    cue.video_sequence = types.SimpleNamespace(
        handle=_rec("video_sequence", "handle"), tick=_rec("video_sequence", "tick")
    )
    cue.speed_resolver = types.SimpleNamespace(
        clear_pending=_rec("speed_resolver", "clear_pending"),
        base_path_for=lambda current_file: None,
        is_variant_of=lambda path, target: False,
    )
    cue.importer = _ns("importer", ["scan"])
    cue.exporter = _ns("exporter", ["refresh"])

    return cue


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

    def __init__(self, out_bytes=b"", returncode=0, poll_result=None, timeout_error=False):
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

    def invalidate_speed_cache(self):
        pass

    def variant_path(self, base_path, speed):
        _b, _e = os.path.splitext(base_path)
        return _b + "__cue_{:.1f}x{}".format(speed, _e)

    def _split_ext(self, path):
        return os.path.splitext(path)
