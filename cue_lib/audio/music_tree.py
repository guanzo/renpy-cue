# -*- coding: utf-8 -*-
# CueCombinedMusicTree -- display-only merge of the separate My Music and Game
# Music trees into one "Music Library" tree for the Music page.  The two
# sub-managers stay untouched (their scans, files, trees, and u:/g: ref tags
# are the data model); this class only wraps them under two synthetic
# top-level folders so the UI shows one tree with a single shared search bar.
# Instantiated once as _cue.music.library; lives on the NoRollback _cue object.

from cue_lib.audio.file_tree import CueAudioTreeManager
from cue_lib.audio.file_tree_rows import CueMusicTreeRows
from cue_lib.constants import CUE_GAME_MUSIC_FOLDER, CUE_MUSIC_GAME_TAG, CUE_MY_MUSIC_FOLDER, CUE_MUSIC_PREFIX

MYPY = False
if MYPY:
    from typing import Any, Dict, List
    from cue_lib.audio.game_music import CueGameMusic
    from cue_lib.audio.music import CueMusicManager
    from cue_lib.audio.user_music import CueUserMusic


class CueCombinedMusicTree(CueAudioTreeManager):
    """Combined file-tree display for My Music + Game Music.

    Subclasses CueAudioTreeManager so the search-bar contract (search_query,
    clear_search, toggle_folder, search truncation) and the one-time root
    expansion are inherited.  scan() is not used -- the sub-managers scan
    independently, and rebuild_tree()/maybe_rebuild() re-merge their trees on
    demand.  The user "music/" data root is renamed to a synthetic "My Music"
    display folder; game files are wrapped under a synthetic "Game Music"
    folder, so the display always has exactly two top-level folders regardless
    of how many top-level dirs the Game Music heuristic finds."""

    _scan_label = "music"
    _log_tag = "MUSIC-LIB"
    # Open both synthetic top folders by default (one-time), so the two
    # sources are visible without a click.
    _auto_expand_roots = True

    def __init__(self, music, user_music, game_music):
        # type: (CueMusicManager, CueUserMusic, CueGameMusic) -> None
        CueAudioTreeManager.__init__(self)
        self._music = music
        self.user_music = user_music
        self.game_music = game_music

        # Row builder for the cue_tree_rows renderer (tree_rows delegates).
        self._rows = CueMusicTreeRows(self)
        # Source tree object ids at the last rebuild, for maybe_rebuild's
        # rescan detection (a re-scan replaces the sub-manager's tree list).
        self._user_tree_id = None
        self._game_tree_id = None

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def rebuild_tree(self):
        # type: () -> None
        """Re-merge the two source trees and rebuild the visible rows.

        The merged self.tree wraps each non-empty source under a synthetic
        top folder.  The one-time root expansion (gated by _has_expanded_roots)
        opens both synthetic folders on the first non-empty rebuild."""
        self.tree = self._merged_tree()

        if self._auto_expand_roots and not self._has_expanded_roots and self.tree:
            self._expand_roots()
            self._has_expanded_roots = True

        CueAudioTreeManager.rebuild_tree(self)

        # Stamp the source-tree ids so the tick loop's maybe_rebuild skips until
        # a source re-scans or the query changes (mirrors _search_applied).
        self._user_tree_id = id(self.user_music.tree)
        self._game_tree_id = id(self.game_music.tree)

    def _merged_tree(self):
        # type: () -> List[Dict[str, Any]]
        """Build the combined nested tree from the two source trees.

        The user tree is always rooted at a single "music/" folder (every
        user file carries that data prefix), so its children are hoisted under
        a synthetic "My Music/" display folder.  The game tree is wrapped
        unchanged under "Game Music/" -- it may have several top-level
        folders (music/, bgm/, ost/), which is exactly why the synthetic
        wrapper is needed.  Empty sources contribute nothing."""
        result = []
        user_tree = self.user_music.tree

        if user_tree:
            if len(user_tree) == 1 and user_tree[0]["type"] == "folder" and user_tree[0]["name"] == CUE_MUSIC_PREFIX:
                children = user_tree[0].get("children", [])
                has_files = user_tree[0].get("has_files", False)
            else:
                children = user_tree
                has_files = False
            result.append({"type": "folder", "name": CUE_MY_MUSIC_FOLDER, "children": children, "has_files": has_files})

        game_tree = self.game_music.tree
        if game_tree:
            result.append({"type": "folder", "name": CUE_GAME_MUSIC_FOLDER, "children": game_tree, "has_files": False})
        return result

    def maybe_rebuild(self):
        # type: () -> None
        """Rebuild only when the query changed or either source re-scanned.

        Search keystrokes are debounced via _search_applied (inherited).  A
        re-scan replaces the sub-manager's tree object, so its id changing is
        the cheap rescan signal -- this keeps the combined tree fresh without
        re-merging on every frame."""
        q = self.search_query
        if (
            q == self._search_applied
            and id(self.user_music.tree) == self._user_tree_id
            and id(self.game_music.tree) == self._game_tree_id
        ):
            return

        self.rebuild_tree()
        self._search_applied = q
        self._user_tree_id = id(self.user_music.tree)
        self._game_tree_id = id(self.game_music.tree)

    # ------------------------------------------------------------------
    # Dispatch: display path -> data path
    # ------------------------------------------------------------------
    #
    # The visible rows carry merged display paths ("My Music/Folder/song.ogg",
    # "Game Music/bgm/x.ogg").  Before reaching the stored-ref methods these
    # are converted back to the data model: a user path re-gains its "music/"
    # prefix, a game path is the game-relative path unchanged.  Ref tags
    # (u:/g:) and stored refs are therefore untouched by the UI merge.

    def add_song_to_trigger(self, display_path, record=True):
        # type: (str, bool) -> None
        """Add the song under display_path to the selected trigger.

        record=False is passed by recently-used rows so acting from the list
        doesn't re-feed it."""
        if display_path.startswith(CUE_GAME_MUSIC_FOLDER):
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
        if display_path.startswith(CUE_GAME_MUSIC_FOLDER):
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
        keeps its path under "Game Music/".  An untagged legacy ref is treated
        as user, which is the round-trip of the user-default dispatch."""
        tag, path = self._music._split_ref_tag(ref)
        if tag == CUE_MUSIC_GAME_TAG:
            return CUE_GAME_MUSIC_FOLDER + path
        if path.startswith(CUE_MUSIC_PREFIX):
            path = path[len(CUE_MUSIC_PREFIX) :]
        return CUE_MY_MUSIC_FOLDER + path

    def preview(self, display_path, volume=1.0):
        # type: (str, float) -> None
        """Preview the file under display_path on the music channel (untracked).

        Mirrors the previous _cue_preview_music/_cue_preview_game_music: user
        paths resolve through _resolve_music_path (which also tolerates legacy
        no-prefix entries), game paths play game-relative as-is."""
        if display_path.startswith(CUE_GAME_MUSIC_FOLDER):
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
