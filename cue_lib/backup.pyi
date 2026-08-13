# Type stub for cue_lib.backup
from typing import Final

CUE_BACKUP_INTERVAL: Final = 3600
CUE_BACKUP_MAX: Final = 100
CUE_BACKUP_DIR: Final = "backups"
CUE_BACKUP_AUTO_DIR: Final = "auto"
CUE_BACKUP_PREFIX: Final = "auto_backup_"

class CueBackupManager(object):
    def __init__(self, path: str, game_id: str) -> None: ...
    def maybe(self) -> None: ...
