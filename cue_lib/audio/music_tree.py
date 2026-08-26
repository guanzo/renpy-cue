# -*- coding: utf-8 -*-
# CueMusicTree -- the Music Library: scans both My Music (shared dir) and Game
# Music (game VFS), keeps their per-source trees and scan errors, and merges
# them under two synthetic folders for display.  Instantiated once as
# _cue.music.library; lives on the NoRollback _cue object.

import time

import renpy

from cue_lib.audio.file_tree import CueAudioTreeManager
from cue_lib.audio.file_tree_rows import CueMusicTreeRows
from cue_lib.constants import (
    CUE_AUDIO_EXTS,
    CUE_GAME_MUSIC_FOLDER,
    CUE_MUSIC_GAME_TAG,
    CUE_MY_MUSIC_FOLDER,
    CUE_MUSIC_PREFIX,
    CUE_PERSIST_MUSIC_TREE_EXPANDED,
)
from cue_lib.state import _cue
from cue_lib.util import _cue_build_tree, _cue_is_abs_path, _cue_log

# Directory-name heuristic for Game Music discovery: a game file whose path
# contains one of these segments (case-insensitive) is classified as music.
CUE_GAME_MUSIC_DIRS = ("music", "bgm", "ost", "soundtrack")

MYPY = False
if MYPY:
    from typing import Any, Callable, Dict, List, Optional, Set
    from cue_lib.audio.music import CueMusicManager


