# Type stub for cue_lib.audio.game_music
from typing import Any, Dict, List

class CueGameMusic:
    music_files: List[str]
    music_tree: List[Dict[str, Any]]
    music_scan_error: str
    visible_tree: List[Dict[str, Any]]
    expanded_folders: Dict[str, bool]

    def __init__(self) -> None: ...
    def scan(self) -> None: ...
    def rebuild_tree(self) -> None: ...
    def _walk_tree(
        self,
        items: List[Dict[str, Any]],
        prefix: str,
        depth: int,
        result: List[Dict[str, Any]]) -> None: ...
    def toggle_folder(self, folder_path: str) -> None: ...
