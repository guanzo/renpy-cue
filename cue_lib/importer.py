# -*- coding: utf-8 -*-
# cue_lib/importer.py -- the import side: scans imports/*.zip, activates one
# as a root-swap overlay, and merges selected categories.
#
# CueImportManager owns the imports list (scanned from imports/*.zip), the
# Activate root-swap overlay, and the Merge flow.  It depends only on
# importer_io (pure logic/IO) + db/paths/backup/state -- never runtime -- so
# the overlay refresh is constructor-injected from cue_z.rpy init -900.

import os
import shutil as _shutil
import threading

from renpy.store import Function

from cue_lib.constants import (
    CUE_IMPORT_DIR,
    CUE_IMPORT_UNZIP_DIR,
    CUE_IMPORT_MANIFEST_NAME,
    CueImportMatch,
)
from cue_lib.db import _atomic_json_write
from cue_lib.importer_io import (
    _cue_extract_import_zip,
    _cue_filter_contents,
    _cue_load_manifest,
    _cue_merge_files,
    _cue_missing_files,
    _cue_import_match,
    _cue_validate_manifest,
    _cue_zip_file_names,
)
from cue_lib.state import _cue
from cue_lib.util import _cue_log

MYPY = False
if MYPY:
    from typing import Any, Callable, List, Optional, Tuple  # pyright: ignore[reportUnusedImport]


def _imp_file_names(imp_dir):
    # type: (str) -> set
    """Set of every file under imp_dir as a '/' relative path -- the merge
    source list."""
    result = set()
    for dirpath, _dirs, names in os.walk(imp_dir):
        for name in names:
            rel = os.path.relpath(
                os.path.join(dirpath, name), imp_dir).replace("\\", "/")
            result.add(rel)
    return result


def _cue_rename_if_exists(src, dst):
    # type: (str, str) -> None
    """Rename the folder src to dst only if src exists and dst is free --
    remap must never clobber a folder the user already has."""
    if not os.path.isdir(src):
        return
    if os.path.isdir(dst) or os.path.isfile(dst):
        return
    _shutil.move(src, dst)


def _cue_rewrite_rel(rel, old_gid, new_gid):
    # type: (str, str, str) -> str
    """Rewrite a content path whose game-namespaced folder changed name.
    Only markers and speed-variant videos carry the game_id; presets and
    media live under shared, un-namespaced prefixes and are untouched."""
    marker = "data/markers/{}/".format(old_gid)
    if rel.startswith(marker):
        return "data/markers/{}/{}".format(new_gid, rel[len(marker):])
    video = "video/{}/".format(old_gid)
    if rel.startswith(video):
        return "video/{}/{}".format(new_gid, rel[len(video):])
    return rel


def _zip_mtime(zip_path):
    # type: (str) -> float
    """Last-modified time of a dropped zip -- the recency sort key.  A missing
    or unreadable file sorts as 0 (oldest), never raises mid-scan."""
    try:
        return os.path.getmtime(zip_path)
    except Exception:
        return 0.0


