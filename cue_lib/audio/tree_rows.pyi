# Type stub for cue_lib.audio.tree_rows
from typing import Any, Dict, List

class CueTreeRowsBuilder:
    file_gap: int
    _tree: Any

    def __init__(self, tree: Any) -> None: ...
    def tree_rows(self, *state: object) -> List[Dict[str, Any]]: ...
    def row_buttons(self, item: Dict[str, Any], *state: object) -> List[Dict[str, Any]]: ...
    def warn_reason(self, item: Dict[str, Any], *state: object) -> str: ...

class CueSfxTreeRows(CueTreeRowsBuilder):
    def row_buttons(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, item: Dict[str, Any], target_ok: bool, target_tt: str, unplayable: Dict[str, str]
    ) -> List[Dict[str, Any]]: ...
    def _add_row_button(self, item: Dict[str, Any], kind: str, target_ok: bool, target_tt: str) -> Dict[str, Any]: ...
    def warn_reason(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, item: Dict[str, Any], target_ok: bool, target_tt: str, unplayable: Dict[str, str]
    ) -> str: ...

class CueMusicTreeRows(CueTreeRowsBuilder):
    file_gap: int

    def row_buttons(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, item: Dict[str, Any], current_file: object
    ) -> List[Dict[str, Any]]: ...
