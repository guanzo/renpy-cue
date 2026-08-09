# Type stub for renpy.config
from typing import Any, Callable, List

gamedir: str
screen_width: int
screen_height: int
developer: bool
console: bool
overlay_screens: List[str]
all_character_callbacks: List[Callable[..., Any]]
after_load_callbacks: List[Callable[..., Any]]
start_interact_callbacks: List[Callable[..., Any]]
