# -*- coding: utf-8 -*-
# Tests for cue_lib.sharing.importer_io -- pure logic: category mapping, game_id matching,
# contents grouping/filtering, manifest build/validate, replay-scoped export.

import json as _json
import os

from cue_lib.sharing import importer_io as _imp
from cue_lib.constants import CUE_IMPORT_CATEGORY_ORDER, CUE_IMPORT_MANIFEST_NAME, CueImportCategory, CueImportMatch
from cue_lib.sharing.importer_io import CUE_IMPORT_FORMAT_VERSION

GAME_ID = "test_game"


def _write(root, rel, content):
    path = os.path.join(root, *rel.split("/"))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as f:
        f.write(content)
    return path


def _write_marker(cue_env, name, entry):
    """Write one marker JSON to the game's marker dir."""
    _write(cue_env.paths.original_root, "data/markers/{}/{}.json".format(GAME_ID, name), _json.dumps(entry))


def _preset_rel(preset_name, sub):
    """Rel path of the stored preset file, mirroring db._preset_path naming."""
    import hashlib as _hashlib

    safe = preset_name.replace("/", "_").replace("\\", "_")
    digest = _hashlib.sha1(preset_name.encode("utf-8")).hexdigest()[:8]
    return "data/presets/{}/{}_{}.json".format(sub, safe, digest)


# ---------------------------------------------------------------------------
# _cue_import_category -- path prefix -> category
# ---------------------------------------------------------------------------


def test_category_maps_each_prefix():
    cats = CueImportCategory
    cases = [
        ("data/markers/g1/pool.json", cats.MARKERS),
        ("audio/sfx1.ogg", cats.SFX),
        ("music/Folder/song.ogg", cats.MUSIC),
        ("video/g1/movie_cue0.5x.mkv", cats.SPEED_VARIANTS),
        ("data/presets/audio/save_1a2b.json", cats.PRESETS),
        ("data/presets/video/save_1a2b.json", cats.PRESETS),
        ("data/presets/music/save_1a2b.json", cats.PRESETS),
    ]
    for path, expected in cases:
        assert _imp._cue_import_category(path) == expected, path


def test_category_unknown_for_unmapped():
    assert _imp._cue_import_category("data/other/x.json") == CueImportCategory.UNKNOWN
    assert _imp._cue_import_category("manifest.json") == CueImportCategory.UNKNOWN
    assert _imp._cue_import_category("") == CueImportCategory.UNKNOWN


# ---------------------------------------------------------------------------
# _cue_digit_strip_normalize
# ---------------------------------------------------------------------------


def test_digit_strip_normalize():
    assert _imp._cue_digit_strip_normalize("MyGame123") == "mygame"
    assert _imp._cue_digit_strip_normalize("MyGame456") == "mygame"
    assert _imp._cue_digit_strip_normalize("MyGame") == "mygame"
    assert _imp._cue_digit_strip_normalize("my_game_99") == "mygame"
    assert _imp._cue_digit_strip_normalize("") == ""


# ---------------------------------------------------------------------------
# _cue_import_match -- three match levels + reasons
# ---------------------------------------------------------------------------


def test_match_raw_equal_is_auto():
    lvl, reason = _imp._cue_import_match("Game-Patreon-123", "Game-Patreon-123")
    assert lvl == CueImportMatch.AUTO
    assert reason == ""


def test_match_tokens_equal_is_auto():
    # Cosmetic case/hyphen variance only.
    lvl, reason = _imp._cue_import_match("Game-Pat-123", "game-pat-123")
    assert lvl == CueImportMatch.AUTO
    assert reason == ""


def test_match_shared_prefix_is_confirm():
    # The two BeingaDIK installs: same install-method prefix, different store.
    a = "BeingaDIKSeason3-Patreon-1535311494"
    b = "BeingaDIKSeason3-Steam-15353234234"
    lvl, reason = _imp._cue_import_match(a, b)
    assert lvl == CueImportMatch.CONFIRM
    assert "BeingaDIKSeason3" in reason


def test_match_digit_strip_is_confirm():
    lvl, reason = _imp._cue_import_match("MyGame123", "MyGame456")
    assert lvl == CueImportMatch.CONFIRM
    assert reason  # a guess must come with a why


