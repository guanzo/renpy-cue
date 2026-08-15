# Type stub for cue_lib.video.auto_speed
from typing import Final, List, Optional

from cue_lib.marker_store import CueMarkerStore
from cue_lib.video.speed import CueVidSpeedResolver, CueVidSpeedSequence
from cue_lib.video.video import CueVideoManager
from cue_lib.state import CueContext

CUE_AUTO_SPEED_MIN_VARIANTS: Final = 4
CUE_AUTO_UNIT_ALLOWANCE_TU: Final = 10.0

def _cue_auto_preset_label(preset_name: str) -> str: ...
def _cue_auto_preset_description(preset_name: str) -> str: ...

class CueAutoSpeedGenerator:
    min_duration_tu: float
    max_duration_tu: float
    min_hold_tu: float
    max_hold_tu: float
    max_step: int
    momentum_min_steps: int
    momentum_max_steps: int
    momentum_drift_chance: float
    shuffle_pool: List[str]
    active_preset: Optional[str]
    is_shuffle_mode: bool
    custom_drift: float
    custom_intensity: float
    custom_volatility: float
    custom_center: float
    _store: CueMarkerStore
    _speed_resolver: CueVidSpeedResolver
    _vid_manager: CueVideoManager
    _video_sequence: CueVidSpeedSequence
    _ctx: CueContext

    def __init__(
        self,
        store: CueMarkerStore,
        speed_resolver: CueVidSpeedResolver,
        vid_manager: CueVideoManager,
        video_sequence: CueVidSpeedSequence,
        ctx: CueContext) -> None: ...
    def select_preset(self, preset_name: str) -> None: ...
    def shuffle(self) -> None: ...
    def toggle_speed(self, speed: float) -> None: ...
    def is_speed_enabled(self, speed: float) -> bool: ...
    @property
    def enabled_speeds(self) -> list: ...
    def generate(self, enabled_speeds: list) -> list: ...
    def on_wrap_around(self) -> None: ...
