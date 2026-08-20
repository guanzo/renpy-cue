# -*- coding: utf-8 -*-
# Tests for cue_lib.importer -- CueImportManager: scan/auto-extract, match
# surfacing, activate/deactivate root swap, remap, delete, merge.
#
# scan() runs the whole pass (listing, extraction, manifest reads, entry
# build) on a single background worker.  The import_threads fixture records
# every Thread so tests drive the worker body synchronously via _scan_and_join.

import os
import types
import zipfile

import pytest

import cue_lib.importer as _imports
from cue_lib import importer_io as _imp
from cue_lib.constants import (
    CUE_IMPORT_DIR,
    CUE_IMPORT_UNZIP_DIR,
    CueImportCategory,
    CueImportMatch,
)
from cue_lib.importer import CueImportManager

GAME_ID = "test_game"


@pytest.fixture
def imp_cue(monkeypatch):
    """Replaces imports._cue with a fake confirm dialog recording shows."""
    shown = []

    def _show(message, action):
        shown.append((message, action))

    fake = types.SimpleNamespace(
        dialogs=types.SimpleNamespace(
            confirm=types.SimpleNamespace(show=_show),
            merge=None))
    monkeypatch.setattr(_imports, "_cue", fake)
    return shown


def _entry(imp="pack", match=CueImportMatch.CONFIRM, reason="x",
           valid=True, game_id="other"):
    return {
        "imp": imp, "zip": imp + ".zip", "name": "Pack", "author": "",
        "description": "", "game_id": game_id, "contents": ["audio/a.ogg"],
        "match": match, "match_reason": reason, "valid": valid,
        "missing": [], "error": "",
    }


def _write(root, rel, content):
    path = os.path.join(root, *rel.split("/"))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as f:
        f.write(content)
    return path


def _unzip_dir(tmp_path):
    """Extracted working copies live under imports/unzipped/ -- the drop
    zone (imports/) holds archives only."""
    return os.path.join(
        str(tmp_path / "cue_root"), CUE_IMPORT_DIR, CUE_IMPORT_UNZIP_DIR)


def _drop_package(tmp_path, game_id, files, zip_name="pack.zip"):
    """Build a package zip from a source tree and drop it into imports/."""
    src = str(tmp_path / "src")
    for rel, content in files:
        _write(src, rel, content)
    flat = []
    for fs in _imp._cue_enumerate_import_files(src, game_id).values():
        flat.extend(fs)
    imports_dir = os.path.join(str(tmp_path / "cue_root"), CUE_IMPORT_DIR)
    if not os.path.isdir(imports_dir):
        os.makedirs(imports_dir)
    zip_path = os.path.join(imports_dir, zip_name)
    _imp._cue_build_import_zip(src, game_id, "My pack", "author", "desc", flat, zip_path)
    return imports_dir, zip_path


def _make_mgr(cue_env):
    calls = []

    def _refresh():
        calls.append(1)

    mgr = CueImportManager(cue_env.paths, cue_env.db, _refresh)
    return mgr, calls


class _FakeThread(object):
    """Records the thread body without running it -- lets tests drive the
    worker synchronously and assert on the wiring (daemon, deferral)."""

    def __init__(self, target=None, args=()):
        self.target = target
        self.args = args
        self.daemon = False
        self.started = False
        self.joined = False

    def start(self):
        self.started = True


@pytest.fixture
def import_threads(monkeypatch):
    """Patch Thread with a recording factory so scan()'s background worker is
    deferred instead of run live.  Returns (created, _join); _join() runs every
    recorded thread body inline once, so tests can drive the worker
    synchronously."""
    created = []

    def _factory(**kw):
        t = _FakeThread(**kw)
        created.append(t)
        return t

    monkeypatch.setattr(_imports.threading, "Thread", _factory)

    def _join():
        for t in created:
            if t.started and not t.joined:
                t.joined = True
                t.target()

    return created, _join


def _scan_and_join(mgr, import_threads):
    """scan() kicks a background worker; the worker extracts, builds entries,
    and swaps the snapshot in.  This helper drives that one pass synchronously."""
    _created, _join = import_threads
    mgr.scan()
    _join()