def test_match_mismatch():
    lvl, reason = _imp._cue_import_match("GameOne", "CompletelyDifferentGame")
    assert lvl == CueImportMatch.MISMATCH
    assert reason


# ---------------------------------------------------------------------------
# contents grouping / counts / empty / filter
# ---------------------------------------------------------------------------


def test_group_contents_groups_by_category():
    contents = ["audio/a.ogg", "music/b.ogg", "data/markers/g1/x.json"]
    grouped = _imp._cue_group_contents(contents)
    assert grouped[CueImportCategory.SFX] == ["audio/a.ogg"]
    assert grouped[CueImportCategory.MUSIC] == ["music/b.ogg"]
    assert grouped[CueImportCategory.MARKERS] == ["data/markers/g1/x.json"]


def test_category_counts_only_has_present_categories():
    contents = ["audio/a.ogg", "audio/b.ogg"]
    counts = _imp._cue_category_counts(contents)
    assert counts == {CueImportCategory.SFX: 2}


def test_empty_categories_lists_absent():
    contents = ["audio/a.ogg"]
    empty = _imp._cue_empty_categories(contents)
    assert CueImportCategory.SFX not in empty
    for cat in CUE_IMPORT_CATEGORY_ORDER:
        if cat != CueImportCategory.SFX:
            assert cat in empty


def test_filter_contents_keeps_only_checked():
    contents = ["audio/a.ogg", "music/b.ogg", "data/markers/g1/x.json"]
    filtered = _imp._cue_filter_contents(contents, [CueImportCategory.SFX])
    assert filtered == ["audio/a.ogg"]


def test_filter_contents_drops_unknown_always():
    contents = ["data/other/x.json", "audio/a.ogg"]
    filtered = _imp._cue_filter_contents(contents, CUE_IMPORT_CATEGORY_ORDER)
    assert filtered == ["audio/a.ogg"]


# ---------------------------------------------------------------------------
# manifest build / validate
# ---------------------------------------------------------------------------


def test_build_manifest_shape():
    m = _imp._cue_build_manifest("g1", "My pack", "author", "desc", ["audio/a.ogg"])
    assert m["format_version"] == CUE_IMPORT_FORMAT_VERSION
    assert m["game_id"] == "g1"
    assert m["name"] == "My pack"
    assert m["author"] == "author"
    assert m["description"] == "desc"
    assert m["contents"] == ["audio/a.ogg"]


def test_build_manifest_truncates_long_fields():
    m = _imp._cue_build_manifest("g1", "n" * 100, "a" * 100, "d" * 500, ["audio/a.ogg"])
    assert m["name"] == "n" * 60
    assert m["author"] == "a" * 40
    assert m["description"] == "d" * 300


def test_build_manifest_includes_replays():
    replays = [{"replay": "Run 1", "marker_count": 2}]
    m = _imp._cue_build_manifest("g1", "", "", "", ["audio/a.ogg"], replays)
    assert m["replays"] == replays


def test_build_manifest_replays_default_empty():
    m = _imp._cue_build_manifest("g1", "", "", "", ["audio/a.ogg"])
    assert m["replays"] == []


def test_validate_manifest_accepts_ok():
    m = _imp._cue_build_manifest("g1", "", "", "", ["audio/a.ogg"])
    ok, _err = _imp._cue_validate_manifest(m, {"audio/a.ogg"})
    assert ok


def test_validate_manifest_rejects_newer_format():
    m = _imp._cue_build_manifest("g1", "", "", "", ["audio/a.ogg"])
    m["format_version"] = CUE_IMPORT_FORMAT_VERSION + 1
    ok, err = _imp._cue_validate_manifest(m, {"audio/a.ogg"})
    assert not ok
    assert "newer" in err


def test_validate_manifest_rejects_non_dict():
    ok, err = _imp._cue_validate_manifest(None, set())
    assert not ok
    assert "not a renpy_cue import" in err


def test_validate_manifest_rejects_missing_contents_list():
    m = {"format_version": CUE_IMPORT_FORMAT_VERSION}
    ok, err = _imp._cue_validate_manifest(m, set())
    assert not ok
    assert "not a renpy_cue import" in err


def test_validate_manifest_allows_file_not_in_zip():
    # A listed file absent from the zip is a warning, not a refusal -- the
    # missing list drives a confirm dialog, never a hard invalid state.
    m = _imp._cue_build_manifest("g1", "", "", "", ["audio/a.ogg"])
    ok, _err = _imp._cue_validate_manifest(m, {"audio/b.ogg"})
    assert ok


