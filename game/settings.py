"""Player-facing settings, and the one object the game reads them from.

Settings are declared as data rather than written out as fields, for the same
reason weapons and shop entries are: the menu is generated from this list, the
save file round-trips it, and adding "show a frame counter" is one entry here
instead of an entry plus a menu row plus a save key plus a default, four places
that can disagree.

Gameplay code reads ``settings.damage_numbers`` and similar directly. That is a
deliberate global — the alternative is threading a settings object through
``World``, every weapon's ``draw``, and the camera, which is a wide change to
express "the player turned screen shake down".
"""

SLIDER = "slider"
TOGGLE = "toggle"
CHOICE = "choice"


class Option:
    """One setting: how it is stored, shown, and edited.

    ``restart`` marks settings that cannot take effect mid-run — the renderer
    owns an SDL window created at startup. The menu says so rather than letting
    the player click and wonder why nothing changed.
    """

    def __init__(self, key, label, kind, default, description="",
                 choices=(), restart=False):
        self.key = key
        self.label = label
        self.kind = kind
        self.default = default
        self.description = description
        self.choices = choices
        self.restart = restart

    def clamp(self, value):
        """Coerce anything the save file offers into something usable.

        Hand-edited or older save files are expected, not exceptional, so an
        unreadable value falls back to the default rather than raising.
        """
        if self.kind == SLIDER:
            try:
                return max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                return self.default
        if self.kind == TOGGLE:
            return bool(value)
        if self.kind == CHOICE:
            return value if value in self.choices else self.default
        return self.default


OPTIONS = [
    Option("sfx_volume", "Sound", SLIDER, 0.7,
           "Weapons, hits, pickups and the interface."),
    Option("music_volume", "Music", SLIDER, 0.22,
           "The background track for each arena."),
    Option("screen_shake", "Screen shake", SLIDER, 1.0,
           "How hard the camera kicks when things explode."),
    Option("damage_numbers", "Damage numbers", TOGGLE, True,
           "Numbers floating off everything you hit."),
    Option("health_bars", "Enemy health bars", TOGGLE, True,
           "Shown above elites and Wardens."),
    Option("show_fps", "Frame counter", TOGGLE, False,
           "Frames per second, in the corner."),
    Option("renderer", "Renderer", CHOICE, "software",
           "Software is faster below about 1200 enemies.",
           choices=("software", "gpu"), restart=True),
]

OPTIONS_BY_KEY = {option.key: option for option in OPTIONS}

# Sliders that feed the mixer rather than a gameplay flag. The menu treats them
# like any other slider; ``Settings.set`` knows they need pushing to audio.
AUDIO_KEYS = ("sfx_volume", "music_volume")


class Settings:
    """Live values, with attribute access for the code that reads them."""

    def __init__(self, stored=None):
        stored = stored or {}
        for option in OPTIONS:
            setattr(self, option.key, option.clamp(stored.get(option.key, option.default)))

    def get(self, key):
        return getattr(self, key)

    def set(self, key, value):
        option = OPTIONS_BY_KEY[key]
        setattr(self, key, option.clamp(value))
        return getattr(self, key)

    def toggle(self, key):
        return self.set(key, not getattr(self, key))

    def cycle(self, key, step=1):
        option = OPTIONS_BY_KEY[key]
        current = option.choices.index(getattr(self, key))
        return self.set(key, option.choices[(current + step) % len(option.choices)])

    def as_dict(self):
        return {option.key: getattr(self, option.key) for option in OPTIONS}

    def reset(self):
        for option in OPTIONS:
            setattr(self, option.key, option.default)


# The instance the game reads. Replaced wholesale when a save loads.
current = Settings()


def load_from(stored):
    """Point ``current`` at freshly loaded values without rebinding the name.

    Callers do ``from .settings import current`` and hold that reference, so the
    object has to be updated in place rather than reassigned.
    """
    fresh = Settings(stored)
    for option in OPTIONS:
        setattr(current, option.key, getattr(fresh, option.key))
    return current
