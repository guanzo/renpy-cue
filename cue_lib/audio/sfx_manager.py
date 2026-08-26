# -*- coding: utf-8 -*-
# CueSfxManager -- SFX playback (shared _cue_ channels) plus the SFX library
# orchestration around it.  The library tree (audio scan, folder/preset tree
# UI state, disabled files) lives in CueSfxLibraryTree, owned here as
# ``library`` -- mirroring how CueMusicManager owns its CueCombinedMusicTree.
# Collaborators (paths/db/volume/ctx) are constructor-injected; markers is
# late-bound via bind_markers (construction cycle with CueMarkerManager).
# Instantiated once at _cue.sfx, lives on the NoRollback _cue object.

import random as _random
import threading
import renpy
import renpy.audio.music as _music

from renpy.store import persistent

from cue_lib.audio.file_tree import CueAudioTreeManager
from cue_lib.audio.file_tree_rows import CueSfxTreeRows
from cue_lib.audio.wav_playable import CueWavPlayable
from cue_lib.constants import (
    CUE_SFX_CHANNEL_COUNT,
    CUE_SIDEBAR_DEFAULT_WIDTH,
    CUE_SIDEBAR_MIN_WIDTH,
    CUE_SIDEBAR_MAX_WIDTH_RATIO,
    CUE_PERSIST_SIDEBAR_MODE,
    CUE_PERSIST_SIDEBAR_WIDTH,
)
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

    def __init__(self, paths, db, volume, ctx, supports_relative_volume):
        # type: (CuePaths, CueDatabase, CueVolumeManager, CueContext, bool) -> None
        self.library = CueSfxLibraryTree(paths, db)
        self.library._sfx = self
        self._paths = paths
        self._db = db
        self._volume = volume
        self._ctx = ctx
        self._supports_relative_volume = supports_relative_volume
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
        rel_paths = list(self.library.files)
        paths = self._paths
        wav_playable = self._wav_playable

        def _run():
            wav_playable.warm(rel_paths, paths.audio_dir)

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
        marker_delta=None,
    ):
        # type: (Optional[MarkerEntry], str, PoolDict, int, Optional[str], bool, Optional[float], Optional[float], Optional[float], Optional[float]) -> Optional[str]
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
            f, key, volume=vol, marker_time=marker_time, marker_elapsed=marker_elapsed, marker_delta=marker_delta
        )

    def play_sfx(self, filename, source="", volume=1.0, marker_time=None, marker_elapsed=None, marker_delta=None):
        # type: (str, str, float, Optional[float], Optional[float], Optional[float]) -> Optional[str]

        # Apply +-10% volume jitter for natural variation
        MAX_JITTER = 0.1
        jitter = _random.uniform(1.0 - MAX_JITTER, 1.0 + MAX_JITTER)
        volume = volume * jitter

        full_path = self._wav_playable.ensure_playable(self._paths.audio_dir + filename)

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

            log = "PLAY-SFX file={} src={} ch={} jitter={:.2f} vol={:.2f}".format(
                filename.rsplit("/", 1)[-1], source, target_ch, jitter, volume
            )
            if marker_time is not None:
                # Trigger accuracy: marker timestamp vs. actual media position at
                # fire.  delta is reference-time error (positive = fired late).
                log += " mt={:.3f} elapsed={:.3f} delta={:+.3f}".format(marker_time, marker_elapsed, marker_delta)
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
        preset = self._markers_ctx().get_preset(preset_name)
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
        preset = self._markers_ctx().get_video_preset(preset_name)
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


