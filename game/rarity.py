"""Rarity tiers for level-up and chest rewards.

A tier does one thing: it decides how many levels of the rolled upgrade you
actually get. Expressing rarity as levels rather than as a separate damage
multiplier means it rides on machinery that already exists — max levels still
cap it, the loadout panel still shows the truth, and no stat needs a second
scaling path that could drift out of sync with the first.

Legendary additionally throws in a level of something else entirely, which is
the part that makes hitting one feel like hitting one.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rarity:
    key: str
    label: str
    color: tuple
    weight: float
    levels: int
    bonus_passive: bool = False

    @property
    def is_common(self):
        return self.levels <= 1


# Ordered worst to best; index doubles as the exponent Fortune leans on.
RARITIES = (
    Rarity("common", "Common", (178, 184, 198), 68.0, 1),
    Rarity("uncommon", "Uncommon", (108, 214, 126), 21.0, 2),
    Rarity("rare", "Rare", (92, 166, 255), 7.5, 3),
    Rarity("epic", "Epic", (194, 118, 255), 2.8, 4),
    Rarity("legendary", "Legendary", (255, 186, 64), 0.7, 5, bonus_passive=True),
)
COMMON = RARITIES[0]
LEGENDARY = RARITIES[-1]
BY_KEY = {r.key: r for r in RARITIES}


def weights_for(luck=0.0, luck_bonus=0.10):
    """Tier weights after Fortune tilts them.

    Each tier is boosted by the luck factor raised to its own index, so Fortune
    lifts the top of the table far more than the bottom — which is the only way
    a 0.7% Legendary ever becomes something you might actually plan around.
    """
    factor = 1.0 + luck * luck_bonus
    return [rarity.weight * (factor ** index) for index, rarity in enumerate(RARITIES)]


def roll(rng, luck=0.0, luck_bonus=0.10):
    weights = weights_for(luck, luck_bonus)
    total = sum(weights)
    ticket = rng.uniform(0.0, total)
    accumulated = 0.0
    for rarity, weight in zip(RARITIES, weights):
        accumulated += weight
        if ticket <= accumulated:
            return rarity
    return RARITIES[-1]


def chance_of(rarity, luck=0.0, luck_bonus=0.10):
    """Probability of rolling exactly ``rarity``. Used by tests and tuning."""
    weights = weights_for(luck, luck_bonus)
    index = RARITIES.index(rarity)
    return weights[index] / sum(weights)


def expected_levels(luck=0.0, luck_bonus=0.10):
    """Average levels granted per pick — the power-creep number to watch."""
    weights = weights_for(luck, luck_bonus)
    total = sum(weights)
    return sum(r.levels * w for r, w in zip(RARITIES, weights)) / total
