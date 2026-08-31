# -*- coding: utf-8 -*-
# Tests for cue_lib.sharing.exporter -- CueExportManager: category selection state,
# selected_contents, and zip export with collision-safe filenames.

import hashlib
import json
import os
import zipfile

import pytest

import cue_lib.sharing.exporter as _exporter

from cue_lib.constants import (
    CUE_HASH_TRUNC_LEN,
    CUE_IMPORT_MANIFEST_NAME,
    CueExportFileTypes,
    CueExportScope,
    CueImportCategory,
)
from cue_lib.sharing.exporter import CueExportManager

GAME_ID = "test_game"


class _FakeThread(object):
    """Records the thread body without running it -- lets the tests drive the
    zip build synchronously and assert on the wiring (daemon, reentry)."""

    def __init__(self, target=None, args=()):
        self.target = target
        self.args = args
        self.daemon = False
        self.started = False
        self.joined = False

    def start(self):
        self.started = True

    def join(self):
        """Run the recorded body once -- tests drive both the refresh worker
        and the zip build through join(), real or fake, uniformly."""
        if self.started and not self.joined:
            self.joined = True
            self.target()


def _capture_thread_factory():
    """Patch Thread with a factory that records every created thread, so tests
    can drive the recorded bodies synchronously."""
    created = []

    def _factory(**kw):
        t = _FakeThread(**kw)
        created.append(t)
        return t

    return created, _factory


def _write(root, rel, content):
    path = os.path.join(root, *rel.split("/"))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as f:
        f.write(content)
    return path


def _seed(cue_env, files):
    for rel, content in files:
        _write(cue_env.paths.original_root, rel, content)


def _export_and_join(mgr):
    """export() now builds on a background thread; tests join it before
    asserting on the zip or the status message."""
    mgr.export()
    if mgr._export_thread is not None:
        mgr._export_thread.join()


def _refresh_and_join(mgr):
    """refresh() now defers the enumeration to a background worker so the UI
    thread never blocks on the disk walk; tests join it before asserting on
    the swapped-in snapshot.  Works for real and recorded threads alike."""
    mgr.refresh()
    if mgr._refresh_thread is not None:
        mgr._refresh_thread.join()


def _switch(mgr, method, value):
    """Call a mode-switching setter and join the refresh it kicks when the
    cached snapshot is stale, so the background pass can't race the
    assertions."""
    getattr(mgr, method)(value)
    if mgr._refresh_thread is not None:
        mgr._refresh_thread.join()


# ---------------------------------------------------------------------------
# refresh / counts / enabled
# ---------------------------------------------------------------------------


def test_refresh_counts_and_enabled(cue_env):
    _seed(
        cue_env,
        [
            ("audio/a.ogg", "a"),
            ("audio/b.ogg", "b"),
            ("data/markers/{}/v_a.json".format(GAME_ID), '{}'),
            ("video/{}/m.mkv".format(GAME_ID), "v"),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)

    assert mgr.counts[CueImportCategory.SFX] == 2
    assert mgr.counts[CueImportCategory.MARKERS] == 1
    assert mgr.counts[CueImportCategory.SPEED_VARIANTS] == 1
    assert mgr.is_category_enabled(CueImportCategory.SFX) is True
    assert mgr.is_category_enabled(CueImportCategory.MUSIC) is False


def test_refresh_empty_root_has_no_enabled(cue_env):
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    assert mgr.counts == {}
    for cat in (CueImportCategory.SFX, CueImportCategory.MARKERS, CueImportCategory.MUSIC):
        assert mgr.is_category_enabled(cat) is False


def test_exports_dir_under_original_root(cue_env):
    mgr = CueExportManager(cue_env.paths)
    assert mgr._paths.exports_dir == os.path.join(cue_env.paths.original_root, "exports")


def test_cache_reuses_snapshot_until_invalidated(cue_env, monkeypatch):
    """The disk snapshot is cached: a second mode toggle doesn't re-walk the
    disk, and invalidate_cache() (wired to marker saves) forces a rebuild."""
    _seed(cue_env, [("audio/a.ogg", "a")])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    assert mgr._cache_valid is True

    created, _factory = _capture_thread_factory()
    monkeypatch.setattr(_exporter.threading, "Thread", _factory)
    mgr.set_scope(CueExportScope.SPECIFIC_REPLAYS)
    assert created == []  # cached snapshot -> no new refresh pass

    mgr.invalidate_cache()
    mgr.set_scope(CueExportScope.SPECIFIC_REPLAYS)
    assert len(created) == 1
    created[0].join()
    assert mgr._cache_valid is True


def test_export_always_refreshes_contents(cue_env):
    """Export always re-enumerates, so a file added after the last refresh is
    still packed -- the cached snapshot never serves an export."""
    _seed(cue_env, [("audio/a.ogg", "a")])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)  # cache now valid
    _seed(cue_env, [("music/m.ogg", "m")])  # added after the snapshot
    mgr.name = "Fresh"

    _export_and_join(mgr)

    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "Fresh.zip")) as zf:
        names = zf.namelist()
        assert "audio/a.ogg" in names
        assert "music/m.ogg" in names


