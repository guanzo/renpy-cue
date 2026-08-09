# CuePopper — Reusable positioned popup for Ren'Py.
# sl-displayable registration (must be python early).
# The CuePopper class and helpers live in cue_lib/popper.py.

python early:
    def _cue_popper_factory(*args, **kwargs):
        """Factory for register_sl_displayable. Returns a CuePopper instance.
        CuePopper is resolved at call time (screen execution), by which point
        the init -999 bridge has imported it into store."""
        return CuePopper(*args, **kwargs)

    renpy.register_sl_displayable(
        "popper",
        _cue_popper_factory,
        style="default",
        nchildren=1,
        default_keywords={
            "placement": "top",
            "offset": 5,
            "viewport_margin": 8,
        },
    ).add_property("target").add_property("placement").add_property("offset").add_property("viewport_margin")
