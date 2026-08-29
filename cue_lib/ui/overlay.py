# -*- coding: utf-8 -*-
# Overlay manager -- owns the cue overlay's lifecycle (show/hide/toggle,
# page switching) and cross-page UI state (section toggle status).  Wired as
# _cue.overlay at init -900 after the managers its actions touch exist.

import renpy
from renpy.store import persistent

from cue_lib.constants import CUE_PERSIST_COLLAPSED_SECTIONS, CuePage
from cue_lib.runtime import _cue_refresh_context
from cue_lib.state import _cue
from cue_lib.ui.displayables import CueVideoMarkerTimeline
from cue_lib.util import _cue_unwrap_persistent


class CueOverlay(object):
    def __init__(self):
        self.is_visible = False
        self.active_page = CuePage.SFX
        self.collapsed_sections = {}  # section_name -> bool (cue_section_frame)

    def toggle(self):
        # type: () -> None
        if self.is_visible:
            self.hide()
        else:
            self.show()

    def set_page(self, page):
        # type: (int) -> None
        """Switch the overlay sidebar to the given page.

        Clicking the page that is already open is a no-op.
        """
        if self.active_page == page:
            return
        if page == CuePage.SETTINGS:
            _cue.settings.prepare_for_page()
        elif page == CuePage.IMPORT:
            _cue.importer.scan()
            _cue.exporter.refresh()

        self.active_page = page

    def show(self):
        # type: () -> None
        self.is_visible = True
        # A field may have been left mid-edit when the overlay was hidden; clear
        # the sticky editing state so the focus pin doesn't start the next open
        # already "editing" a field that isn't focused.
        _cue.active_input = ""
        _cue.active_input_rect = None

        _cue_refresh_context()
        _cue.music.library.maybe_rebuild()
        _cue.sfx.library.maybe_rebuild()
        _cue.video_editor.refresh(restart_interaction=False)

        renpy.show_screen("cue_overlay", _layer="cue_layer")
        renpy.restart_interaction()

    def hide(self):
        # type: () -> None
        self.is_visible = False
        _cue.active_input = ""
        _cue.active_input_rect = None
        # The marker timeline outlives the overlay (built once as a class
        # singleton), so a hide mid-drag would otherwise leave a stale in-flight
        # drag on the next show.
        CueVideoMarkerTimeline.reset_timeline_drag()
        renpy.hide_screen("cue_overlay", layer="cue_layer")

    # ------------------------------------------------------------------
    # Section frames (shared by all pages via cue_section_frame)
    # ------------------------------------------------------------------

    def toggle_section(self, section_name):
        # type: (str) -> None
        """Toggle expand/collapse for a cue_section_frame."""
        self.collapsed_sections[section_name] = not self.collapsed_sections.get(section_name, False)
        self._save_collapsed_sections()
        renpy.restart_interaction()

    def _save_collapsed_sections(self):
        # type: () -> None
        """Persist the section toggle dict under persistent._cue."""
        if persistent._cue is None:
            persistent._cue = {}
        persistent._cue[CUE_PERSIST_COLLAPSED_SECTIONS] = dict(self.collapsed_sections)

    def _load_collapsed_sections(self):
        # type: () -> None
        """Hydrate section toggles from persistent (called at boot)."""
        raw = persistent._cue or {}
        value = _cue_unwrap_persistent(raw.get(CUE_PERSIST_COLLAPSED_SECTIONS))
        if isinstance(value, dict):
            self.collapsed_sections = dict((k, bool(v)) for k, v in value.items())
