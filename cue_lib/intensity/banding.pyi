# Type stub for cue_lib.intensity.banding
from typing import List, Tuple

CUE_BAND_MAX_SETS: int

def _cue_band_speeds(variants: List[float], n: int) -> Tuple[List[float], List[int]]: ...
def _cue_resolve_level(speed: float, speeds: List[float], levels: List[int]) -> int: ...
