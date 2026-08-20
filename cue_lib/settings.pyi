# Type stub for cue_lib.settings

class CueSettings:
    setup_dir_text: str
    shared_dir_error: str
    shared_dir_success: str

    def __init__(self) -> None: ...
    def prepare_for_page(self) -> None: ...
    def confirm_shared_dir(self) -> None: ...