def test_missing_files_lists_absent_paths():
    m = _imp._cue_build_manifest("g1", "", "", "", ["audio/a.ogg", "music/m.ogg", "video/v.mkv"])
    assert _imp._cue_missing_files(m, {"audio/a.ogg", "music/m.ogg"}) == ["video/v.mkv"]
    assert _imp._cue_missing_files(m, set(m["contents"])) == []
    assert _imp._cue_missing_files(None, set()) == []


def test_missing_files_coerces_unicode_and_bytes(monkeypatch):
    """Py2: manifest rels decode from json as unicode, zip names come back
    from zipfile as raw str bytes.  Without _to_str bridging both sides, a
    non-ASCII filename present in the zip is falsely reported missing."""
    # Simulate Py2's _to_str (a no-op on Py3): decode the bytes side to
    # unicode so the membership compare sees two equal values.
    monkeypatch.setattr(_imp, "_to_str", lambda obj: obj.decode("utf-8") if isinstance(obj, bytes) else obj)
    m = _imp._cue_build_manifest("g1", "", "", "", ["music/café.ogg"])
    zip_names = [b"music/caf\xc3\xa9.ogg"]  # Py2 str bytes, not Py3 .encode()
    assert _imp._cue_missing_files(m, zip_names) == []


def test_manifest_replays_counts_by_field(cue_env):
    _write_marker(cue_env, "a", {"replay": "Run 2", "pools": []})
    _write_marker(cue_env, "b", {"replay": "Run 1", "pools": []})
    _write_marker(cue_env, "c", {"replay": "Run 1", "pools": []})
    _write_marker(cue_env, "d", {"pools": []})  # never edited inside a replay
    contents = [
        "data/markers/{}/a.json".format(GAME_ID),
        "data/markers/{}/b.json".format(GAME_ID),
        "data/markers/{}/c.json".format(GAME_ID),
        "data/markers/{}/d.json".format(GAME_ID),
    ]
    replays = _imp._cue_manifest_replays(cue_env.paths.original_root, GAME_ID, contents)
    assert replays == [{"replay": "Run 1", "marker_count": 2}, {"replay": "Run 2", "marker_count": 1}]


def test_manifest_replays_only_counts_packed_files(cue_env):
    # A marker excluded from the zip must not be listed -- a Specific-Replays
    # export carries only its own replays' markers.
    _write_marker(cue_env, "a", {"replay": "Run 1", "pools": []})
    _write_marker(cue_env, "b", {"replay": "Run 2", "pools": []})
    contents = ["data/markers/{}/a.json".format(GAME_ID)]
    replays = _imp._cue_manifest_replays(cue_env.paths.original_root, GAME_ID, contents)
    assert replays == [{"replay": "Run 1", "marker_count": 1}]


def test_manifest_replays_ignores_unreadable_marker(cue_env):
    _write_marker(cue_env, "a", {"replay": "Run 1", "pools": []})
    contents = [
        "data/markers/{}/a.json".format(GAME_ID),
        "data/markers/{}/broken.json".format(GAME_ID),  # not on disk
    ]
    replays = _imp._cue_manifest_replays(cue_env.paths.original_root, GAME_ID, contents)
    assert replays == [{"replay": "Run 1", "marker_count": 1}]


# ---------------------------------------------------------------------------
# filename sanitization
# ---------------------------------------------------------------------------


def test_sanitize_filename():
    assert _imp._cue_sanitize_filename("My Pack") == "My Pack"
    assert _imp._cue_sanitize_filename("a/b\\c") == "a_b_c"
    assert _imp._cue_sanitize_filename("x:y*?<>|z") == "xyz"
    assert _imp._cue_sanitize_filename("...") == "cue_import"
    assert _imp._cue_sanitize_filename("") == "cue_import"


# ---------------------------------------------------------------------------
# _cue_replay_labels / _cue_replay_assets -- replay-scoped export content
# ---------------------------------------------------------------------------


