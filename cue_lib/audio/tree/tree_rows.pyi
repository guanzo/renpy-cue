# Type stub for cue_lib.audio.tree.tree_rows
from typing import Any, Dict, List, Optional

CUE_SETTINGS_FOLDER_TIP: str

def _cue_file_row(
    key: str,
    label: str,
    depth: int,
    buttons: List[Dict[str, Any]],
    warn: Optional[str] = ...,
    gap: Optional[int] = ...,
    size: Optional[int] = ...,
) -> Dict[str, Any]: ...
def _cue_help_row(
    key: str, label: str, color: Optional[str] = ..., v_gap: Optional[int] = ..., depth: int = ..., plain: bool = ...
) -> Dict[str, Any]: ...
def _cue_action_row(
    key: str,
    label: str,
    action: Any = ...,
    tt: Optional[str] = ...,
    depth: int = ...,
    explorer: Optional[str] = ...,
    sensitive: bool = ...,
    icon: Optional[str] = ...,
) -> Dict[str, Any]: ...
def _cue_actions_row(key: str, actions: List[Dict[str, Any]], depth: int = ...) -> Dict[str, Any]: ...
def _cue_external_empty_rows(tree: Any, kind_word: str) -> List[Dict[str, Any]]: ...
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
    hover_buttons: Optional[List[Dict[str, Any]]] = ...,
) -> List[Dict[str, Any]]: ...

class CueTreeRowsBuilder:
    file_gap: int
    _tree: Any

    def __init__(self, tree: Any) -> None: ...
    def tree_rows(self, *state: object) -> List[Dict[str, Any]]: ...
    def row_buttons(self, item: Dict[str, Any], *state: object) -> List[Dict[str, Any]]: ...
    def warn_reason(self, item: Dict[str, Any], *state: object) -> str: ...
