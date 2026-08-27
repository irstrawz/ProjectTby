"""The wave director: decides what shows up, when, and from where.

Enemies appear on a ring just outside the camera view rather than at random
points on the map. That single change removes the old build's worst spawn bug —
mobs materialising inside sealed rooms where they could never reach you — and it
is what makes the pressure feel like it is closing in rather than wandering by.
"""

import math

import pygame

from .config import (
    BOSS_INTERVAL,
    DESPAWN_DISTANCE,
    ELITE_CHANCE_CAP,
    ELITE_CHANCE_PER_MIN,
    ELITE_START_TIME,
    MAX_ENEMIES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPAWN_RING_MARGIN,
    TILE_SIZE,
)
from .entities import ARCHETYPES, Enemy

RING_RADIUS = math.hypot(SCREEN_WIDTH, SCREEN_HEIGHT) / 2 + SPAWN_RING_MARGIN

# Pressure spikes: a dense pack from one direction, so the run has a rhythm
# instead of a flat trickle.
SURGE_INTERVAL = 26.0
SURGE_ARC = 55.0
SURGE_FIRST = 45.0        # no pressure spikes until you have a second weapon

# Ring-spawned enemies need RING_RADIUS / speed seconds to walk into range —
# about seven at the opening. Seeding a ring inside the view means the run starts
# with something to kill instead of seven dead seconds.
OPENING_COUNT = 8
OPENING_RADIUS = 430.0


