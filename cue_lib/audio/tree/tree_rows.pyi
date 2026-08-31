# Type stub for cue_lib.audio.tree.tree_rows
from typing import Any, Dict, List, Optional

from cue_lib._types import (
    TreeActionRowDict,
    TreeActionsRowDict,
    TreeButtonDict,
    TreeFileRowDict,
    TreeFolderRowDict,
    TreeHelpRowDict,
    TreeRowDict,
)

CUE_SETTINGS_FOLDER_TIP: str
CUE_ELIDE_SAFETY_PX: int

def _cue_tree_adjustment(key: str) -> Any: ...
def _cue_tree_window(key: str, pitch: int, first: int, buf: int) -> None: ...
def _cue_tree_restart(key: str, value: float) -> None: ...
def _cue_elide_label(label: str, max_chars: int) -> str: ...
def _cue_row_label_max(row: TreeRowDict, container_w: int) -> int: ...
def _cue_file_row(
    key: str,
    label: str,
    depth: int,
    buttons: List[TreeButtonDict],
    warn: Optional[str] = ...,
    gap: int = ...,
    size: Optional[int] = ...,
) -> TreeFileRowDict: ...
def _cue_help_row(
    key: str, label: str, color: Optional[str] = ..., v_gap: Optional[int] = ..., depth: int = ..., plain: bool = ...
) -> TreeHelpRowDict: ...
def _cue_action_row(
    key: str,
    label: str,
    action: Any = ...,
    tt: Optional[str] = ...,
    depth: int = ...,
    explorer: Optional[str] = ...,
    sensitive: bool = ...,
    icon: Optional[str] = ...,
) -> TreeActionRowDict: ...
def _cue_actions_row(key: str, actions: List[TreeActionRowDict], depth: int = ...) -> TreeActionsRowDict: ...
def _cue_folder_row(
    key: str, label: str, depth: int, buttons: List[TreeButtonDict], toggle: Any
) -> TreeFolderRowDict: ...
def _cue_external_empty_rows(tree: Any, kind_word: str) -> List[TreeRowDict]: ...
def _cue_section_rows(
    key: str,
    label: str,
    toggle_fn: Any,
    expanded: bool,
    searching: bool,
    has_any: Any,
    child_fn: Any,
    auto_show: bool = ...,
) -> List[TreeRowDict]: ...
def _cue_folder_rows(
    key: str,
    label: str,
    depth: int,
    toggle_fn: Any,
    expanded: bool,
    searching: bool,
    buttons: List[TreeButtonDict],
    children: List[TreeRowDict],
    hover_buttons: Optional[List[TreeButtonDict]] = ...,
) -> List[TreeRowDict]: ...

class CueTreeRowsBuilder:
    file_gap: int
    _tree: Any

    def __init__(self, tree: Any) -> None: ...
    def tree_rows(self, *state: object) -> List[TreeRowDict]: ...
    def row_buttons(self, item: Dict[str, Any], *state: object) -> List[TreeButtonDict]: ...
    def warn_reason(self, item: Dict[str, Any], *state: object) -> str: ...
