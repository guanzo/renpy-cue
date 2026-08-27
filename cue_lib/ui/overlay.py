# -*- coding: utf-8 -*-
# Overlay lifecycle driver -- show/hide/toggle the cue overlay and switch
# sidebar pages.  These are Function()-bound screen actions, so the names
# stay importable as stable module-level objects (re-exported via cue_z.rpy).

import renpy

from cue_lib.constants import CuePage
from cue_lib.runtime import _cue_refresh_context
from cue_lib.state import _cue
from cue_lib.ui.displayables import CueVideoMarkerTimeline


def _cue_toggle_overlay():
    # type: () -> None
    if _cue.is_overlay_visible:
        _cue_hide_overlay()
    else:
        _cue_show_overlay()


def _cue_set_page(page):
    # type: (int) -> None
    """Switch the overlay sidebar to the given page.

    Clicking the page that is already open is a no-op.
    """
    if _cue.overlay_active_page == page:
        return
    if page == CuePage.SETTINGS:
        _cue.settings.prepare_for_page()
    elif page == CuePage.IMPORT:
        _cue.importer.scan()
        _cue.exporter.refresh()

    _cue.overlay_active_page = page


def _cue_show_overlay():
    # type: () -> None
    _cue.is_overlay_visible = True
    # A field may have been left mid-edit when the overlay was hidden; clear the
    # sticky editing state so the focus pin doesn't start the next open already
    # "editing" a field that isn't focused.
    _cue.active_input = ""
    _cue.active_input_rect = None

    _cue_refresh_context()
    _cue.music.library.maybe_rebuild()
    _cue.sfx.library.maybe_rebuild()
    _cue.video_editor.refresh(restart_interaction=False)

    renpy.show_screen("cue_overlay", _layer="cue_layer")
    renpy.restart_interaction()


def _cue_hide_overlay():
    # type: () -> None
    _cue.is_overlay_visible = False
    _cue.active_input = ""
    _cue.active_input_rect = None
    # The marker timeline outlives the overlay (built once as a class
    # singleton), so a hide mid-drag would otherwise leave a stale in-flight
    # drag on the next show.
    CueVideoMarkerTimeline.reset_timeline_drag()
    renpy.hide_screen("cue_overlay", layer="cue_layer")
