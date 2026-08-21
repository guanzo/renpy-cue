# -*- coding: utf-8 -*-
# Real export-format fixtures -- three hand-crafted imports committed under
# tests/fixtures/data/imports/.  They pin the import format and the match
# heuristics against real bytes (not synthetic zips built in-test).
#
#   cue-max-test.zip        gid cue_test_harness          -> AUTO
#       All 5 categories, speed variants, presets, shared config, traversal
#       entries, a phantom file, foreign exts.
#   cue-match-mismatch.zip  gid SomeUnrelatedGame-123     -> MISMATCH
#   cue-match-prefix.zip    gid cue_test_harness-patreon  -> CONFIRM (prefix)

import os
import zipfile

import pytest

from cue_lib import importer_io as _imp
from cue_lib.constants import (
    CUE_IMPORT_CATEGORY_ORDER,
    CUE_IMPORT_DIR,
    CUE_IMPORT_MANIFEST_NAME,
    CueImportMatch,
)
from cue_lib.importer import CueImportManager

LOCAL_GID = "cue_test_harness"

FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "import_exports")

MAX_ZIP = "cue-max-test.zip"
MISMATCH_ZIP = "cue-match-mismatch.zip"
PREFIX_ZIP = "cue-match-prefix.zip"


def _fixture_path(name):
    return os.path.join(FIXTURES_DIR, name)


def _walk_rel(root):
    result = set()
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            result.add(os.path.relpath(os.path.join(dirpath, name), root)
                       .replace("\\", "/"))
    return result


def _zip_names(path):
    return zipfile.ZipFile(path).namelist()


def _load(tmp_path, name):
    """Extract a fixture to a temp dir and read its manifest."""
    out = str(tmp_path / "extract")
    _imp._cue_extract_import_zip(_fixture_path(name), out)
    return _imp._cue_load_manifest(out)


# ---------------------------------------------------------------------------
# importer_io level -- extract / match / validate / missing
# ---------------------------------------------------------------------------

def test_max_extracts_clean_and_flags_phantom(tmp_path):
    path = _fixture_path(MAX_ZIP)
    out = os.path.join(str(tmp_path), "out")
    count = _imp._cue_extract_import_zip(path, out)

    rels = _walk_rel(out)
    # Traversal entries are skipped, never rewritten into a sibling path.
    assert "audio/escape.ogg" not in rels
    assert "escape.ogg" not in rels
    # Phantom file (in the manifest, absent from the zip) never lands.
    assert "audio/Missing/song.ogg" not in rels
    # Root junk, foreign exts, and shared config are filtered out.
    assert "evil.exe" not in rels
    assert "README.txt" not in rels
    assert "data/cue_config.json" not in rels

    # Manifest + 28 real content files (33 entries minus 2 traversal, minus
    # evil.exe / README.txt / audio/notes.txt / presets/readme.md /
    # data/cue_config.json).
    assert CUE_IMPORT_MANIFEST_NAME in rels
    assert count == 29

    # The missing file is reported separately (warn-and-confirm), not fatal.
    man = _imp._cue_load_manifest(out)
    assert _imp._cue_missing_files(man, _zip_names(path)) == \
        ["audio/Missing/song.ogg"]


def test_max_covers_every_category(tmp_path):
    man = _load(tmp_path, MAX_ZIP)
    counts = _imp._cue_category_counts(man["contents"])
    assert set(counts) == set(CUE_IMPORT_CATEGORY_ORDER)


def test_max_matches_auto(tmp_path):
    man = _load(tmp_path, MAX_ZIP)
    lvl, reason = _imp._cue_import_match(LOCAL_GID, man["game_id"])
    assert lvl == CueImportMatch.AUTO
    assert reason == ""


def test_mismatch_matches_mismatch():
    lvl, reason = _imp._cue_import_match(LOCAL_GID, "SomeUnrelatedGame-123")
    assert lvl == CueImportMatch.MISMATCH
    assert reason == "no shared identifier"


def test_prefix_matches_confirm():
    lvl, reason = _imp._cue_import_match(LOCAL_GID, "cue_test_harness-patreon")
    assert lvl == CueImportMatch.CONFIRM
    assert reason == "both share prefix 'cue_test_harness'"


def test_all_fixtures_validate(tmp_path):
    for name in (MAX_ZIP, MISMATCH_ZIP, PREFIX_ZIP):
        man = _load(tmp_path, name)
        valid, why = _imp._cue_validate_manifest(
            man, _zip_names(_fixture_path(name)))
        assert valid, (name, why)


# ---------------------------------------------------------------------------
# manager level -- drop in imports/, scan(), assert the entry
# ---------------------------------------------------------------------------

class _FakeThread(object):
    def __init__(self, target=None, args=()):
        self.target = target
        self.args = args
        self.started = False
        self.joined = False

    def start(self):
        self.started = True


@pytest.fixture
def import_threads(monkeypatch):
    import cue_lib.importer as _imports
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


def _make_mgr(tmp_path, refresh_calls):
    from cue_lib.db import CueDatabase
    from cue_lib.paths import CuePaths

    root = str(tmp_path / "cue_root")
    paths = CuePaths(root, game_id=LOCAL_GID)
    db = CueDatabase(paths)
    db.open()
    mgr = CueImportManager(paths, db, lambda: refresh_calls.append(1))
    return mgr


def test_scan_real_exports_builds_expected_entries(tmp_path, import_threads):
    mgr = _make_mgr(tmp_path, [])
    imports_dir = os.path.join(str(tmp_path / "cue_root"), CUE_IMPORT_DIR)
    os.makedirs(imports_dir)
    for name in (MAX_ZIP, MISMATCH_ZIP, PREFIX_ZIP):
        dst = os.path.join(imports_dir, name)
        with open(_fixture_path(name), "rb") as src_f:
            with open(dst, "wb") as dst_f:
                dst_f.write(src_f.read())

    _created, _join = import_threads
    mgr.scan()
    _join()

    # Entry "imp" keys are the zip names minus the extension.
    by_name = {e["imp"]: e for e in mgr.imports}
    max_imp = MAX_ZIP[:-len(".zip")]
    mismatch_imp = MISMATCH_ZIP[:-len(".zip")]
    prefix_imp = PREFIX_ZIP[:-len(".zip")]

    assert by_name[max_imp]["valid"]
    assert by_name[max_imp]["match"] == CueImportMatch.AUTO
    assert by_name[max_imp]["missing"] == ["audio/Missing/song.ogg"]

    assert by_name[mismatch_imp]["valid"]
    assert by_name[mismatch_imp]["match"] == CueImportMatch.MISMATCH
    assert by_name[mismatch_imp]["match_reason"] == "no shared identifier"

    assert by_name[prefix_imp]["valid"]
    assert by_name[prefix_imp]["match"] == CueImportMatch.CONFIRM
    assert by_name[prefix_imp]["match_reason"] == \
        "both share prefix 'cue_test_harness'"

    # The committed manifests carry the replays field (replay + marker_count),
    # computed from the packed markers -- exactly what a real export writes.
    assert by_name[max_imp]["replays"] == [
        {"replay": "scene_A_label", "marker_count": 3},
        {"replay": "scene_B_label", "marker_count": 2},
    ]
    assert by_name[prefix_imp]["replays"] == [
        {"replay": "probe_label", "marker_count": 1},
    ]
    assert by_name[mismatch_imp]["replays"] == []
