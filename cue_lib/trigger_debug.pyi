# Type stub for cue_lib.trigger_debug
from typing import List, Optional, Set

CUE_TD_LATE_THRESHOLD: float
CUE_TD_MISS_TOLERANCE: float
CUE_TD_STALL_GAP: float
CUE_TD_GATE_CLOSED_GAP: float
CUE_TD_COOLDOWN: float
CUE_TD_RESTART_WINDOW: float
CUE_TD_RESTART_BURST_N: int
CUE_TD_ACCURACY_MAX_FIRES: int
CUE_TD_DIAG_WINDOW: float
CUE_TD_DIAG_MAX_LINES: int

def _cue_td_missed_times(
    marker_times: List[float], played_keys: Set[str], effective_elapsed: float, tolerance: float
) -> List[float]: ...

class CueTriggerDebug:
    _last_dump: float
    _last_tick_wall: float
    _gate_closed_since: float
    _late_deltas: List[float]
    _acc_file: Optional[str]
    _acc_deltas: List[float]
    _acc_late: int
    _beyond_reported: Set[tuple]
    _restarts: List[float]
    _restart_burst_armed: bool
    _diag_lines: int
    _diag_win_start: float
    _diag_ticks: int
    _diag_int_n: int
    _diag_int_min: float
    _diag_int_sum: float
    _diag_int_max: float
    _diag_body_max: float
    _diag_last_pos: Optional[float]
    _diag_last_rate_wall: float
    _diag_rate_dp_sum: float
    _diag_rate_dw_sum: float
    _diag_skips: int

    def __init__(self) -> None: ...
    def tick(self, now: float, current_file: str, top_layer_type: str, channel: Optional[str]) -> None: ...
    def tick_end(self, t0: float) -> None: ...
    def _sample_rate(self) -> None: ...
    def _emit_summary(self) -> None: ...
    def note_fire(self, t: float, effective_elapsed: float, current_file: str) -> None: ...
    def note_failed_fire(self, t: float, effective_elapsed: float, current_file: str) -> None: ...
    def note_restart(self) -> None: ...
    def _flush_accuracy(self) -> None: ...
    def end_fire_loop(
        self,
        current_file: str,
        effective_elapsed: float,
        played_keys: Set[str],
        markers: List[dict],
        preview_count: int,
    ) -> None: ...
    def _note_beyond_duration(self, current_file: str, marker_times: List[float]) -> None: ...
    def report(self, kind: str, details: str) -> None: ...
