# Type stub for cue_lib.audio.game_music
from typing import Final, Set

from cue_lib.audio.file_tree import CueAudioTreeManager

CUE_GAME_MUSIC_DIRS: Final = ("music", "bgm", "ost", "soundtrack")

class CueGameMusic(CueAudioTreeManager):
    def __init__(self) -> None: ...
    def _discover(self, results_set: Set[str]) -> None: ...
