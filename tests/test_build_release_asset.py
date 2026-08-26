import os
import shutil
import subprocess
import sys
import tempfile
import zipfile


def make_fixture():
    src = tempfile.mkdtemp()
    cue = os.path.join(src, "cue_lib")
    os.makedirs(os.path.join(cue, "images"))
    open(os.path.join(cue, "images", "icon.png"), "w").close()
    open(os.path.join(cue, "__init__.py"), "w").close()
    open(os.path.join(cue, "mod.py"), "w").close()
    open(os.path.join(cue, "z.rpy"), "w").close()
    open(os.path.join(cue, "stale.rpyc"), "w").close()
    open(os.path.join(cue, "stale.pyo"), "w").close()
    os.makedirs(os.path.join(cue, "__pycache__"))
    open(os.path.join(cue, "__pycache__", "x.pyc"), "w").close()
    return src


def test_build_strips_bytecode_and_wraps():
    src = make_fixture()
    out = os.path.join(tempfile.mkdtemp(), "renpy_cue_9.9.9.zip")
    try:
        r = subprocess.run(
            [sys.executable, "bin/build_release_asset.py", "--source", os.path.join(src, "cue_lib"), "--out", out],
            check=True,
            capture_output=True,
        )
        assert r.returncode == 0, r.stderr
        names = zipfile.ZipFile(out).namelist()
        assert any(n == "renpy_cue/cue_lib/__init__.py" for n in names)
        assert any(n.startswith("renpy_cue/cue_lib/images/") for n in names)
        assert not any(n.endswith((".rpyc", ".pyo", ".pyc")) for n in names)
        assert not any("__pycache__" in n for n in names)
    finally:
        shutil.rmtree(src, ignore_errors=True)
