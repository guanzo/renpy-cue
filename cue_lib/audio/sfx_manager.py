# -*- coding: utf-8 -*-
# CueSfxManager -- SFX playback (shared _cue_ channels) plus the SFX library
# orchestration around it.  The library tree (audio scan, folder/preset tree
# UI state, disabled files) lives in CueSfxLibraryTree, owned here as
# ``library`` -- mirroring how CueMusicManager owns its CueMusicTree.
# Collaborators (paths/db/volume/ctx/presets) are constructor-injected; markers
# is late-bound via bind_markers (construction cycle with CueMarkerManager).
# Instantiated once at _cue.sfx, lives on the NoRollback _cue object.

import random as _random
import threading

import renpy.audio.music as _music

from cue_lib.audio.tree.sfx_tree import CueSfxLibraryTree
from cue_lib.audio.wav_playable import CueWavPlayable
from cue_lib.constants import CUE_SFX_CHANNEL_COUNT
from cue_lib.preset_store import CuePresetStore
from cue_lib.util import (
    _cue_log,
    _cue_resolve_files,
    _cue_pick_file,
    is_vid_key,
    is_img_key,
    is_dlg_key,
    get_key_file,
    get_key_dialogue,
    create_dlg_key,
)

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import MarkerEntry, PoolDict  # pyright: ignore[reportUnusedImport]
    from cue_lib.db import CueDatabase  # pyright: ignore[reportUnusedImport]
    from cue_lib.intensity.intensity import CueIntensityManager  # pyright: ignore[reportUnusedImport]
    from cue_lib.markers import CueMarkerManager  # pyright: ignore[reportUnusedImport]
    from cue_lib.paths import CuePaths  # pyright: ignore[reportUnusedImport]
    from cue_lib.state import CueContext  # pyright: ignore[reportUnusedImport]
    from cue_lib.volume import CueVolumeManager  # pyright: ignore[reportUnusedImport]


# Quick cross-fade duration for exclusive cut-in sweeps.
CUE_EXCLUSIVE_FADE = 0.1


def _cue_sfx_channel_name(index):
    # type: (int) -> str
    """Channel name for a 1-based index into the shared _cue_ SFX channels."""
    return "_cue_{}".format(index)


def _cue_sfx_channel_index(ch_name):
    # type: (str) -> int
    """Reverse of _cue_sfx_channel_name: parse the 1-based index from a
    shared _cue_ SFX channel name."""
    return int(ch_name.split("_")[-1])


