# Type stub for cue_lib.preset_store
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from cue_lib.db import CueDatabase
from cue_lib.pool import CueAudioPreset, CueVideoPresetPool

# =========================================================================
# CuePresets (base)
# =========================================================================

class CuePresets:
    _kind: str
    _db: Optional[CueDatabase]
    _session_created: Set[Tuple[str, str]]
    _on_save: Optional[Callable[[], None]]
    _presets: Dict[str, Any]

    def __init__(
        self,
        db: Optional[CueDatabase],
        session_created: Set[Tuple[str, str]],
        on_save: Optional[Callable[[], None]] = None,
    ) -> None: ...

    # Unified CRUD
    def create(self, name: str, data: Any) -> None: ...
    def _do_create(self, name: str, data: Any) -> None: ...
    def _log_create(self, name: str, data: Any) -> None: ...
    def delete(self, name: str) -> None: ...
    def get(self, name: str) -> Optional[Any]: ...
    def list(self) -> List[str]: ...
    def items(self) -> Any: ...
    def view(self, name: str, index: int = 0) -> Any: ...

    # Persistence
    def save(self, name: str) -> None: ...
    def _db_save(self, name: str) -> None: ...
    def _db_save_all(self) -> None: ...
    def _post_save(self) -> None: ...
    def load(self, data: Optional[Dict[str, Any]] = None) -> None: ...
    def reload(self, data: Optional[Dict[str, Any]] = None) -> None: ...
    def _disk(self) -> Dict[str, Any]: ...
    def _migrate(self) -> None: ...
    def delete_removed_files(self, old_presets: Dict[str, Any], old_session_created: Set[Tuple[str, str]]) -> None: ...

# =========================================================================
# CueAudioPresets
# =========================================================================

class CueAudioPresets(CuePresets):
    _kind: str

    def __init__(
        self,
        db: Optional[CueDatabase],
        session_created: Set[Tuple[str, str]],
        on_save: Optional[Callable[[], None]] = None,
    ) -> None: ...
    def create(self, name: str, data: Any) -> None: ...
    def _log_create(self, name: str, data: Any) -> None: ...
    def view(self, name: str, index: int = 0) -> CueAudioPreset: ...
    def preset_remove_file(self, name: str, file_path: str) -> None: ...
    def _migrate(self) -> None: ...
    def _migrate_preset_exclusive(self) -> int: ...

# =========================================================================
# CueVideoPresets
# =========================================================================

class CueVideoPresets(CuePresets):
    _kind: str

    def __init__(
        self,
        db: Optional[CueDatabase],
        session_created: Set[Tuple[str, str]],
        on_save: Optional[Callable[[], None]] = None,
    ) -> None: ...
    def create(self, name: str, entry: Any, source_dur: float = 0.0) -> None: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def view(self, name: str, index: int = 0) -> CueVideoPresetPool: ...
    def remove_video_preset_pool(self, name: str, pool_index: int) -> None: ...
    def remove_video_preset_pool_file(self, name: str, pool_index: int, file_path: str) -> None: ...
    def _migrate(self) -> None: ...
    def _sanitize_video_presets(self) -> int: ...
    def _migrate_preset_speed_mode_rename(self) -> None: ...
    def _migrate_video_presets_to_pools(self) -> int: ...

# =========================================================================
# CueMusicPresets
# =========================================================================

class CueMusicPresets(CuePresets):
    _kind: str

    def __init__(
        self,
        db: Optional[CueDatabase],
        session_created: Set[Tuple[str, str]],
        on_save: Optional[Callable[[], None]] = None,
    ) -> None: ...
    def create(self, name: str, songs: List[str]) -> None: ...  # pyright: ignore[reportIncompatibleMethodOverride]

# =========================================================================
# CueIntensityPresets
# =========================================================================

class CueIntensityPresets(CuePresets):
    _kind: str

    def __init__(
        self,
        db: Optional[CueDatabase],
        session_created: Set[Tuple[str, str]],
        on_save: Optional[Callable[[], None]] = None,
    ) -> None: ...
    def create(self, name: str) -> Optional[str]: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def _migrate(self) -> None: ...

# =========================================================================
# CuePresetStore (container)
# =========================================================================

class CuePresetStore:
    _db: Optional[CueDatabase]
    _on_save: Optional[Callable[[], None]]
    audio: CueAudioPresets
    video: CueVideoPresets
    music: CueMusicPresets
    intensity: CueIntensityPresets
    _session_created: Set[Tuple[str, str]]

    def __init__(self, db: Optional[CueDatabase], on_save: Optional[Callable[[], None]] = None) -> None: ...

    # Cross-kind persistence
    def reload_presets(self) -> None: ...
    def save_all(self) -> None: ...
    def _post_save(self) -> None: ...
    def delete_removed_files(
        self, old_presets: Dict[str, Any], old_video_presets: Dict[str, Any], old_session_created: Set[Tuple[str, str]]
    ) -> None: ...
    def load(self) -> None: ...
