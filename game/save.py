"""Persistent progress between runs.

Kept deliberately small: a gold total and a dict of permanent upgrade levels.
Anything the save file cannot explain is ignored rather than crashing, so an
older save still loads after you add a new shop entry.
"""

import json
import os
from dataclasses import dataclass

from . import paths
from . import settings
from .config import SAVE_FILENAME

# Outside the application folder once packaged: an update replaces that folder
# wholesale, and a save file living inside it would go with it.
SAVE_PATH = paths.user_data_path(SAVE_FILENAME)


def _migrate_legacy_save():
    """Move a save written by an older build beside the .exe into user data.

    Anyone who played before the save moved has their only copy in the old
    place. Copying rather than ignoring it is the difference between an update
    that is invisible and one that looks like it wiped their progress.
    """
    if os.path.exists(SAVE_PATH):
        return
    legacy = paths.legacy_user_data_path(SAVE_FILENAME)
    if legacy == SAVE_PATH or not os.path.exists(legacy):
        return
    try:
        os.makedirs(os.path.dirname(SAVE_PATH), exist_ok=True)
        with open(legacy, "r", encoding="utf-8") as source:
            content = source.read()
        with open(SAVE_PATH, "w", encoding="utf-8") as target:
            target.write(content)
    except OSError as exc:
        print(f"Could not carry the old save across: {exc}")


@dataclass
class ShopEntry:
    key: str
    label: str
    description: str
    max_level: int
    base_cost: int
    cost_growth: float = 1.6

    def cost(self, level):
        return int(self.base_cost * (self.cost_growth ** level))


SHOP_ENTRIES = [
    ShopEntry("health", "Constitution", "+22 starting max health", 8, 40),
    ShopEntry("might", "Warmark", "+10% damage from the start", 8, 60),
    ShopEntry("speed", "Fleetfoot", "+7% movement speed", 6, 55),
    ShopEntry("magnet", "Attunement", "+28% pickup radius", 4, 45),
    ShopEntry("armor", "Hardened", "-1.6 damage taken per hit", 6, 70),
    ShopEntry("wisdom", "Scholar", "+12% experience gained", 6, 65),
    ShopEntry("crit", "Keen Edge", "+5% critical hit chance", 5, 80),
    ShopEntry("regen", "Rootbound", "+0.5 health regen per second", 5, 90),
    ShopEntry("revive", "Second Wind", "Survive one lethal hit per run", 2, 250, 2.5),
    # Charges spent at the level-up screen, refilled at the start of every run.
    # Capped low on purpose: a reroll turns a bad hand into a good one every
    # time, so an unlimited supply would remove the only real decision the
    # level-up screen asks you to make.
    ShopEntry("reroll", "Foresight", "+1 level-up reroll per run", 3, 110, 1.8),
    ShopEntry("skip", "Restraint", "+1 level-up skip per run", 5, 60, 1.55),
]
SHOP_BY_KEY = {entry.key: entry for entry in SHOP_ENTRIES}

DEFAULT_SAVE = {"gold": 0, "upgrades": {}, "best_time": 0.0, "best_kills": 0,
                "runs": 0, "wins": 0, "deepest": 0, "settings": {}}


class SaveData:
    def __init__(self, data=None):
        merged = dict(DEFAULT_SAVE)
        merged.update(data or {})
        self.gold = int(merged.get("gold", 0))
        self.best_time = float(merged.get("best_time", 0.0))
        self.best_kills = int(merged.get("best_kills", 0))
        self.runs = int(merged.get("runs", 0))
        self.wins = int(merged.get("wins", 0))
        self.deepest = int(merged.get("deepest", 0))

        # Settings live in the save rather than a separate file: they are
        # per-player state that must survive a restart, which is exactly what
        # this file already is.
        #
        # Volumes used to sit at the top level. Saves written before the
        # settings menu existed still have them there, and silently resetting
        # somebody's audio because the storage layout moved would be a rotten
        # thing to do for no reason — so they are read across if the settings
        # block does not already carry them.
        stored = dict(merged.get("settings") or {})
        for legacy in ("sfx_volume", "music_volume"):
            if legacy not in stored and legacy in merged:
                stored[legacy] = merged[legacy]
        self.settings = settings.load_from(stored)
        # Drop keys that no longer exist and clamp anything above its cap.
        self.upgrades = {}
        for key, level in (merged.get("upgrades") or {}).items():
            entry = SHOP_BY_KEY.get(key)
            if entry:
                self.upgrades[key] = max(0, min(int(level), entry.max_level))

    # main.py and the pause screen still speak in terms of two volumes; these
    # keep that working now that the values live inside ``settings``.
    @property
    def sfx_volume(self):
        return self.settings.sfx_volume

    @sfx_volume.setter
    def sfx_volume(self, value):
        self.settings.set("sfx_volume", value)

    @property
    def music_volume(self):
        return self.settings.music_volume

    @music_volume.setter
    def music_volume(self, value):
        self.settings.set("music_volume", value)

    def level_of(self, key):
        return self.upgrades.get(key, 0)

    def can_afford(self, entry):
        level = self.level_of(entry.key)
        return level < entry.max_level and self.gold >= entry.cost(level)

    def purchase(self, entry):
        if not self.can_afford(entry):
            return False
        level = self.level_of(entry.key)
        self.gold -= entry.cost(level)
        self.upgrades[entry.key] = level + 1
        self.save()
        return True

    def record_run(self, result, earned_gold):
        self.gold += earned_gold
        self.runs += 1
        self.best_time = max(self.best_time, result["time"])
        self.best_kills = max(self.best_kills, result["kills"])
        self.deepest = max(self.deepest, result.get("maps_cleared", 0) + 1)
        if result.get("victory"):
            self.wins += 1
        self.save()

    def as_dict(self):
        return {
            "gold": self.gold,
            "upgrades": self.upgrades,
            "best_time": self.best_time,
            "best_kills": self.best_kills,
            "runs": self.runs,
            "wins": self.wins,
            "deepest": self.deepest,
            "settings": self.settings.as_dict(),
        }

    def save(self):
        try:
            with open(SAVE_PATH, "w", encoding="utf-8") as handle:
                json.dump(self.as_dict(), handle, indent=2)
        except OSError as exc:
            print(f"Could not write save file: {exc}")


def load():
    _migrate_legacy_save()
    if not os.path.exists(SAVE_PATH):
        return SaveData()
    try:
        with open(SAVE_PATH, "r", encoding="utf-8") as handle:
            return SaveData(json.load(handle))
    except (OSError, ValueError) as exc:
        print(f"Save file unreadable ({exc}); starting fresh.")
        return SaveData()
