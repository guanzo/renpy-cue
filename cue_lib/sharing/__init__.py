# -*- coding: utf-8 -*-
# cue_lib/sharing -- the import/export side of the mod.
#
# exporter.py builds a .zip import from this game's data; importer.py scans
# imports/*.zip and activates one as a root-swap overlay or merges categories;
# importer_io.py owns the pure .zip format logic + filesystem ops; and
# url_importer.py downloads a .zip into the drop zone.  The package re-exports
# the manager API so consumers keep importing from the package.
#
# Submodules are imported in dependency order (leaf-first) -- Ren'Py's
# import_all() discovers modules through the package namespace, so they must
# be loaded even when only the package name is imported.

# pyright: reportUnusedImport=false

from cue_lib.sharing import importer_io
from cue_lib.sharing import exporter
from cue_lib.sharing import importer
from cue_lib.sharing import url_importer

from cue_lib.sharing.exporter import CueExportManager
from cue_lib.sharing.importer import CueImportManager
from cue_lib.sharing.url_importer import CueUrlImporter