# ---------------------------------------------------------------------------
# selection state
# ---------------------------------------------------------------------------


def test_all_categories_checked_by_default(cue_env):
    mgr = CueExportManager(cue_env.paths)
    for cat in range(CueImportCategory.PRESETS + 1):
        assert mgr.is_checked(cat) is True


def test_toggle_category_flips_checked(cue_env):
    mgr = CueExportManager(cue_env.paths)
    mgr.toggle_category(CueImportCategory.SFX)
    assert mgr.is_checked(CueImportCategory.SFX) is False
    mgr.toggle_category(CueImportCategory.SFX)
    assert mgr.is_checked(CueImportCategory.SFX) is True


def test_selected_contents_drops_unchecked_and_empty(cue_env):
    _seed(cue_env, [("audio/a.ogg", "a"), ("music/m.ogg", "m")])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_file_types", CueExportFileTypes.SPECIFIC)
    mgr.toggle_category(CueImportCategory.SFX)

    sel = mgr.selected_contents()

    assert "music/m.ogg" in sel
    assert "audio/a.ogg" not in sel
    assert len(sel) == 1


def test_selected_contents_in_category_order(cue_env):
    _seed(cue_env, [("audio/a.ogg", "a"), ("data/markers/{}/v_a.json".format(GAME_ID), '{}')])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    sel = mgr.selected_contents()
    assert sel.index("data/markers/{}/v_a.json".format(GAME_ID)) < sel.index("audio/a.ogg")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_export_writes_sanitized_zip(cue_env):
    _seed(cue_env, [("audio/a.ogg", "a"), ("music/m.ogg", "m")])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "My Pack"
    mgr.author = "author"
    mgr.description = "desc"

    _export_and_join(mgr)

    zip_path = os.path.join(mgr._paths.exports_dir, "My Pack.zip")
    assert os.path.isfile(zip_path)
    assert mgr.export_error == ""
    assert mgr.export_status == "Exported to {}.".format(os.path.join(mgr._paths.exports_dir, "My Pack.zip"))
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert CUE_IMPORT_MANIFEST_NAME in names
        assert "audio/a.ogg" in names
        assert "music/m.ogg" in names


def test_export_collision_suffix(cue_env):
    _seed(cue_env, [("audio/a.ogg", "a")])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "Pack"

    for _i in range(3):
        _export_and_join(mgr)

    exports = mgr._paths.exports_dir
    assert os.path.isfile(os.path.join(exports, "Pack.zip"))
    assert os.path.isfile(os.path.join(exports, "Pack (2).zip"))
    assert os.path.isfile(os.path.join(exports, "Pack (3).zip"))


def test_export_sanitizes_filename(cue_env):
    _seed(cue_env, [("audio/a.ogg", "a")])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "a/b\\c:bad"

    _export_and_join(mgr)

    assert os.path.isfile(os.path.join(mgr._paths.exports_dir, "a_b_cbad.zip"))


def test_export_empty_is_error(cue_env):
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)

    mgr.export()

    assert mgr.export_error
    assert mgr.export_status == ""
    exports = mgr._paths.exports_dir
    assert not os.path.isdir(exports) or os.listdir(exports) == []


def test_export_runs_zip_build_off_thread(cue_env, monkeypatch):
    _seed(cue_env, [("audio/a.ogg", "a")])
    created, _factory = _capture_thread_factory()
    monkeypatch.setattr(_exporter.threading, "Thread", _factory)
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "Pack"

    mgr.export()

    # The build is deferred to a daemon thread; state reflects that it's live.
    fake_thread = created[-1]
    assert mgr.is_exporting is True
    assert mgr.export_fraction == 0.0
    assert mgr._export_thread is fake_thread
    assert fake_thread.daemon is True
    assert fake_thread.started is True
    # Driving the recorded body synchronously reproduces the thread's finish:
    # status lands and the exporting flag clears.
    fake_thread.target(*fake_thread.args)
    assert mgr.export_status == "Exported to {}.".format(os.path.join(mgr._paths.exports_dir, "Pack.zip"))
    assert mgr.is_exporting is False


