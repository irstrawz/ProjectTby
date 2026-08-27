"""Timed status effects on enemies: burn, poison, chill.

One mechanism covers all of them, because they only differ in two numbers: how
much damage they tick, and how much they slow. Fireball's burn, Poison Aura's
poison and Frost Orb's chill are the same object with different values, so
adding a fourth element later is a data change rather than a code change.

Stacking is refresh-and-take-max, not additive. Additive stacking with hundreds
of enemies and multi-hit weapons compounds into damage nobody can reason about;
taking the strongest application and extending its duration stays predictable
while still rewarding a specced-up element.
"""

from dataclasses import dataclass

BURN = "burn"
POISON = "poison"
CHILL = "chill"

STATUS_COLORS = {
    BURN: (255, 145, 55),
    POISON: (130, 225, 95),
    CHILL: (135, 205, 255),
}

# Bosses shrug off most of a slow — a fully frozen boss is not a fight.
BOSS_SLOW_CAP = 0.4


@dataclass(frozen=True)
class StatusSpec:
    """An application of a status: what to inflict, and for how long."""

    key: str
    duration: float
    dps: float = 0.0
    interval: float = 0.5
    slow: float = 0.0
    weapon_key: str = None

    @property
    def color(self):
        return STATUS_COLORS.get(self.key, (255, 255, 255))


class ActiveStatus:
    __slots__ = ("key", "remaining", "dps", "interval", "tick_timer", "slow", "weapon_key")

    def __init__(self, spec):
        self.key = spec.key
        self.remaining = spec.duration
        self.dps = spec.dps
        self.interval = spec.interval
        self.tick_timer = spec.interval
        self.slow = spec.slow
        self.weapon_key = spec.weapon_key

    def refresh(self, spec):
        """Re-applying extends the timer and keeps the strongest magnitude."""
        self.remaining = max(self.remaining, spec.duration)
        if spec.dps > self.dps:
            self.dps = spec.dps
            self.interval = spec.interval
            self.weapon_key = spec.weapon_key
        self.slow = max(self.slow, spec.slow)

    @property
    def color(self):
        return STATUS_COLORS.get(self.key, (255, 255, 255))