class CueImportManager(object):
    """Scans imports/*.zip, activates an import as a root-swap overlay, and
    merges selected categories into the real data tree."""

    def __init__(self, paths, db, refresh_overlay):
        # type: (Any, Any, Callable[[], None]) -> None
        self._paths = paths
        self._db = db
        self._refresh_overlay = refresh_overlay
        self.imports = []          # list of entry dicts (see _build_entry)
        self.scan_error = ""
        self.is_active = False
        self.active_import = None  # type: Optional[str]
        self.merge_status = ""
        self.is_scanning = False    # a background scan pass is running
        self._scan_thread = None    # type: Any
        self.is_importing = False   # the worker is extracting right now
        self.import_label = ""      # zip name currently being extracted
        self.import_fraction = 0.0  # 0..1 progress of the active extraction

    # ------------------------------------------------------------------
    # scanning
    # ------------------------------------------------------------------

    def imports_dir(self):
        # type: () -> str
        """Where dropped .zips live -- always under original_root, never the
        active import, so activation can't hide the import folder."""
        return os.path.join(
            self._paths.original_root, CUE_IMPORT_DIR).replace("\\", "/")

    def imports_unzip_dir(self):
        # type: () -> str
        """Where dropped zips are extracted into editable working copies --
        imports/ stays archives-only, so the drop zone isn't cluttered."""
        return os.path.join(
            self.imports_dir(), CUE_IMPORT_UNZIP_DIR).replace("\\", "/")

    def _imp_dir(self, imp):
        # type: (str) -> str
        """The extracted working folder for one import."""
        return os.path.join(self.imports_unzip_dir(), imp)

    def scan(self):
        # type: () -> None
        """Request a background scan.  The worker thread does all the disk
        work -- listing, extraction, manifest reads, zip listing -- so the UI
        thread never blocks on it.  The page keeps showing the last snapshot
        until the worker swaps a fresh one in, which the next poll displays.
        Idempotent and safe to call on every poll: no-op while a pass runs."""
        self._kick_scan_thread()

    def _kick_scan_thread(self):
        # type: () -> None
        """Start one daemon scan worker if none is running.  A poll that lands
        mid-pass is dropped; the next poll starts a fresh pass over whatever
        the last one left behind."""
        if self.is_scanning:
            return
        self.is_scanning = True
        thread = threading.Thread(target=self._scan_worker)
        thread.daemon = True
        self._scan_thread = thread
        thread.start()

    def _scan_worker(self):
        # type: () -> None
        """The background scan pass.  Any failure is logged and the previous
        snapshot stays put rather than a half-built one."""
        try:
            self._do_scan()
        except Exception as e:
            _cue_log("IMPORT: scan failed: {}".format(e))
        finally:
            self.is_scanning = False
            self._scan_thread = None
            self.is_importing = False
            self.import_label = ""
            self.import_fraction = 0.0

    def _do_scan(self):
        # type: () -> None
        """The full scan, run entirely off the UI thread: list the drop zone,
        extract zips that have no working copy yet, and build an entry for
        every zip (manifest read, game match).  The snapshot is swapped in with
        a single attribute write, so the UI only ever sees a consistent list."""
        imports = []
        imports_dir = self.imports_dir()
        try:
            if not os.path.isdir(imports_dir):
                os.makedirs(imports_dir)
            unzip_dir = self.imports_unzip_dir()
            if not os.path.isdir(unzip_dir):
                os.makedirs(unzip_dir)
            names = sorted(os.listdir(imports_dir))
        except Exception as e:
            self.scan_error = "Could not read {}: {}".format(imports_dir, e)
            return
        for name in names:
            if not name.endswith(".zip"):
                continue
            imp_name = name[:-len(".zip")]
            imp_dir = self._imp_dir(imp_name)
            zip_path = os.path.join(imports_dir, name)
            if not os.path.isdir(imp_dir):
                # New zip -- extract it here (progress feeds the page), so the
                # UI thread never does the heavy work.  A failure is a
                # per-import error row, retried on the next pass once the copy
                # finishes.
                self.is_importing = True
                self.import_label = name
                self.import_fraction = 0.0
                try:
                    _cue_extract_import_zip(
                        zip_path, imp_dir, progress=self._set_import_progress)
                except Exception as e:
                    _cue_log("IMPORT: failed to extract {}: {}".format(name, e))
                    imports.append(self._error_entry(
                        imp_name, name, _zip_mtime(zip_path),
                        "This import could not be extracted."))
                    continue
                finally:
                    self.is_importing = False
                    self.import_label = ""
                    self.import_fraction = 0.0
            imports.append(self._build_entry(imp_name, name, imp_dir, zip_path))
        imports.sort(key=self._sort_key)
        self.imports = imports
        self.scan_error = ""

    def _error_entry(self, imp_name, zip_name, mtime, error):
        # type: (str, str, float, str) -> dict
        return {
            "imp": imp_name,
            "zip": zip_name,
            "name": imp_name,
            "author": "",
            "description": "",
            "game_id": "",
            "contents": [],
            "match": CueImportMatch.MISMATCH,
            "match_reason": "",
            "valid": False,
            "missing": [],
            "error": error,
            "mtime": mtime,
        }

    def _build_entry(self, imp_name, zip_name, imp_dir, zip_path):
        # type: (str, str, str, str) -> dict
        manifest = _cue_load_manifest(imp_dir)
        zip_names = _cue_zip_file_names(zip_path)
        ok, err = _cue_validate_manifest(manifest, zip_names)
        if not ok:
            return self._error_entry(
                imp_name, zip_name, _zip_mtime(zip_path), err)
        match, reason = _cue_import_match(
            self._paths.game_id, manifest.get("game_id", ""))
        return {
            "imp": imp_name,
            "zip": zip_name,
            "name": manifest.get("name") or imp_name,
            "author": manifest.get("author") or "",
            "description": manifest.get("description") or "",
            "game_id": manifest.get("game_id") or "",
            "contents": list(manifest.get("contents") or []),
            "match": match,
            "match_reason": reason,
            "valid": True,
            "missing": _cue_missing_files(manifest, zip_names),
            "error": "",
            "mtime": _zip_mtime(zip_path),
        }

    def _set_import_progress(self, written, total):
        # type: (int, int) -> None
        self.import_fraction = (written / float(total)) if total else 1.0

    def _sort_key(self, entry):
        # type: (dict) -> Tuple[int, float]
        """Order the import list: exact matches for this game first, then
        near-matches, then mismatches, then broken rows at the bottom (an
        error entry isn't 'the wrong game', it's unreadable -- it belongs
        last).  Within a tier, most recently dropped imports come first."""
        if entry.get("valid"):
            rank = entry.get("match", CueImportMatch.MISMATCH)
        else:
            rank = CueImportMatch.MISMATCH + 1
        return (rank, -(entry.get("mtime") or 0.0))

    def import_for(self, imp):
        # type: (str) -> Optional[dict]
        for entry in self.imports:
            if entry["imp"] == imp:
                return entry
        return None

    def active_import_name(self):
        # type: () -> str
        if not self.is_active or not self.active_import:
            return ""
        entry = self.import_for(self.active_import)
        if entry:
            return entry["name"]
        return self.active_import

    def match_label(self, imp):
        # type: (str) -> str
        """Status for an import row.  Empty when there's nothing to say -- a
        import that already matches this game needs no attention.  Any
        mismatch shows the same reminder with both game ids: the user decides
        whether it's really this game, then Remap rehomes it."""
        entry = self.import_for(imp)
        if entry is None:
            return ""
        if not entry["valid"]:
            return entry["error"]
        if entry["match"] == CueImportMatch.AUTO:
            return ""
        return ("Game ID mismatch.\nCheck if it's really the same game, then click Remap.\n\n"
                "Current Game ID: {}\n"
                "Import Game ID: {}").format(
                    self._paths.game_id, entry.get("game_id") or "")

    # ------------------------------------------------------------------
    # activate / deactivate -- root-swap overlay
    # ------------------------------------------------------------------

    def activate(self, imp):
        # type: (str) -> None
        """Serve the whole editor from the import's extracted folder instead
        of live data.  Refuses invalid imports and any import that isn't
        exactly this game yet (remap first -- the import's markers/videos
        live under its own game_id until then); an import whose zip is missing
        manifest-listed files asks first, then activates on confirm."""
        if self.is_active:
            return
        entry = self.import_for(imp)
        if entry is None or not entry["valid"]:
            return
        if entry["match"] != CueImportMatch.AUTO:
            return
        if entry.get("missing"):
            self._confirm_missing_activate(imp)
            return
        self._do_activate(imp)

    def _confirm_missing_activate(self, imp):
        # type: (str) -> None
        """Warn that the zip is missing manifest-listed files, then activate
        on confirm.  The missing files simply won't play."""
        entry = self.import_for(imp)
        if entry is None:
            return
        missing = entry.get("missing") or []
        listing = "\n".join("  " + m for m in missing)
        message = (
            "The zip is missing {} file(s) listed in its manifest:\n\n"
            "{}\n\nThose files won't be there.  Activate anyway?").format(
                len(missing), listing)
        _cue.dialogs.confirm.show(message, Function(self._do_activate, imp))

    def _do_activate(self, imp):
        # type: (str) -> None
        """The actual root swap, shared by activate() and the confirm dialog."""
        if self.is_active:
            return
        entry = self.import_for(imp)
        if entry is None or not entry["valid"]:
            return
        if entry["match"] == CueImportMatch.MISMATCH:
            return
        imp_dir = self._imp_dir(imp)
        if not os.path.isdir(imp_dir):
            return
        self._paths._active_root = imp_dir
        self.is_active = True
        self.active_import = imp
        self._refresh_overlay()

    def deactivate(self):
        # type: () -> None
        """Drop the overlay back to the live data tree."""
        self._paths._active_root = None
        self.is_active = False
        self.active_import = None
        self._refresh_overlay()

    # ------------------------------------------------------------------
    # remap -- bring a CONFIRM import to this game's namespaced folders
    # ------------------------------------------------------------------

    def remap(self, imp):
        # type: (str) -> None
        """Rename the import's game-namespaced folders (data/markers/<old>/
        and video/<old>/) to this game, then rewrite the manifest's contents
        list and game_id.  Markers are never rewritten -- only rehomed."""
        entry = self.import_for(imp)
        if entry is None:
            return
        old_gid = entry.get("game_id", "")
        new_gid = self._paths.game_id
        
        if not old_gid or old_gid == new_gid:
            return
        imp_dir = self._imp_dir(imp)

        _cue_rename_if_exists(
            os.path.join(imp_dir, "data", "markers", old_gid),
            os.path.join(imp_dir, "data", "markers", new_gid))
        
        _cue_rename_if_exists(
            os.path.join(imp_dir, "video", old_gid),
            os.path.join(imp_dir, "video", new_gid))
        manifest = _cue_load_manifest(imp_dir)

        if isinstance(manifest, dict) and manifest.get("game_id") == old_gid:
            manifest["game_id"] = new_gid
            manifest["contents"] = [
                _cue_rewrite_rel(rel, old_gid, new_gid)
                for rel in (manifest.get("contents") or [])
            ]
            _atomic_json_write(
                os.path.join(imp_dir, CUE_IMPORT_MANIFEST_NAME),
                manifest,
                indent=2)
        self.scan()

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------

    def confirm_delete(self, imp):
        # type: (str) -> None
        entry = self.import_for(imp)
        if entry is None:
            return
        _cue.dialogs.confirm.show(
            "Delete import '{}'?  The .zip and its extracted folder are "
            "removed.".format(entry["name"]),
            Function(self.delete_confirmed, imp),
        )

    def delete_confirmed(self, imp):
        # type: (str) -> None
        if self.is_active and self.active_import == imp:
            self.deactivate()
        entry = self.import_for(imp)
        zip_path = None
        if entry:
            zip_path = os.path.join(self.imports_dir(), entry["zip"])
        imp_dir = self._imp_dir(imp)
        _shutil.rmtree(imp_dir, ignore_errors=True)
        if zip_path and os.path.isfile(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        self.scan()

    # ------------------------------------------------------------------
    # merge -- filesystem-only, import stays intact
    # ------------------------------------------------------------------

    def folder_files(self, imp):
        # type: (str) -> List[str]
        """Every file in the extracted import folder as '/' relative paths.
        The merge source: walks the folder rather than trusting the manifest,
        so files added during an active edit session are mergeable."""
        if not imp:
            return []
        imp_dir = self._imp_dir(imp)
        if not os.path.isdir(imp_dir):
            return []
        return sorted(_imp_file_names(imp_dir))

    def open_merge(self, imp):
        # type: (str) -> None
        entry = self.import_for(imp)
        if entry is None or not entry["valid"]:
            return
        if entry["match"] != CueImportMatch.AUTO:
            return
        _cue.dialogs.merge.open(imp)

    def merge_confirm(self, imp, checked):
        # type: (str, Any) -> None
        """Copy the selected categories from the extracted import into the
        real data tree (original_root).  No overlay change -- activation is a
        separate, explicit choice."""
        entry = self.import_for(imp)
        if entry is None or not entry["valid"]:
            return
        if entry["match"] != CueImportMatch.AUTO:
            self.merge_status = ("This import isn't remapped to this game "
                                 "yet.  Remap it first.")
            return
        filtered = _cue_filter_contents(self.folder_files(imp), checked)
        if not filtered:
            self.merge_status = "Nothing selected to merge."
            return
        src_root = self._imp_dir(imp)
        count = _cue_merge_files(self._paths.original_root, src_root, filtered)
        self.merge_status = "Merged {} file(s) into your data.".format(count)
