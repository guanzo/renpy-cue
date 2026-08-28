# -*- coding: utf-8 -*-
# cue_lib/music -- the music manager, split into focused modules.
#
# manager.py (CueMusicManager) keeps the channel interception + playback and
# delegates the trigger log/editing (triggers.py), preset screen behavior
# (presets.py), and stored-ref resolution (refs.py) to sibling modules, with
# flat property delegates so the manager-level API stays stable.
#
# Submodules are imported in dependency order (leaf-first) -- Ren'Py's
# import_all() discovers modules through the package namespace, so they must
# be loaded even when only the package name is imported.

# pyright: reportUnusedImport=false

import cue_lib.music.refs
import cue_lib.music.triggers
import cue_lib.music.presets
import cue_lib.music.manager