# ---------------------------------------------------------------------------
# scan -- background auto-extract + entry build
# ---------------------------------------------------------------------------

def test_scan_auto_extracts_and_lists(cue_env, tmp_path, import_threads):
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [
        ("audio/sfx.ogg", "sfx"),
        ("data/markers/{}/v_a.json".format(GAME_ID), '{"pools": []}'),
    ])

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert len(mgr.imports) == 1
    entry = mgr.imports[0]
    assert entry["imp"] == "pack"
    assert entry["zip"] == "pack.zip"
    assert entry["valid"] is True
    assert entry["name"] == "My pack"
    assert entry["author"] == "author"
    assert entry["game_id"] == GAME_ID
    assert entry["match"] == CueImportMatch.AUTO
    assert os.path.isdir(os.path.join(_unzip_dir(tmp_path), "pack"))
    assert os.path.isfile(os.path.join(_unzip_dir(tmp_path), "pack", "manifest.json"))
    # drop zone stays archives-only -- extracted copies live in imports/unzipped/
    assert not os.path.exists(os.path.join(imports_dir, "pack"))


def test_scan_reuses_existing_extract(cue_env, tmp_path, import_threads):
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [
        ("audio/sfx.ogg", "sfx"),
    ])
    # Manually "extract" first; scan must not re-extract or clobber.
    unzip_dir = _unzip_dir(tmp_path)
    marker = os.path.join(unzip_dir, "pack", "data", "markers", GAME_ID, "mine.json")
    _write(unzip_dir, "pack/data/markers/{}/mine.json".format(GAME_ID), '{}')

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert len(mgr.imports) == 1
    assert mgr.imports[0]["imp"] == "pack"
    assert os.path.isfile(marker)  # untouched by scan


def test_scan_flags_wrong_game_mismatch(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, "other-game", [
        ("audio/sfx.ogg", "sfx"),
        ("data/markers/other-game/v_a.json", '{}'),
    ])

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    entry = mgr.imports[0]
    assert entry["match"] == CueImportMatch.MISMATCH
    assert entry["valid"] is True


