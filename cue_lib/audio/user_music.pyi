# Type stub for cue_lib.audio.user_music
from typing import Set

from cue_lib.audio.audio_tree import CueAudioTreeManager

class CueUserMusic(CueAudioTreeManager):
    def _discover(self, results_set: Set[str]) -> None: ...
