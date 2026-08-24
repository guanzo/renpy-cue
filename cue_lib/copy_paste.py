# -*- coding: utf-8 -*-
# CueCopyPaste -- the marker context clipboard (copy_context / paste_context)
# plus the entry-key whitelist that governs which keys travel between scenes.
# Functions are manager-bound (take CueMarkerManager); the manager keeps thin
# delegating methods so screens can call _cue.markers.copy_context directly.

import copy as _copy
import renpy

from cue_lib.util import (
    _cue_clamp_time,
    _cue_log,
    create_img_key,
    create_vid_key,
    create_dlg_key,
    create_loop_key,
    is_img_key,
    is_vid_key,
    is_dlg_key,
    is_loop_key,
    get_key_file,
)

MYPY = False
if MYPY:
    from typing import Any, List  # pyright: ignore[reportUnusedImport]
    from cue_lib._types import MarkerEntry  # pyright: ignore[reportUnusedImport]
    from cue_lib.markers import CueMarkerManager  # pyright: ignore[reportUnusedImport]

# Copy/paste whitelist -- which entry-level keys travel with a context.
# Infra stays behind: speed keys reference variant files the target may not
# have, music is per-trigger audio intent, _key is derived (regenerated on
# save), and replay is re-stamped from the current replay on paste.
CUE_COPY_ENTRY_KEYS = ("pools", "volume", "video_file_muted")


def _cue_copy_entry(entry):
    # type: (MarkerEntry) -> MarkerEntry
    """Return a copy of *entry* carrying only the whitelisted keys."""
    out = {}  # type: MarkerEntry
    for key in CUE_COPY_ENTRY_KEYS:
        if key in entry:
            out[key] = _copy.deepcopy(entry[key])  # pyright: ignore[reportGeneralTypeIssues, reportTypedDictNotRequiredAccess]  # union of optional keys into a total=False TypedDict
    return out


def copy_context(mgr):
    # type: (CueMarkerManager) -> None
    ctx_file = mgr._ctx.current_file
    ctx_dlg = mgr._ctx.current_dialogue
    copied = {}
    all_keys = [
        create_vid_key(ctx_file),
        create_img_key(ctx_file),
        create_dlg_key((ctx_file, ctx_dlg)),
        create_loop_key(ctx_file),
    ]
    for key in all_keys:
        entry = mgr._data.get(key)
        if entry:
            copied[key] = _cue_copy_entry(entry)
    mgr.clipboard = {"markers": copied, "source_file": ctx_file, "source_dialogue": ctx_dlg}


def paste_context(mgr):
    # type: (CueMarkerManager) -> None
    if mgr.clipboard is None:
        return
    ctx_file = mgr._ctx.current_file
    ctx_dlg = mgr._ctx.current_dialogue
    source_file = mgr.clipboard.get("source_file", "")
    pasted_keys = []
    pasted_loop = False

    for source_key, entry in mgr.clipboard.get("markers", {}).items():
        if get_key_file(source_key) != source_file:
            continue
        new_key = source_key
        if is_vid_key(source_key):
            new_key = create_vid_key(ctx_file)
        elif is_img_key(source_key):
            new_key = create_img_key(ctx_file)
        elif is_dlg_key(source_key):
            new_key = create_dlg_key((ctx_file, ctx_dlg))
        elif is_loop_key(source_key):
            new_key = create_loop_key(ctx_file)
            pasted_loop = True
        mgr._data[new_key] = _cue_copy_entry(entry)

        if renpy.store._in_replay:
            mgr._data[new_key]["replay"] = renpy.store._in_replay

        _cue_log("{} {}".format(new_key, str(entry)))

        if is_vid_key(source_key):
            dur = mgr._vid_manager.get_duration()
            pasted_entry = mgr._data[new_key]
            for pool_entry in pasted_entry.get("pools", []):
                t = pool_entry.get("time", 0)
                if dur > 0:
                    t = _cue_clamp_time(t, dur)
                else:
                    t = max(0.0, t)
                pool_entry["time"] = t  # pyright: ignore[reportGeneralTypeIssues]  # video pools carry "time" but flow through PoolDict
        pasted_keys.append(new_key)

    if pasted_keys:
        mgr.save_markers(pasted_keys)

    # A pasted loop marker takes over the target scene's loop key; drop the
    # state the old marker was scheduling so it starts on a fresh cycle.
    if pasted_loop and mgr._trigger is not None:
        mgr._trigger.loop_states.pop(create_loop_key(ctx_file), None)
