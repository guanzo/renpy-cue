#!/usr/bin/env python3
"""Build the published mod zip.

Output is a top-level `renpy_cue/` folder whose only child is `cue_lib/` (source
+ images), with version-specific bytecode (.rpyc/.pyo/.pyc/__pycache__) stripped.
Ships only cue_lib/ -- tests/, bin/, tools/, docs/, README never go in the asset.
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BYTECODE = (".rpyc", ".pyo", ".pyc")


def cue_version():
    with open(os.path.join(ROOT, "cue_lib", "constants.py")) as f:
        m = re.search(r'^CUE_VERSION\s*=\s*["\']([^"\']+)["\']', f.read(), re.MULTILINE)
    if not m:
        raise SystemExit("CUE_VERSION not found in cue_lib/constants.py")
    return m.group(1)


def _ignore(dirpath, names):
    return [n for n in names if n.endswith(BYTECODE) or n == "__pycache__"]


def build_zip(source, out, version):
    stage = tempfile.mkdtemp(prefix="cue_asset_")
    try:
        mod = os.path.join(stage, "renpy_cue")
        shutil.copytree(source, os.path.join(mod, "cue_lib"), ignore=_ignore)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for base, _, files in os.walk(mod):
                for name in files:
                    p = os.path.join(base, name)
                    zf.write(p, os.path.relpath(p, stage))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=os.path.join(ROOT, "cue_lib"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--version", default=None)
    args = ap.parse_args()
    version = args.version or cue_version()
    out = args.out or os.path.join(ROOT, f"Cue_{version}.zip")
    if not os.path.isdir(args.source):
        sys.exit(f"source dir not found: {args.source}")
    print(f"built {build_zip(args.source, out, version)} (CUE_VERSION={version})")


if __name__ == "__main__":
    main()
