# -*- coding: utf-8 -*-
# Tests for cue_lib.importer_io -- filesystem IO: zip build/extract, and
# merge copy with the data_bak safety net.

import hashlib as _hashlib
import json as _json
import os
import zipfile

from cue_lib import importer_io as _imp
from cue_lib.backup import _safe_extract_path
from cue_lib.constants import CUE_IMPORT_MANIFEST_NAME

GAME_ID = "g1"


def _write(root, rel, content):
    path = os.path.join(root, *rel.split("/"))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as f:
        f.write(content)
    return path


def _read(path):
    with open(path) as f:
        return f.read()


def _preset_rel(preset_name, sub):
    """Rel path of the stored preset file, mirroring db._preset_path naming."""
    safe = preset_name.replace("/", "_").replace("\\", "_")
    digest = _hashlib.sha1(preset_name.encode("utf-8")).hexdigest()[:8]
    return "data/presets/{}/{}_{}.json".format(sub, safe, digest)


def _walk_rel(root):
    """Every file under root as a '/' relative path."""
    result = set()
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            result.add(os.path.relpath(os.path.join(dirpath, name), root)
                       .replace("\\", "/"))
    return result


def _build_root(tmp_path):
    """A shared root with one file in every category."""
    root = str(tmp_path / "root")
    files = [
        ("data/markers/{}/v_a.json".format(GAME_ID), '{"pools": []}'),
        ("audio/sfx.ogg", "sfx"),
        ("music/song.ogg", "music"),
        ("video/{}/m_cue0.5x.mkv".format(GAME_ID), "video"),
        ("data/presets/audio/p.json", "ap"),
        ("data/presets/video/p.json", "vp"),
        ("data/presets/music/p.json", "mp"),
    ]
    for rel, content in files:
        _write(root, rel, content)
    return root


# ---------------------------------------------------------------------------
# _cue_build_import_zip / _cue_extract_import_zip
# ---------------------------------------------------------------------------

