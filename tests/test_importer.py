# -*- coding: utf-8 -*-
# Tests for cue_lib.sharing.importer -- CueImportManager: scan/auto-extract, match
# surfacing, activate/deactivate root swap, remap, delete, merge.
#
# scan() runs the whole pass (listing, extraction, manifest reads, entry
# build) on a single background worker.  The import_threads fixture records
# every Thread so tests drive the worker body synchronously via _scan_and_join.

import os
import types
import zipfile

import pytest

import cue_lib.sharing.importer as _imports
from cue_lib.sharing import importer_io as _imp
from cue_lib.constants import CueImportCategory, CueImportMatch
from cue_lib.sharing.importer import CueImportManager

GAME_ID = "test_game"


@pytest.fixture
def imp_cue(monkeypatch):
    """Replaces imports._cue with a fake confirm dialog recording shows."""
    shown = []

    def _show(message, action):
        shown.append((message, action))

    fake = types.SimpleNamespace(
        dialogs=types.SimpleNamespace(
            confirm=types.SimpleNamespace(show=_show, show_or_run=lambda message, action: _show(message, action)),
            merge=None,
        )
    )
    monkeypatch.setattr(_imports, "_cue", fake)
    return shown


def _entry(imp="pack", match=CueImportMatch.CONFIRM, reason="x", valid=True, game_id="other"):
    return {
        "imp": imp,
        "zip": imp + ".zip",
        "name": "Pack",
        "author": "",
        "description": "",
        "game_id": game_id,
        "contents": ["audio/a.ogg"],
        "match": match,
        "match_reason": reason,
        "valid": valid,
        "missing": [],
        "error": "",
        "replays": [],
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
    return os.path.join(str(tmp_path / "cue_root"), "imports", "unzipped")


def _drop_package(tmp_path, game_id, files, zip_name="pack.zip"):
    """Build a package zip from a source tree and drop it into imports/."""
    src = str(tmp_path / "src")
    for rel, content in files:
        _write(src, rel, content)
    flat = []
    for fs in _imp._cue_enumerate_import_files(src, game_id).values():
        flat.extend(fs)
    imports_dir = os.path.join(str(tmp_path / "cue_root"), "imports")
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
    imports_dir, _zip_path = _drop_package(
        tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx"), ("data/markers/{}/v_a.json".format(GAME_ID), '{"pools": []}')]
    )

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
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
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
    _drop_package(tmp_path, "other-game", [("audio/sfx.ogg", "sfx"), ("data/markers/other-game/v_a.json", '{}')])

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    entry = mgr.imports[0]
    assert entry["match"] == CueImportMatch.MISMATCH
    assert entry["valid"] is True


def test_match_label_mismatch_shows_both_game_ids(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, "other-game", [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    assert mgr.match_label(imp) == "Potential problem"
    warnings = mgr.match_warnings(imp)
    assert len(warnings) == 1
    assert "Check if it's really the same game, then click Remap" in warnings[0]
    assert "Current Game ID: {}".format(GAME_ID) in warnings[0]
    assert "Import Game ID: other-game" in warnings[0]


def test_match_label_confirm_shows_same_mismatch_text(cue_env, tmp_path, import_threads):
    # A probable-same-game package gets the same status as a hard mismatch.
    # The "probably the same game" guess is dropped from the row; Remap is
    # still the one action that confirms it.
    _drop_package(tmp_path, "test_game456", [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert mgr.imports[0]["match"] == CueImportMatch.CONFIRM
    imp = mgr.imports[0]["imp"]

    assert mgr.match_label(imp) == "Potential problem"
    warnings = mgr.match_warnings(imp)
    assert "Import Game ID: test_game456" in warnings[0]
    assert "Looks like the same game" not in warnings[0]


def test_match_warnings_missing_files(cue_env, tmp_path, import_threads):
    # A matching import missing manifest-listed files warns about it -- the
    # warning icon shows even though the game_id already matches.
    _drop_missing_files_package(tmp_path, GAME_ID)
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    entry = mgr.imports[0]
    assert entry["match"] == CueImportMatch.AUTO
    assert entry["missing"] == ["audio/nope.ogg"]

    assert mgr.match_label(entry["imp"]) == "Potential problem"
    warnings = mgr.match_warnings(entry["imp"])
    assert len(warnings) == 1
    assert "missing 1 file(s)" in warnings[0]


def test_match_label_clean_import_empty(cue_env, tmp_path, import_threads):
    # A matching, complete import needs no label and no warning icon.
    _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    imp = mgr.imports[0]["imp"]
    assert mgr.match_label(imp) == ""
    assert mgr.match_warnings(imp) == []


def test_scan_marks_newer_format_invalid(cue_env, tmp_path, import_threads):
    imports_dir = os.path.join(str(tmp_path / "cue_root"), "imports")
    os.makedirs(imports_dir)
    zip_path = os.path.join(imports_dir, "bad.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", '{"format_version": 999, "game_id": "x", "contents": []}')

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    entry = mgr.imports[0]
    assert entry["valid"] is False
    assert "newer" in entry["error"]


def test_scan_flags_missing_files_not_invalid(cue_env, tmp_path, import_threads):
    imports_dir = os.path.join(str(tmp_path / "cue_root"), "imports")
    os.makedirs(imports_dir)
    with zipfile.ZipFile(os.path.join(imports_dir, "bad.zip"), "w") as zf:
        zf.writestr("manifest.json", '{"format_version": 1, "game_id": "x", "contents": ["audio/nope.ogg"]}')

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    entry = mgr.imports[0]
    assert entry["valid"] is True
    assert entry["missing"] == ["audio/nope.ogg"]
    assert entry["error"] == ""


# ---------------------------------------------------------------------------
# scan -- list ordering: most likely to be this game first, then recency
# ---------------------------------------------------------------------------


def test_scan_sorts_exact_then_confirm_then_mismatch(cue_env, tmp_path, import_threads):
    # Exact matches for this game on top, near-matches next, mismatches below.
    _drop_package(tmp_path, GAME_ID, [("audio/a.ogg", "a")], zip_name="exact.zip")
    _drop_package(tmp_path, "test_game456", [("audio/b.ogg", "b")], zip_name="confirm.zip")
    _drop_package(tmp_path, "other-game", [("audio/c.ogg", "c")], zip_name="mismatch.zip")

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert [e["imp"] for e in mgr.imports] == ["exact", "confirm", "mismatch"]


def test_scan_sorts_recent_drop_first_within_tier(cue_env, tmp_path, import_threads):
    # Secondary key: the most recently dropped zip leads its tier.
    _drop_package(tmp_path, GAME_ID, [("audio/a.ogg", "a")], zip_name="old.zip")
    _drop_package(tmp_path, GAME_ID, [("audio/b.ogg", "b")], zip_name="new.zip")
    imports_dir = os.path.join(str(tmp_path / "cue_root"), "imports")
    os.utime(os.path.join(imports_dir, "old.zip"), (1000, 1000))
    os.utime(os.path.join(imports_dir, "new.zip"), (2000, 2000))

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert [e["imp"] for e in mgr.imports] == ["new", "old"]


def test_scan_sorts_error_rows_last(cue_env, tmp_path, import_threads):
    # A broken zip isn't 'the wrong game' -- it sinks below every match tier.
    _drop_package(tmp_path, "other-game", [("audio/c.ogg", "c")], zip_name="mismatch.zip")
    imports_dir = os.path.join(str(tmp_path / "cue_root"), "imports")
    _write(imports_dir, "corrupt.zip", "not a zip at all")

    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert [e["imp"] for e in mgr.imports] == ["mismatch", "corrupt"]


# ---------------------------------------------------------------------------
# scan -- the background worker: deferral, progress, failure
# ---------------------------------------------------------------------------


def test_scan_defers_all_work_until_background_thread(cue_env, tmp_path, import_threads):
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


def test_corrupt_zip_shows_error_and_retries_next_pass(cue_env, tmp_path, import_threads):
    imports_dir = os.path.join(str(tmp_path / "cue_root"), "imports")
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
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    _write(_unzip_dir(tmp_path), "pack/audio/extra.ogg", "new")

    files = mgr.folder_files("pack")

    assert "audio/sfx.ogg" in files
    assert "audio/extra.ogg" in files
    assert "manifest.json" in files


def test_merge_confirm_walks_folder_not_manifest(cue_env, tmp_path, import_threads):
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx"), ("music/song.ogg", "music")])
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
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
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
    assert cue_env.paths.shared_config_path == os.path.join(str(tmp_path / "cue_root"), "data", "cue_config.json")
    assert len(calls) == 1

    mgr.deactivate()

    assert cue_env.paths._active_root is None
    assert cue_env.paths.root == str(tmp_path / "cue_root")
    assert mgr.is_active is False
    assert mgr.active_import is None
    assert len(calls) == 2


def test_scan_and_activate_cover_every_category(cue_env, tmp_path, import_threads):
    # A package carrying every content category -- presets are the one
    # category no other manager test drops.  Scan must list them all, and
    # activation must serve a preset from the extracted root.
    imports_dir, _zip_path = _drop_package(
        tmp_path,
        GAME_ID,
        [
            ("data/markers/{}/v_a.json".format(GAME_ID), '{"pools": []}'),
            ("audio/sfx.ogg", "sfx"),
            ("music/song.ogg", "music"),
            ("video/{}/m_cue0.5x.mkv".format(GAME_ID), "v"),
            ("data/presets/audio/p.json", "ap"),
            ("data/presets/video/p.json", "vp"),
            ("data/presets/music/p.json", "mp"),
        ],
    )
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    entry = mgr.imports[0]
    assert entry["valid"]
    assert entry["match"] == CueImportMatch.AUTO
    contents = set(entry["contents"])
    assert "data/markers/{}/v_a.json".format(GAME_ID) in contents
    assert "audio/sfx.ogg" in contents
    assert "music/song.ogg" in contents
    assert "video/{}/m_cue0.5x.mkv".format(GAME_ID) in contents
    assert "data/presets/audio/p.json" in contents
    assert "data/presets/video/p.json" in contents
    assert "data/presets/music/p.json" in contents

    mgr.activate(entry["imp"])
    assert os.path.isfile(os.path.join(cue_env.paths.root, "data", "presets", "audio", "p.json"))


def test_activate_refuses_mismatch(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, "other-game", [("audio/sfx.ogg", "sfx"), ("data/markers/other-game/v_a.json", '{}')])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    mgr.activate(mgr.imports[0]["imp"])

    assert mgr.is_active is False
    assert cue_env.paths._active_root is None


def test_activate_refuses_confirm_until_remapped(cue_env, tmp_path, import_threads):
    # A CONFIRM package (names match once version numbers are dropped) must be
    # remapped before it can be activated.  Its markers/videos live under the
    # import.s game_id, not ours, so the swap would show an empty import.
    _drop_package(tmp_path, "test_game456", [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert mgr.imports[0]["match"] == CueImportMatch.CONFIRM
    mgr.activate(mgr.imports[0]["imp"])

    assert mgr.is_active is False
    assert cue_env.paths._active_root is None


def test_activate_refuses_invalid(cue_env, tmp_path, import_threads):
    imports_dir = os.path.join(str(tmp_path / "cue_root"), "imports")
    os.makedirs(imports_dir)
    with zipfile.ZipFile(os.path.join(imports_dir, "bad.zip"), "w") as zf:
        zf.writestr("manifest.json", '{"format_version": 999, "contents": []}')
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    mgr.activate(mgr.imports[0]["imp"])

    assert mgr.is_active is False


def _drop_missing_files_package(tmp_path, game_id):
    """A zip whose manifest lists a file the archive doesn't carry."""
    imports_dir = os.path.join(str(tmp_path / "cue_root"), "imports")
    os.makedirs(imports_dir)
    with zipfile.ZipFile(os.path.join(imports_dir, "pack.zip"), "w") as zf:
        zf.writestr(
            "manifest.json", '{{"format_version": 1, "game_id": "{}", "contents": ["audio/nope.ogg"]}}'.format(game_id)
        )
    return imports_dir


def test_activate_missing_files_previews_directly(cue_env, imp_cue, tmp_path, import_threads):
    # Missing manifest-listed files no longer block Preview with a confirm
    # dialog -- the row's warning icon already flags them, so activate swaps
    # straight to the overlay and no confirm is shown.
    imports_dir = _drop_missing_files_package(tmp_path, GAME_ID)
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    mgr.activate(imp)

    assert mgr.is_active is True
    assert cue_env.paths._active_root == os.path.join(_unzip_dir(tmp_path), imp)
    assert len(imp_cue) == 0


def test_activate_switches_from_another_preview(cue_env, tmp_path, import_threads):
    # Previewing one import and activating another drops the first preview
    # and swaps the root to the clicked import -- no "Exit Preview" needed
    # in between.  Re-clicking the already-active import is a no-op.
    _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "a")], zip_name="a.zip")
    _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "b")], zip_name="b.zip")
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imps = {e["imp"]: e for e in mgr.imports}
    imp_a, imp_b = imps["a"]["imp"], imps["b"]["imp"]

    mgr.activate(imp_a)
    assert mgr.is_active is True
    assert mgr.active_import == imp_a

    mgr.activate(imp_b)

    assert mgr.is_active is True
    assert mgr.active_import == imp_b
    assert cue_env.paths._active_root == os.path.join(_unzip_dir(tmp_path), imp_b)
    # the abandoned preview's folder is untouched, just no longer served
    assert os.path.isdir(os.path.join(_unzip_dir(tmp_path), imp_a))

    # activating the already-active import does not reset the overlay
    mgr.activate(imp_b)
    assert mgr.active_import == imp_b


# ---------------------------------------------------------------------------
# replays -- manifest replay list, preview guard, jump-to-play
# ---------------------------------------------------------------------------


def test_scan_entry_carries_manifest_replays(cue_env, tmp_path, import_threads):
    # A package whose markers carry a replay field gets a normalized replays
    # list on its entry -- the exporter wrote it into the manifest.  A marker
    # never edited inside a replay has no replay field and is skipped.
    _drop_package(
        tmp_path,
        GAME_ID,
        [
            ("data/markers/{}/a.json".format(GAME_ID), '{"replay": "Run 2", "pools": []}'),
            ("data/markers/{}/b.json".format(GAME_ID), '{"replay": "Run 1", "pools": []}'),
            ("data/markers/{}/c.json".format(GAME_ID), '{"pools": []}'),
            ("audio/sfx.ogg", "sfx"),
        ],
    )
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    entry = mgr.imports[0]
    assert entry["replays"] == [{"replay": "Run 1", "marker_count": 1}, {"replay": "Run 2", "marker_count": 1}]
    assert mgr.replays_for(entry["imp"]) == entry["replays"]


def test_old_manifest_without_replays_yields_empty(cue_env, tmp_path, import_threads):
    # A pre-replays-field export has no replay list -- the row stays compact.
    imports_dir = os.path.join(str(tmp_path / "cue_root"), "imports")
    os.makedirs(imports_dir)
    with zipfile.ZipFile(os.path.join(imports_dir, "old.zip"), "w") as zf:
        zf.writestr("manifest.json", '{"format_version": 1, "game_id": "%s", "contents": ["audio/sfx.ogg"]}' % GAME_ID)
        zf.writestr("audio/sfx.ogg", "sfx")
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)

    assert mgr.imports[0]["replays"] == []
    assert mgr.replays_for(mgr.imports[0]["imp"]) == []


