# -*- coding: utf-8 -*-
# cue_lib/audio/tree -- the file-tree UI data model.
#
# The tree classes build the folder/file data model the shared cue_tree_rows
# renderer draws: file_tree.py (CueAudioTreeManager, the SFX library scan) and
# music_tree.py (CueMusicTree, the combined Music Library scan) each own scan /
# search / expand state and construct a builder that emits the flat row stream.
# tree_rows.py is the shared row core (row shapes + CueTreeRowsBuilder base);
# sfx_tree_rows.py / music_tree_rows.py are the per-source button/warn
# variations; pool_rows.py renders a marker pool's refs.  A builder reaches its
# data tree through _tree, so no module here imports the concrete managers
# (sfx_manager / music) -- no import cycle.
#
# Submodules are imported in dependency order (leaf-first) -- Ren'Py's
# import_all() discovers modules through the package namespace, so they must
# be loaded even when only the package name is imported.

# pyright: reportUnusedImport=false

import cue_lib.audio.tree.tree_rows
import cue_lib.audio.tree.file_tree
import cue_lib.audio.tree.pool_rows
import cue_lib.audio.tree.sfx_tree_rows
import cue_lib.audio.tree.sfx_tree
import cue_lib.audio.tree.music_tree_rows
import cue_lib.audio.tree.music_tree