class Director:
    def __init__(self, rng):
        self.rng = rng
        self.reset()

    def reset(self):
        self.elapsed = 0.0
        self.spawn_accumulator = 0.0
        self.surge_timer = SURGE_FIRST
        self.boss_timer = BOSS_INTERVAL
        self.boss_number = 0
        self.announced = set()
        self.pending_announcements = []

    # -- pacing --------------------------------------------------------------
    def spawn_rate(self, chaos_mult=1.0):
        """Enemies per second.

        Deliberately quadratic. A linear ramp that feels right at minute five is
        already drowning a level-1 loadout at minute zero — the opening has to
        sit below what one starting weapon can actually clear, then accelerate
        past what any single weapon can handle.

            0:00  0.9/s      3:00  5.6/s      8:00  19.9/s
            1:00  2.2/s      5:00 10.4/s     10:00 26.0/s (cap)
        """
        minutes = self.elapsed / 60.0
        base = 0.9 + minutes * 1.1 + minutes * minutes * 0.16
        return min(26.0 * chaos_mult, base * chaos_mult)

    def elite_chance(self):
        if self.elapsed < ELITE_START_TIME:
            return 0.0
        minutes = self.elapsed / 60.0
        return min(ELITE_CHANCE_CAP, minutes * ELITE_CHANCE_PER_MIN)

    def available_archetypes(self):
        return [
            a for a in ARCHETYPES.values()
            if a.weight > 0 and self.elapsed >= a.unlock_time
        ]

    def pick_archetype(self):
        options = self.available_archetypes()
        weights = [a.weight for a in options]
        total = sum(weights)
        roll = self.rng.uniform(0, total)
        accumulated = 0.0
        for archetype, weight in zip(options, weights):
            accumulated += weight
            if roll <= accumulated:
                return archetype
        return options[-1]

    # -- placement -----------------------------------------------------------
    def ring_position(self, arena, player_pos, angle=None, attempts=14, radius=None):
        radius = RING_RADIUS if radius is None else radius
        for _ in range(attempts):
            theta = math.radians(angle if angle is not None else self.rng.uniform(0, 360))
            candidate = player_pos + pygame.Vector2(math.cos(theta), math.sin(theta)) * radius

            candidate.x = max(TILE_SIZE * 1.5, min(candidate.x, arena.width - TILE_SIZE * 1.5))
            candidate.y = max(TILE_SIZE * 1.5, min(candidate.y, arena.height - TILE_SIZE * 1.5))

            probe = pygame.Rect(0, 0, TILE_SIZE, TILE_SIZE)
            probe.center = (candidate.x, candidate.y)
            if not arena.rect_hits_wall(probe):
                return candidate
            angle = None      # first retry after a blocked angle goes random
        return None

    # -- main tick -----------------------------------------------------------
    def update(self, dt, world):
        self.elapsed += dt
        self._check_unlocks()

        enemies = world.enemies
        headroom = MAX_ENEMIES - len(enemies)

        if headroom > 0:
            rate = self.spawn_rate(world.player.chaos_spawn_mult * world.map_def.spawn_mult)
            self.spawn_accumulator += rate * dt
            while self.spawn_accumulator >= 1.0 and headroom > 0:
                self.spawn_accumulator -= 1.0
                if self.spawn_one(world):
                    headroom -= 1
        else:
            self.spawn_accumulator = 0.0

        self.surge_timer -= dt
        if self.surge_timer <= 0:
            self.surge_timer = SURGE_INTERVAL
            self.spawn_surge(world)

        self.boss_timer -= dt
        if self.boss_timer <= 0:
            self.boss_timer = BOSS_INTERVAL
            self.spawn_boss(world)

        self.recycle_strays(world)

    def opening_wave(self, world):
        """Seed the first ring so the run has action from second zero."""
        for i in range(OPENING_COUNT):
            angle = 360 * i / OPENING_COUNT + self.rng.uniform(-10, 10)
            self.spawn_one(world, angle=angle, radius=OPENING_RADIUS)

    def spawn_one(self, world, archetype=None, angle=None, force_elite=None, radius=None):
        pos = self.ring_position(world.arena, world.player.pos, angle, radius=radius)
        if pos is None:
            return False
        archetype = archetype or self.pick_archetype()
        elite = force_elite if force_elite is not None else self.rng.random() < self.elite_chance()
        enemy = Enemy(archetype, pos, self.elapsed, elite=elite, chaos=world.player.chaos)
        world.apply_map_modifiers(enemy)
        world.enemies.append(enemy)
        return True

    def spawn_surge(self, world):
        """A tight pack from one side — the thing you have to actually dodge."""
        count = min(int(9 + self.elapsed / 12), MAX_ENEMIES - len(world.enemies))
        if count <= 0:
            return
        base_angle = self.rng.uniform(0, 360)
        for _ in range(count):
            angle = base_angle + self.rng.uniform(-SURGE_ARC / 2, SURGE_ARC / 2)
            self.spawn_one(world, angle=angle)

    def spawn_boss(self, world, from_altar=False):
        pos = self.ring_position(world.arena, world.player.pos)
        if pos is None:
            pos = pygame.Vector2(world.player.pos) + pygame.Vector2(RING_RADIUS, 0)
        self.boss_number += 1

        # The final map's altar answers with the Warchief, not another Warden.
        final = from_altar and world.map_def.is_final
        archetype = ARCHETYPES["king" if final else "boss"]
        boss = Enemy(archetype, pos, self.elapsed, chaos=world.player.chaos)
        world.apply_map_modifiers(boss)
        # Later bosses are meaningfully tougher than the first, on top of the
        # normal time scaling every enemy gets.
        extra = 1.0 if final else 1.0 + 0.45 * (self.boss_number - 1)
        boss.max_health *= extra
        boss.health = boss.max_health
        boss.xp_value *= extra
        world.enemies.append(boss)

        # Only the Warden you deliberately summoned opens the way onward, so the
        # timed boss waves stay a threat rather than a free exit.
        boss.from_altar = from_altar

        if final:
            world.announce("THE WARCHIEF STIRS", 4.0)
            world.camera.add_trauma(1.0)
        else:
            world.announce(
                f"{archetype.label} {_roman(self.boss_number)} awakens!" if not from_altar
                else f"You have summoned the {archetype.label}!"
            )
            world.camera.add_trauma(0.55)
        return boss

    def recycle_strays(self, world):
        """Re-ring enemies that wandered too far instead of letting them pile up.

        The old build never removed anything, so stuck or abandoned enemies
        accumulated for the whole run and dragged the frame rate down.
        """
        player_pos = world.player.pos
        for enemy in world.enemies:
            if enemy.is_boss or enemy.elite:
                continue
            if enemy.pos.distance_to(player_pos) > DESPAWN_DISTANCE:
                new_pos = self.ring_position(world.arena, player_pos)
                if new_pos is not None:
                    enemy.pos.update(new_pos)
                else:
                    enemy.kill()

    def _check_unlocks(self):
        for archetype in ARCHETYPES.values():
            if archetype.weight <= 0 or archetype.unlock_time <= 0:
                continue
            if archetype.key in self.announced:
                continue
            if self.elapsed >= archetype.unlock_time:
                self.announced.add(archetype.key)
                self.pending_announcements.append(f"{archetype.label}s have joined the hunt!")


def _roman(n):
    numerals = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
    return numerals[n] if n < len(numerals) else str(n)
