###############################################################################
# Import / Export Page
###############################################################################

screen cue_import_export_page():
    style_group "cue"
    vbox:
        use cue_export_section()
        use cue_import_imports()


screen cue_export_section():
    style_group "cue"

    $ _exporter = _cue.exporter

    $ _exports_hint = ("Exports are saved to:\n{}").format(_exporter.exports_dir())

    use cue_section_frame("Export", tt=_exports_hint):
        vbox:
            spacing 5
            $ _current_replay = _exporter.current_replay
            $ _current_has_data = bool(
                _current_replay and _current_replay in _exporter.replay_labels())


            $ _exports_source = ("Exports always come from your data, "
                                 "not from a previewed import.")
            etext _exports_source

            null height 5

            hbox:
                spacing 10
                use cue_radio_btn(
                    (_exporter.scope == CueExportScope.ALL_REPLAYS),
                    "All Replays",
                    Function(_exporter.set_scope, CueExportScope.ALL_REPLAYS))
                use cue_radio_btn(
                    (_exporter.scope == CueExportScope.SPECIFIC_REPLAYS),
                    "Specific Replays",
                    Function(_exporter.set_scope, CueExportScope.SPECIFIC_REPLAYS))

            if (_exporter.scope == CueExportScope.SPECIFIC_REPLAYS):
                if not _exporter.replays:
                    etext ("No replays yet.  Markers edited inside a replay "
                          "show up here.")
                else:
                    if _current_has_data:
                        $ _in_replay_line = (
                            "You're in \"{}\" now:".format(_current_replay))
                        hbox:
                            spacing 8
                            etext _in_replay_line color _cue_color_text_muted
                            use cue_txt_button(
                                "Export this replay",
                                Function(_exporter.export_replay, _current_replay))
                    hbox:
                        spacing 8
                        use cue_txt_button(
                            "Toggle All",
                            Function(_exporter.toggle_all_replays),
                            tt="Check or uncheck every replay at once.")
                    viewport:
                        ysize 200
                        mousewheel True
                        scrollbars "vertical"
                        vscrollbar_unscrollable "hide"
                        vbox:
                            spacing 4
                            for _r in _exporter.replays:
                                hbox:
                                    spacing 8
                                    use cue_checkbox(
                                        _exporter.is_replay_checked(_r["replay"]),
                                        _r["replay"],
                                        Function(_exporter.toggle_replay, _r["replay"]))
                                    etext "{} marker(s)".format(_r["marker_count"]) color _cue_color_text_muted
                                    if (_r["replay"] == _current_replay):
                                        etext "(current)" color _cue_color_warn

            null height 5

            hbox:
                spacing 10
                use cue_radio_btn(
                    (_exporter.file_types == CueExportFileTypes.ALL),
                    "All File Types",
                    Function(_exporter.set_file_types, CueExportFileTypes.ALL),
                    tt="All markers, SFX files, Music Files, etc.")
                use cue_radio_btn(
                    (_exporter.file_types == CueExportFileTypes.SPECIFIC),
                    "Specific File Types",
                    Function(_exporter.set_file_types, CueExportFileTypes.SPECIFIC))

            null height 5

            if (_exporter.file_types == CueExportFileTypes.SPECIFIC):
                for _cat in CUE_IMPORT_CATEGORY_ORDER:
                    $ _label = CUE_IMPORT_CATEGORY_LABELS.get(_cat, "?")
                    $ _count = _exporter.counts.get(_cat, 0)
                    $ _enabled = _exporter.is_category_enabled(_cat)
                    hbox:
                        spacing 8
                        use cue_checkbox(
                            _exporter.is_checked(_cat),
                            _label,
                            Function(_exporter.toggle_category, _cat),
                            enabled=_enabled)
                        if (_exporter.scope == CueExportScope.ALL_REPLAYS):
                            if _enabled:
                                etext "{} file(s)".format(_count) color _cue_color_text_muted
                            else:
                                etext "empty" color _cue_color_text_dim
                if _exporter.any_unchecked():
                    etext ("Some file types are unchecked, so this export may not "
                          "fully work when imported.") color _cue_color_warn size 11

            null height 4

            vbox:
                spacing 5
                hbox:
                    spacing 8
                    frame:
                        style "empty"
                        xsize 40
                        etext "Title:" yalign 0.5
                    use cue_text_input(
                        "_cue.exporter.name",
                        Function(_exporter.clear_status),
                        _exporter.name or "(none)",
                        xsize=1.0)
                hbox:
                    spacing 8
                    frame:
                        style "empty"
                        xsize 40
                        etext "Author:" yalign 0.5
                    use cue_text_input(
                        "_cue.exporter.author",
                        Function(_exporter.clear_status),
                        _exporter.author or "(none)",
                        xsize=1.0)
                hbox:
                    spacing 8
                    frame:
                        style "empty"
                        xsize 40
                        etext "Notes:" yalign 0.5
                    use cue_text_input(
                        "_cue.exporter.description",
                        Function(_exporter.clear_status),
                        _exporter.description or "(none)",
                        xsize=1.0)

            null height 4

            hbox:
                spacing 5
                use cue_txt_button(
                    "Export",
                    Function(_exporter.export),
                    sensitive=(not _exporter.is_exporting))
                if _exporter.is_exporting:
                    $ _export_pct = int(_exporter.export_fraction * 100)
                    etext ("Exporting ({}%)".format(_export_pct)) color _cue_color_text_muted
                elif _exporter.export_error:
                    etext _exporter.export_error color _cue_color_error
                elif _exporter.export_status:
                    etext _exporter.export_status color _cue_color_green

            null height 4

            if _exporter.export_warning:
                etext _exporter.export_warning color _cue_color_warn size 11


