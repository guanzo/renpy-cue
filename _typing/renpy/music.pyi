"""Stub for renpy.music (actually renpy.audio.music, aliased at runtime)."""

from typing import Any, Optional

def play(
    filename: str,
    channel: Optional[str] = None,
    loop: bool = False,
    fadeout: float = 0.0,
    synchro_start: bool = False,
    fadein: float = 0.0,
    tight: bool = False,
    if_changed: bool = False,
    relative_volume: float = 1.0,
    selected: bool = False,
) -> None: ...

def queue(
    filename: str,
    channel: Optional[str] = None,
    loop: bool = False,
    clear_queue: bool = True,
    synchro_start: bool = False,
    fadein: float = 0.0,
    tight: bool = False,
    relative_volume: float = 1.0,
) -> None: ...

def stop(channel: Optional[str] = None, fadeout: float = 0.0) -> None: ...
def get_playing(channel: Optional[str] = None) -> Optional[str]: ...
def get_pos(channel: Optional[str] = None) -> Optional[float]: ...
def get_duration(channel: Optional[str] = None) -> Optional[float]: ...
def is_playing(channel: Optional[str] = None) -> bool: ...
def set_volume(volume: float, delay: float = 0.0, channel: Optional[str] = None) -> None: ...
def set_pause(value: bool, channel: Optional[str] = None) -> None: ...
def register_channel(name: str, mixer: Optional[Any] = None, loop: bool = False, stop_on_mute: bool = True, tight: bool = False, file_prefix: str = "", file_suffix: str = "", buffer_queue: bool = True, movie: bool = False, framedrop: bool = False) -> None: ...
def channel_defined(name: str) -> bool: ...
