import subprocess
import sys
import zipfile


def test_sfx_excludes_test_bad(tmp_path):
    src = tmp_path / "audio"
    for cat in ("Breathe", "Cum", "Moan", "Impact"):
        (src / cat).mkdir(parents=True)
        (src / cat / "a.wav").write_bytes(b"RIFF")
    (src / "test_bad").mkdir()
    (src / "test_bad" / "bad.wav").write_bytes(b"RIFF")
    out = tmp_path / "renpy_cue_sfx_9.9.9.zip"
    r = subprocess.run(
        [sys.executable, "bin/build_sfx_asset.py", str(src), "--out", str(out)], check=True, capture_output=True
    )
    assert r.returncode == 0, r.stderr
    names = zipfile.ZipFile(out).namelist()
    assert any("Breathe" in n for n in names)
    assert any("Cum" in n for n in names)
    assert not any("test_bad" in n for n in names)