def test_match_label_mismatch_shows_both_game_ids(cue_env, tmp_path,
                                                  import_threads):
    _drop_package(tmp_path, "other-game", [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    status = mgr.match_label(imp)

    assert "Game ID mismatch" in status
    assert "Current Game ID: {}".format(GAME_ID) in status
    assert "Import Game ID: other-game" in status


def test_match_label_confirm_shows_same_mismatch_text(cue_env, tmp_path,
                                                      import_threads):
    # A probable-same-game package gets the same status as a hard mismatch.
    # The "probably the same game" guess is dropped from the row; Remap is
    # still the one action that confirms it.
    _drop_package(tmp_path, "test_game456", [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert mgr.imports[0]["match"] == CueImportMatch.CONFIRM
    status = mgr.match_label(mgr.imports[0]["imp"])

    assert "Import Game ID: test_game456" in status
    assert "Looks like the same game" not in status


def test_scan_marks_newer_format_invalid(cue_env, tmp_path, import_threads):
    imports_dir = os.path.join(str(tmp_path / "cue_root"), CUE_IMPORT_DIR)
    os.makedirs(imports_dir)
    zip_path = os.path.join(imports_dir, "bad.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json",
                    '{"format_version": 999, "game_id": "x", "contents": []}')

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    entry = mgr.imports[0]
    assert entry["valid"] is False
    assert "newer" in entry["error"]


def test_scan_flags_missing_files_not_invalid(cue_env, tmp_path, import_threads):
    imports_dir = os.path.join(str(tmp_path / "cue_root"), CUE_IMPORT_DIR)
    os.makedirs(imports_dir)
    with zipfile.ZipFile(os.path.join(imports_dir, "bad.zip"), "w") as zf:
        zf.writestr("manifest.json",
                    '{"format_version": 1, "game_id": "x", "contents": ["audio/nope.ogg"]}')

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    entry = mgr.imports[0]
    assert entry["valid"] is True
    assert entry["missing"] == ["audio/nope.ogg"]
    assert entry["error"] == ""


# ---------------------------------------------------------------------------
# scan -- list ordering: most likely to be this game first, then recency
# ---------------------------------------------------------------------------

def test_scan_sorts_exact_then_confirm_then_mismatch(cue_env, tmp_path,
                                                     import_threads):
    # Exact matches for this game on top, near-matches next, mismatches below.
    _drop_package(tmp_path, GAME_ID, [("audio/a.ogg", "a")],
                  zip_name="exact.zip")
    _drop_package(tmp_path, "test_game456", [("audio/b.ogg", "b")],
                  zip_name="confirm.zip")
    _drop_package(tmp_path, "other-game", [("audio/c.ogg", "c")],
                  zip_name="mismatch.zip")

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert [e["imp"] for e in mgr.imports] == \
        ["exact", "confirm", "mismatch"]


def test_scan_sorts_recent_drop_first_within_tier(cue_env, tmp_path,
                                                  import_threads):
    # Secondary key: the most recently dropped zip leads its tier.
    _drop_package(tmp_path, GAME_ID, [("audio/a.ogg", "a")],
                  zip_name="old.zip")
    _drop_package(tmp_path, GAME_ID, [("audio/b.ogg", "b")],
                  zip_name="new.zip")
    imports_dir = os.path.join(str(tmp_path / "cue_root"), CUE_IMPORT_DIR)
    os.utime(os.path.join(imports_dir, "old.zip"), (1000, 1000))
    os.utime(os.path.join(imports_dir, "new.zip"), (2000, 2000))

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert [e["imp"] for e in mgr.imports] == ["new", "old"]


def test_scan_sorts_error_rows_last(cue_env, tmp_path, import_threads):
    # A broken zip isn't 'the wrong game' -- it sinks below every match tier.
    _drop_package(tmp_path, "other-game", [("audio/c.ogg", "c")],
                  zip_name="mismatch.zip")
    imports_dir = os.path.join(str(tmp_path / "cue_root"), CUE_IMPORT_DIR)
    _write(imports_dir, "corrupt.zip", "not a zip at all")

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert [e["imp"] for e in mgr.imports] == ["mismatch", "corrupt"]


# ---------------------------------------------------------------------------
# scan -- the background worker: deferral, progress, failure
# ---------------------------------------------------------------------------

def test_scan_defers_all_work_until_background_thread(cue_env, tmp_path,
                                                      import_threads):
    _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    created, _join = import_threads

    mgr.scan()

    # scan() only kicked a daemon worker -- nothing has been extracted and the
    # snapshot is still the previous one.
    assert mgr.imports == []
    assert mgr.is_scanning is True
    assert mgr.is_importing is False
    assert len(created) == 1
    t = created[0]
    assert t.daemon is True
    assert t.started is True
    assert not os.path.isdir(os.path.join(_unzip_dir(tmp_path), "pack"))

    # Run the worker body: extraction + entry build + snapshot swap.
    _join()

    assert len(mgr.imports) == 1
    assert mgr.imports[0]["valid"] is True
    assert mgr.is_scanning is False
    assert os.path.isdir(os.path.join(_unzip_dir(tmp_path), "pack"))


def test_scan_is_noop_while_worker_runs(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    created, _join = import_threads

    mgr.scan()
    mgr.scan()  # the 3s poll re-fires while a pass is in flight

    assert len(created) == 1  # one daemon worker, no stacked passes
    assert mgr.is_scanning is True


def test_corrupt_zip_shows_error_and_retries_next_pass(cue_env, tmp_path,
                                                       import_threads):
    imports_dir = os.path.join(str(tmp_path / "cue_root"), CUE_IMPORT_DIR)
    _write(imports_dir, "corrupt.zip", "not a zip at all")
    mgr, _calls = _make_mgr(cue_env)
    created, _join = import_threads

    mgr.scan()
    _join()

    entry = mgr.imports[0]
    assert entry["valid"] is False
    assert "could not be extracted" in entry["error"]

    # Not cached: the next poll starts a fresh pass that re-attempts the
    # failing zip (a still-copying archive self-heals once the copy lands),
    # still failing fast.
    mgr.scan()
    _join()

    assert len(created) == 2
    assert mgr.imports[0]["error"]
    assert mgr.is_scanning is False


def test_import_progress_callback_reports_fraction(cue_env, import_threads):
    mgr, _calls = _make_mgr(cue_env)

    assert mgr.import_fraction == 0.0
    mgr._set_import_progress(3, 10)
    assert mgr.import_fraction == 0.3
    mgr._set_import_progress(10, 10)
    assert mgr.import_fraction == 1.0
    mgr._set_import_progress(0, 0)
    assert mgr.import_fraction == 1.0


# ---------------------------------------------------------------------------
# folder walk -- merge source is the folder, not the manifest
# ---------------------------------------------------------------------------

def test_folder_files_walks_extract(cue_env, tmp_path, import_threads):
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    _write(_unzip_dir(tmp_path), "pack/audio/extra.ogg", "new")

    files = mgr.folder_files("pack")

    assert "audio/sfx.ogg" in files
    assert "audio/extra.ogg" in files
    assert "manifest.json" in files


def test_merge_confirm_walks_folder_not_manifest(cue_env, tmp_path, import_threads):
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [
        ("audio/sfx.ogg", "sfx"),
        ("music/song.ogg", "music"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    # Add a file to the extracted folder the manifest never listed -- the
    # folder walk must pick it up even though it is absent from contents.
    _write(_unzip_dir(tmp_path), "pack/audio/new.ogg", "added")
    original_root = str(tmp_path / "cue_root")

    mgr.merge_confirm(imp, [CueImportCategory.SFX])

    assert os.path.isfile(os.path.join(original_root, "audio", "sfx.ogg"))
    assert os.path.isfile(os.path.join(original_root, "audio", "new.ogg"))
    assert not os.path.exists(os.path.join(original_root, "music", "song.ogg"))
    assert "Merged 2 file(s)" in mgr.merge_status


# ---------------------------------------------------------------------------
# activate / deactivate -- root swap + backup pause
# ---------------------------------------------------------------------------

def test_activate_swaps_root_and_pauses_backup(cue_env, tmp_path, import_threads):
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    mgr.activate(imp)

    assert mgr.is_active is True
    assert mgr.active_import == imp
    expected = os.path.join(_unzip_dir(tmp_path), imp)
    assert cue_env.paths._active_root == expected
    assert cue_env.paths.root == expected
    assert cue_env.paths.audio_dir == os.path.join(expected, "audio") + "/"
    assert cue_env.paths.shared_config_path == os.path.join(
        str(tmp_path / "cue_root"), "data", "cue_config.json")
    assert cue_env.db._backup._is_paused is True
    assert len(calls) == 1

    mgr.deactivate()

    assert cue_env.paths._active_root is None
    assert cue_env.paths.root == str(tmp_path / "cue_root")
    assert cue_env.db._backup._is_paused is False
    assert mgr.is_active is False
    assert mgr.active_import is None
    assert len(calls) == 2


def test_activate_refuses_mismatch(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, "other-game", [
        ("audio/sfx.ogg", "sfx"),
        ("data/markers/other-game/v_a.json", '{}'),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    mgr.activate(mgr.imports[0]["imp"])

    assert mgr.is_active is False
    assert cue_env.paths._active_root is None


def test_activate_refuses_confirm_until_remapped(cue_env, tmp_path,
                                                 import_threads):
    # A CONFIRM package (names match once version numbers are dropped) must be
    # remapped before it can be activated.  Its markers/videos live under the
    # import.s game_id, not ours, so the swap would show an empty import.
    _drop_package(tmp_path, "test_game456", [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert mgr.imports[0]["match"] == CueImportMatch.CONFIRM
    mgr.activate(mgr.imports[0]["imp"])

    assert mgr.is_active is False
    assert cue_env.paths._active_root is None


def test_activate_refuses_invalid(cue_env, tmp_path, import_threads):
    imports_dir = os.path.join(str(tmp_path / "cue_root"), CUE_IMPORT_DIR)
    os.makedirs(imports_dir)
    with zipfile.ZipFile(os.path.join(imports_dir, "bad.zip"), "w") as zf:
        zf.writestr("manifest.json", '{"format_version": 999, "contents": []}')
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    mgr.activate(mgr.imports[0]["imp"])

    assert mgr.is_active is False


def _drop_missing_files_package(tmp_path, game_id):
    """A zip whose manifest lists a file the archive doesn't carry."""
    imports_dir = os.path.join(str(tmp_path / "cue_root"), CUE_IMPORT_DIR)
    os.makedirs(imports_dir)
    with zipfile.ZipFile(os.path.join(imports_dir, "pack.zip"), "w") as zf:
        zf.writestr(
            "manifest.json",
            '{{"format_version": 1, "game_id": "{}", "contents": ["audio/nope.ogg"]}}'
            .format(game_id))
    return imports_dir


def test_activate_missing_files_confirms(cue_env, imp_cue, tmp_path,
                                         import_threads):
    imports_dir = _drop_missing_files_package(tmp_path, GAME_ID)
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    mgr.activate(imp)

    assert mgr.is_active is False
    assert cue_env.paths._active_root is None
    assert len(imp_cue) == 1
    message, _action = imp_cue[0]
    assert "audio/nope.ogg" in message
    assert "Activate anyway" in message


def test_do_activate_missing_files_swaps(cue_env, imp_cue, tmp_path,
                                         import_threads):
    imports_dir = _drop_missing_files_package(tmp_path, GAME_ID)
    mgr, calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    # The confirm dialog's action: proceed with the swap anyway.
    mgr._do_activate(imp)

    assert mgr.is_active is True
    assert cue_env.paths._active_root == os.path.join(_unzip_dir(tmp_path), imp)
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# remap -- 2-folder rename + manifest rewrite, never a marker rewrite
# ---------------------------------------------------------------------------

def test_remap_renames_folders_and_updates_manifest(cue_env, tmp_path,
                                                    import_threads):
    imports_dir, _zip_path = _drop_package(tmp_path, "other-game", [
        ("data/markers/other-game/v_a.json", '{"pools": []}'),
        ("video/other-game/m_cue0.5x.mkv", "v"),
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _created, _join = import_threads
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    mgr.remap(imp)  # kicks a scan internally
    _join()         # run it so the snapshot reflects the remap

    imp_dir = os.path.join(_unzip_dir(tmp_path), imp)
    assert os.path.isdir(os.path.join(imp_dir, "data", "markers", GAME_ID))
    assert not os.path.exists(os.path.join(imp_dir, "data", "markers", "other-game"))
    assert os.path.isdir(os.path.join(imp_dir, "video", GAME_ID))
    entry = mgr.import_for(imp)
    assert entry["game_id"] == GAME_ID
    assert entry["match"] == CueImportMatch.AUTO
    manifest = _imp._cue_load_manifest(imp_dir)
    assert manifest["game_id"] == GAME_ID
    assert "data/markers/{}/v_a.json".format(GAME_ID) in manifest["contents"]
    assert "video/{}/m_cue0.5x.mkv".format(GAME_ID) in manifest["contents"]
    assert "audio/sfx.ogg" in manifest["contents"]


def test_remap_noop_when_already_matched(cue_env, tmp_path, import_threads):
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    mgr.remap(imp)  # must not raise or rewrite

    manifest = _imp._cue_load_manifest(os.path.join(_unzip_dir(tmp_path), imp))
    assert manifest["game_id"] == GAME_ID


def test_activate_succeeds_after_remap(cue_env, tmp_path, import_threads):
    # The full user flow: a mismatched package is remapped (game_id rehomed to
    # this game), the rescan flips it to AUTO, and only then does activate work.
    # Audio-only package: no namespaced folders to rename, so the remap leaves
    # the manifest matching the zip and activate swaps without a confirm.
    _drop_package(tmp_path, "other-game", [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _created, _join = import_threads
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    assert mgr.imports[0]["match"] == CueImportMatch.MISMATCH

    mgr.remap(imp)  # kicks a scan internally
    _join()         # run it so the entry reflects the remap

    assert mgr.import_for(imp)["match"] == CueImportMatch.AUTO
    mgr.activate(imp)

    assert mgr.is_active is True
    assert cue_env.paths.root == os.path.join(_unzip_dir(tmp_path), imp)


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

def test_delete_confirmed_removes_dir_and_zip(cue_env, tmp_path, import_threads):
    imports_dir, zip_path = _drop_package(tmp_path, GAME_ID, [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _created, _join = import_threads
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    mgr.delete_confirmed(imp)  # kicks a scan internally
    _join()

    assert not os.path.exists(os.path.join(_unzip_dir(tmp_path), imp))
    assert not os.path.exists(zip_path)
    assert mgr.imports == []


def test_delete_confirmed_deactivates_if_active(cue_env, tmp_path, import_threads):
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, calls = _make_mgr(cue_env)
    _created, _join = import_threads
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    mgr.activate(imp)
    before = len(calls)

    mgr.delete_confirmed(imp)  # kicks a scan internally
    _join()

    assert mgr.is_active is False
    assert cue_env.paths._active_root is None
    assert not os.path.exists(os.path.join(_unzip_dir(tmp_path), imp))
    assert len(calls) > before


# ---------------------------------------------------------------------------
# merge -- filesystem-only, filtered by selected categories
# ---------------------------------------------------------------------------

def test_merge_confirm_copies_selected_only(cue_env, tmp_path, import_threads):
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [
        ("data/markers/{}/v_a.json".format(GAME_ID), '{"pools": []}'),
        ("audio/sfx.ogg", "sfx"),
        ("music/song.ogg", "music"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    original_root = str(tmp_path / "cue_root")

    mgr.merge_confirm(imp, [CueImportCategory.SFX])

    assert os.path.isfile(os.path.join(original_root, "audio", "sfx.ogg"))
    assert not os.path.exists(os.path.join(original_root, "music", "song.ogg"))
    assert "Merged 1 file(s)" in mgr.merge_status
    # Package stays intact (recovery without re-download).
    assert os.path.isfile(os.path.join(_unzip_dir(tmp_path), imp, "audio", "sfx.ogg"))


def test_merge_confirm_nothing_selected(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, GAME_ID, [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    mgr.merge_confirm(imp, [])

    assert "Nothing selected" in mgr.merge_status


def test_merge_confirm_refuses_mismatch(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, "other-game", [
        ("audio/sfx.ogg", "sfx"),
        ("data/markers/other-game/v_a.json", '{}'),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    original_root = str(tmp_path / "cue_root")

    mgr.merge_confirm(imp, [CueImportCategory.SFX])

    assert "Remap it first" in mgr.merge_status
    assert not os.path.exists(os.path.join(original_root, "audio", "sfx.ogg"))


def test_merge_confirm_refuses_confirm_until_remapped(cue_env, tmp_path,
                                                      import_threads):
    # Same gate as activate: a CONFIRM import must be remapped first, or the
    # namespaced files would merge under the import.s game_id and nothing
    # would read them.
    _drop_package(tmp_path, "test_game456", [
        ("audio/sfx.ogg", "sfx"),
    ])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    original_root = str(tmp_path / "cue_root")

    assert mgr.imports[0]["match"] == CueImportMatch.CONFIRM
    mgr.merge_confirm(imp, [CueImportCategory.SFX])

    assert "Remap it first" in mgr.merge_status
    assert not os.path.exists(os.path.join(original_root, "audio", "sfx.ogg"))


# ---------------------------------------------------------------------------
# confirm dialogs -- remap / delete
# ---------------------------------------------------------------------------

def test_confirm_delete_shows(cue_env, imp_cue):
    mgr, _calls = _make_mgr(cue_env)
    mgr.imports = [_entry()]

    mgr.confirm_delete("pack")

    assert len(imp_cue) == 1
    assert "Delete import" in imp_cue[0][0]


def test_confirm_delete_noop_unknown(cue_env, imp_cue):
    mgr, _calls = _make_mgr(cue_env)
    mgr.confirm_delete("pack")

    assert imp_cue == []
