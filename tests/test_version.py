# -*- coding: utf-8 -*-
import re
from cue_lib.constants import CUE_VERSION


def test_cue_version_is_semver():
    assert re.match(r"^\d+\.\d+\.\d+$", CUE_VERSION) is not None


def test_cue_version_is_nonempty():
    assert len(CUE_VERSION) > 0
