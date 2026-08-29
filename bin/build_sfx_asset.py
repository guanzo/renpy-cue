#!/usr/bin/env python3
"""Build the SFX pack zip from a local source dir.

The source dir is passed in (the /release skill reads it from gitignored .env as
CUE_SFX_SOURCE_DIR). No path is committed here. Category folders sit at the top
level of the zip (no wrapping dir); test_bad is excluded.
"""

import argparse
import os
import sys
import zipfile

DEFAULT_EXCLUDE = ("test_bad",)


def build_zip(src, out, exclude):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(os.listdir(src)):
            if entry in exclude:
                continue
            p = os.path.join(src, entry)
            if os.path.isdir(p):
                for base, _, files in os.walk(p):
                    for name in files:
                        fp = os.path.join(base, name)
                        zf.write(fp, os.path.relpath(fp, src))
            else:
                zf.write(p, entry)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default=None)
    ap.add_argument("--exclude", action="append", default=list(DEFAULT_EXCLUDE))
    args = ap.parse_args()
    if not os.path.isdir(args.src):
        sys.exit(f"source dir not found: {args.src}")
    if args.out is None:
        args.out = "cue_sfx.zip"
    print(f"built {build_zip(args.src, args.out, set(args.exclude))} (excluded {', '.join(args.exclude)})")


if __name__ == "__main__":
    main()