def test_export_ignores_reentry_while_building(cue_env, monkeypatch):
    _seed(cue_env, [("audio/a.ogg", "a")])
    created, _factory = _capture_thread_factory()
    monkeypatch.setattr(_exporter.threading, "Thread", _factory)
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "Pack"

    mgr.export()
    first = mgr._export_thread
    mgr.export()  # is_exporting still True -> no-op, no second thread

    assert mgr._export_thread is first
    assert len(created) == 2  # one refresh worker + one zip build, no more


def test_export_progress_callback_reports_fraction(cue_env, monkeypatch):
    _seed(cue_env, [("audio/a.ogg", "a")])
    created, _factory = _capture_thread_factory()
    monkeypatch.setattr(_exporter.threading, "Thread", _factory)
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "Pack"

    mgr.export()

    assert mgr.export_fraction == 0.0
    mgr._set_export_progress(3, 10)
    assert mgr.export_fraction == 0.3
    mgr._set_export_progress(10, 10)
    assert mgr.export_fraction == 1.0
    mgr._set_export_progress(0, 0)
    assert mgr.export_fraction == 1.0


def test_export_includes_music_trigger_log(cue_env):
    # The per-replay trigger files live in marker_dir/music_triggers/; the
    # exporter walks the whole dir recursively, so they must travel with the
    # markers category.
    _seed(
        cue_env,
        [
            ("data/markers/{}/v_a.json".format(GAME_ID), '{}'),
            (
                "data/markers/{}/music_triggers/replay_r1.json".format(GAME_ID),
                '[{"key_before": "i_room", "filepath": "m.ogg"}]',
            ),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "LogPack"

    _export_and_join(mgr)

    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "LogPack.zip")) as zf:
        names = zf.namelist()
        assert "data/markers/{}/music_triggers/replay_r1.json".format(GAME_ID) in names


def test_export_ships_every_category(cue_env):
    # One export carrying all five categories -- presets are the one category
    # the other exporter tests never seed, and no test asserts a single
    # package spanning every category.
    _seed(
        cue_env,
        [
            ("data/markers/{}/v_a.json".format(GAME_ID), '{}'),
            ("audio/sfx.ogg", "a"),
            ("music/song.ogg", "m"),
            ("video/{}/clip.mkv".format(GAME_ID), "v"),
            ("data/presets/audio/p.json", "ap"),
            ("data/presets/video/p.json", "vp"),
            ("data/presets/music/p.json", "mp"),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "Full"
    assert mgr.is_category_enabled(CueImportCategory.PRESETS) is True
    assert mgr.counts[CueImportCategory.PRESETS] == 3

    _export_and_join(mgr)

    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "Full.zip")) as zf:
        names = set(zf.namelist())
    for rel in (
        "data/markers/{}/v_a.json".format(GAME_ID),
        "audio/sfx.ogg",
        "music/song.ogg",
        "video/{}/clip.mkv".format(GAME_ID),
        "data/presets/audio/p.json",
        "data/presets/video/p.json",
        "data/presets/music/p.json",
    ):
        assert rel in names


def test_export_skips_unchecked(cue_env):
    _seed(cue_env, [("audio/a.ogg", "a"), ("music/m.ogg", "m")])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "Only music"
    _switch(mgr, "set_file_types", CueExportFileTypes.SPECIFIC)
    mgr.toggle_category(CueImportCategory.SFX)

    _export_and_join(mgr)

    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "Only music.zip")) as zf:
        names = zf.namelist()
        assert "music/m.ogg" in names
        assert "audio/a.ogg" not in names


# ---------------------------------------------------------------------------
# replay scope -- _cue_replay_labels-driven selection + one-click export
# ---------------------------------------------------------------------------


def test_scope_defaults_to_all_replays(cue_env):
    mgr = CueExportManager(cue_env.paths)
    assert mgr.scope == CueExportScope.ALL_REPLAYS


def test_set_scope_switches_content_source(cue_env):
    _seed(cue_env, [("audio/a.ogg", "a")])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_scope", CueExportScope.SPECIFIC_REPLAYS)

    assert mgr.scope == CueExportScope.SPECIFIC_REPLAYS
    assert mgr.selected_contents() == []  # no replays checked -> nothing


def test_file_types_defaults_to_all(cue_env):
    mgr = CueExportManager(cue_env.paths)
    assert mgr.file_types == CueExportFileTypes.ALL


