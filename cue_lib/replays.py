# cue_lib/replays.py -- the Replays library: every replay label in the current
# game that contains markers, with its marker count.  Owns the replay label
# enumeration so it is not export-specific: the Replays overlay page reads
# entries, and the exporter calls _cue_replay_labels for its own async export
# snapshot.

import os
import renpy

from cue_lib.paths import CuePaths
from cue_lib.sharing.importer_io import _cue_read_json_file

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Tuple  # pyright: ignore[reportUnusedImport]


def _cue_replay_labels(root, game_id):
    # type: (str, str) -> List[Tuple[str, int]]
    """[(replay label, marker count)] for every replay that has markers,
    sorted by label.  A marker never edited inside a replay has no replay
    field and is not counted.  Labels are used as opaque keys, so str vs
    unicode (Py2) needs no coercion."""
    paths = CuePaths(root, game_id)
    counts = {}
    try:
        names = sorted(os.listdir(paths.marker_dir))
    except Exception:
        return []

    for name in names:
        if not name.endswith(".json"):
            continue
        entry = _cue_read_json_file(os.path.join(paths.marker_dir, name))
        if not isinstance(entry, dict):
            continue
        label = entry.get("replay")
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1

    return sorted(counts.items())


class CueReplayLibrary(object):
    """Tracks the current game's replays that contain markers.

    scan() re-derives entries from disk, so it is idempotent and safe to call
    on page entry, replay exit, and full reload.  The marker count is the
    number of markers last edited inside that replay.
    """

    def __init__(self, paths):
        # type: (CuePaths) -> None
        self._paths = paths
        self.entries = []  # type: List[Dict[str, Any]]  # {"replay", "marker_count"}
        # A scene clicked while another replay runs: the end_replay unwind
        # fires after_replay_callback, which is where the new replay chains on.
        self.pending_replay = None  # type: Optional[str]

    def scan(self):
        # type: () -> None
        labels = _cue_replay_labels(self._paths.original_root, self._paths.game_id)
        self.entries = [{"replay": label, "marker_count": count} for label, count in labels]

    def play(self, label):
        # type: (str) -> None
        """Start Ren'Py's replay machinery for a scene label.

        Guarded so a stale label (one the current script no longer defines)
        is a no-op instead of a crash; the Replays page disables the button
        for those anyway.

        Clicking a scene while another replay runs replaces the active one
        instead of nesting: call_replay pushes a second context, and the
        menu's "End Replay" would then unwind only back to the previous
        scene, leaving a stack to click through.  end_replay's unwind always
        invokes after_replay_callback, so the replacement chains off that.
        """
        if not renpy.has_label(label):
            return
        if renpy.store._in_replay:
            self.pending_replay = label
            renpy.end_replay()
        else:
            renpy.call_replay(label)
