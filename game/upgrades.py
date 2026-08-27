"""The level-up offer pool.

Offers are generated from live state rather than hand-listed, so there is no way
for a card to reference a stat the player does not have. The old
``_validate_upgrade_pool`` assertion existed to catch exactly that class of typo;
building the pool from the weapon and passive registries removes the possibility.
"""

import random
from dataclasses import dataclass
from typing import Callable

from .config import (
    CHEST_FALLBACK_GOLD,
    COL_GOLD,
    COL_HEAL,
    CHEST_LUCK_BONUS,
    LUCK_RARITY_BONUS,
    MAX_LEVEL_UP_CARDS,
    MAX_PASSIVES,
    MAX_WEAPONS,
)
from . import rarity as rarities
from .weapons import EVOLUTIONS, WEAPON_TYPES


# Total weight all available passive offers share between them, so the odds of
# being shown a weapon upgrade do not depend on how long the passive list is.
PASSIVE_WEIGHT_BUDGET = 15.0


@dataclass
class PassiveDef:
    key: str
    label: str
    description: str
    max_level: int
    color: tuple


PASSIVE_DEFS = [
    PassiveDef("health", "Vitality", "+22 max health", 10, (110, 225, 130)),
    PassiveDef("might", "Might", "+10% damage from every source", 10, (255, 130, 110)),
    PassiveDef("speed", "Swiftness", "+7% movement speed", 8, (140, 220, 255)),
    PassiveDef("magnet", "Lodestone", "+28% pickup radius", 6, (200, 160, 255)),
    PassiveDef("crit", "Precision", "+5% critical hit chance", 8, (255, 190, 90)),
    PassiveDef("savagery", "Savagery", "+25% critical hit damage", 8, (255, 140, 70)),
    PassiveDef("armor", "Plating", "-1.6 damage taken per hit", 8, (170, 180, 200)),
    PassiveDef("regen", "Regrowth", "+0.5 health per second", 8, (120, 230, 170)),
    PassiveDef("wisdom", "Insight", "+12% experience gained", 8, (255, 235, 140)),
    PassiveDef("haste", "Momentum", "-6% weapon cooldowns", 8, (255, 200, 240)),
    PassiveDef("volley", "Volley", "+1 projectile from every weapon that fires them",
               2, (140, 255, 220)),
    PassiveDef("chaos", "Chaos",
               "Enemies are tougher and more numerous, but worth far more XP",
               5, (255, 110, 160)),
    PassiveDef("luck", "Fortune", "Rarer upgrades, better drops, sometimes a 4th choice",
               5, (255, 240, 170)),
]
PASSIVES_BY_KEY = {p.key: p for p in PASSIVE_DEFS}


@dataclass
class Offer:
    """One card. ``grant`` takes (player, levels); rarity decides the levels."""

    title: str
    subtitle: str
    detail: str
    color: tuple
    grant: Callable
    kind: str            # "fusion" | "new_weapon" | "weapon" | "passive" | "heal" | "gold"
    rarity: object = rarities.COMMON
    level_from: int = None      # current level, for rebuilding the subtitle
    level_cap: int = None
    rng: object = None

    @property
    def levels(self):
        """Levels this card actually delivers, never more than the cap allows."""
        wanted = self.rarity.levels
        if self.level_from is not None and self.level_cap is not None:
            return max(1, min(wanted, self.level_cap - self.level_from))
        return wanted

    @property
    def capped(self):
        """True when the tier promised more levels than the target could take."""
        return self.levels < self.rarity.levels

    def apply(self, player):
        self.grant(player, self.levels)
        if self.rarity.bonus_passive:
            grant_bonus_passive(player, self.rng or random)


def _fusion_offers(player):
    """Offers for any evolution whose ingredients are all owned and maxed."""
    by_key = {w.key: w for w in player.weapons}
    offers = []
    for evolution in EVOLUTIONS:
        if by_key.get(evolution.key) is not None:
            continue                      # already fused
        if not evolution.available_for(player):
            continue
        parts = " + ".join(evolution.ingredient_labels(by_key))
        offers.append(
            Offer(
                title=evolution.label,
                subtitle=f"Fuse {parts}",
                detail=evolution.description,
                color=evolution.color,
                grant=lambda p, n, e=evolution: e.apply(p),
                kind="fusion",
            )
        )
    return offers


def _weapon_offers(player):
    offers = []
    owned = {w.key: w for w in player.weapons}

    for weapon in player.weapons:
        if weapon.level < weapon.max_level:
            offers.append(
                Offer(
                    title=weapon.label,
                    subtitle=f"Level {weapon.level} -> {weapon.level + 1}",
                    detail=weapon.upgrade_text(),
                    color=weapon.color,
                    grant=lambda p, n, w=weapon: setattr(
                        w, "level", min(w.max_level, w.level + n)),
                    kind="weapon",
                    level_from=weapon.level,
                    level_cap=weapon.max_level,
                )
            )

    if len(player.weapons) < MAX_WEAPONS:
        for cls in WEAPON_TYPES:
            if cls.key in owned:
                continue

            def start(p, n, c=cls):
                fresh = c()
                fresh.level = min(c.max_level, n)   # a rare find arrives trained
                p.weapons.append(fresh)

            offers.append(
                Offer(
                    title=cls.label,
                    subtitle="New weapon",
                    detail=cls.description,
                    color=cls.color,
                    grant=start,
                    kind="new_weapon",
                    level_from=0,
                    level_cap=cls.max_level,
                )
            )
    return offers