def test_normalize_replays_drops_malformed():
    raw = [
        {"replay": "Run 2", "marker_count": "3"},
        {"replay": "Run 1"},
        {"replay": "", "marker_count": 9},
        {"marker_count": 4},
        "not-a-dict",
    ]
    assert _imports._cue_normalize_replays(raw) == [
        {"replay": "Run 1", "marker_count": 0},
        {"replay": "Run 2", "marker_count": 3},
    ]


def test_normalize_replays_rejects_non_list():
    assert _imports._cue_normalize_replays(None) == []
    assert _imports._cue_normalize_replays({}) == []


def test_replay_expansion_toggles_per_import(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    assert mgr.is_replays_expanded("row", imp) is False
    mgr.toggle_replays("row", imp)
    assert mgr.is_replays_expanded("row", imp) is True
    mgr.toggle_replays("row", imp)
    assert mgr.is_replays_expanded("row", imp) is False


def test_replay_expansion_row_and_banner_independent(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    # The same import can be expanded in the banner while its row stays
    # collapsed -- and vice versa.  The section is part of the state key.
    mgr.toggle_replays("row", imp)
    assert mgr.is_replays_expanded("row", imp) is True
    assert mgr.is_replays_expanded("banner", imp) is False

    mgr.toggle_replays("banner", imp)
    assert mgr.is_replays_expanded("banner", imp) is True
    assert mgr.is_replays_expanded("row", imp) is True

    mgr.toggle_replays("row", imp)
    assert mgr.is_replays_expanded("row", imp) is False
    assert mgr.is_replays_expanded("banner", imp) is True


def test_can_preview_true_for_valid_auto(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    assert mgr.imports[0]["match"] == CueImportMatch.AUTO

    assert mgr.can_preview(imp) is True


def test_can_preview_false_when_not_matched(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, "other-game", [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    assert mgr.imports[0]["match"] == CueImportMatch.MISMATCH

    assert mgr.can_preview(imp) is False


def test_play_replay_enters_preview_then_calls(monkeypatch, cue_env, tmp_path, import_threads):
    calls = []
    monkeypatch.setattr(_imports.renpy, "call_replay", lambda label: calls.append(label), raising=False)
    _drop_package(tmp_path, GAME_ID, [("data/markers/{}/a.json".format(GAME_ID), '{"replay": "Run 1", "pools": []}')])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    assert not mgr.is_active

    mgr.play_replay(imp, "Run 1")

    assert mgr.is_active is True
    assert mgr.active_import == imp
    assert cue_env.paths._active_root == os.path.join(_unzip_dir(tmp_path), imp)
    assert calls == ["Run 1"]


def test_play_replay_noop_when_not_previewable(monkeypatch, cue_env, tmp_path, import_threads):
    calls = []
    monkeypatch.setattr(_imports.renpy, "call_replay", lambda label: calls.append(label), raising=False)
    _drop_package(tmp_path, "other-game", [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    mgr.play_replay(imp, "Run 1")

    assert mgr.is_active is False
    assert calls == []


def test_play_replay_reuses_existing_preview(monkeypatch, cue_env, tmp_path, import_threads):
    # Already previewing the same import: no root swap, straight to call.
    calls = []
    monkeypatch.setattr(_imports.renpy, "call_replay", lambda label: calls.append(label), raising=False)
    _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    mgr.activate(imp)

    mgr.play_replay(imp, "Run 1")

    assert mgr.active_import == imp
    assert calls == ["Run 1"]


# ---------------------------------------------------------------------------
# remap -- 2-folder rename + manifest rewrite, never a marker rewrite
# ---------------------------------------------------------------------------


def test_remap_renames_folders_and_updates_manifest(cue_env, tmp_path, import_threads):
    imports_dir, _zip_path = _drop_package(
        tmp_path,
        "other-game",
        [
            ("data/markers/other-game/v_a.json", '{"pools": []}'),
            ("video/other-game/m_cue0.5x.mkv", "v"),
            ("audio/sfx.ogg", "sfx"),
        ],
    )
    mgr, _calls = _make_mgr(cue_env)
    _created, _join = import_threads
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    mgr.remap(imp)  # kicks a scan internally
    _join()  # run it so the snapshot reflects the remap

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
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
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
    _drop_package(tmp_path, "other-game", [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _created, _join = import_threads
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    assert mgr.imports[0]["match"] == CueImportMatch.MISMATCH

    mgr.remap(imp)  # kicks a scan internally
    _join()  # run it so the entry reflects the remap

    assert mgr.import_for(imp)["match"] == CueImportMatch.AUTO
    mgr.activate(imp)

    assert mgr.is_active is True
    assert cue_env.paths.root == os.path.join(_unzip_dir(tmp_path), imp)


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_confirmed_removes_dir_and_zip(cue_env, tmp_path, import_threads):
    imports_dir, zip_path = _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
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
    imports_dir, _zip_path = _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
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
    imports_dir, _zip_path = _drop_package(
        tmp_path,
        GAME_ID,
        [
            ("data/markers/{}/v_a.json".format(GAME_ID), '{"pools": []}'),
            ("audio/sfx.ogg", "sfx"),
            ("music/song.ogg", "music"),
        ],
    )
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
    _drop_package(tmp_path, GAME_ID, [("audio/sfx.ogg", "sfx")])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]

    mgr.merge_confirm(imp, [])

    assert "Nothing selected" in mgr.merge_status


def test_merge_confirm_refuses_mismatch(cue_env, tmp_path, import_threads):
    _drop_package(tmp_path, "other-game", [("audio/sfx.ogg", "sfx"), ("data/markers/other-game/v_a.json", '{}')])
    mgr, _calls = _make_mgr(cue_env)
    _scan_and_join(mgr, import_threads)
    imp = mgr.imports[0]["imp"]
    original_root = str(tmp_path / "cue_root")

    mgr.merge_confirm(imp, [CueImportCategory.SFX])

    assert "Remap it first" in mgr.merge_status
    assert not os.path.exists(os.path.join(original_root, "audio", "sfx.ogg"))


def test_merge_confirm_refuses_confirm_until_remapped(cue_env, tmp_path, import_threads):
    # Same gate as activate: a CONFIRM import must be remapped first, or the
    # namespaced files would merge under the import.s game_id and nothing
    # would read them.
    _drop_package(tmp_path, "test_game456", [("audio/sfx.ogg", "sfx")])
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