class CueSfxManager(object):
    """SFX playback + library orchestration.

    Owns the SFX library tree (CueSfxLibraryTree) and the playback state
    and methods that drive the shared _cue_ channels.  Playback methods are
    callable via Function() from screen actions; trigger.py calls play_pool
    / fade_out for exclusive cut-ins."""

    def __init__(self, paths, db, volume, ctx, supports_relative_volume, presets):
        # type: (CuePaths, CueDatabase, CueVolumeManager, CueContext, bool, CuePresetStore) -> None
        self.library = CueSfxLibraryTree(paths, db)
        self.library._sfx = self  # pyright: ignore[reportAttributeAccessIssue]
        self._paths = paths
        self._db = db
        self._volume = volume
        self._ctx = ctx
        self._supports_relative_volume = supports_relative_volume
        self._presets = presets
        self._markers = None  # type: Optional[CueMarkerManager]
        self._wav_playable = CueWavPlayable()

        # SFX playback state
        self._next_sfx_channel = 0  # round-robin fallback when all channels are busy
        self._preview_channel = None  # channel currently playing a preview
        self._warm_thread = None  # background wide->16 cache warm, if running

    def bind_markers(self, markers):
        # type: (CueMarkerManager) -> None
        """Late-bind markers -- CueMarkerManager takes sfx_manager (its
        library) at construction, so this breaks the two-way construction
        cycle.  Called by cue_z.rpy once markers exists; playback methods
        read it at call time."""
        self._markers = markers

    def _markers_ctx(self):
        # type: () -> CueMarkerManager
        """The bound marker manager.  Always set by the time playback runs
        (cue_z.rpy calls bind_markers at init); a missing bind is a wiring
        bug, so fail loudly rather than skip playback silently."""
        if self._markers is None:
            raise RuntimeError("CueSfxManager markers not bound (bind_markers never called)")
        return self._markers

    def warm_cache(self):
        # type: () -> None
        """Pre-generate 16-bit copies for discovered SFX on a background thread.

        Used so the first play of a 24-bit file doesn't convert on the UI thread.
        The converter makes no Ren'Py API calls, so a daemon thread is safe.  A
        no-op while a warm is already running (an overlay reload would otherwise
        spawn one each time).  Logs the pass duration (WARM-SFX) via wav_playable.

        Only files never seen before are probed; the rest are a dict hit from the
        persisted index, so a repeat launch warm fast."""
        if self._warm_thread is not None and self._warm_thread.is_alive():
            return
        # library.files holds refs (built-in audio-relative + bare absolute
        # external); the converter needs absolute paths, so resolve here with an
        # empty dir.
        abs_paths = [self.library.resolve_path(r) for r in list(self.library.files)]
        wav_playable = self._wav_playable

        def _run():
            try:
                wav_playable.warm(abs_paths, "")
            finally:
                # Release the finished thread so it (and the abs_paths list it
                # closes over) is not pinned for the session.
                self._warm_thread = None

        self._warm_thread = threading.Thread(target=_run)
        self._warm_thread.daemon = True
        self._warm_thread.start()

    def unplayable_files(self):
        # type: () -> Dict[str, str]
        """{path: reason} for WAVs SDL_mixer can't play, for a warning glyph in
        the SFX Library.  Keys are audio_dir-prefixed full paths."""
        return self._wav_playable.unplayable()

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play_pool(
        self,
        entry,
        key,
        pool,
        pool_index,
        file=None,
        avoid_repeats=True,
        volume_mult=None,
        marker_time=None,
        marker_elapsed=None,
        marker_err=None,
        marker_gap=None,
        marker_gap_expected=None,
    ):
        # type: (Optional[MarkerEntry], str, PoolDict, int, Optional[str], bool, Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]) -> Optional[str]
        """Play one sound from a pool.  The single fire choke point for all
        trigger paths.

        The trigger engine hands in a single concrete ``file``; when it is
        None (direct callers, UI previews) the pool's own files are expanded
        and picked.  ``volume_mult`` multiplies the pool's effective volume
        (intensity level scale)."""
        resolved = self._markers_ctx().resolve_pool(pool, expand=True)
        f = file
        if f is None:
            files = resolved.files
            if not files:
                return None
            f = _cue_pick_file(files, avoid_repeats=avoid_repeats)  # type: Any
        vol = self._volume.get_effective(entry, key, pool_index=pool_index)
        if volume_mult is not None:
            vol = vol * volume_mult
        return self.play_sfx(
            f,
            key,
            volume=vol,
            marker_time=marker_time,
            marker_elapsed=marker_elapsed,
            marker_err=marker_err,
            marker_gap=marker_gap,
            marker_gap_expected=marker_gap_expected,
        )

    def play_sfx(
        self,
        filename,
        source="",
        volume=1.0,
        marker_time=None,
        marker_elapsed=None,
        marker_err=None,
        marker_gap=None,
        marker_gap_expected=None,
    ):
        # type: (str, str, float, Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]) -> Optional[str]

        # Apply +-10% volume jitter for natural variation
        MAX_JITTER = 0.1
        jitter = _random.uniform(1.0 - MAX_JITTER, 1.0 + MAX_JITTER)
        volume = volume * jitter

        full_path = self._wav_playable.ensure_playable(self.library.resolve_path(filename))

        target_ch = None
        for i in range(1, CUE_SFX_CHANNEL_COUNT + 1):
            ch_name = _cue_sfx_channel_name(i)
            if not _music.is_playing(channel=ch_name):
                target_ch = ch_name
                break

        if target_ch is None:
            idx = self._next_sfx_channel
            target_ch = _cue_sfx_channel_name(idx + 1)
            self._next_sfx_channel = (idx + 1) % CUE_SFX_CHANNEL_COUNT
        else:
            ch_num = _cue_sfx_channel_index(target_ch)
            self._next_sfx_channel = ch_num % CUE_SFX_CHANNEL_COUNT

        try:
            curr_file = self._ctx.current_file
            warn = None
            if is_vid_key(source):
                expected_vid = get_key_file(source)
                if expected_vid and curr_file and expected_vid != curr_file:
                    warn = "expected vid={} actual vid={}".format(expected_vid, curr_file)
            elif is_img_key(source):
                expected_img = get_key_file(source)
                if expected_img and curr_file and expected_img != curr_file:
                    warn = "expected img={} actual img={}".format(expected_img, curr_file)
            elif is_dlg_key(source):
                expected_img = get_key_file(source)
                expected_dlg = get_key_dialogue(source)
                cur_dlg = self._ctx.current_dialogue
                if expected_img != curr_file or expected_dlg != cur_dlg:
                    warn = "expected_dlg={} actual_dlg={}".format(
                        create_dlg_key((expected_img, expected_dlg)), create_dlg_key((curr_file, cur_dlg))
                    )
            if warn:
                _cue_log("WARN CTX-MISMATCH file={} src={} {}".format(filename.rsplit("/", 1)[-1], source, warn))

            if self._supports_relative_volume:
                _music.play(full_path, channel=target_ch, loop=False, relative_volume=volume)
            else:
                _music.play(full_path, channel=target_ch, loop=False)
                _music.set_volume(volume, delay=0, channel=target_ch)

            log = "PLAY-SFX file={} ch={}".format(filename.rsplit("/", 1)[-1], target_ch)
            if marker_time is not None:
                # Trigger accuracy: err is the reference-time fire error (signed,
                # positive = fired late).  gap is the reference-time spacing to
                # the previous fire -- near 0 on a double-fire.  Each carries a
                # %-of-expected: err% = err vs the marker time; gap% = gap vs the
                # marker-time spacing (marker_gap_expected).
                log += " mt={:.3f} err={:+.3f}".format(marker_time, marker_err)
                if marker_err is not None and marker_time != 0:
                    log += " ({:+.1f}%)".format(marker_err / marker_time * 100.0)
                if marker_gap is not None:
                    log += " gap={:.3f}".format(marker_gap)
                    if marker_gap_expected is not None and marker_gap_expected != 0:
                        log += " ({:+.1f}%)".format((marker_gap - marker_gap_expected) / marker_gap_expected * 100.0)
            if marker_elapsed is not None:
                log += " elapsed={:.3f}".format(marker_elapsed)
            log += " src={}".format(source)
            _cue_log(log)

            return target_ch
        except Exception as e:
            _cue_log("PLAY-SFX: exception during playback of {}: {}".format(full_path, e))
            return None

    def preview_sfx(self, filename, volume=1.0):
        # type: (str, float) -> None
        prev_ch = self._preview_channel
        if prev_ch is not None and _music.is_playing(channel=prev_ch):
            _music.stop(channel=prev_ch, fadeout=0)
        self._preview_channel = self.play_sfx(filename, "preview", volume=volume)

    # ------------------------------------------------------------------
    # Library previews
    # ------------------------------------------------------------------

    def preview_preset(self, preset_name):
        # type: (str) -> None
        preset = self._presets.get_preset(preset_name)
        if preset is None:
            return
        files = _cue_resolve_files(preset.get("files", []))
        if files:
            f = _random.choice(files)
            self.preview_sfx(f)

    def preview_folder(self, folder_path, volume=1.0):
        # type: (str, float) -> None
        """Preview a random file from an SFX Library folder."""
        files = _cue_resolve_files([folder_path])
        if files:
            f = _random.choice(files)
            self.preview_sfx(f, volume=volume)

    def preview_level(self, group_name, ilevel_id):
        # type: (str, int) -> None
        """Preview a random file from an intensity level."""
        library = self.library
        if library._intensity is None:
            return
        files = library._intensity.level_files_by_id(group_name, ilevel_id)
        if not files:
            return
        resolved = _cue_resolve_files(files)
        if resolved:
            f = _random.choice(resolved)
            self.preview_sfx(f)

    def preview_video_pool(self, preset_name, pool_index):
        # type: (str, int) -> None
        """Preview a random file from one pool of a video preset."""
        preset = self._presets.get_video_preset(preset_name)
        if preset is None:
            return
        pools = preset.get("pools", [])
        if not (0 <= pool_index < len(pools)):
            return
        resolved = _cue_resolve_files(pools[pool_index].get("files", []))
        if resolved:
            f = _random.choice(resolved)
            self.preview_sfx(f)

    def fade_out(self, exclude_channels=None, only_channels=None):
        # type: (Optional[List[str]], Optional[List[str]]) -> int
        """Quickly fade out SFX on the shared _cue_ channels.

        ``exclude_channels`` are channels to spare -- same-group friends, or
        video-marker SFX (immune to cut-ins).  ``only_channels`` restricts the
        sweep to a single domain (loops fade only loops). Returns the number of
        channels faded."""
        excluded = set(exclude_channels) if exclude_channels else set()
        only = set(only_channels) if only_channels is not None else None
        faded = 0
        for i in range(1, CUE_SFX_CHANNEL_COUNT + 1):
            ch_name = _cue_sfx_channel_name(i)
            if only is not None and ch_name not in only:
                continue
            if ch_name in excluded:
                continue
            if _music.is_playing(channel=ch_name):
                _music.stop(channel=ch_name, fadeout=CUE_EXCLUSIVE_FADE)
                faded += 1
        return faded