def test_all_file_types_ignores_category_checks(cue_env):
    _seed(cue_env, [("audio/a.ogg", "a"), ("music/m.ogg", "m")])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.toggle_category(CueImportCategory.SFX)

    sel = mgr.selected_contents()

    # All File Types mode: the category checkboxes don't filter anything.
    assert "audio/a.ogg" in sel
    assert "music/m.ogg" in sel


def test_any_unchecked_only_in_specific_mode(cue_env):
    _seed(cue_env, [("audio/a.ogg", "a"), ("music/m.ogg", "m")])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.toggle_category(CueImportCategory.SFX)

    assert mgr.any_unchecked() is False  # All mode: nothing can be off

    _switch(mgr, "set_file_types", CueExportFileTypes.SPECIFIC)

    assert mgr.any_unchecked() is True


def test_refresh_populates_replays_and_seeds_checked(cue_env):
    _seed(
        cue_env,
        [
            ("data/markers/{}/a.json".format(GAME_ID), '{"replay": "Run 1", "pools": []}'),
            ("data/markers/{}/b.json".format(GAME_ID), '{"replay": "Run 2", "pools": []}'),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)

    assert mgr.replays == [{"replay": "Run 1", "marker_count": 1}, {"replay": "Run 2", "marker_count": 1}]
    assert mgr.is_replay_checked("Run 1") is True
    assert mgr.is_replay_checked("Run 2") is True


def test_toggle_replay_unchecks(cue_env):
    _seed(cue_env, [("data/markers/{}/a.json".format(GAME_ID), '{"replay": "Run 1", "pools": []}')])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.toggle_replay("Run 1")

    assert mgr.is_replay_checked("Run 1") is False


def test_toggle_all_replays_alternates(cue_env):
    _seed(
        cue_env,
        [
            ("data/markers/{}/a.json".format(GAME_ID), '{"replay": "Run 1", "pools": []}'),
            ("data/markers/{}/b.json".format(GAME_ID), '{"replay": "Run 2", "pools": []}'),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)  # all checked by default

    mgr.toggle_all_replays()
    assert mgr.is_replay_checked("Run 1") is False
    assert mgr.is_replay_checked("Run 2") is False

    mgr.toggle_all_replays()
    assert mgr.is_replay_checked("Run 1") is True
    assert mgr.is_replay_checked("Run 2") is True

    mgr.toggle_all_replays()
    assert mgr.is_replay_checked("Run 1") is False


def test_toggle_all_replays_from_partial_checks_all(cue_env):
    _seed(
        cue_env,
        [
            ("data/markers/{}/a.json".format(GAME_ID), '{"replay": "Run 1", "pools": []}'),
            ("data/markers/{}/b.json".format(GAME_ID), '{"replay": "Run 2", "pools": []}'),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.toggle_replay("Run 2")  # one left unchecked

    mgr.toggle_all_replays()

    assert mgr.is_replay_checked("Run 1") is True
    assert mgr.is_replay_checked("Run 2") is True


def test_replay_scope_contents_is_subset(cue_env):
    _seed(
        cue_env,
        [
            ("audio/a.ogg", "a"),
            ("audio/b.ogg", "b"),
            ("data/markers/{}/r1.json".format(GAME_ID), '{"replay": "Run 1", "pools": [{"files": ["audio/a.ogg"]}]}'),
            ("data/markers/{}/r2.json".format(GAME_ID), '{"replay": "Run 2", "pools": [{"files": ["audio/b.ogg"]}]}'),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_scope", CueExportScope.SPECIFIC_REPLAYS)
    mgr.toggle_replay("Run 2")  # only Run 1 stays checked

    sel = mgr.selected_contents()

    assert "data/markers/{}/r1.json".format(GAME_ID) in sel
    assert "data/markers/{}/r2.json".format(GAME_ID) not in sel
    assert "audio/a.ogg" in sel
    assert "audio/b.ogg" not in sel


def test_export_preserves_replay_deselection(cue_env):
    # export() refreshes synchronously for fresh data, but that refresh must
    # never re-check a replay the user turned off -- the deselection is a
    # choice, not stale data to overwrite.
    _seed(
        cue_env,
        [
            ("audio/a.ogg", "a"),
            ("audio/b.ogg", "b"),
            ("data/markers/{}/r1.json".format(GAME_ID), '{"replay": "Run 1", "pools": [{"files": ["audio/a.ogg"]}]}'),
            ("data/markers/{}/r2.json".format(GAME_ID), '{"replay": "Run 2", "pools": [{"files": ["audio/b.ogg"]}]}'),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_scope", CueExportScope.SPECIFIC_REPLAYS)
    mgr.toggle_replay("Run 2")  # only Run 1 stays checked

    _export_and_join(mgr)

    assert mgr.checked_replays == set(["Run 1"])
    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "{}.zip".format(GAME_ID))) as zf:
        names = set(zf.namelist())
    assert "data/markers/{}/r1.json".format(GAME_ID) in names
    assert "data/markers/{}/r2.json".format(GAME_ID) not in names


def test_refresh_preserves_replay_selection(cue_env):
    # A cache-invalidated background refresh swaps fresh data only; the
    # checkbox selection survives it.
    _seed(
        cue_env,
        [
            ("data/markers/{}/r1.json".format(GAME_ID), '{"replay": "Run 1", "pools": []}'),
            ("data/markers/{}/r2.json".format(GAME_ID), '{"replay": "Run 2", "pools": []}'),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_scope", CueExportScope.SPECIFIC_REPLAYS)
    mgr.toggle_replay("Run 2")  # only Run 1 stays checked

    mgr.invalidate_cache()
    _refresh_and_join(mgr)

    assert mgr.checked_replays == set(["Run 1"])


def test_export_preserves_file_types_selection(cue_env):
    # Export refreshes synchronously for fresh data; the Specific File Types
    # checkboxes are a user choice and must survive it, same as replay
    # deselection.
    _seed(cue_env, [("audio/a.ogg", "a"), ("data/markers/{}/v.json".format(GAME_ID), '{"pools": []}')])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_file_types", CueExportFileTypes.SPECIFIC)
    mgr.toggle_category(CueImportCategory.SFX)

    _export_and_join(mgr)

    assert mgr.is_checked(CueImportCategory.SFX) is False
    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "{}.zip".format(GAME_ID))) as zf:
        names = set(zf.namelist())
    assert "data/markers/{}/v.json".format(GAME_ID) in names
    assert "audio/a.ogg" not in names


def test_replay_contents_respect_file_types(cue_env):
    _seed(
        cue_env,
        [
            ("audio/a.ogg", "a"),
            ("data/markers/{}/r1.json".format(GAME_ID), '{"replay": "Run 1", "pools": [{"files": ["audio/a.ogg"]}]}'),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_scope", CueExportScope.SPECIFIC_REPLAYS)
    _switch(mgr, "set_file_types", CueExportFileTypes.SPECIFIC)
    mgr.toggle_category(CueImportCategory.SFX)

    sel = mgr.selected_contents()

    # Markers stay, the SFX the marker references is pruned.
    assert "data/markers/{}/r1.json".format(GAME_ID) in sel
    assert "audio/a.ogg" not in sel

    # All File Types brings the audio reference back.
    mgr.set_file_types(CueExportFileTypes.ALL)
    assert "audio/a.ogg" in mgr.selected_contents()


def test_export_replay_packs_only_that_replay(cue_env):
    _seed(
        cue_env,
        [
            ("audio/a.ogg", "a"),
            ("data/markers/{}/r1.json".format(GAME_ID), '{"replay": "Run 1", "pools": [{"files": ["audio/a.ogg"]}]}'),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)

    mgr.export_replay("Run 1")
    mgr._export_thread.join()

    assert mgr.scope == CueExportScope.SPECIFIC_REPLAYS
    assert mgr.checked_replays == set(["Run 1"])
    assert mgr.name == "Run 1"  # named after the replay when Name is empty
    assert mgr.export_status == "Exported to {}.".format(os.path.join(mgr._paths.exports_dir, "Run 1.zip"))
    assert not mgr.export_error
    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "Run 1.zip")) as zf:
        names = set(zf.namelist())
    assert "data/markers/{}/r1.json".format(GAME_ID) in names
    assert "audio/a.ogg" in names


def test_export_omits_thumbs_cache_in_whole_game(cue_env):
    # cue_thumbs.json is downloaded per-user from the release; shipping the
    # exporter's local snapshot would downgrade a recipient on a newer build.
    _seed(cue_env, [("data/markers/{}/v_a.json".format(GAME_ID), "{}"), ("data/cue_thumbs.json", '{"games": {}}')])
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "Thumbs"

    _export_and_join(mgr)

    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "Thumbs.zip")) as zf:
        names = set(zf.namelist())
    assert "data/cue_thumbs.json" not in names


def test_export_omits_thumbs_cache_in_replay_scope(cue_env):
    _seed(
        cue_env,
        [
            ("audio/a.ogg", "a"),
            ("data/markers/{}/r1.json".format(GAME_ID), '{"replay": "Run 1", "pools": [{"files": ["audio/a.ogg"]}]}'),
            ("data/cue_thumbs.json", '{"games": {}}'),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)

    mgr.export_replay("Run 1")
    mgr._export_thread.join()

    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "Run 1.zip")) as zf:
        names = set(zf.namelist())
    assert "data/cue_thumbs.json" not in names


def test_current_replay_reads_store(cue_env, monkeypatch):
    import renpy

    monkeypatch.setattr(renpy.store, "_in_replay", "Run 1")
    mgr = CueExportManager(cue_env.paths)

    assert mgr._current_replay() == "Run 1"


# ---------------------------------------------------------------------------
# refresh -- background snapshot swap (mirrors CueImportManager.scan)
# ---------------------------------------------------------------------------


@pytest.fixture
def export_threads(monkeypatch):
    """Patch Thread with a recording factory so refresh()'s background worker
    is deferred instead of run live.  Returns (created, _join); _join() runs
    every recorded thread body inline once, so tests can drive the worker
    synchronously."""
    created = []

    def _factory(**kw):
        t = _FakeThread(**kw)
        created.append(t)
        return t

    monkeypatch.setattr(_exporter.threading, "Thread", _factory)

    def _join():
        for t in created:
            if t.started and not t.joined:
                t.joined = True
                t.target()

    return created, _join


def test_refresh_defers_disk_work_off_thread(cue_env, export_threads):
    _seed(cue_env, [("audio/a.ogg", "a"), ("data/markers/{}/v_a.json".format(GAME_ID), '{}')])
    mgr = CueExportManager(cue_env.paths)

    mgr.refresh()

    # Nothing populated yet -- the snapshot swap hasn't happened; the disk
    # walk is deferred to a daemon worker.
    assert mgr.counts == {}
    assert mgr.is_refreshing is True
    _created, _join = export_threads
    assert len(_created) == 1
    assert _created[0].daemon is True
    assert _created[0].started is True

    # Driving the recorded body reproduces the worker's finish.
    _join()

    assert mgr.is_refreshing is False
    assert mgr.counts[CueImportCategory.SFX] == 1
    assert mgr.counts[CueImportCategory.MARKERS] == 1


def test_refresh_ignores_reentry_while_running(cue_env, export_threads):
    mgr = CueExportManager(cue_env.paths)

    mgr.refresh()
    mgr.refresh()  # is_refreshing still True -> no-op, no second worker

    _created, _join = export_threads
    assert len(_created) == 1


def test_refresh_keeps_last_snapshot_on_failure(cue_env, export_threads, monkeypatch):
    _seed(cue_env, [("audio/a.ogg", "a")])
    mgr = CueExportManager(cue_env.paths)
    _created, _join = export_threads

    mgr.refresh()
    _join()
    assert mgr.counts[CueImportCategory.SFX] == 1

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_exporter, "_cue_enumerate_import_files", _boom)
    mgr.refresh()
    _join()

    # The failed pass leaves the previous snapshot in place, never a
    # half-built one, and clears the running flag.
    assert mgr.is_refreshing is False
    assert mgr.counts[CueImportCategory.SFX] == 1


# ---------------------------------------------------------------------------
# external bake -- abs refs are baked into the bundle as portable relative refs
# ---------------------------------------------------------------------------


def _write_shared_config(cue_env, sfx=None, music=None):
    """Write the shared config with external folder roots so
    _cue_external_roots() picks them up during the zip build."""
    cfg = {}
    if sfx is not None:
        cfg["sfx_folders"] = sfx
    if music is not None:
        cfg["music_folders"] = music
    _write(cue_env.paths.original_root, "data/cue_config.json", json.dumps(cfg))


def _baked_ns(arcname):
    """The per-source namespace (e.g. 'ext_sfx-abc123') of a baked arcname."""
    return arcname.split("/_external/", 1)[1].split("/", 1)[0]


def test_external_bake_sfx_ref_exported_relative(tmp_path, cue_env):
    # An abs SFX ref under a configured external root ships as a portable
    # audio/_external/<ns>/<rel> arcname, and the bundled marker references the
    # baked-relative path instead of the exporter's machine-local abs path.
    ext = str(tmp_path / "ext_sfx")
    _write(ext, "g1/drip.ogg", "drip")
    _seed(
        cue_env,
        [
            (
                "data/markers/{}/a.json".format(GAME_ID),
                '{{"replay": "Run 1", "pools": [{{"files": ["{}"]}}]}}'.format(ext + "/g1/drip.ogg"),
            )
        ],
    )
    _write_shared_config(cue_env, sfx=[ext])

    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_scope", CueExportScope.SPECIFIC_REPLAYS)
    mgr.name = "Replay"

    _export_and_join(mgr)

    zip_path = os.path.join(mgr._paths.exports_dir, "Replay.zip")
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        marker = json.loads(zf.read("data/markers/{}/a.json".format(GAME_ID)))

    baked = [n for n in names if n.startswith("audio/_external/")]
    assert len(baked) == 1
    ns = _baked_ns(baked[0])
    assert ns.startswith("ext_sfx-")
    assert baked[0].endswith("g1/drip.ogg")
    # The marker's pool ref is now the portable relative path (no abs root).
    assert marker["pools"][0]["files"] == ["_external/{}/g1/drip.ogg".format(ns)]


def test_external_bake_music_ref_exported_relative(tmp_path, cue_env):
    # A music entry ships as music/_external/... and keeps the u: music/ prefix
    # so _cue_music_rel still resolves it on import.
    ext = str(tmp_path / "ext_music")
    _write(ext, "artist/song.ogg", "song")
    _seed(
        cue_env,
        [
            (
                "data/markers/{}/a.json".format(GAME_ID),
                '{{"replay": "Run 1", "pools": [], "music": ["{}"]}}'.format(ext + "/artist/song.ogg"),
            )
        ],
    )
    _write_shared_config(cue_env, music=[ext])

    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_scope", CueExportScope.SPECIFIC_REPLAYS)
    mgr.name = "Music"

    _export_and_join(mgr)

    zip_path = os.path.join(mgr._paths.exports_dir, "Music.zip")
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        marker = json.loads(zf.read("data/markers/{}/a.json".format(GAME_ID)))

    baked = [n for n in names if n.startswith("music/_external/")]
    assert len(baked) == 1
    ns = _baked_ns(baked[0])
    assert ns.startswith("ext_music-")
    assert baked[0].endswith("artist/song.ogg")
    assert marker["music"] == ["u:music/_external/{}/artist/song.ogg".format(ns)]


def test_external_bake_folder_ref_expands_files(tmp_path, cue_env):
    # A folder ref (trailing '/') under an external root expands to every file
    # beneath it, each baked individually under the same per-source namespace.
    ext_root = str(tmp_path / "ext_hits")
    ext_folder = str(tmp_path / "ext_hits" / "impacts") + "/"  # folder ref keeps the trailing '/'
    _write(str(tmp_path / "ext_hits" / "impacts"), "a.ogg", "a")
    _write(str(tmp_path / "ext_hits" / "impacts"), "b.ogg", "b")
    _seed(
        cue_env,
        [
            (
                "data/markers/{}/a.json".format(GAME_ID),
                '{{"replay": "Run 1", "pools": [{{"files": ["{}"]}}]}}'.format(ext_folder),
            )
        ],
    )
    _write_shared_config(cue_env, sfx=[ext_root])

    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_scope", CueExportScope.SPECIFIC_REPLAYS)
    mgr.name = "Folder"

    _export_and_join(mgr)

    zip_path = os.path.join(mgr._paths.exports_dir, "Folder.zip")
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        marker = json.loads(zf.read("data/markers/{}/a.json".format(GAME_ID)))

    baked = sorted(n for n in names if n.startswith("audio/_external/"))
    assert len(baked) == 2
    ns = _baked_ns(baked[0])
    assert ns.startswith("ext_hits-")
    assert baked == ["audio/_external/{}/impacts/a.ogg".format(ns), "audio/_external/{}/impacts/b.ogg".format(ns)]
    # The folder ref is rewritten to a folder ref under the baked namespace.
    assert marker["pools"][0]["files"] == ["_external/{}/impacts/".format(ns)]


def test_external_bake_respects_unchecked_category(tmp_path, cue_env):
    # Specific File Types with SFX unchecked must NOT bake the external SFX ref
    # nor rewrite the marker -- an unchecked category never sneaks its media in.
    ext = str(tmp_path / "ext_sfx")
    _write(ext, "g1/drip.ogg", "drip")
    _seed(
        cue_env,
        [
            (
                "data/markers/{}/a.json".format(GAME_ID),
                '{{"replay": "Run 1", "pools": [{{"files": ["{}"]}}]}}'.format(ext + "/g1/drip.ogg"),
            )
        ],
    )
    _write_shared_config(cue_env, sfx=[ext])

    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_scope", CueExportScope.SPECIFIC_REPLAYS)
    _switch(mgr, "set_file_types", CueExportFileTypes.SPECIFIC)
    mgr.toggle_category(CueImportCategory.SFX)  # off
    mgr.name = "NoSfx"

    _export_and_join(mgr)

    zip_path = os.path.join(mgr._paths.exports_dir, "NoSfx.zip")
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        marker = json.loads(zf.read("data/markers/{}/a.json".format(GAME_ID)))

    assert not any(n.startswith("audio/_external/") for n in names)
    # Marker ships, unchanged -- the abs ref is left as-is.
    assert marker["pools"][0]["files"] == [ext + "/g1/drip.ogg"]


def test_external_bake_whole_game_scope(tmp_path, cue_env):
    # Whole-game export bakes external refs too (markers are all in scope).
    ext = str(tmp_path / "ext_sfx")
    _write(ext, "g1/drip.ogg", "drip")
    _seed(
        cue_env,
        [("data/markers/{}/a.json".format(GAME_ID), '{{"pools": [{{"files": ["{}"]}}]}}'.format(ext + "/g1/drip.ogg"))],
    )
    _write_shared_config(cue_env, sfx=[ext])

    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    assert mgr.scope == CueExportScope.ALL_REPLAYS
    mgr.name = "Whole"

    _export_and_join(mgr)

    zip_path = os.path.join(mgr._paths.exports_dir, "Whole.zip")
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        marker = json.loads(zf.read("data/markers/{}/a.json".format(GAME_ID)))

    baked = [n for n in names if n.startswith("audio/_external/")]
    assert len(baked) == 1
    ns = _baked_ns(baked[0])
    assert marker["pools"][0]["files"] == ["_external/{}/g1/drip.ogg".format(ns)]


# intensity groups -- a hooked pool ships the WHOLE group (JSON + audio)
# ---------------------------------------------------------------------------


def _igroup_rel(name):
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:CUE_HASH_TRUNC_LEN]
    return "data/presets/intensity/{}_{}.json".format(name, digest)


def test_export_ships_intensity_group_content(cue_env):
    # A whole-game export ships the igroup JSON (Presets) and the audio files
    # its level refs point at (SFX).
    name = "Impacts"
    _seed(
        cue_env,
        [
            (_igroup_rel(name), '{"_key": "Impacts", "levels": [{"id": 1, "files": ["soft/"]}]}'),
            ("audio/soft/a.ogg", "a"),
            ("audio/soft/b.ogg", "b"),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    mgr.name = "FullI"
    assert mgr.counts[CueImportCategory.PRESETS] == 1

    _export_and_join(mgr)

    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "FullI.zip")) as zf:
        names = set(zf.namelist())
    assert _igroup_rel(name) in names
    assert "audio/soft/a.ogg" in names
    assert "audio/soft/b.ogg" in names


def test_export_replay_packs_intensity_group(cue_env):
    # A hooked pool: replay export must detect the igroup and pull the WHOLE
    # group (JSON + every level's referenced files, not just the pinned level).
    name = "Impacts"
    _seed(
        cue_env,
        [
            (
                _igroup_rel(name),
                '{"_key": "Impacts", "levels": [{"id": 1, "files": ["soft/"]}, '
                '{"id": 2, "files": ["hard/c.ogg"]}], "next_ilevel_id": 3}',
            ),
            ("audio/soft/a.ogg", "a"),
            ("audio/soft/b.ogg", "b"),
            ("audio/hard/c.ogg", "c"),
            (
                "data/markers/{}/r1.json".format(GAME_ID),
                '{"replay": "Run 1", "pools": [{"igroup": {"name": "Impacts", "level": 1}}]}',
            ),
        ],
    )
    mgr = CueExportManager(cue_env.paths)
    _refresh_and_join(mgr)
    _switch(mgr, "set_scope", CueExportScope.SPECIFIC_REPLAYS)
    mgr.name = "Intensity"

    _export_and_join(mgr)

    with zipfile.ZipFile(os.path.join(mgr._paths.exports_dir, "Intensity.zip")) as zf:
        names = set(zf.namelist())
    assert "data/markers/{}/r1.json".format(GAME_ID) in names
    assert _igroup_rel(name) in names
    assert "audio/soft/a.ogg" in names
    assert "audio/soft/b.ogg" in names
    assert "audio/hard/c.ogg" in names