def test_replay_labels_counts_per_replay(cue_env):
    _write_marker(cue_env, "a", {"replay": "Run 1", "pools": []})
    _write_marker(cue_env, "b", {"replay": "Run 1", "pools": []})
    _write_marker(cue_env, "c", {"replay": "Run 2", "pools": []})
    _write_marker(cue_env, "d", {"pools": []})  # never edited in a replay

    labels = _imp._cue_replay_labels(cue_env.paths.original_root, GAME_ID)

    assert labels == [("Run 1", 2), ("Run 2", 1)]


def test_replay_assets_picks_markers_for_selected_labels(cue_env):
    _write_marker(cue_env, "a", {"replay": "Run 1", "pools": []})
    _write_marker(cue_env, "b", {"replay": "Run 2", "pools": []})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets == {CueImportCategory.MARKERS: ["data/markers/{}/a.json".format(GAME_ID)]}


def test_replay_assets_follows_sfx_pool_refs_and_expands_folders(cue_env):
    _write(cue_env.paths.original_root, "audio/g1/boom.ogg", "b")
    _write(cue_env.paths.original_root, "audio/g1/folder/hit.ogg", "h")
    _write_marker(
        cue_env, "a", {"replay": "Run 1", "pools": [{"files": ["audio/g1/boom.ogg"]}, {"files": ["audio/g1/folder/"]}]}
    )

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets[CueImportCategory.SFX] == ["audio/g1/boom.ogg", "audio/g1/folder/hit.ogg"]


def test_audio_rel_prefixes_relative_refs():
    assert _imp._cue_audio_rel("g1/s.ogg") == "audio/g1/s.ogg"
    assert _imp._cue_audio_rel("g1/") == "audio/g1/"
    assert _imp._cue_audio_rel("s.ogg") == "audio/s.ogg"
    # Already root-relative (or another category) passes through.
    assert _imp._cue_audio_rel("audio/g1/s.ogg") == "audio/g1/s.ogg"
    assert _imp._cue_audio_rel("video/v.mkv") == "video/v.mkv"


def test_music_rel_strips_tags():
    assert _imp._cue_music_rel("u:music/song.ogg") == "music/song.ogg"
    assert _imp._cue_music_rel("g:music/song.ogg") is None
    assert _imp._cue_music_rel("music/song.ogg") == "music/song.ogg"
    assert _imp._cue_music_rel("game/bgm.ogg") is None
    assert _imp._cue_music_rel(None) is None


def test_replay_assets_resolves_audio_relative_pool_refs(cue_env):
    # On disk, pool file refs are audio-dir-relative (they index the SFX
    # manager's flat file list) -- the exporter must prefix audio/ to resolve
    # them into the shared root.  Folder refs keep their trailing '/' and
    # expand against the shared tree.
    _write(cue_env.paths.original_root, "audio/g1/s.ogg", "s")
    _write(cue_env.paths.original_root, "audio/g1/boom.ogg", "b")
    _write_marker(cue_env, "a", {"replay": "Run 1", "pools": [{"files": ["g1/s.ogg", "g1/"]}]})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets[CueImportCategory.SFX] == ["audio/g1/s.ogg", "audio/g1/boom.ogg"]


def test_replay_assets_music_refs_are_source_tagged(cue_env):
    # My Music refs are stored 'u:'-tagged (shareable); Game Music is 'g:'-
    # tagged or a bare game-relative path -- the recipient has their own.
    _write(cue_env.paths.original_root, "music/Folder/song.ogg", "m")
    _write(cue_env.paths.original_root, "music/Folder/other.ogg", "o")
    _write_marker(
        cue_env,
        "a",
        {"replay": "Run 1", "music": ["u:music/Folder/song.ogg", "g:music/Folder/other.ogg", "game/bgm.ogg"]},
    )

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets.get(CueImportCategory.MUSIC) == ["music/Folder/song.ogg"]
    assert not any("other" in v for v in assets.values())
    assert not any("bgm" in v for v in assets.values())


def test_replay_assets_expands_tagged_my_music_folder_ref(cue_env):
    _write(cue_env.paths.original_root, "music/Folder/song.ogg", "m")
    _write_marker(cue_env, "a", {"replay": "Run 1", "music": ["u:music/Folder/"]})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets.get(CueImportCategory.MUSIC) == ["music/Folder/song.ogg"]


