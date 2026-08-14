# Type stub for cue_lib.audio.game_music
from typing import Set

from cue_lib.audio.audio_tree import CueAudioTreeManager

class CueGameMusic(CueAudioTreeManager):
    def __init__(self) -> None: ...
    def _discover(self, results_set: Set[str]) -> None: ...