class CueSfxLibraryTree(CueAudioTreeManager):
    """SFX library audio tree state, expand/collapse, disabled files, and scan.

    Owns all UI state for the SFX Library audio tree, preset folders,
    video preset folders, section frames, and pool file-list folder refs.
    The audio file caches (files / tree / scan_error) and the scan that
    builds them live in CueAudioTreeManager.  Provides toggle methods
    callable via Function() from screen actions.  Owned by CueSfxManager
    as its ``library`` attribute."""

    _scan_label = "audio folder"
    _log_tag = "AUDIO"

    def __init__(self, paths, db):
        # type: (CuePaths, CueDatabase) -> None
        super(CueSfxLibraryTree, self).__init__()
        self._paths = paths
        # Parent CueSfxManager, wired by CueSfxManager.__init__ (preview fns).
        self._sfx = None  # type: Any
        self._db = db

        # Row builder for the cue_tree_rows renderer (tree_rows delegates).
        self._rows = CueSfxTreeRows(self)

        # Pool file-list folder refs
        self.expanded_file_refs = {}  # folder_ref -> bool (pool file lists)

        # Presets expand/collapse
        self.presets_expanded = False
        self.expanded_presets = {}  # preset_name -> bool

        # Video presets expand/collapse
        self.video_presets_expanded = False
        self.expanded_video_presets = {}  # preset_name -> bool
        self.expanded_video_pools = {}  # preset_name -> {pool_index: bool}

        # Intensity group block: expand/collapse + per-group expand, the active
        # add-files target (one (group, level) pair at a time), and per-level
        # expand/collapse for a level's file rows.
        self.igroups_expanded = False
        self.expanded_igroups = {}  # group_name -> bool
        self.ilevel_add_target = None  # (group_name, ilevel_id) in add-files mode (None = none)
        self.expanded_ilevels = {}  # group_name -> set of ilevel_id
        self._intensity = None  # type: Optional[CueIntensityManager]
        # late-bound CueIntensityManager (cue_z.rpy)
        # Guardrail notice shown under the target bar; "" = none.  Set on a
        # rejected folder add, cleared by any successful pool add.
        self.add_to_pool_warning = ""

        # File disable
        self.disabled_files = set()  # full_path strings

        # Sidebar mode: SFX Library renders as a right-side sidebar (mode on)
        # or as a section frame inside the overlay page (mode off).
        self.is_sidebar_mode = False
        self.sidebar_width = CUE_SIDEBAR_DEFAULT_WIDTH

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _discover(self, results_set):
        # type: (Set[str]) -> None
        """Scan the audio dir -- files the user drops in for SFX."""
        self._discover_walk_dir(results_set, self._paths.audio_dir)

    def _file_node(self, item, full, depth):
        # type: (Dict[str, Any], str, int) -> Dict[str, Any]
        """File row with index/enabled for the SFX Library."""
        node = super(CueSfxLibraryTree, self)._file_node(item, full, depth)
        node["index"] = self._file_index.get(full, -1)
        node["enabled"] = full not in self.disabled_files
        return node

    # ------------------------------------------------------------------
    # Row stream: delegate to the shared cue_tree_rows builder
    # ------------------------------------------------------------------

    def tree_rows(self, *state):
        # type: (*Any) -> List[Dict[str, Any]]
        """Flat row stream for the cue_tree_rows renderer.  SFX button/warn
        logic lives in CueSfxTreeRows; this just forwards *state."""
        return self._rows.tree_rows(*state)

    def content_rows(self, search_query, preset_names, video_preset_names, igroup_names, is_video, tgt_ok, unplayable):
        # type: (str, List[str], List[str], List[str], bool, bool, Dict[str, str]) -> List[Dict[str, Any]]
        """Full SFX Library section row stream for the cue_tree_rows renderer
        (recent + pool presets + video presets + intensity + file tree).  All
        builder logic lives in CueSfxTreeRows; this just forwards."""
        return self._rows.content_rows(
            search_query, preset_names, video_preset_names, igroup_names, is_video, tgt_ok, unplayable
        )

    # ------------------------------------------------------------------
    # Toggle: file enabled/disabled
    # ------------------------------------------------------------------

    def toggle_file_enabled(self, full_path):
        # type: (str) -> None
        """Toggle whether a file is enabled for marker addition."""
        if full_path in self.disabled_files:
            self.disabled_files.discard(full_path)
        else:
            self.disabled_files.add(full_path)
        self.rebuild_tree()
        self._db.update_shared_config({"disabled_files": list(self.disabled_files)})

    # ------------------------------------------------------------------
    # Pool file-list folder refs
    # ------------------------------------------------------------------

    def toggle_file_ref_expand(self, folder_ref):
        # type: (str) -> None
        """Toggle expand/collapse for a folder ref in a pool file list."""
        if folder_ref in self.expanded_file_refs:
            self.expanded_file_refs[folder_ref] = not self.expanded_file_refs[folder_ref]
        else:
            self.expanded_file_refs[folder_ref] = True

    def count_file_list_rows(self, folder_label, folder_children, files):
        # type: (Optional[str], Optional[List[str]], List[str]) -> int
        """Count rendered rows in a pool file list (for viewport sizing)."""
        rows = 0
        if folder_label is not None:
            rows += 1
            if self.expanded_file_refs.get(folder_label, False) and folder_children:
                rows += len(folder_children)
        for f in files:
            rows += 1
            if f.endswith("/"):
                if self.expanded_file_refs.get(f, False):
                    rows += len(_cue_resolve_files([f]))
        return rows

    # ------------------------------------------------------------------
    # Toggle: Presets/ folder
    # ------------------------------------------------------------------

    def toggle_presets_expand(self):
        # type: () -> None
        """Toggle expand/collapse for the Presets/ folder in the SFX Library."""
        self.presets_expanded = not self.presets_expanded

    def toggle_preset_expand(self, preset_name):
        # type: (str) -> None
        """Toggle expand/collapse for a single preset in the SFX Library."""
        if preset_name in self.expanded_presets:
            self.expanded_presets[preset_name] = not self.expanded_presets[preset_name]
        else:
            self.expanded_presets[preset_name] = True

    # ------------------------------------------------------------------
    # Toggle: Video Presets/ folder
    # ------------------------------------------------------------------

    def toggle_video_presets_expand(self):
        # type: () -> None
        """Toggle expand/collapse for the Video Presets/ folder in the SFX Library."""
        self.video_presets_expanded = not self.video_presets_expanded

    def toggle_video_preset_expand(self, preset_name):
        # type: (str) -> None
        """Toggle expand/collapse for a single video preset in the SFX Library."""
        if preset_name in self.expanded_video_presets:
            self.expanded_video_presets[preset_name] = not self.expanded_video_presets[preset_name]
        else:
            self.expanded_video_presets[preset_name] = True

    def toggle_video_pool_expand(self, preset_name, pool_index):
        # type: (str, int) -> None
        """Toggle expand/collapse for a single pool row inside a video preset."""
        pools = self.expanded_video_pools.setdefault(preset_name, {})
        if pool_index in pools:
            pools[pool_index] = not pools[pool_index]
        else:
            pools[pool_index] = True

    # ------------------------------------------------------------------
    # Toggle: sidebar mode
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Toggle: Intensity Groups/ block
    # ------------------------------------------------------------------

    def toggle_igroups_expand(self):
        # type: () -> None
        """Toggle expand/collapse for the Intensity Groups/ block."""
        self.igroups_expanded = not self.igroups_expanded

    def toggle_igroup_expand(self, group_name):
        # type: (str) -> None
        """Toggle expand/collapse for a single intensity group."""
        if group_name in self.expanded_igroups:
            self.expanded_igroups[group_name] = not self.expanded_igroups[group_name]
        else:
            self.expanded_igroups[group_name] = True

    def add_level(self, group_name):
        # type: (str) -> None
        """Store bridge for the [+ Level] button: create an empty level and
        auto-expand it (so the add-files toggle lands visibly)."""
        if self._intensity is None:
            return
        new_id = self._intensity.add_level(group_name)
        if new_id is not None:
            self.expanded_igroups[group_name] = True
            self.expanded_ilevels.setdefault(group_name, set()).add(new_id)

    def toggle_ilevel_add_mode(self, group_name, ilevel_id):
        # type: (str, int) -> None
        """Toggle add-files mode for one (group, level) pair.  Only one level
        can be in add mode at a time; toggling the active level exits.  Entering
        add mode expands the group and the level's file rows so appends land
        visibly."""
        target = (group_name, ilevel_id)
        if self.ilevel_add_target == target:
            self.ilevel_add_target = None
        else:
            self.ilevel_add_target = target
            self.expanded_igroups[group_name] = True
            self.expanded_ilevels.setdefault(group_name, set()).add(ilevel_id)

    def toggle_ilevel_expand(self, group_name, ilevel_id):
        # type: (str, int) -> None
        """Toggle expand/collapse for a single level's file rows."""
        expanded = self.expanded_ilevels.setdefault(group_name, set())
        if ilevel_id in expanded:
            expanded.discard(ilevel_id)
        else:
            expanded.add(ilevel_id)

    def _ilevel_target_valid(self, group_name, ilevel_id):
        # type: (str, int) -> bool
        """True when the (group, level) add target still exists; clears a stale
        target whose group was deleted."""
        data = self._intensity.get_igroup(group_name) if self._intensity is not None else None
        if data is None:
            self.ilevel_add_target = None
            return False
        for level in data.get("levels", []):
            if level.get("id") == ilevel_id:
                return True
        return False

    def ilevel_add_file(self, group_name, ilevel_id, file_ref):
        # type: (str, int, str) -> None
        """Add a tree file to a level's files (add-files mode)."""
        if not self._ilevel_target_valid(group_name, ilevel_id):
            return
        intensity = self._intensity
        if intensity is None:
            return
        intensity.add_level_file(group_name, ilevel_id, file_ref)

    def ilevel_add_folder(self, group_name, ilevel_id, folder_path):
        # type: (str, int, str) -> None
        """Add a tree folder ref to a level's files (add-files mode)."""
        if not self._ilevel_target_valid(group_name, ilevel_id):
            return
        intensity = self._intensity
        if intensity is None:
            return
        folder_ref = folder_path.rstrip("/") + "/"
        intensity.add_level_file(group_name, ilevel_id, folder_ref)

    def level_has_file(self, group_name, ilevel_id, file_ref):
        # type: (str, int, str) -> bool
        """True when *file_ref* is already in the level's files (used to disable
        a duplicate add in the tree)."""
        if self._intensity is None:
            return False
        files = self._intensity.level_files_by_id(group_name, ilevel_id)
        if files is None:
            return False
        return file_ref in files

    def set_add_to_pool_warning(self, message):
        # type: (str) -> None
        """Show the one-group-per-pool guardrail notice under the target bar.
        Overwrites any prior notice; a successful add clears it."""
        self.add_to_pool_warning = message

    def clear_add_to_pool_warning(self):
        # type: () -> None
        self.add_to_pool_warning = ""

    def toggle_sidebar_mode(self):
        # type: () -> None
        """Toggle sidebar mode for the SFX Library section."""
        self.is_sidebar_mode = not self.is_sidebar_mode
        self.persist_sidebar_state()
        renpy.restart_interaction()

    def persist_sidebar_state(self):
        # type: () -> None
        """Persist sidebar mode + width to per-game persistent."""
        if persistent._cue is None:
            persistent._cue = {}
        persistent._cue[CUE_PERSIST_SIDEBAR_MODE] = self.is_sidebar_mode
        persistent._cue[CUE_PERSIST_SIDEBAR_WIDTH] = self.sidebar_width

    def set_sidebar_width(self, width):
        # type: (int) -> None
        """Clamp and store the sidebar width (logical px, pre-zoom)."""
        max_w = int(renpy.config.screen_width * CUE_SIDEBAR_MAX_WIDTH_RATIO)
        self.sidebar_width = max(CUE_SIDEBAR_MIN_WIDTH, min(width, max_w))
