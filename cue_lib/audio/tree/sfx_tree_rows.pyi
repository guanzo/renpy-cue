# Type stub for cue_lib.audio.tree.sfx_tree_rows
from typing import Any, Dict, List

from cue_lib._types import TreeActionRowDict, TreeButtonDict, TreeRowDict
from cue_lib.audio.tree.tree_rows import CueTreeRowsBuilder

class CueSfxTreeRows(CueTreeRowsBuilder):
    def row_buttons(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, item: Dict[str, Any], target_ok: bool, target_tt: str, unplayable: Dict[str, str]
    ) -> List[TreeButtonDict]: ...
    def _add_row_button(self, item: Dict[str, Any], kind: str, target_ok: bool, target_tt: str) -> TreeButtonDict: ...
    def _recent_rows(self, entries: List[Dict[str, str]], target_ok: bool, target_tt: str) -> List[TreeRowDict]: ...
    def _preset_rows(
        self, preset_names: List[str], search_query: str, target_ok: bool, target_tt: str
    ) -> List[TreeRowDict]: ...
    def _video_preset_rows(self, video_preset_names: List[str], is_video: bool) -> List[TreeRowDict]: ...
    def _intensity_rows(
        self, igroup_names: List[str], search_query: str, lv_hook_ok: bool, lv_tt: str
    ) -> List[TreeRowDict]: ...
    def _ilevel_file_rows(self, gname: str, lv_id: object, file_ref: str) -> List[TreeRowDict]: ...
    def content_rows(
        self,
        search_query: str,
        preset_names: List[str],
        video_preset_names: List[str],
        igroup_names: List[str],
        is_video: bool,
        tgt_ok: bool,
        unplayable: Dict[str, str],
    ) -> List[TreeRowDict]: ...
    def _rows_key(
        self,
        search_query: str,
        preset_names: List[str],
        video_preset_names: List[str],
        igroup_names: List[str],
        is_video: bool,
        tgt_ok: bool,
        unplayable: Dict[str, str],
    ) -> tuple: ...
    def _build_content_rows(
        self,
        search_query: str,
        preset_names: List[str],
        video_preset_names: List[str],
        igroup_names: List[str],
        is_video: bool,
        tgt_ok: bool,
        unplayable: Dict[str, str],
    ) -> List[TreeRowDict]: ...
    def _builtin_empty_rows(self, tree: Any) -> List[TreeRowDict]: ...
    def _download_pack_button(self, tree: Any) -> TreeActionRowDict: ...
    def _download_pack_status_rows(self, tree: Any) -> List[TreeRowDict]: ...
    def _preset_children(
        self, preset_names: List[str], search_query: str, target_ok: bool, target_tt: str
    ) -> List[TreeRowDict]: ...
    def _video_preset_children(self, video_preset_names: List[str], is_video: bool) -> List[TreeRowDict]: ...
    def warn_reason(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, item: Dict[str, Any], target_ok: bool, target_tt: str, unplayable: Dict[str, str]
    ) -> str: ...
