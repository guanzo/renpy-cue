# -*- coding: utf-8 -*-
# CueUserMusic -- the "My Music" section on the Music page: filesystem scan,
# folder/file tree caches, and tree UI state (expand/collapse, visible rows).
# The tree/scan/toggle core is inherited from CueAudioTreeManager; this class
# only supplies the scan source (the shared music dir).
# Instantiated once as _cue.music.user_music; lives on the NoRollback
# _cue object.

from cue_lib.audio.file_tree import CueAudioTreeManager
from cue_lib.constants import CUE_MUSIC_PREFIX
from cue_lib.state import _cue

MYPY = False
if MYPY:
    from typing import Set


class CueUserMusic(CueAudioTreeManager):
    """Scan state and nested tree for the My Music section.

    The files / tree / scan_error caches live here (inherited from
    CueAudioTreeManager) instead of on _cue.  A leaner sibling of
    CueSfxManager: no disabled files, presets, overlay mode, or pool folder
    refs.  Scan-only -- the combined tree (_cue.music.library) owns the
    visible rows; this manager only supplies the scan source.  Section
    collapse reuses _cue.collapsed_sections via cue_section_frame."""

    _scan_label = "music folder"
    _log_tag = "MUSIC"
    _build_visible = False

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _discover(self, results_set):
        # type: (Set[str]) -> None
        """Scan the My Music dir -- files the user drops in for music.

        Paths are stored relative to the shared root, prefixed with "music/",
        so the tree gains a natural "music/" root folder that can be added to
        a trigger as one ref.  Mirrors the SFX library scan but targets
        shared_dir/music, so user music never mixes with the SFX library."""
        _sub = set()
        self._discover_walk_dir(_sub, _cue.paths.music_dir)
        for _rel in _sub:
            results_set.add(CUE_MUSIC_PREFIX + _rel)