class CueMusicTree(CueAudioTreeManager):
    """The combined "Music Library" tree: My Music + Game Music in one view.

    Single owner of both music-tree data sources.  scan() runs the two
    discoveries, keeps per-source files / tree / scan_error, and merges them
    under the synthetic "My Music"/"Game Music" folders for display.  The
    search-bar contract (search_query, clear_search, toggle_folder, search
    truncation) and the one-time root expansion are inherited from the base.
    The user "music/" data root is renamed to a synthetic "My Music" display
    folder; game files are wrapped under a synthetic "Game Music" folder, so
    the display always has exactly two top-level folders regardless of how
    many top-level dirs the Game Music heuristic finds."""

    _scan_label = "music library"
    _log_tag = "MUSIC-LIB"
    # Open both synthetic top folders by default (one-time), so the two
    # sources are visible without a click.
    _auto_expand_roots = True
    _persist_key = CUE_PERSIST_MUSIC_TREE_EXPANDED
    _reserved_labels = (CUE_MY_MUSIC_FOLDER, CUE_GAME_MUSIC_FOLDER)

    def __init__(self, music):
        # type: (CueMusicManager) -> None
        CueAudioTreeManager.__init__(self)
        self._music = music

        # Row builder for the cue_tree_rows renderer (tree_rows delegates).
        self._rows = CueMusicTreeRows(self)
        # Per-source scan state, read by ref resolution (_resolve_folder_ref,
        # _cue_keep_music) and the per-source empty/error rows.
        self.user_files = []  # type: List[str]
        self.game_files = []  # type: List[str]
        self.user_tree = []  # type: List[Dict[str, Any]]
        self.game_tree = []  # type: List[Dict[str, Any]]
        self.user_scan_error = ""  # type: str
        self.game_scan_error = ""  # type: str
        # External sources (Settings > Data Folder music folders).  external_folders
        # is the configured list (absolute paths, from shared config); the scan
        # populates external_sources (per-root dict) and external_files (the
        # flat list of absolute payloads, used by folder expansion + recent
        # membership).  External payloads are stored as bare absolute paths.

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self):
        # type: () -> None
        """Scan both sources, then merge and rebuild the visible rows.

        Each source scans independently: a failure sets that source's empty
        files/tree and its scan_error, and the other source still contributes.
        The merged self.tree then drives the visible rows (the one-time root
        expansion opens both synthetic folders on the first non-empty scan)."""
        _t0 = time.time()

        self.user_files, self.user_scan_error = self._scan_source(self._discover_user, "music folder")
        self.game_files, self.game_scan_error = self._scan_source(self._discover_game, "game music")
        self.user_tree = _cue_build_tree(self.user_files)
        self.game_tree = _cue_build_tree(self.game_files)
        self._scan_external()

        self._rebuild_merged()

        _cue_log(
            "SCAN-{}: {:.3f}s {} + {} + {} files".format(
                self._log_tag, time.time() - _t0, len(self.user_files), len(self.game_files), len(self.external_files)
            )
        )

    def _scan_source(self, discover, label):
        # type: (Callable[[Set[str]], None], str) -> tuple
        """Run one source scan; return (sorted files, scan_error)."""
        results = set()
        try:
            discover(results)
        except Exception as err:
            return [], "Failed to scan {}: {}".format(label, err)
        return sorted(results), ""

    def _discover_user(self, results_set):
        # type: (Set[str]) -> None
        """Scan the My Music dir -- files the user drops in for music.

        Paths are stored relative to the shared root, prefixed with "music/",
        so the tree gains a natural "music/" root folder that can be added to
        a trigger as one ref."""
        _sub = set()
        self._discover_walk_dir(_sub, _cue.paths.music_dir)
        for _rel in _sub:
            results_set.add(CUE_MUSIC_PREFIX + _rel)

    def _discover_game(self, results_set):
        # type: (Set[str]) -> None
        """Scan the game's virtual filesystem for music.

        A file counts as music when its path has a directory segment matching
        CUE_GAME_MUSIC_DIRS and it ends with an audio extension.  Paths are
        kept game-relative so they play directly on the music channel."""
        for f in renpy.list_files():
            path = f.replace("\\", "/")
            if not path.lower().endswith(CUE_AUDIO_EXTS):
                continue
            parts = path.split("/")
            dirs = [p.lower() for p in parts[:-1]]
            if any(d in CUE_GAME_MUSIC_DIRS for d in dirs):
                results_set.add(path)

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def _merged_tree(self):
        # type: () -> List[Dict[str, Any]]
        """Build the combined nested tree from the two per-source trees.

        The user tree is always rooted at a single "music/" folder (every
        user file carries that data prefix), so its children are hoisted under
        a synthetic "My Music/" display folder.  The game tree is wrapped
        unchanged under "Game Music/" -- it may have several top-level
        folders (music/, bgm/, ost/), which is exactly why the synthetic
        wrapper is needed.  Empty sources contribute nothing."""
        result = []
        user_tree = self.user_tree

        if user_tree:
            if len(user_tree) == 1 and user_tree[0]["type"] == "folder" and user_tree[0]["name"] == CUE_MUSIC_PREFIX:
                children = user_tree[0].get("children", [])
                has_files = user_tree[0].get("has_files", False)
            else:
                children = user_tree
                has_files = False
            my_music = {"type": "folder", "name": CUE_MY_MUSIC_FOLDER, "children": children, "has_files": has_files}
            if _cue.paths is not None:
                my_music["abs_root"] = _cue.paths.music_dir
            result.append(my_music)

        game_tree = self.game_tree
        if game_tree:
            result.append({"type": "folder", "name": CUE_GAME_MUSIC_FOLDER, "children": game_tree, "has_files": False})

        # External sources render as additional top-level entries after the
        # built-ins.  A source with no files (missing folder) still appears so
        # its warning row is reachable.
        self._append_external_sources(result)
        return result

    # ------------------------------------------------------------------
    # Dispatch: display path -> data path
    # ------------------------------------------------------------------
    #
    # The visible rows carry merged display paths ("My Music/Folder/song.ogg",
    # "Game Music/bgm/x.ogg").  Before reaching the stored-ref methods these
    # are converted back to the data model: a user path re-gains its "music/"
    # prefix, a game path is the game-relative path unchanged.  Ref tags
    # (u:/g:) and stored refs are therefore untouched by the UI merge.

    def _display_to_external(self, display_path):
        # type: (str) -> Optional[str]
        """Absolute payload for display_path if it points into an external
        source tree, else None.  Label prefix matching is exact (label + "/"),
        so "ExtA2/..." never matches a source labelled "ExtA"."""
        return self._external_payload_for_display(display_path)

    def add_song_to_trigger(self, display_path, record=True):
        # type: (str, bool) -> None
        """Add the song under display_path to the selected trigger.

        record=False is passed by recently-used rows so acting from the list
        doesn't re-feed it."""
        external = self._display_to_external(display_path)
        if external is not None:
            self._music.add_external_song_to_trigger(external, record=record)
        elif display_path.startswith(CUE_GAME_MUSIC_FOLDER):
            self._music.add_game_song_to_trigger(display_path[len(CUE_GAME_MUSIC_FOLDER) :], record=record)
        else:
            self._music.add_user_song_to_trigger(
                CUE_MUSIC_PREFIX + display_path[len(CUE_MY_MUSIC_FOLDER) :], record=record
            )

    def add_folder_to_trigger(self, display_path, record=True):
        # type: (str, bool) -> None
        """Add the folder under display_path to the selected trigger.

        The synthetic "Game Music/" root is skipped -- it groups several real
        folders and has no single data path.  record=False is passed by
        recently-used rows so acting from the list doesn't re-feed it."""
        external = self._display_to_external(display_path)
        if external is not None:
            self._music.add_external_folder_to_trigger(external, record=record)
        elif display_path.startswith(CUE_GAME_MUSIC_FOLDER):
            if display_path == CUE_GAME_MUSIC_FOLDER:
                return
            self._music.add_game_folder_to_trigger(display_path[len(CUE_GAME_MUSIC_FOLDER) :], record=record)
        else:
            self._music.add_user_folder_to_trigger(
                CUE_MUSIC_PREFIX + display_path[len(CUE_MY_MUSIC_FOLDER) :], record=record
            )

    def ref_display_path(self, ref):
        # type: (str) -> str
        """Display path for a stored (tagged) music ref.

        Inverts the dispatch in add_song_to_trigger/add_folder_to_trigger: a
        user ref sheds its "music/" data prefix under "My Music/", a game ref
        keeps its path under "Game Music/", an external ref sheds its absolute
        root under its source label (or falls back to the absolute path when
        the source was removed).  An untagged legacy ref is treated as user,
        which is the round-trip of the user-default dispatch."""
        tag, path = self._music._split_ref_tag(ref)
        if tag == CUE_MUSIC_GAME_TAG:
            return CUE_GAME_MUSIC_FOLDER + path
        if _cue_is_abs_path(ref):
            # External: bare absolute path; show under its source label when
            # the source is still configured, else the absolute path itself.
            for source in self.external_sources:
                root = source["abs_root"]
                if path.startswith(root + "/"):
                    return source["label"] + "/" + path[len(root) + 1 :]
            return path
        if path.startswith(CUE_MUSIC_PREFIX):
            path = path[len(CUE_MUSIC_PREFIX) :]
        return CUE_MY_MUSIC_FOLDER + path

    def preview(self, display_path, volume=1.0):
        # type: (str, float) -> None
        """Preview the file under display_path on the music channel (untracked).

        Mirrors the previous _cue_preview_music/_cue_preview_game_music: user
        paths resolve through _resolve_music_path (which also tolerates legacy
        no-prefix entries), game paths play game-relative as-is, external paths
        play the absolute payload directly."""
        external = self._display_to_external(display_path)
        if external is not None:
            self._music.play_untracked(external, volume=volume)
        elif display_path.startswith(CUE_GAME_MUSIC_FOLDER):
            self._music.play_untracked(display_path[len(CUE_GAME_MUSIC_FOLDER) :], volume=volume)
        else:
            self._music.play_untracked(
                self._music._resolve_music_path(CUE_MUSIC_PREFIX + display_path[len(CUE_MY_MUSIC_FOLDER) :]),
                volume=volume,
            )

    def tree_rows(self, *state):
        # type: (*Any) -> List[Dict[str, Any]]
        """Flat row stream for the cue_tree_rows renderer.  Music button logic
        lives in CueMusicTreeRows; this just forwards *state (current_file)."""
        return self._rows.tree_rows(*state)

    def content_rows(self, search_query, preset_names, current_file):
        # type: (str, List[str], object) -> List[Dict[str, Any]]
        """Full Music Library section row stream for the cue_tree_rows renderer
        (recent + music presets + per-source empty states + file tree).  All
        builder logic lives in CueMusicTreeRows; this just forwards."""
        return self._rows.content_rows(search_query, preset_names, current_file)
