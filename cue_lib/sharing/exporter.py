# -*- coding: utf-8 -*-
# cue_lib/exporter.py -- the export side: builds a .zip import from this
# game's data.
#
# CueExportManager owns the scope toggle (whole game vs selected replays),
# the category/replay checkboxes, and the zip build.  It enumerates this
# game's files from original_root (never the active overlay) and writes
# exports/<sanitized-name>.zip with a collision-safe name.  A replay export
# packs the replay's markers plus the files those markers reference.

import os
import renpy
import threading

from cue_lib.constants import CUE_IMPORT_CATEGORY_ORDER, CueExportFileTypes, CueExportScope, CueImportCategory
from cue_lib.replays import _cue_replay_labels
from cue_lib.sharing.importer_io import (
    _cue_build_import_zip,
    _cue_enumerate_import_files,
    _cue_external_bake,
    _cue_external_roots,
    _cue_replay_assets_full,
    _cue_sanitize_filename,
    _cue_thumbs_cache_rel,
)
from cue_lib.util import _cue_log


MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]


class CueExportManager(object):
    """Scope + selection + zip build for sharing this game's data."""

    def __init__(self, paths):
        # type: (Any) -> None
        self._paths = paths
        self.scope = CueExportScope.ALL_REPLAYS
        self.file_types = CueExportFileTypes.ALL
        self.checked = dict((cat, True) for cat in CUE_IMPORT_CATEGORY_ORDER)  # type: Dict[int, bool]
        self.name = ""
        self.author = ""
        self.description = ""
        self.contents_by_category = {}  # type: Dict[int, List[str]]
        self.counts = {}  # type: Dict[int, int]
        self.replays = []  # list of {"label": str, "count": int}
        self.checked_replays = set()  # type: Set[str]
        self.current_replay = ""  # the replay the user is in right now
        self.export_status = ""
        self.export_error = ""
        self.is_exporting = False  # zip build running on a background thread
        self.export_fraction = 0.0  # 0..1 progress of the active build
        self._export_thread = None  # type: Any
        self.is_refreshing = False  # a background refresh pass is running
        self._refresh_thread = None  # type: Any

    @property
    def is_busy(self):
        # type: () -> bool
        """True while a refresh pass or zip build runs in the background."""
        return self.is_refreshing or self.is_exporting

    def exports_dir(self):
        # type: () -> str
        """Where export zips are written -- owned by paths.py on the live
        shared tree."""
        return self._paths.exports_dir

    def refresh(self):
        # type: () -> None
        """Request a background refresh.  The worker thread does the whole
        disk pass -- tree enumeration + replay label scan -- so the UI thread
        never blocks on it.  The page keeps showing the last snapshot until
        the worker swaps a fresh one in, which the next poll displays.
        Idempotent and safe to call on every poll: no-op while a pass runs."""
        self._kick_refresh_thread()

    def _kick_refresh_thread(self):
        # type: () -> None
        """Start one daemon refresh worker if none is running.  A call that
        lands mid-pass is dropped; the next one starts a fresh pass over
        whatever the last one left behind."""
        if self.is_refreshing:
            return
        self.is_refreshing = True
        thread = threading.Thread(target=self._refresh_worker)
        thread.daemon = True
        self._refresh_thread = thread
        thread.start()

    def _refresh_worker(self):
        # type: () -> None
        """The background refresh pass.  Any failure is logged and the
        previous snapshot stays put rather than a half-built one."""
        try:
            self._do_refresh()
        except Exception as e:
            _cue_log("EXPORT: refresh failed: {}".format(e))
        finally:
            self.is_refreshing = False
            self._refresh_thread = None

    def _do_refresh(self):
        # type: () -> None
        """The full refresh, run entirely off the UI thread: enumerate every
        exportable file, count each category, and collect the replay labels.
        The snapshot is swapped in with a few attribute writes, so the UI
        only ever sees a consistent result -- a torn read between two writes
        is one cosmetic frame at worst, since the GIL makes each assignment
        atomic.  Replays are seeded checked; a selection made in an earlier
        refresh survives."""
        contents = _cue_enumerate_import_files(self._paths.original_root, self._paths.game_id)
        counts = dict((cat, len(files)) for cat, files in contents.items())
        labels = _cue_replay_labels(self._paths.original_root, self._paths.game_id)
        replays = [{"replay": label, "marker_count": count} for label, count in labels]
        known = set(self.checked_replays)
        self.contents_by_category = contents
        self.counts = counts
        self.replays = replays
        self.checked_replays = known | set(label for label, _c in labels)
        self.current_replay = self._current_replay()

    def _current_replay(self):
        # type: () -> str
        """The replay label the user is inside right now, or ''."""
        try:
            return getattr(renpy.store, "_in_replay", None) or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # scope + selection state
    # ------------------------------------------------------------------

    def set_scope(self, scope):
        # type: (int) -> None
        self.scope = scope
        self.clear_status()

    def set_file_types(self, file_types):
        # type: (int) -> None
        self.file_types = file_types
        self.clear_status()

    def toggle_category(self, cat):
        # type: (int) -> None
        self.checked[cat] = not self.is_checked(cat)

    def is_checked(self, cat):
        # type: (int) -> bool
        return bool(self.checked.get(cat, False))

    def is_category_enabled(self, cat):
        # type: (int) -> bool
        return self.counts.get(cat, 0) > 0

    def any_unchecked(self):
        # type: () -> bool
        """True if the user turned off at least one category in Specific File
        Types mode -- the import may not fully work (referenced files will be
        missing).  Never true in All File Types mode, where no category can be
        off."""
        if self.file_types == CueExportFileTypes.ALL:
            return False
        return any(not self.is_checked(cat) for cat in CUE_IMPORT_CATEGORY_ORDER)

    def toggle_replay(self, label):
        # type: (str) -> None
        if label in self.checked_replays:
            self.checked_replays.discard(label)
        else:
            self.checked_replays.add(label)

    def toggle_all_replays(self):
        # type: () -> None
        """Flip every replay checkbox at once.  All checked becomes all off,
        anything else becomes all on -- after a refresh (all checked by
        default) the first click clears everything, the next checks all."""
        labels = set(self.replay_labels())
        if self.checked_replays == labels:
            self.checked_replays = set()
        else:
            self.checked_replays = labels

    def is_replay_checked(self, label):
        # type: (str) -> bool
        return label in self.checked_replays

    def replay_labels(self):
        # type: () -> List[str]
        return [r["replay"] for r in self.replays]

    # ------------------------------------------------------------------
    # content selection
    # ------------------------------------------------------------------

    def selected_contents(self):
        # type: () -> List[str]
        """Files to pack for the current scope, in canonical category order."""
        return self._selection()[0]

    def _selection(self):
        # type: () -> Tuple[List[str], List[str]]
        """(contents, marker_arcnames) for the current scope.

        marker_arcnames are the in-scope markers, so the export thread can hunt
        each for absolute external refs to bake.  The scene-thumbnail cache
        rides along in either scope when present.  A no-op scope (nothing
        checked) yields ([], [])."""
        if self.scope == CueExportScope.SPECIFIC_REPLAYS:
            contents, marker_arcnames = self._replay_selection()
        else:
            contents, marker_arcnames = self._category_selection()
        cache_arc = self._cache_arcname()
        if cache_arc and cache_arc not in contents:
            contents.append(cache_arc)
        return contents, marker_arcnames

    def _cache_arcname(self):
        # type: () -> Optional[str]
        """The scene-thumbnail mapping arcname when a cache exists on disk,
        else None.  Exports snapshot whatever mapping the game has downloaded
        -- never fabricate thumbnails it hasn't got."""
        rel = _cue_thumbs_cache_rel()
        if os.path.isfile(os.path.join(self._paths.original_root, rel.replace("/", os.sep))):
            return rel
        return None

    def _category_selection(self):
        # type: () -> Tuple[List[str], List[str]]
        """Whole-game selection: every enabled category in scope, plus the full
        marker list (all markers are in scope in whole-game mode)."""
        marker_arcnames = list(self.contents_by_category.get(CueImportCategory.MARKERS, []))
        selected = []
        for cat in CUE_IMPORT_CATEGORY_ORDER:
            if not self.is_category_enabled(cat):
                continue
            if self.file_types == CueExportFileTypes.SPECIFIC:
                if not self.is_checked(cat):
                    continue
            selected.extend(self.contents_by_category.get(cat, []))
        return selected, marker_arcnames

    def _replay_selection(self):
        # type: () -> Tuple[List[str], List[str]]
        """Replay selection: markers + referenced assets for the checked
        replays, plus the markers themselves as the bake targets.  The
        file-types filter prunes whole categories, same as whole-game."""
        labels = sorted(self.checked_replays)
        if not labels:
            return [], []
        per_cat, _ext = _cue_replay_assets_full(self._paths.original_root, self._paths.game_id, labels)
        marker_arcnames = list(per_cat.get(CueImportCategory.MARKERS, []))
        selected = []
        for cat in CUE_IMPORT_CATEGORY_ORDER:
            if self.file_types == CueExportFileTypes.SPECIFIC:
                if not self.is_checked(cat):
                    continue
            selected.extend(per_cat.get(cat, []))
        return selected, marker_arcnames

    def allowed_categories(self):
        # type: () -> Set[int]
        """CueImportCategory values the current export is allowed to pack.
        Everything in All File Types mode; only the checked categories in
        Specific mode.  The external bake honors this so an unchecked category
        never sneaks its media (or ref rewrite) into the zip."""
        if self.file_types == CueExportFileTypes.ALL:
            return set(CUE_IMPORT_CATEGORY_ORDER)
        return set(cat for cat in CUE_IMPORT_CATEGORY_ORDER if self.is_checked(cat))

    def clear_status(self):
        # type: () -> None
        self.export_status = ""
        self.export_error = ""

    # ------------------------------------------------------------------
    # export -- the zip build runs on a background thread so a large import
    # doesn't freeze the game; the UI polls is_exporting / export_fraction
    # ------------------------------------------------------------------

    def export(self):
        # type: () -> None
        """Kick off an import zip build for the current scope.  Content
        selection, the name, and the collision-safe path are resolved here on
        the UI thread (so an empty selection errors immediately); only the zip
        write happens off-thread.  Name defaults to the game_id; an existing
        file gets a ' (N)' collision suffix."""
        if self.is_exporting:
            return
        self.clear_status()
        selected, marker_arcnames = self._selection()

        if not selected:
            self.export_error = "Nothing selected to export."
            return
        base = self.name.strip() or self._paths.game_id
        safe = _cue_sanitize_filename(base)
        exports_dir = self._paths.exports_dir

        if not os.path.isdir(exports_dir):
            os.makedirs(exports_dir)
        zip_path = os.path.join(exports_dir, safe + ".zip")
        suffix = 2

        while os.path.exists(zip_path):
            zip_path = os.path.join(exports_dir, "{} ({}).zip".format(safe, suffix))
            suffix += 1

        # Snapshot name/author/description so mid-build edits to the form
        # can't corrupt the manifest the thread is writing.
        name = self.name
        author = self.author
        description = self.description
        self.is_exporting = True
        self.export_fraction = 0.0

        thread = threading.Thread(
            target=self._build_zip_thread, args=(selected, marker_arcnames, zip_path, name, author, description)
        )
        thread.daemon = True
        self._export_thread = thread
        thread.start()

    def _build_zip_thread(self, contents, marker_arcnames, zip_path, name, author, description):
        # type: (Any, Any, str, str, str, str) -> None
        """The off-thread zip write.  Sets export_status / export_error and
        clears is_exporting when done; a failure mid-write is caught and
        reported (the .tmp it was writing is left for the next build to
        overwrite).  External refs are baked first (copy to a portable
        relative namespace + rewrite the marker JSONs) so the recipient's
        import needs no knowledge of the exporter's absolute paths."""
        try:
            extra_roots = _cue_external_roots(self._paths.shared_config_path)
            add_contents, overrides, rewrites = _cue_external_bake(
                self._paths.original_root, self._paths.game_id, marker_arcnames, extra_roots, self.allowed_categories()
            )
            full = list(contents)
            for arc in add_contents:
                if arc not in full:
                    full.append(arc)
            _cue_build_import_zip(
                self._paths.original_root,
                self._paths.game_id,
                name,
                author,
                description,
                full,
                zip_path,
                progress=self._set_export_progress,
                overrides=overrides,
                rewrites=rewrites,
            )
        except Exception as e:
            self.export_error = "Export failed: {}".format(e)
        else:
            self.export_status = "Exported to {}.".format(zip_path)
        finally:
            self.is_exporting = False

    def _set_export_progress(self, written, total):
        # type: (int, int) -> None
        self.export_fraction = (written / float(total)) if total else 1.0

    def export_replay(self, label):
        # type: (str) -> None
        """One-click replay export: scope to replays, check only this one,
        and export now.  Names the import after the replay when the Name
        field is empty."""
        if self.is_exporting:
            return
        self.scope = CueExportScope.SPECIFIC_REPLAYS
        self.checked_replays = set([label])
        if not self.name.strip():
            self.name = label
        self.export()
