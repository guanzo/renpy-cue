# Type stub for cue_lib.audio.tree.pool_rows
from typing import Any, Dict, List, Optional

def _cue_pool_files_rows(
    files: List[str],
    preview_vol: float,
    detach_action: Any,
    remove_fn: Any,
    remove_args: tuple,
    child_remove_fn: Any,
    marker_key: Optional[str],
    pool_index: Optional[int],
    folder_label: Optional[str],
    folder_children: Optional[List[str]],
    igroup: Optional[str] = ...,
    ilevel_id: Optional[int] = ...,
) -> List[Dict[str, Any]]: ...
def _cue_pool_virtual_rows(
    folder_label: str,
    folder_children: Optional[List[str]],
    preview_vol: float,
    detach_action: Any,
    marker_key: Optional[str],
    pool_index: Optional[int],
    child_remove_fn: Any,
) -> List[Dict[str, Any]]: ...
def _cue_pool_ref_rows(
    index: int,
    ref: str,
    preview_vol: float,
    remove_fn: Any,
    remove_args: tuple,
    marker_key: Optional[str],
    pool_index: Optional[int],
    child_remove_fn: Any,
) -> List[Dict[str, Any]]: ...
def _cue_pool_igroup_rows(
    level_files: List[str], preview_vol: float, detach_action: Any, hook_tt: str, hint: bool
) -> List[Dict[str, Any]]: ...
