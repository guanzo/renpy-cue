# cue_lib/replays.py -- the Replays library: every replay label in the current
# game that contains markers, with its marker count.  Owns the replay label
# enumeration so it is not export-specific: the Replays overlay page reads
# entries, and the exporter calls _cue_replay_labels for its own async export
# snapshot.

import json as _json
import os
import renpy

from cue_lib.paths import CuePaths
from cue_lib.sharing.importer_io import _cue_read_json_file
from cue_lib.util import _cue_replace_file

MYPY = False
if MYPY:
    from typing import Any, Dict, List, Optional, Set, Tuple  # pyright: ignore[reportUnusedImport]


def _cue_speaker_label(who):
    # type: (Any) -> Any
    """Map the protagonist to the universal tag 'mc' so speaker fields and
    per-replay casts stay comparable across games that rename the MC."""
    mc = getattr(renpy.store, "mc", None)
    if mc is not None:
        name = getattr(mc, "name", None)
        if name and who == name:
            return "mc"
    return who


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
        self.cast = CueReplayCast(paths)

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


class CueReplayCast(object):
    """Speaking cast of a replay, one JSON file under <replays_dir>/.

    record_speaker keeps an in-memory set per replay, lazily loaded from disk
    on first use.  A new speaker writes through immediately, so a mid-replay
    crash keeps earlier discoveries; existing speakers never rewrite the file.
    """

    def __init__(self, paths):
        # type: (CuePaths) -> None
        self._paths = paths
        self._casts = {}  # type: Dict[str, Set[str]]  # replay_id -> speakers

    def record_speaker(self, replay_id, speaker):
        # type: (str, str) -> None
        speakers = self._casts.get(replay_id)
        if speakers is None:
            speakers = self._load(replay_id)
            self._casts[replay_id] = speakers
        if speaker in speakers:
            return
        speakers.add(speaker)
        self._save(replay_id, speakers)

    def _load(self, replay_id):
        # type: (str) -> Set[str]
        data = _cue_read_json_file(self._paths.replay_path(replay_id))
        chars = data.get("characters") if data is not None else None
        if not isinstance(chars, list):
            return set()
        return set(chars)

    def _save(self, replay_id, speakers):
        # type: (str, Set[str]) -> None
        path = self._paths.replay_path(replay_id)
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            _json.dump({"replay": replay_id, "characters": sorted(speakers)}, fh, sort_keys=True)
        _cue_replace_file(tmp, path)
