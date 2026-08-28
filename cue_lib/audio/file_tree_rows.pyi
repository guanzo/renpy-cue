# Type stub for cue_lib.audio.file_tree_rows
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
    def _video_preset_rows(self, video_preset_names: List[str], is_video: bool) -> List[Dict[str, Any]]: ...
    def _intensity_rows(
        self, igroup_names: List[str], search_query: str, lv_hook_ok: bool, lv_tt: str
    ) -> List[Dict[str, Any]]: ...
    def _ilevel_file_rows(self, gname: str, lv_id: object, file_ref: str) -> List[Dict[str, Any]]: ...
    def content_rows(
        self,
        search_query: str,
        preset_names: List[str],
        video_preset_names: List[str],
        igroup_names: List[str],
        is_video: bool,
        tgt_ok: bool,
        unplayable: Dict[str, str],
    ) -> List[Dict[str, Any]]: ...
    def _builtin_empty_rows(self, tree: Any) -> List[Dict[str, Any]]: ...
    def _download_pack_button(self, tree: Any) -> Dict[str, Any]: ...
    def _download_pack_status_rows(self, tree: Any) -> List[Dict[str, Any]]: ...
    def _preset_children(
        self, preset_names: List[str], search_query: str, target_ok: bool, target_tt: str
    ) -> List[Dict[str, Any]]: ...
    def _video_preset_children(self, video_preset_names: List[str], is_video: bool) -> List[Dict[str, Any]]: ...
    def warn_reason(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, item: Dict[str, Any], target_ok: bool, target_tt: str, unplayable: Dict[str, str]
    ) -> str: ...

class CueMusicTreeRows(CueTreeRowsBuilder):
    def row_buttons(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, item: Dict[str, Any], current_file: object
    ) -> List[Dict[str, Any]]: ...
    def _recent_rows(self, entries: List[Dict[str, str]], current_file: object) -> List[Dict[str, Any]]: ...
    def _preset_rows(self, preset_names: List[str]) -> List[Dict[str, Any]]: ...
    def _preset_children(self, preset_names: List[str]) -> List[Dict[str, Any]]: ...
    def content_rows(
        self, search_query: str, preset_names: List[str], current_file: object
    ) -> List[Dict[str, Any]]: ...
