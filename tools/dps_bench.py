"""Compare every weapon's damage output under identical conditions.

    python tools/dps_bench.py            all weapons at levels 1, 4 and 8
    python tools/dps_bench.py --level 8  a single level

Each weapon is measured alone, against a frozen field of unkillable dummies
arranged the same way every time, with no passives. The numbers are only
meaningful relative to each other — they are a balance instrument, not a
prediction of real-run DPS, because they ignore movement, targeting pressure and
how often a weapon actually has something in range.
"""

import argparse
import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from game import assets
from game.config import FPS, SCREEN_HEIGHT, SCREEN_WIDTH
from game.entities import ARCHETYPES, Enemy
from game.weapons import EVOLUTIONS, EVOLVED_TYPES, WEAPON_TYPES
from game.world import World

DUMMY_HEALTH = 1e12
SECONDS = 12.0
DUMMY_COUNT = 30
INNER_RADIUS = 45.0
OUTER_RADIUS = 320.0

# Dummies are scattered at even *area* density rather than on a couple of rings.
# Concentric rings badly distort the comparison: an orbiting weapon whose radius
# happens to coincide with a ring looks enormous, and the same weapon one level
# later — orbiting between the rings — reads as zero.
_GOLDEN_ANGLE = 137.508


def field_positions():
    positions = []
    for index in range(DUMMY_COUNT):
        # sqrt spacing keeps density uniform per unit area, not per unit radius.
        fraction = (index + 0.5) / DUMMY_COUNT
        radius = INNER_RADIUS + (OUTER_RADIUS - INNER_RADIUS) * math.sqrt(fraction)
        positions.append(pygame.Vector2(radius, 0).rotate(index * _GOLDEN_ANGLE))
    return positions


def build_field(world):
    """Create the dummies once. They are reused, never recreated.

    Weapons with a per-enemy hit cooldown key it on ``id(enemy)``. Rebuilding
    the field each frame hands out fresh identities, so those cooldowns never
    match and the weapon re-hits every single frame — which reported Frost Orb
    at roughly six times its real output.
    """
    world.enemies.clear()
    for offset in field_positions():
        enemy = Enemy(ARCHETYPES["goblin"], world.player.pos + offset, 0.0)
        enemy.max_health = DUMMY_HEALTH
        enemy.speed = 0.0                  # frozen, so geometry stays identical
        enemy.contact_damage = 0.0
        world.enemies.append(enemy)
    return list(world.enemies)


def restore_field(world, dummies, origin):
    """Put the dummies back exactly where they started, still alive."""
    for enemy, offset in zip(dummies, field_positions()):
        enemy.health = DUMMY_HEALTH
        enemy.alive = True
        enemy.pos.update(origin + offset)
        enemy.knockback.update(0, 0)
        enemy.statuses.clear()
    world.enemies = list(dummies)


# Every weapon is measured walking a lap through the static field rather than
# standing in the middle of it. Trail weapons need it — they produce nothing
# standing still — but it turned out to matter for accuracy generally: Solar
# Beam H and V are the same weapon on different axes, and measured static they
# read 25% apart purely because the scattered field is not symmetric. Walking a
# lap averages that away and they land within 2% of each other.
MOVE_RADIUS = 130.0
LAP_SECONDS = 4.0


def measure(weapon_cls, level, moving=None):
    world = World({}, seed=1234, starting_weapon=weapon_cls.key)
    player = world.player
    player.passives.clear()
    player.weapons = [weapon_cls()]
    # Fusions cap at level 6, so asking for level 8 would measure a state the
    # game can never reach.
    player.weapons[0].level = min(level, weapon_cls.max_level)
    if moving is None:
        moving = True

    world.director.spawn_rate = lambda: 0.0        # no interference
    world.director.spawn_surge = lambda w: None
    world.director.spawn_boss = lambda w, from_altar=False: None
    world.director.recycle_strays = lambda w: None

    origin = pygame.Vector2(player.pos)
    dummies = build_field(world)

    dt = 1.0 / FPS
    for step in range(int(SECONDS * FPS)):
        restore_field(world, dummies, origin)     # same objects, pristine state
        if moving:
            angle = step * (360.0 / (LAP_SECONDS * FPS))
            player.pos.update(origin + pygame.Vector2(MOVE_RADIUS, 0).rotate(angle))
        else:
            player.pos.update(origin)
        player.health = player.max_health
        world.update(dt, pygame.Vector2())
        world.finished = False

    return player.damage_dealt / SECONDS


def main():
    parser = argparse.ArgumentParser(description="Weapon DPS comparison")
    parser.add_argument("--level", type=int, action="append",
                        help="weapon level to measure (repeatable)")
    args = parser.parse_args()
    levels = args.level or [1, 4, 8]

    pygame.init()
    pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.HIDDEN)
    assets.load_images()

    print(f"\ndamage per second, alone, walking a lap through {DUMMY_COUNT} frozen "
          f"dummies spread {INNER_RADIUS:.0f}-{OUTER_RADIUS:.0f}px, no passives")
    header = "  ".join(f"lv{level:<8d}" for level in levels)
    print(f"\n{'weapon':<16s}{header}")
    print("-" * (16 + 11 * len(levels)))

    results = {}
    for weapon_cls in WEAPON_TYPES + EVOLVED_TYPES:
        row = [measure(weapon_cls, level) for level in levels]
        results[weapon_cls.label] = row
        cells = "  ".join(f"{value:<10,.0f}" for value in row)
        mark = "  (fusion, caps at lv%d)" % weapon_cls.max_level if weapon_cls.evolved else ""
        print(f"{weapon_cls.label:<16s}{cells}{mark}")

    print()
    base_labels = {cls.label for cls in WEAPON_TYPES}
    for index, level in enumerate(levels):
        # Fusions are meant to out-damage their ingredients, so they would
        # dominate the spread and hide any real imbalance among the base kit.
        column = {label: row[index] for label, row in results.items()
                  if label in base_labels}
        best = max(column.values())
        worst = min(v for v in column.values() if v > 0) if any(column.values()) else 1
        spread = best / max(worst, 1)
        strongest = max(column, key=column.get)
        weakest = min(column, key=column.get)
        print(f"level {level}: base-weapon spread {spread:.1f}x   "
              f"strongest {strongest} ({best:,.0f})   weakest {weakest} ({column[weakest]:,.0f})")

    # The question a fusion has to answer is not "how does it compare to a level-1
    # weapon" — you only ever see one after maxing two others. It is "is this
    # better than the two maxed weapons I am giving up?" A fusion that starts
    # below that line is a trap the player cannot un-pick.
    print("\nfusion payoff, against the maxed ingredients it consumes")
    by_key = {cls.key: cls for cls in WEAPON_TYPES}
    for evolution in EVOLUTIONS:
        parts = [by_key[k] for k in evolution.ingredients if k in by_key]
        combined = sum(measure(cls, cls.max_level) for cls in parts)
        names = " + ".join(cls.label for cls in parts)
        result_cls = evolution.result
        entry = measure(result_cls, 1)
        maxed = measure(result_cls, result_cls.max_level)
        print(f"  {names}  maxed = {combined:,.0f}")
        print(f"    {result_cls.label:<14s} lv1 {entry:>9,.0f}  ({entry / max(combined, 1):.2f}x)"
              f"   lv{result_cls.max_level} {maxed:>9,.0f}  ({maxed / max(combined, 1):.2f}x)")

    pygame.quit()


if __name__ == "__main__":
    main()
