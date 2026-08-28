# -*- coding: utf-8 -*-
# CueSfxLibraryTree -- the SFX Library's audio tree: scan source, folder/preset
# expand state, disabled files, pool-ref expansion, and sidebar persist.
# Extends CueAudioTreeManager (file_tree.py) and delegates row construction to
# CueSfxTreeRows (sfx_tree_rows.py).  Owned by CueSfxManager as its
# ``library`` attribute; the manager wires the _sfx back-ref in __init__.
# Extracted from sfx_manager.py so every tree class lives in this package.

import time

import renpy

from renpy.store import persistent

from cue_lib.audio.cue_sfx_pack import CueSfxPackDownloader
from cue_lib.audio.tree.file_tree import CueAudioTreeManager
from cue_lib.audio.tree.sfx_tree_rows import CueSfxTreeRows
from cue_lib.constants import (
    CUE_PERSIST_SFX_TREE_EXPANDED,
    CUE_PERSIST_SFX_UI_STATE,
    CUE_PERSIST_SIDEBAR_MODE,
    CUE_PERSIST_SIDEBAR_WIDTH,
    CUE_SFX_FOLDER,
    CUE_SIDEBAR_DEFAULT_WIDTH,
    CUE_SIDEBAR_MAX_WIDTH_RATIO,
    CUE_SIDEBAR_MIN_WIDTH,
)
from cue_lib.util import _cue_build_tree, _cue_is_abs_path, _cue_log, _cue_unwrap_persistent

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]
    from cue_lib.db import CueDatabase  # pyright: ignore[reportUnusedImport]
    from cue_lib.intensity import CueIntensityManager  # pyright: ignore[reportUnusedImport]
    from cue_lib.paths import CuePaths  # pyright: ignore[reportUnusedImport]


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
    # The synthetic "SFX" root opens by default like music's roots;
    # persisted toggles still win via _restore_expansion.
    _auto_expand_roots = True
    _persist_key = CUE_PERSIST_SFX_TREE_EXPANDED
    _reserved_labels = (CUE_SFX_FOLDER,)

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
        self.disabled_files = set()  # stored refs (audio-relative or e:<abs>)

        # Sidebar mode: SFX Library renders as a right-side sidebar (mode on)
        # or as a section frame inside the overlay page (mode off).
        self.is_sidebar_mode = False
        self.sidebar_width = CUE_SIDEBAR_DEFAULT_WIDTH

        # Curated-pack bootstrap for the empty library: fetch+extract runs on a
        # background thread; the empty-state screen polls sfx_pack.poll_sfx_pack
        # to finish (rescan on success) and show progress.
        self.sfx_pack = CueSfxPackDownloader(self, self._paths.audio_dir)

        # Per-source scan state, mirroring CueMusicTree.  builtin_* is the
        # shared {shared}/audio/ source; external_* comes from the configured
        # external SFX folders (Settings > Data Folder).  library.files stays
        # the flat ref list -- built-in audio-relative refs plus bare absolute
        # payloads -- so _cue_resolve_files / _cue_pick_file / _cue_keep_sfx
        # and the [+] index path keep working unchanged.
        self.builtin_files = []  # type: List[str]
        self.builtin_tree = []  # type: List[Dict[str, Any]]
        self.builtin_scan_error = ""  # type: str

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _discover(self, results_set):
        # type: (Set[str]) -> None
        """Scan the audio dir -- files the user drops in for SFX."""
        self._discover_walk_dir(results_set, self._paths.audio_dir)

    def scan(self):
        # type: () -> None
        """Scan every source (built-in audio dir + external folders), then
        merge the per-source trees under a synthetic "SFX" root.

        Mirror of CueMusicTree.scan.  A built-in scan failure leaves that
        source's files/tree empty and sets its scan_error; external folders
        keep their entries (with a warning) even when missing.  library.files
        is rebuilt as the sorted flat ref list that the resolution helpers
        (_cue_resolve_files, _cue_expand_folder_ref, _cue_pick_file) depend
        on."""
        _t0 = time.time()

        results_set = set()
        builtin_error = ""  # type: str
        try:
            self._discover(results_set)
        except Exception as err:
            builtin_error = "Failed to scan {}: {}".format(self._scan_label, err)
        self.builtin_files = sorted(results_set)
        self.builtin_tree = _cue_build_tree(self.builtin_files)
        self.builtin_scan_error = builtin_error

        self._scan_external()

        # Flat ref list, sorted for the bisect-based folder expansion.
        external_refs = list(self.external_files)
        self.files = sorted(self.builtin_files + external_refs)
        self._file_index = {ref: i for i, ref in enumerate(self.files)}

        # Whole-tree error, read only when the merged tree is empty.
        self.scan_error = builtin_error

        self._rebuild_merged()

        _cue_log(
            "SCAN-{}: {:.3f}s {} + {} files".format(
                self._log_tag, time.time() - _t0, len(self.builtin_files), len(self.external_files)
            )
        )

    def ref_from_display(self, display_path):
        # type: (str) -> str
        """Stored ref for a merged display path.

        Inverts the merged tree: the synthetic "SFX" root maps back to
        the audio-relative ref; an external source label maps to the bare
        absolute payload.  Any other path passes through unchanged (row
        builders feed untagged paths in tests and for legacy trees)."""
        if display_path.startswith(CUE_SFX_FOLDER):
            return display_path[len(CUE_SFX_FOLDER) :]
        payload = self._external_payload_for_display(display_path)
        if payload is not None:
            return payload
        return display_path

    def resolve_path(self, ref):
        # type: (str) -> str
        """Absolute filesystem path for a stored SFX ref.

        Built-in refs are audio-relative; external refs are bare absolute
        paths (their absolute payload is the ref itself).  Shared by playback,
        WAV warming, and the unplayable-warning lookup."""
        if _cue_is_abs_path(ref):
            return ref
        return self._paths.audio_dir + ref

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def _merged_tree(self):
        # type: () -> List[Dict[str, Any]]
        """Build the combined nested tree from the per-source trees.

        Built-in files wrap under the synthetic "SFX" root; external
        sources render as additional top-level entries below it.  A source
        with no files (missing folder) still appears so its warning row is
        reachable."""
        result = []
        if self.builtin_tree:
            result.append(
                {
                    "type": "folder",
                    "name": CUE_SFX_FOLDER,
                    "children": self.builtin_tree,
                    "has_files": False,
                    "abs_root": self._paths.audio_dir,
                }
            )
        self._append_external_sources(result)
        return result

    def _file_node(self, item, full, depth):
        # type: (Dict[str, Any], str, int) -> Dict[str, Any]
        """File row with ref/index/enabled for the SFX Library.

        ``full`` is the merged display path ("SFX/g1/x.ogg" for
        built-in, "ExtA/g1/x.ogg" for external); the stored ref inverts it so
        both built-in AND external rows get valid indices and disabled
        membership without changing the [+] index path."""
        node = super(CueSfxLibraryTree, self)._file_node(item, full, depth)
        ref = self.ref_from_display(full)
        node["ref"] = ref
        node["index"] = self._file_index.get(ref, -1)
        node["enabled"] = ref not in self.disabled_files
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
        self.save_ui_state()

    # ------------------------------------------------------------------
    # Toggle: Presets/ folder
    # ------------------------------------------------------------------

    def toggle_presets_expand(self):
        # type: () -> None
        """Toggle expand/collapse for the Presets/ folder in the SFX Library."""
        self.presets_expanded = not self.presets_expanded
        self.save_ui_state()

    def toggle_preset_expand(self, preset_name):
        # type: (str) -> None
        """Toggle expand/collapse for a single preset in the SFX Library."""
        if preset_name in self.expanded_presets:
            self.expanded_presets[preset_name] = not self.expanded_presets[preset_name]
        else:
            self.expanded_presets[preset_name] = True
        self.save_ui_state()

    # ------------------------------------------------------------------
    # Toggle: Video Presets/ folder
    # ------------------------------------------------------------------

    def toggle_video_presets_expand(self):
        # type: () -> None
        """Toggle expand/collapse for the Video Presets/ folder in the SFX Library."""
        self.video_presets_expanded = not self.video_presets_expanded
        self.save_ui_state()

    def toggle_video_preset_expand(self, preset_name):
        # type: (str) -> None
        """Toggle expand/collapse for a single video preset in the SFX Library."""
        if preset_name in self.expanded_video_presets:
            self.expanded_video_presets[preset_name] = not self.expanded_video_presets[preset_name]
        else:
            self.expanded_video_presets[preset_name] = True
        self.save_ui_state()

    def toggle_video_pool_expand(self, preset_name, pool_index):
        # type: (str, int) -> None
        """Toggle expand/collapse for a single pool row inside a video preset."""
        pools = self.expanded_video_pools.setdefault(preset_name, {})
        if pool_index in pools:
            pools[pool_index] = not pools[pool_index]
        else:
            pools[pool_index] = True
        self.save_ui_state()

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
        self.save_ui_state()

    def toggle_igroup_expand(self, group_name):
        # type: (str) -> None
        """Toggle expand/collapse for a single intensity group."""
        if group_name in self.expanded_igroups:
            self.expanded_igroups[group_name] = not self.expanded_igroups[group_name]
        else:
            self.expanded_igroups[group_name] = True
        self.save_ui_state()

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
            self.save_ui_state()

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
        self.save_ui_state()

    def toggle_ilevel_expand(self, group_name, ilevel_id):
        # type: (str, int) -> None
        """Toggle expand/collapse for a single level's file rows."""
        expanded = self.expanded_ilevels.setdefault(group_name, set())
        if ilevel_id in expanded:
            expanded.discard(ilevel_id)
        else:
            expanded.add(ilevel_id)
        self.save_ui_state()

    def _ilevel_target_valid(self, group_name, ilevel_id):
        # type: (str, int) -> bool
        """True when the (group, level) add target still exists; clears a stale
        target whose group was deleted."""
        data = self._intensity._presets.get(group_name) if self._intensity is not None else None
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

    # ------------------------------------------------------------------
    # Folder-UI toggle state persistence (presets, video presets, pools,
    # intensity groups).  The file-tree folder toggles persist separately
    # through the base manager (see _save_expansion/_restore_expansion).
    # ------------------------------------------------------------------

    def _encode_ui_state(self):
        # type: () -> Dict[str, Any]
        """Plain dict of the folder-UI toggle state, ready for persistent.

        Ren'Py persistent can't round-trip int dict keys or sets as-is:
        expanded_video_pools uses int pool indexes (serialized as str keys)
        and expanded_ilevels uses sets (serialized as sorted lists)."""
        return {
            "expanded_file_refs": dict(self.expanded_file_refs),
            "presets_expanded": self.presets_expanded,
            "expanded_presets": dict(self.expanded_presets),
            "video_presets_expanded": self.video_presets_expanded,
            "expanded_video_presets": dict(self.expanded_video_presets),
            "expanded_video_pools": dict(
                (name, dict((str(idx), val) for idx, val in pools.items()))
                for name, pools in self.expanded_video_pools.items()
            ),
            "igroups_expanded": self.igroups_expanded,
            "expanded_igroups": dict(self.expanded_igroups),
            "expanded_ilevels": dict((name, sorted(ids)) for name, ids in self.expanded_ilevels.items()),
        }

    def save_ui_state(self):
        # type: () -> None
        """Persist the SFX Library's folder-UI toggle state."""
        if persistent._cue is None:
            persistent._cue = {}
        persistent._cue[CUE_PERSIST_SFX_UI_STATE] = self._encode_ui_state()

    def _apply_ui_state(self, blob):
        # type: (Optional[Dict[str, Any]]) -> None
        """Apply a decoded UI-state blob to the toggle attributes."""
        if not isinstance(blob, dict):
            return
        if isinstance(blob.get("expanded_file_refs"), dict):
            self.expanded_file_refs = dict(blob["expanded_file_refs"])
        if isinstance(blob.get("presets_expanded"), bool):
            self.presets_expanded = blob["presets_expanded"]
        if isinstance(blob.get("expanded_presets"), dict):
            self.expanded_presets = dict(blob["expanded_presets"])
        if isinstance(blob.get("video_presets_expanded"), bool):
            self.video_presets_expanded = blob["video_presets_expanded"]
        if isinstance(blob.get("expanded_video_presets"), dict):
            self.expanded_video_presets = dict(blob["expanded_video_presets"])
        if isinstance(blob.get("expanded_video_pools"), dict):
            pools = {}
            for name, raw_pools in blob["expanded_video_pools"].items():
                if isinstance(raw_pools, dict):
                    pools[name] = dict((int(idx), val) for idx, val in raw_pools.items() if isinstance(val, bool))
            self.expanded_video_pools = pools
        if isinstance(blob.get("igroups_expanded"), bool):
            self.igroups_expanded = blob["igroups_expanded"]
        if isinstance(blob.get("expanded_igroups"), dict):
            self.expanded_igroups = dict(blob["expanded_igroups"])
        if isinstance(blob.get("expanded_ilevels"), dict):
            levels = {}
            for name, ids in blob["expanded_ilevels"].items():
                if isinstance(ids, (list, tuple, set)):
                    levels[name] = set(int(i) for i in ids)
            self.expanded_ilevels = levels

    def restore_ui_state(self):
        # type: () -> None
        """Overlay persisted SFX Library folder-UI toggle state onto the attrs."""
        raw = (persistent._cue or {}).get(CUE_PERSIST_SFX_UI_STATE)
        self._apply_ui_state(_cue_unwrap_persistent(raw) if raw is not None else None)
