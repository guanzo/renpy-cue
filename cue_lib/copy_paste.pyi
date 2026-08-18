# Type stub for cue_lib.copy_paste
from typing import Tuple

from cue_lib._types import MarkerEntry
from cue_lib.markers import CueMarkerManager

# Which entry-level keys travel with a context on copy/paste. Infra stays
# behind: speed keys reference variant files the target may not have, music is
# per-trigger audio intent, _key is derived, and replay is re-stamped on paste.
CUE_COPY_ENTRY_KEYS: Tuple[str, ...]

def _cue_copy_entry(entry: MarkerEntry) -> MarkerEntry: ...
def copy_context(mgr: CueMarkerManager) -> None: ...
def paste_context(mgr: CueMarkerManager) -> None: ...