screen cue_import_imports():
    style_group "cue"

    $ _imports_hint = ("Add export .zip file to:\n{}").format(_cue.importer.imports_dir())

    use cue_section_frame("Import", tt=_imports_hint):
        etext ("Imports can be previewed, which will temporarily replace your data (except your Settings). "
            "If you like the preview, you can copy it into your data folder with \"Merge\".")

        null height 4
        use cue_url_downloader()
        null height 2

        if _cue.importer.scan_error:
            etext _cue.importer.scan_error color _cue_color_error
        if _cue.importer.is_importing:
            $ _imp_pct = int(_cue.importer.import_fraction * 100)
            etext ("Extracting {} ({}%)...".format(
                _cue.importer.import_label, _imp_pct)) color _cue_color_text_muted
        elif not _cue.importer.imports:
            etext "No imports found yet."
            etext _imports_hint
            
        viewport:
            xfill True
            mousewheel True
            scrollbars "vertical"
            vscrollbar_unscrollable "hide"
            vbox:
                for _imp in _cue.importer.imports:
                    use cue_import_row(_imp)


screen cue_url_downloader():
    style_group "cue"

    vbox:
        spacing 8
        hbox:
            spacing 5
            use cue_text_input(
                "_cue.url_importer.url",
                Function(_cue.url_importer.clear_status),
                _cue.url_importer.url or "Paste a URL to a .zip",
                xsize=370,
                clear_action=Function(_cue.url_importer.clear_url),
                paste_btn=True)
            if _cue.url_importer.is_downloading:
                use cue_txt_button(
                    "Cancel",
                    Function(_cue.url_importer.cancel))
            else:
                use cue_txt_button(
                    "Import URL",
                    [Function(_cue.url_importer.import_url),
                     SetField(_cue, "editing_input", "")],
                    sensitive=(not _cue.url_importer.is_downloading),
                    tt="Download a .zip from a URL into your imports folder.")

        if _cue.url_importer.is_downloading:
            $ _url_done = _cue_format_size(_cue.url_importer.download_done)
            $ _url_elapsed = _cue_format_duration(_cue.url_importer.download_duration())
            if _cue.url_importer.download_total:
                $ _url_total = _cue_format_size(_cue.url_importer.download_total)
                $ _url_pct = int(_cue.url_importer.download_done * 100.0 / _cue.url_importer.download_total)
                etext ("{}% - {} / {} - {}".format(
                    _url_pct, _url_done, _url_total, _url_elapsed)) color _cue_color_text_muted
            else:
                etext ("Downloading... {}".format(_url_done)) color _cue_color_text_muted
        elif _cue.url_importer.download_error:
            etext _cue.url_importer.download_error color _cue_color_error substitute False
        elif _cue.url_importer.download_status:
            etext _cue.url_importer.download_status color _cue_color_green substitute False
        else:
            etext "URL must be a direct download link, not a website with a download button." style "cue_help"


