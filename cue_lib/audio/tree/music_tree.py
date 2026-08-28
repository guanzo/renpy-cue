# -*- coding: utf-8 -*-
# CueMusicTree -- the Music Library: scans both My Music (shared dir) and Game
# Music (game VFS), keeps their per-source trees and scan errors, and merges
# them under two synthetic folders for display.  Instantiated once as
# _cue.music.library; lives on the NoRollback _cue object.

import time

import renpy

from cue_lib.audio.tree.file_tree import CueAudioTreeManager
from cue_lib.audio.tree.music_tree_rows import CueMusicTreeRows
from cue_lib.constants import (
    CUE_AUDIO_EXTS,
    CUE_GAME_MUSIC_FOLDER,
    CUE_MUSIC_GAME_TAG,
    CUE_MUSIC_USER_TAG,
    CUE_MY_MUSIC_FOLDER,
    CUE_MUSIC_PREFIX,
    CUE_PERSIST_MUSIC_TREE_EXPANDED,
)
from cue_lib.state import _cue
from cue_lib.util import _cue_is_abs_path, _cue_log

# Directory-name heuristic for Game Music discovery: a game file whose path
# contains one of these segments (case-insensitive) is classified as music.
CUE_GAME_MUSIC_DIRS = ("music", "bgm", "ost", "soundtrack")

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Set

    from cue_lib._types import TreeRowDict
    from cue_lib.music.manager import CueMusicManager


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

    _log_tag = "MUSIC-LIB"
    # Open both synthetic top folders by default (one-time), so the two
    # sources are visible without a click.
    _auto_expand_roots = True
    _persist_key = CUE_PERSIST_MUSIC_TREE_EXPANDED
    _reserved_labels = (CUE_MY_MUSIC_FOLDER, CUE_GAME_MUSIC_FOLDER)
    CUE_BUILTIN_SOURCES = (
        {
            "key": "user",
            "discover": "_discover_user",
            "display_root": CUE_MY_MUSIC_FOLDER,
            "scan_label": "music folder",
        },
        {
            "key": "game",
            "discover": "_discover_game",
            "display_root": CUE_GAME_MUSIC_FOLDER,
            "scan_label": "game music",
        },
    )

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

        self._scan_builtin_sources()
        self._scan_external()

        self._rebuild_merged()

        _cue_log(
            "SCAN-{}: {:.3f}s {} + {} + {} files".format(
                self._log_tag, time.time() - _t0, len(self.user_files), len(self.game_files), len(self.external_files)
            )
        )

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

        # External sources render between the built-ins: folders the user adds
        # via Settings > Data Folder.  A source with no files (missing folder)
        # still appears so its warning row is reachable.
        self._append_external_sources(result)

        # Game Music is always last, below any user-added external folders.
        if self.game_tree:
            result.append(self._wrap_source_tree("game"))

        return result

    # ------------------------------------------------------------------
    # Dispatch: stored ref -> manager (tags route by source)
    # ------------------------------------------------------------------
    #
    # The visible rows carry stored refs (item["ref"]: "u:music/x.ogg",
    # "g:bgm/x.ogg", or a bare absolute path) stashed by the base _file_node.
    # The tag routing already lives in the manager's add_*_to_trigger family,
    # so these just split the tag and hand the untagged path to the right
    # manager method.  ref_from_display / display_for_ref invert each other
    # and are the only display<->stored conversion in the tree.

    def ref_from_display(self, display_path):
        # type: (str) -> str
        """Stored ref for a merged display path.

        Inverts display_for_ref: "My Music/x.ogg" regains its "u:music/x.ogg"
        stored form, "Game Music/bgm/x.ogg" becomes "g:bgm/x.ogg", and an
        external label path becomes the bare absolute payload."""
        payload = self._external_payload_for_display(display_path)
        if payload is not None:
            return payload
        if display_path.startswith(CUE_GAME_MUSIC_FOLDER):
            return CUE_MUSIC_GAME_TAG + display_path[len(CUE_GAME_MUSIC_FOLDER) :]
        return CUE_MUSIC_USER_TAG + CUE_MUSIC_PREFIX + display_path[len(CUE_MY_MUSIC_FOLDER) :]

    def display_for_ref(self, ref):
        # type: (str) -> str
        """Display path for a stored (tagged) music ref.

        Inverts ref_from_display: a user ref sheds its "music/" data prefix
        under "My Music/", a game ref keeps its path under "Game Music/", an
        external ref sheds its absolute root under its source label (or falls
        back to the absolute path when the source was removed).  An untagged
        legacy ref is treated as user, which is the round-trip of the
        user-default dispatch."""
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

    def add_song_to_trigger(self, ref, record=True):
        # type: (str, bool) -> None
        """Add the song at stored ref to the selected trigger.

        record=False is passed by recently-used rows so acting from the list
        doesn't re-feed it."""
        if _cue_is_abs_path(ref):
            self._music.add_external_song_to_trigger(ref, record=record)
            return
        tag, path = self._music._split_ref_tag(ref)
        if tag == CUE_MUSIC_GAME_TAG:
            self._music.add_game_song_to_trigger(path, record=record)
        else:
            self._music.add_user_song_to_trigger(path, record=record)

    def add_folder_to_trigger(self, ref, record=True):
        # type: (str, bool) -> None
        """Add the folder at stored ref to the selected trigger.

        The synthetic "Game Music" root (stored ref "g:") is skipped -- it
        groups several real folders and has no single data path.  record=False
        is passed by recently-used rows so acting from the list doesn't re-feed
        it."""
        if _cue_is_abs_path(ref):
            self._music.add_external_folder_to_trigger(ref, record=record)
            return
        tag, path = self._music._split_ref_tag(ref)
        if tag == CUE_MUSIC_GAME_TAG:
            if not path:
                return
            self._music.add_game_folder_to_trigger(path, record=record)
        else:
            self._music.add_user_folder_to_trigger(path, record=record)

    def preview(self, ref, volume=1.0):
        # type: (str, float) -> None
        """Preview the file at stored ref on the music channel (untracked).

        _resolve_music_path handles the source tags: "u:" resolves under the
        shared music dir, "g:" plays game-relative as-is, absolute payloads
        play directly."""
        self._music.play_untracked(self._music._resolve_music_path(ref), volume=volume)

    def tree_rows(self, *state):
        # type: (*Any) -> List[TreeRowDict]
        """Flat row stream for the cue_tree_rows renderer.  Music button logic
        lives in CueMusicTreeRows; this just forwards *state (current_file)."""
        return self._rows.tree_rows(*state)

    def content_rows(self, search_query, preset_names, current_file):
        # type: (str, List[str], object) -> List[TreeRowDict]
        """Full Music Library section row stream for the cue_tree_rows renderer
        (recent + music presets + per-source empty states + file tree).  All
        builder logic lives in CueMusicTreeRows; this just forwards."""
        return self._rows.content_rows(search_query, preset_names, current_file)