def test_replay_assets_treats_timestamps_like_pools(cue_env):
    _write(cue_env.paths.original_root, "audio/g1/boom.ogg", "b")
    _write_marker(cue_env, "a", {"replay": "Run 1", "timestamps": [{"files": ["audio/g1/boom.ogg"]}]})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets[CueImportCategory.SFX] == ["audio/g1/boom.ogg"]


def test_replay_assets_drops_game_music_keeps_my_music(cue_env):
    _write(cue_env.paths.original_root, "music/song.ogg", "m")
    _write_marker(cue_env, "a", {"replay": "Run 1", "music": ["music/song.ogg", "game/bgm.ogg"]})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets.get(CueImportCategory.MUSIC) == ["music/song.ogg"]
    assert not any("game/bgm.ogg" in v for v in assets.values())


def test_replay_assets_includes_speed_variant_videos(cue_env):
    _write(cue_env.paths.original_root, "video/{}/clip.mkv".format(GAME_ID), "v")
    _write_marker(cue_env, "a", {"replay": "Run 1", "files": ["video/{}/clip.mkv".format(GAME_ID)]})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets.get(CueImportCategory.SPEED_VARIANTS) == ["video/{}/clip.mkv".format(GAME_ID)]


def test_replay_assets_resolves_preset_references(cue_env):
    _write(cue_env.paths.original_root, _preset_rel("Growl", "audio"), "{}")
    _write_marker(cue_env, "a", {"replay": "Run 1", "pools": [{"preset": "Growl"}]})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets.get(CueImportCategory.PRESETS) == [_preset_rel("Growl", "audio")]


def test_replay_assets_skips_unparsable_marker(cue_env):
    _write(cue_env.paths.original_root, "data/markers/{}/bad.json".format(GAME_ID), "{ not json")
    _write_marker(cue_env, "ok", {"replay": "Run 1", "pools": []})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets == {CueImportCategory.MARKERS: ["data/markers/{}/ok.json".format(GAME_ID)]}


def test_replay_assets_dedupes_shared_files(cue_env):
    _write(cue_env.paths.original_root, "audio/g1/boom.ogg", "b")
    _write_marker(cue_env, "a", {"replay": "Run 1", "pools": [{"files": ["audio/g1/boom.ogg"]}]})
    _write_marker(cue_env, "b", {"replay": "Run 1", "pools": [{"files": ["audio/g1/boom.ogg"]}]})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets[CueImportCategory.SFX] == ["audio/g1/boom.ogg"]


def test_replay_assets_includes_all_variants_when_replay_has_video_marker(cue_env):
    # Speed variants live in video/<gid>/ but the base movie path is runtime
    # state, not on markers -- so a replay with any video marker pulls the
    # whole tree (accepting over-inclusion).
    _write(cue_env.paths.original_root, "video/{}/clip_cue0.5x.mkv".format(GAME_ID), "a")
    _write(cue_env.paths.original_root, "video/{}/clip_cue2.0x.mkv".format(GAME_ID), "b")
    _write_marker(cue_env, "v_clip.mkv", {"replay": "Run 1", "pools": []})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert sorted(assets.get(CueImportCategory.SPEED_VARIANTS)) == [
        "video/{}/clip_cue0.5x.mkv".format(GAME_ID),
        "video/{}/clip_cue2.0x.mkv".format(GAME_ID),
    ]


def test_replay_assets_leaves_variants_out_for_non_video_markers(cue_env):
    _write(cue_env.paths.original_root, "video/{}/clip_cue0.5x.mkv".format(GAME_ID), "a")
    _write_marker(cue_env, "a", {"replay": "Run 1", "files": ["video/{}/clip.mkv".format(GAME_ID)]})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    # Only the referenced clip ships -- no video marker means the variant
    # tree is not pulled.
    assert assets.get(CueImportCategory.SPEED_VARIANTS) == ["video/{}/clip.mkv".format(GAME_ID)]


def test_replay_assets_skips_variants_for_unselected_replay(cue_env):
    _write(cue_env.paths.original_root, "video/{}/clip_cue0.5x.mkv".format(GAME_ID), "a")
    _write_marker(cue_env, "v_clip.mkv", {"replay": "Run 2", "pools": []})

    assets = _imp._cue_replay_assets(cue_env.paths.original_root, GAME_ID, ["Run 1"])

    assert assets.get(CueImportCategory.SPEED_VARIANTS) is None