def _passive_offers(player):
    offers = []
    at_slot_limit = len(player.passives) >= MAX_PASSIVES

    for passive in PASSIVE_DEFS:
        level = player.passives.get(passive.key, 0)
        if level >= passive.max_level:
            continue
        if level == 0 and at_slot_limit:
            continue
        offers.append(
            Offer(
                title=passive.label,
                subtitle="New passive" if level == 0 else f"Level {level} -> {level + 1}",
                detail=passive.description,
                color=passive.color,
                grant=lambda p, n, k=passive.key: p.add_passive(k, n),
                kind="passive",
                level_from=level,
                level_cap=passive.max_level,
            )
        )
    return offers


def grant_bonus_passive(player, rng):
    """Legendary's extra: one free level of something you are not maxed on.

    Deliberately a *different* stat from the card you picked — the point is the
    surprise, and doubling up on the thing you already chose would just read as
    a bigger number.
    """
    at_slot_limit = len(player.passives) >= MAX_PASSIVES
    candidates = [
        p for p in PASSIVE_DEFS
        if player.passives.get(p.key, 0) < p.max_level
        and not (at_slot_limit and p.key not in player.passives)
    ]
    if not candidates:
        return None
    chosen = rng.choice(candidates)
    player.add_passive(chosen.key, 1)
    return chosen


def assign_rarity(offer, rng, luck=0.0):
    """Roll this card's tier and restate its subtitle to match."""
    if offer.kind in ("fusion", "heal", "gold"):
        offer.rarity = rarities.COMMON
        offer.rng = rng
        return offer

    offer.rarity = rarities.roll(rng, luck, LUCK_RARITY_BONUS)
    offer.rng = rng

    levels = offer.levels
    if offer.kind == "new_weapon":
        offer.subtitle = "New weapon" if levels == 1 else f"New weapon at level {levels}"
    elif offer.level_from is not None:
        offer.subtitle = f"Level {offer.level_from} -> {offer.level_from + levels}"
    return offer


def _fallback_offer():
    """Shown only when everything is maxed, so the menu is never empty."""
    def grant(player, levels):
        player.heal(player.max_health * 0.4)
        player.gold += 15

    return Offer(
        title="Reliquary",
        subtitle="Nothing left to learn",
        detail="Restore 40% health and gain 15 gold",
        color=(255, 205, 80),
        grant=grant,
        kind="heal",
    )


def roll_chest_reward(player, rng=None):
    """One random upgrade, or a consolation prize when nothing is left.

    Reuses the level-up pool, so a chest can never hand out something the slot
    caps or max levels would forbid — and can hand out a fusion you have earned.
    """
    rng = rng or random

    fusion = _fusion_offers(player)
    if fusion:
        return assign_rarity(rng.choice(fusion), rng, player.luck)

    pool = _weapon_offers(player) + _passive_offers(player)
    if pool:
        # A chest is a paid roll, so it leans one tier friendlier than a level-up.
        return assign_rarity(rng.choice(pool), rng, player.luck + CHEST_LUCK_BONUS)

    # Everything is maxed. Health or gold, decided by the coin flip the design
    # asks for, rather than always the same consolation.
    if rng.random() < 0.5:
        def heal(target, levels):
            target.heal(target.max_health * 0.5)

        return Offer(
            title="Elixir", subtitle="Nothing left to learn",
            detail="Restore 50% of your health",
            color=COL_HEAL, grant=heal, kind="heal", rng=rng,
        )

    def payout(target, levels):
        target.gold += CHEST_FALLBACK_GOLD

    return Offer(
        title="Hoard", subtitle="Nothing left to learn",
        detail=f"Gain {CHEST_FALLBACK_GOLD} gold",
        color=COL_GOLD, grant=payout, kind="gold", rng=rng,
    )


def offer_count(player, rng=None, base=3):
    """How many cards this level-up shows. Fortune sometimes buys a fourth."""
    rng = rng or random
    if rng.random() < player.extra_card_chance:
        return min(MAX_LEVEL_UP_CARDS, base + 1)
    return base


def roll_offers(player, rng=None, count=3):
    """Pick ``count`` distinct offers, weighted to keep runs from stalling."""
    rng = rng or random

    # A fusion you have earned always appears, and appears alone. Burying the
    # payoff for maxing two weapons behind a random roll would be miserable.
    fusion_offers = _fusion_offers(player)
    if fusion_offers:
        return [assign_rarity(o, rng, player.luck) for o in fusion_offers[:count]]

    weapon_offers = _weapon_offers(player)
    passive_offers = _passive_offers(player)
    pool = weapon_offers + passive_offers
    if not pool:
        return [assign_rarity(_fallback_offer(), rng, player.luck)]

    # Passives share a fixed weight budget rather than each carrying a flat
    # weight. Otherwise every passive added to the roster quietly makes weapon
    # upgrades rarer — going from ten passives to thirteen cost about 25% of
    # bot survival time before this was normalised.
    passive_weight = min(2.5, PASSIVE_WEIGHT_BUDGET / max(1, len(passive_offers)))

    # New weapons are pushed early: a run where you never see a second weapon is
    # a boring run, and by mid-game you would rather deepen what you have.
    weights = []
    for offer in pool:
        if offer.kind == "new_weapon":
            weights.append(3.2 if len(player.weapons) < 3 else 1.1)
        elif offer.kind == "weapon":
            weights.append(2.0)
        else:
            weights.append(passive_weight)

    chosen = []
    remaining = list(zip(pool, weights))
    for _ in range(min(count, len(pool))):
        total = sum(w for _, w in remaining)
        roll = rng.uniform(0, total)
        accumulated = 0.0
        for index, (offer, weight) in enumerate(remaining):
            accumulated += weight
            if roll <= accumulated:
                chosen.append(offer)
                remaining.pop(index)
                break

    # Each card rolls its own tier, so a level-up can show a Common next to a
    # Legendary — which is the whole reason to look at all of them.
    return [assign_rarity(offer, rng, player.luck) for offer in chosen]