def test_build_package_zip_writes_manifest_and_contents(tmp_path):
    root = _build_root(tmp_path)
    contents = _imp._cue_enumerate_import_files(root, GAME_ID)
    flat = [f for files in contents.values() for f in files]
    zip_path = str(tmp_path / "out.zip")

    count = _imp._cue_build_import_zip(root, GAME_ID, "My pack", "author", "d", flat, zip_path)

    assert os.path.isfile(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert CUE_IMPORT_MANIFEST_NAME in names
        for rel in flat:
            assert rel in names
            assert _read(os.path.join(root, rel)) == zf.read(rel).decode("utf-8")
        import json as _json
        manifest = _json.loads(zf.read(CUE_IMPORT_MANIFEST_NAME))
        assert manifest["name"] == "My pack"
        assert sorted(manifest["contents"]) == sorted(flat)
    # manifest + every content file
    assert count == len(flat)


def test_build_package_zip_reports_progress(tmp_path):
    root = _build_root(tmp_path)
    flat = [f for files in _imp._cue_enumerate_import_files(root, GAME_ID).values()
            for f in files]
    zip_path = str(tmp_path / "out.zip")
    calls = []

    def _cb(written, total):
        calls.append((written, total))

    _imp._cue_build_import_zip(
        root, GAME_ID, "", "", "", flat, zip_path, progress=_cb)

    # One callback per packed file; the last lands on the full byte total.
    assert len(calls) == len(flat)
    assert calls[-1][0] == calls[-1][1] > 0


def test_build_package_zip_skips_missing_files_and_counts_them_out(tmp_path):
    root = _build_root(tmp_path)
    flat = [f for files in _imp._cue_enumerate_import_files(root, GAME_ID).values()
            for f in files]
    missing = "audio/gone.ogg"
    zip_path = str(tmp_path / "out.zip")
    calls = []

    def _cb(written, total):
        calls.append((written, total))

    count = _imp._cue_build_import_zip(
        root, GAME_ID, "", "", "", flat + [missing], zip_path,
        progress=_cb)

    assert count == len(flat)
    # The missing file contributes nothing to progress, so the last callback
    # still lands on the total.
    assert calls[-1][0] == calls[-1][1]


def test_enumerate_package_files_groups_flat(tmp_path):
    root = _build_root(tmp_path)
    contents = _imp._cue_enumerate_import_files(root, GAME_ID)
    flat = [f for files in contents.values() for f in files]
    assert len(flat) == 7
    assert "data/markers/{}/v_a.json".format(GAME_ID) in flat
    assert "video/{}/m_cue0.5x.mkv".format(GAME_ID) in flat


def test_enumerate_package_files_missing_dir_is_empty(tmp_path):
    root = str(tmp_path / "empty")
    assert _imp._cue_enumerate_import_files(root, GAME_ID) == {}


def test_extract_package_zip_lands_files(tmp_path):
    src = _build_root(tmp_path)
    flat = [f for files in _imp._cue_enumerate_import_files(src, GAME_ID).values() for f in files]
    zip_path = str(tmp_path / "imp.zip")
    _imp._cue_build_import_zip(src, GAME_ID, "", "", "", flat, zip_path)

    out = str(tmp_path / "out")
    count = _imp._cue_extract_import_zip(zip_path, out)

    assert os.path.isfile(os.path.join(out, CUE_IMPORT_MANIFEST_NAME))
    for rel in flat:
        assert _read(os.path.join(out, rel)) == _read(os.path.join(src, rel))
    assert count == len(flat) + 1  # manifest + contents


def test_extract_rejects_parent_traversal(tmp_path):
    out = str(tmp_path / "out")
    zip_path = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.txt", "boom")
        zf.writestr("audio/..\\..\\evil.txt", "boom")   # Windows-style ..\\
        zf.writestr("C:\\evil.exe", "boom")             # drive-absolute
        zf.writestr("audio/ok.mp3", "fine")
        zf.writestr("music/ok.ogg", "fine")

    _imp._cue_extract_import_zip(zip_path, out)

    # Nothing escaped out_dir -- on any platform.
    assert not os.path.isfile(str(tmp_path / "evil.txt"))
    assert not os.path.isfile(os.path.join(str(tmp_path), "evil.exe"))
    # Traversal-dropped names aren't cue content, so they're dropped too.
    assert _walk_rel(out) == {"audio/ok.mp3", "music/ok.ogg"}


def test_safe_extract_path_never_escapes(tmp_path):
    out = str(tmp_path / "out")
    base = os.path.normpath(out)
    for name in ["../evil.txt", "..\\..\\evil.txt", "audio/..\\..\\evil.txt",
                 "C:\\evil.exe", "/abs/evil.txt", "audio/ok.mp3"]:
        dest = _safe_extract_path(out, name)
        assert dest is None or dest == base or dest.startswith(base + os.sep)


def test_extract_keeps_only_known_content(tmp_path):
    out = str(tmp_path / "out")
    zip_path = str(tmp_path / "pkg.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(CUE_IMPORT_MANIFEST_NAME, "{}")
        zf.writestr("audio/ok.mp3", "a")
        zf.writestr("audio/evil.exe", "x")
        zf.writestr("music/track.ogg", "b")
        zf.writestr("data/markers/{}/m.json".format(GAME_ID), "{}")
        zf.writestr("data/presets/audio/p.json", "{}")
        zf.writestr("evil.exe", "x")          # root junk, no prefix
        zf.writestr("notes.txt", "x")         # unknown extension

    count = _imp._cue_extract_import_zip(zip_path, out)

    assert count == 5  # manifest + ok.mp3 + track.ogg + m.json + p.json
    assert _walk_rel(out) == {
        CUE_IMPORT_MANIFEST_NAME,
        "audio/ok.mp3",
        "music/track.ogg",
        "data/markers/{}/m.json".format(GAME_ID),
        "data/presets/audio/p.json",
    }


def test_enumerate_skips_non_media_files(tmp_path):
    """Export never ships non-cue files, so a manifest can't list content the
    import would drop (which would surface as a bogus 'missing files' warn)."""
    root = str(tmp_path / "root")
    _write(root, "audio/ok.ogg", "a")
    _write(root, "audio/notes.txt", "x")
    _write(root, "video/{}/clip.mkv".format(GAME_ID), "v")
    _write(root, "video/{}/thumb.png".format(GAME_ID), "p")

    flat = [f for fs in _imp._cue_enumerate_import_files(root, GAME_ID).values()
            for f in fs]

    assert sorted(flat) == ["audio/ok.ogg", "video/{}/clip.mkv".format(GAME_ID)]


def test_merge_skips_unknown_content(tmp_path):
    root = str(tmp_path / "root")
    src = str(tmp_path / "src")
    _write(src, "audio/ok.mp3", "a")
    _write(src, "audio/evil.exe", "x")
    contents = ["audio/ok.mp3", "audio/evil.exe"]

    count = _imp._cue_merge_files(root, src, contents)

    assert count == 1
    assert os.path.isfile(os.path.join(root, "audio", "ok.mp3"))
    assert not os.path.exists(os.path.join(root, "audio", "evil.exe"))


# ---------------------------------------------------------------------------
# merge: overwrites list + copy with data_bak safety net
# ---------------------------------------------------------------------------

def test_merge_overwrites_lists_only_existing(tmp_path):
    root = str(tmp_path / "root")
    _write(root, "audio/a.ogg", "a")
    contents = ["audio/a.ogg", "audio/missing.ogg"]
    assert _imp._cue_merge_overwrites(root, contents) == ["audio/a.ogg"]


def test_merge_files_copies_and_baks_overwrites(tmp_path):
    root = str(tmp_path / "root")
    src = str(tmp_path / "src")
    _write(root, "data/markers/{}/m.json".format(GAME_ID), "old")
    _write(root, "audio/keep.ogg", "keep-me")
    _write(src, "data/markers/{}/m.json".format(GAME_ID), "new")
    _write(src, "audio/x.ogg", "audio")
    contents = ["data/markers/{}/m.json".format(GAME_ID), "audio/x.ogg"]

    count = _imp._cue_merge_files(root, src, contents)

    assert count == 2
    assert _read(os.path.join(root, "data/markers", GAME_ID, "m.json")) == "new"
    assert _read(os.path.join(root, "audio", "x.ogg")) == "audio"
    # Source package stays intact (recovery without re-download).
    assert _read(os.path.join(src, "data/markers", GAME_ID, "m.json")) == "new"
    # Overwritten file went to data_bak, untouched files stayed put.
    assert _read(os.path.join(root, "data_bak", "data/markers", GAME_ID, "m.json")) == "old"
    assert _read(os.path.join(root, "audio", "keep.ogg")) == "keep-me"


def test_merge_files_skips_missing_source(tmp_path):
    root = str(tmp_path / "root")
    src = str(tmp_path / "src")
    count = _imp._cue_merge_files(root, src, ["audio/nope.ogg"])
    assert count == 0


# ---------------------------------------------------------------------------
# end-to-end: export -> import reconstructs the shareable tree 1:1
# ---------------------------------------------------------------------------

def test_export_import_roundtrip_matches_source(tmp_path):
    """Every form of data a marker can reference (file, folder, preset, My
    Music, video variant) built into a data dir, exported, imported, and the
    extracted tree compared to the source byte-for-byte.  Both halves of the
    roundtrip are checked against the same source, so an arcname or folder-ref
    resolution bug on either side fails here."""
    root = str(tmp_path / "src")
    preset = "Growl"
    files = [
        ("data/markers/{}/scene_a.json".format(GAME_ID),
         _json.dumps({
             "replay": "Run 1",
             "pools": [
                 {"name": "a", "files": ["boom.ogg"]},
                 {"name": "amb", "files": ["ambient/"]},
             ],
             "presets": [preset],
             "music": ["u:shared/song.ogg", "g:game.ogg"],
         })),
        ("audio/boom.ogg", "boom"),
        ("audio/ambient/rain.ogg", "rain"),
        ("audio/ambient/wind.ogg", "wind"),
        ("music/shared/song.ogg", "song"),
        ("video/{}/clip_cue0.5x.mkv".format(GAME_ID), "v0.5"),
        ("video/{}/clip_cue2.0x.mkv".format(GAME_ID), "v2"),
    ]
    for sub in ("audio", "video", "music"):
        files.append((_preset_rel(preset, sub), sub + "preset"))
    for rel, content in files:
        _write(root, rel, content)

    contents = _imp._cue_enumerate_import_files(root, GAME_ID)
    flat = [f for fs in contents.values() for f in fs]
    zip_path = str(tmp_path / "imp.zip")
    _imp._cue_build_import_zip(root, GAME_ID, "Pack", "author", "d", flat, zip_path)

    out = str(tmp_path / "out")
    _imp._cue_extract_import_zip(zip_path, out)

    # Every exported file landed with identical bytes at the same arcname.
    for rel in flat:
        assert _read(os.path.join(out, rel)) == _read(os.path.join(root, rel))
    # And nothing else: the extracted tree is exactly the source's exportable
    # files plus the manifest.  (The g: game-music ref is dropped by design --
    # the recipient has their own copy.)
    assert _walk_rel(out) == set(flat) | {CUE_IMPORT_MANIFEST_NAME}
    # The manifest contents list is authoritative and matches the packed files.
    manifest = _json.loads(
        _read(os.path.join(out, CUE_IMPORT_MANIFEST_NAME)))
    assert sorted(manifest["contents"]) == sorted(flat)


def test_replay_export_import_roundtrip_matches_source(tmp_path):
    """Replay-scoped export: markers for a selected replay plus the files they
    reference (direct, folder, preset, My Music) and the whole video-variant
    tree for a video-keyed marker.  Round-trips through zip build/extract and
    requires the extracted tree to match the exported asset set byte-for-byte
    -- and to exclude files nothing references."""
    root = str(tmp_path / "src")
    _write(root, "data/markers/{}/scene_a.json".format(GAME_ID), _json.dumps({
        "replay": "Run 1",
        "pools": [
            {"name": "a", "files": ["boom.ogg"]},
            {"name": "amb", "files": ["ambient/"]},
            {"name": "growl", "preset": "Growl"},
        ],
        "timestamps": [{"time": 1.5, "files": ["boom.ogg"]}],
        "files": ["extra.ogg"],
        "music": ["u:music/shared/song.ogg", "g:music/game.ogg"],
    }))
    # A video-keyed marker in the same replay pulls the whole variant tree.
    _write(root, "data/markers/{}/v_clip.json".format(GAME_ID),
           _json.dumps({"replay": "Run 1", "pools": []}))
    # Not part of the replay -- must stay out of the package.
    _write(root, "data/markers/{}/no_replay.json".format(GAME_ID),
           _json.dumps({"pools": []}))
    for rel, content in [
        ("audio/boom.ogg", "boom"),
        ("audio/ambient/rain.ogg", "rain"),
        ("audio/ambient/wind.ogg", "wind"),
        ("audio/extra.ogg", "extra"),
        ("audio/unused.ogg", "unused"),   # referenced by nothing -> not shipped
        ("music/shared/song.ogg", "song"),
        ("video/{}/clip_cue0.5x.mkv".format(GAME_ID), "v0.5"),
        ("video/{}/clip_cue2.0x.mkv".format(GAME_ID), "v2"),
        (_preset_rel("Growl", "audio"), "preset"),
    ]:
        _write(root, rel, content)

    assets = _imp._cue_replay_assets(root, GAME_ID, ["Run 1"])
    flat = [f for fs in assets.values() for f in fs]
    zip_path = str(tmp_path / "imp.zip")
    _imp._cue_build_import_zip(root, GAME_ID, "Pack", "author", "d", flat, zip_path)

    out = str(tmp_path / "out")
    _imp._cue_extract_import_zip(zip_path, out)

    # Every exported file landed with identical bytes at the same arcname.
    for rel in flat:
        assert _read(os.path.join(out, rel)) == _read(os.path.join(root, rel))
    # The package is exactly the referenced set plus the manifest: the
    # unreferenced audio file and the no-replay marker never shipped.
    assert _walk_rel(out) == set(flat) | {CUE_IMPORT_MANIFEST_NAME}
    assert "audio/unused.ogg" not in flat
    assert "data/markers/{}/no_replay.json".format(GAME_ID) not in flat
