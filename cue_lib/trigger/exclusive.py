# -*- coding: utf-8 -*-
# CueExclusiveRegistry -- the shared exclusive-tracking backbone.
#
# Tracks playing SFX channels by domain (loop/oneshot/video) with their group
# identity and hold state.  All three trigger domains consult it, so a cut-in
# or gate in one domain sees the others: an exclusive one-shot fades loops,
# and video-marker SFX stay immune to every sweep.

import renpy.audio.music as _music
import renpy.python as _renpy_python

MYPY = False
if MYPY:
    from typing import Any, List, Optional

# Exclusive domains: loops, one-shots, and video-marker SFX.  The wait/hold
# gates are kind-filtered, so a loop never blocks a one-shot or vice versa.
# The fade sweep is asymmetric, though: an exclusive loop fades only other
# loops, while an exclusive one-shot fades everything outside its current
# scene + line context -- loops and one-shots included (one-shots cut loops).
# Video-marker SFX (v_key pools) are immune to every cut-in: they're tracked
# as their own kind and the one-shot sweep spares them.  The movie channel's
# own audio is never swept: fade_out only touches the _cue_ SFX channels.
# Loops never share a group; one-shot group identity is scene AND line
# (in_same_group).
CUE_EXCL_KIND_LOOP = "loop"
CUE_EXCL_KIND_ONESHOT = "oneshot"
CUE_EXCL_KIND_VIDEO = "video"


class CueExclusiveRegistry(_renpy_python.NoRollback):
    """Tracks playing SFX channels by domain (loop/oneshot/video).

    Grouping for one-shots is two-dimensional: the "scene" (file) plus a
    "line" (dialogue key, None for image/shake). Two one-shots share a group
    when they share a scene AND (either side is non-dialogue OR they share a
    line) -- so image and dialogue coexist, but a new dialogue line cuts the
    previous one. Loops never share a group; each loop competes with the rest.

    "kind" is the domain (loop vs one-shot vs video). Domains never
    interact, so an exclusive loop only waits for / fades / blocks other
    loops.  Video-marker SFX live in their own domain and are only tracked
    so the one-shot cut-in sweep can spare them.
    """

    def __init__(self):
        # type: () -> None
        self.channels = {}

    def prune(self):
        # type: () -> None
        """Drop tracked channels that have finished playing."""
        for ch in list(self.channels.keys()):
            if not _music.is_playing(channel=ch):
                del self.channels[ch]

    def in_same_group(self, info, kind, scene, line):
        # type: (Any, str, Optional[str], Optional[str]) -> bool
        """True if a same-domain tracked channel shares self's group.

        Loops never share a group. One-shots share a group when they share a
        scene AND (either side is non-dialogue OR they share a line)."""
        if kind == CUE_EXCL_KIND_LOOP:
            return False
        if info.get("scene") != scene:
            return False
        if line is None or info.get("line") is None:
            return True
        return info.get("line") == line

    def group_channels(self, kind, scene, line):
        # type: (str, Optional[str], Optional[str]) -> List[str]
        """Channels in this domain that share self's group."""
        return [
            ch
            for ch, info in self.channels.items()
            if info.get("kind") == kind and self.in_same_group(info, kind, scene, line)
        ]

    def kind_channels(self, kind):
        # type: (str) -> List[str]
        """Channels currently playing in the given domain (kind)."""
        return [ch for ch, info in self.channels.items() if info.get("kind") == kind]

    def is_hold_blocked(self, kind, scene, line):
        # type: (str, Optional[str], Optional[str]) -> bool
        """True if a holding SFX in the same domain but not self's group is
        playing -- an out-group SFX owns the air, so this SFX may not start.

        Only fire_context and _tick_loop consult this gate; video-marker SFX
        and previews are hold-immune by construction.  The cut-in sweep, by
        contrast, is channel-based and hits everything in the same domain
        outside self's group."""
        self.prune()
        for info in self.channels.values():
            if info.get("kind") != kind:
                continue
            if info["hold"] and not self.in_same_group(info, kind, scene, line):
                return True
        return False

    def is_outgroup_busy(self, kind, scene, line):
        # type: (str, Optional[str], Optional[str]) -> bool
        """True if any same-domain channel outside self's group is playing --
        polite holders wait for this to clear."""
        self.prune()
        for info in self.channels.values():
            if info.get("kind") != kind:
                continue
            if not self.in_same_group(info, kind, scene, line):
                return True
        return False

    def track_channel(self, channel, kind, scene, line, hold):
        # type: (Optional[str], str, Optional[str], Optional[str], bool) -> None
        """Record a playing SFX's domain, group identity, and hold state."""
        if channel:
            self.channels[channel] = {"kind": kind, "scene": scene, "line": line, "hold": hold}
