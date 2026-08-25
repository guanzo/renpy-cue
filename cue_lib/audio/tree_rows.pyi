# Type stub for cue_lib.audio.tree_rows
from typing import Any, Dict, List

def _cue_file_row(
    key: str, label: str, depth: int, buttons: List[Dict[str, Any]], warn: str = ..., gap: int = ..., size: int = ...
) -> Dict[str, Any]: ...
def _cue_help_row(key: str, label: str, color: str = ..., v_gap: int = ...) -> Dict[str, Any]: ...
def _cue_section_rows(
    key: str,
    label: str,
    toggle_fn: Any,
    expanded: bool,
    searching: bool,
    has_any: Any,
    child_fn: Any,
    auto_show: bool = ...,
) -> List[Dict[str, Any]]: ...
def _cue_folder_rows(
    key: str,
    label: str,
    depth: int,
    toggle_fn: Any,
    expanded: bool,
    searching: bool,
    buttons: List[Dict[str, Any]],
    children: List[Dict[str, Any]],
) -> List[Dict[str, Any]]: ...

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
    def _recent_rows(self, entries: List[Dict[str, str]], target_ok: bool, target_tt: str) -> List[Dict[str, Any]]: ...
    def _preset_rows(
        self, preset_names: List[str], search_query: str, target_ok: bool, target_tt: str
    ) -> List[Dict[str, Any]]: ...
    def warn_reason(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, item: Dict[str, Any], target_ok: bool, target_tt: str, unplayable: Dict[str, str]
    ) -> str: ...

class CueMusicTreeRows(CueTreeRowsBuilder):
    file_gap: int

    def row_buttons(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, item: Dict[str, Any], current_file: object
    ) -> List[Dict[str, Any]]: ...