screen cue_import_row(_imp):
    style_group "cue"

    $ _imp_key = _imp["imp"]
    $ _imp_name = _imp["name"]
    $ _status = _cue.importer.match_label(_imp_key)
    $ _warnings = _cue.importer.match_warnings(_imp_key)
    $ _match = _imp["match"]
    $ _valid = _imp["valid"]
    $ _author_line = ("by " + _imp["author"]) if _imp["author"] else ""
    $ _desc_line = _imp["description"]
    $ _replay_toggle_key = "row"
    $ _is_active = (_cue.importer.is_active
                    and _cue.importer.active_import == _imp_key)
    $ _can_preview = (_valid and _match == CueImportMatch.AUTO)
    frame:
        background (_cue_color_bg_panel if not _is_active else _cue_color_bg_input)
        padding (0, 6)
        xfill True
        vbox:
            spacing 4
            hbox:
                spacing 6
                xfill True
                box_wrap True
                box_wrap_spacing 3
                etext _imp_name color _cue_color_text_accent
                if _author_line:
                    etext _author_line color _cue_color_text_muted
            if _desc_line:
                etext _desc_line color _cue_color_text_muted size 11
            if _warnings:
                $ _status_tt = "\n---\n".join(_warnings)
                $ _warn_icon = _cue.icons.displayable_for("triangle-exclamation", _cue_color_warn, 11)
                button:
                    style "empty"
                    padding (0, 0)
                    background None
                    hover_background None
                    action NullAction()
                    tooltip _status_tt
                    hbox:
                        spacing 5
                        add _warn_icon yalign 0.5
                        etext _status color _cue_color_warn size 11
                null height 3

            elif _status:
                etext _status color _cue_color_error size 11
            hbox:
                spacing 6
                if _can_preview:
                    if _is_active:
                        use cue_txt_button(
                            "Exit Preview",
                            Function(_cue.importer.deactivate),
                            tt="Stop previewing. Your own data is restored.")
                    else:
                        use cue_txt_button(
                            "Preview",
                            Function(_cue.importer.activate, _imp_key),
                            tt="Preview this import and optionally edit its data.")
                    use cue_replay_toggle(_imp_key, _replay_toggle_key)
                    use cue_txt_button(
                        "Merge",
                        Function(_cue.importer.open_merge, _imp_key),
                        tt="Choose what to copy from this import into your data.")
                if (_match == CueImportMatch.CONFIRM
                        or _match == CueImportMatch.MISMATCH):
                    use cue_txt_button(
                        "Remap Game ID",
                        Function(_cue.importer.remap, _imp_key),
                        tt="Update this import's Game ID to the current Game ID "
                           "so it can be imported.")
                use cue_txt_button(
                    "Delete",
                    Function(_cue.importer.confirm_delete, _imp_key),
                    tt="Delete this import (zip + extracted folder)." + CUE_HELP_SHIFT_SKIP_DELETE)
            if _can_preview:
                use cue_replay_children(_imp_key, _replay_toggle_key)


###############################################################################
# Active-import banner -- shown while an import is active.  Activate swaps the
# effective root, so the editor serves the import's data: edits land in the
# import folder, not the user's data.  The banner (outside the page body, in
# cue_overlay_content) stays clickable for Merge/Deactivate.
###############################################################################

screen cue_edit_banner():
    style_group "cue"

    $ _active_imp = _cue.importer.active_import
    $ _imp_display = _cue.importer.active_import_name()
    $ _replay_toggle_key = "banner"
    use cue_section_frame("Import Preview"):
        vbox:
            spacing 8
            xfill True
            hbox:
                spacing 6
                etext "Import:"
                etext _imp_display color _cue_color_text_accent
            etext "Edits apply to the import. Your own data will be restored when you exit preview."

            hbox:
                spacing 6
                use cue_replay_toggle(_active_imp, _replay_toggle_key)
                use cue_txt_button(
                    "Merge",
                    Function(_cue.importer.open_merge, _active_imp),
                    tt="Choose what to copy into your data folder")
                use cue_txt_button(
                    "Exit Preview",
                    Function(_cue.importer.deactivate))
            use cue_replay_children(_active_imp, _replay_toggle_key)
