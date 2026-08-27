"""The live run: everything that exists while you are playing.

Enemy queries go through a spatial hash rebuilt once per frame: with 280
enemies on the field, a range query that scanned everything would be 280 checks
in interpreted Python, and bucketing by 64px cells cuts that to a handful.

Separation is the exception and now runs all-pairs through numpy — see
``_apply_separation`` for why the usual argument inverts once the arithmetic
leaves the interpreter.
"""

import math
import random

import numpy
import pygame

from . import audio
from . import settings
from .arena import Arena, Camera
from .config import (
    ALTAR_GOLD_BONUS,
    BOSS_COIN_VALUE,
    CHEST_BASE_COST,
    CHEST_COST_GROWTH,
    CHEST_FIRST_DELAY,
    CHEST_INTERACT_RADIUS,
    CHEST_INTERVAL,
    CHEST_MAX_DISTANCE,
    CHEST_MIN_DISTANCE,
    TILE_SIZE,
    ELITE_MAGNET_CHANCE,
    ELITE_POTION_CHANCE,
    MAGNET_DROP_CHANCE,
    MAX_CHESTS,
    POTION_DROP_CHANCE,
    POTION_HEAL_FRACTION,
    COIN_DROP_CHANCE,
    COIN_VALUE,
    COL_GOLD,
    ELITE_COIN_VALUE,
    ENEMY_SEPARATION_FORCE,
    ENEMY_SEPARATION_RADIUS,
    MAX_DT,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPATIAL_CELL,
)
from . import maps
from .effects import EffectSystem
from .entities import Altar, Chest, Coin, Gem, Magnet, Player, Portal, Potion
from .spawner import Director
from .upgrades import roll_chest_reward
from .weapons import STARTING_WEAPON, WEAPONS_BY_KEY

ALTAR_INTERACT_RADIUS = 110.0
PORTAL_INTERACT_RADIUS = 90.0
ALTAR_RESPAWN_DELAY = 50.0
MAX_DAMAGE_NUMBERS = 26
# Kiting leaves a trail of gems you never double back for — a long run otherwise
# accumulates 500+ of them, all being updated every frame. Past this many, the
# most distant ones fuse into a single richer gem so no experience is lost.
MAX_PICKUPS = 200


class World:
    def __init__(self, meta, seed=None, starting_weapon=None, map_key=None, carry=None):
        """``carry`` is the world you just stepped out of.

        Travelling continues the run rather than restarting it: the same player,
        the same elapsed time, the same escalating chest prices. Only the ground
        under your feet changes, which is the whole point of the portal.
        """
        self.rng = random.Random(seed)
        self.map_def = maps.MAPS_BY_KEY.get(map_key or maps.DEFAULT_MAP, maps.GREENWOOD)
        self.arena = Arena(random.Random(self.rng.random()), self.map_def)
        self.camera = Camera()
        self.effects = EffectSystem(self.rng)
        self.director = Director(self.rng)

        if carry is not None:
            self.player = carry.player
            self.player.pos.update(self.arena.center)
            self.player.knockback.update(0, 0)
            self.player.iframes = 2.0          # a moment to read the new arena
        else:
            self.player = Player(self.arena.center, meta=meta)
            chosen = WEAPONS_BY_KEY.get(starting_weapon or STARTING_WEAPON,
                                        WEAPONS_BY_KEY[STARTING_WEAPON])
            self.player.weapons.append(chosen())

        self.enemies = []
        self.enemy_projectiles = []
        self.player_projectiles = []
        self.pickups = []

        self.altar = Altar(self.arena.random_open_point(self.player.pos, 500))
        self.altar_cooldown = 0.0

        self.chests = []
        self.chests_opened = 0
        self.chest_timer = CHEST_FIRST_DELAY

        self.portal = None
        self.travelling_to = None      # set when the player steps through
        self.maps_cleared = 0

        self.announcement = ""
        self.announcement_timer = 0.0

        self.finished = False
        self.victory = False
        self.result = None
        self._grid = {}

        if carry is not None:
            # Difficulty is a function of elapsed time, so it has to follow you
            # through. Chest prices too, or the new map would reset the economy.
            self.director.elapsed = carry.director.elapsed
            self.director.boss_number = carry.director.boss_number
            self.director.announced = set(carry.director.announced)
            self.chests_opened = carry.chests_opened
            self.maps_cleared = carry.maps_cleared + 1
            self.announce(f"You step into {self.map_def.phrase}.", 3.0)

        self.director.opening_wave(self)

    def apply_map_modifiers(self, enemy):
        """Scale a freshly spawned enemy by whatever this map does to them.

        Applied after construction rather than threaded through ``Enemy`` so the
        constructor does not grow a parameter every time a map wants to tweak
        something new.
        """
        spec = self.map_def
        if spec.enemy_health_mult != 1.0:
            enemy.max_health *= spec.enemy_health_mult
            enemy.health = enemy.max_health
        if spec.enemy_speed_mult != 1.0:
            enemy.speed *= spec.enemy_speed_mult
        if spec.xp_mult != 1.0:
            enemy.xp_value *= spec.xp_mult

    # -- announcements -------------------------------------------------------
    def announce(self, text, duration=2.4):
        self.announcement = text
        self.announcement_timer = duration

    # -- spatial hash --------------------------------------------------------
    def _rebuild_grid(self):
        self._grid = {}
        for enemy in self.enemies:
            key = (int(enemy.pos.x) // SPATIAL_CELL, int(enemy.pos.y) // SPATIAL_CELL)
            self._grid.setdefault(key, []).append(enemy)

    def enemies_near(self, pos, radius):
        """Enemies whose cell overlaps a box of ``radius`` around ``pos``."""
        cell_range = int(radius // SPATIAL_CELL) + 1
        cx, cy = int(pos[0]) // SPATIAL_CELL, int(pos[1]) // SPATIAL_CELL
        found = []
        for dy in range(-cell_range, cell_range + 1):
            for dx in range(-cell_range, cell_range + 1):
                bucket = self._grid.get((cx + dx, cy + dy))
                if bucket:
                    found.extend(bucket)
        return found

    def nearest_enemy(self, pos, max_dist=None, exclude=None):
        best = None
        best_dist_sq = float("inf") if max_dist is None else max_dist * max_dist
        for enemy in self.enemies:
            if exclude and id(enemy) in exclude:
                continue
            dist_sq = (enemy.pos.x - pos[0]) ** 2 + (enemy.pos.y - pos[1]) ** 2
            if dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best = enemy
        return best

    # -- combat --------------------------------------------------------------
    def damage_enemy(self, enemy, amount, source_pos=None, knockback=140.0,
                     weapon_key=None, can_crit=True):
        if not enemy.alive:
            return 0.0

        player = self.player
        # Damage-over-time ticks do not roll crits: a burn critting every half
        # second turns the number stream into confetti and makes the DPS of an
        # elemental build impossible to read off the summary screen.
        crit = can_crit and self.rng.random() < player.crit_chance
        total = amount * player.damage_mult * (player.crit_damage if crit else 1.0)

        enemy.take_damage(total, knockback_from=source_pos, knockback_force=knockback)
        # Bosses get their own deeper impact so a Warden never sounds like a scout.
        audio.play("boss_hurt" if enemy.is_boss else ("crit" if crit else "hit"))
        player.damage_dealt += total
        if weapon_key:
            player.damage_by_weapon[weapon_key] = player.damage_by_weapon.get(weapon_key, 0.0) + total

        # Throttle the number stream so a 200-enemy screen stays readable. Crits
        # get more headroom than regular hits, but not an unlimited pass.
        budget = MAX_DAMAGE_NUMBERS * (2 if crit else 1)
        if settings.current.damage_numbers and len(self.effects.texts) < budget:
            self.effects.damage_number(enemy.pos + pygame.Vector2(0, -enemy.radius), total, crit)

        if not enemy.alive:
            self.on_enemy_death(enemy)
        return total

    def on_enemy_death(self, enemy):
        player = self.player
        luck = player.drop_mult          # scales every optional drop below
        player.kills += 1
        key = enemy.archetype.key
        player.kills_by_type[key] = player.kills_by_type.get(key, 0) + 1
        if enemy.elite:
            player.elite_kills += 1
        self.pickups.append(Gem(enemy.pos, enemy.xp_value))
        audio.play("boom" if enemy.is_boss else "kill")

        if enemy.is_boss:
            self.pickups.append(Coin(enemy.pos, BOSS_COIN_VALUE))
            self.effects.burst(enemy.pos, (255, 190, 120), count=34, speed=340, life=0.7, radius=6)
            self.effects.notice(enemy.pos, "WARDEN FELLED", COL_GOLD, size=40)
            self.camera.add_trauma(0.6)
            player.heal(player.max_health * 0.25)
            if enemy.archetype.is_final:
                self._win(enemy.pos)          # stops the music for the fanfare
            elif getattr(enemy, "from_altar", False):
                self._open_portal(enemy.pos)
                audio.music_for_map(self.map_def.key)
        elif enemy.elite:
            self.pickups.append(Coin(enemy.pos, ELITE_COIN_VALUE))
            self.effects.burst(enemy.pos, (255, 150, 150), count=16, speed=250, life=0.45, radius=5)
            self.camera.add_trauma(0.14)
        else:
            if self.rng.random() < COIN_DROP_CHANCE * luck:
                self.pickups.append(Coin(enemy.pos, COIN_VALUE))
            if len(self.effects.particles) < 260:
                self.effects.burst(enemy.pos, (220, 120, 120), count=5, speed=170, life=0.28, radius=3)

        tough = enemy.elite or enemy.is_boss
        if self.rng.random() < (ELITE_POTION_CHANCE if tough else POTION_DROP_CHANCE) * luck:
            self.pickups.append(Potion(enemy.pos, POTION_HEAL_FRACTION))
        if self.rng.random() < (ELITE_MAGNET_CHANCE if tough else MAGNET_DROP_CHANCE) * luck:
            self.pickups.append(Magnet(enemy.pos))

    # -- update --------------------------------------------------------------
    def update(self, dt, move_input, interact=False):
        dt = min(dt, MAX_DT)

        self.director.update(dt, self)
        for text in self.director.pending_announcements:
            self.announce(text)
        self.director.pending_announcements.clear()

        self.announcement_timer = max(0.0, self.announcement_timer - dt)

        self.player.update(dt, move_input, self.arena)
        self.camera.update(self.player.pos, dt, self.rng,
                           (self.arena.width, self.arena.height))

        self._rebuild_grid()
        self._update_aim()
        self._apply_separation()

        for enemy in self.enemies:
            enemy.update(dt, self.player.pos, self.arena, self.enemy_projectiles, self.rng)

        self._tick_statuses(dt)

        for weapon in self.player.weapons:
            weapon.update(dt, self)

        self._update_player_projectiles(dt)
        self._update_enemy_projectiles(dt)
        self._resolve_contact_damage()
        self._update_pickups(dt)
        self._update_interactables(dt, interact)

        self.effects.update(dt)

        self.enemies = [e for e in self.enemies if e.alive]

        if self.player.health <= 0 and not self.victory:
            self._handle_death()

    def _update_aim(self):
        player = self.player
        target = self.nearest_enemy(player.pos, max_dist=560)
        if target is not None:
            offset = target.pos - player.pos
            if offset.length_squared() > 0.01:
                player.aim = offset.normalize()
                return
        player.aim = pygame.Vector2(player.facing)

    def _tick_statuses(self, dt):
        """Advance burn/poison/chill on every afflicted enemy.

        Ticking lives here rather than on the enemy because a damage-over-time
        kill has to run the whole death path — drops, particles, kill counts —
        which only the world knows how to do.
        """
        for enemy in self.enemies:
            if not enemy.statuses:
                continue
            for key in list(enemy.statuses):
                status = enemy.statuses[key]
                status.remaining -= dt

                if status.dps > 0:
                    status.tick_timer -= dt
                    while status.tick_timer <= 0 and enemy.alive:
                        status.tick_timer += status.interval
                        self.damage_enemy(
                            enemy, status.dps * status.interval,
                            knockback=0.0, weapon_key=status.weapon_key, can_crit=False,
                        )

                if status.remaining <= 0 or not enemy.alive:
                    enemy.statuses.pop(key, None)

    def _apply_separation(self):
        """Push overlapping enemies apart so the horde spreads into a wall.

        Without this they all converge on the exact same point and stack into a
        single-file line, which is why the old build never felt like a swarm.

        This is all-pairs, which sounds like a step backwards from the spatial
        hash it replaces — and in Python it would be. The point is that the
        comparison changes completely once the arithmetic leaves Python: the
        hash existed to avoid ~45,000 *interpreted* distance checks, and numpy
        does the same 45,000 in compiled code faster than Python can walk the
        buckets that avoid them. Profiling put the bucketed version at 26% of
        the whole update, the largest single cost in the simulation.

        Two things make this safe rather than merely fast. Separation radius is
        30px against 64px cells, so the old 3x3 neighbourhood already covered
        every pair inside the radius — all-pairs computes the same set, not a
        different one, and the selftest asserts the two agree. And MAX_ENEMIES
        caps the field at 280, so the N-by-N intermediates top out near 1MB;
        this would need rethinking as a chunked or hashed version if that cap
        ever rose into the thousands.

        The hash itself stays — ``enemies_near`` and ``nearest_enemy`` still
        depend on it, and those are genuine range queries where it earns its
        keep.
        """
        enemies = self.enemies
        count = len(enemies)
        if count < 2:
            return

        radius = ENEMY_SEPARATION_RADIUS
        force = ENEMY_SEPARATION_FORCE

        # fromiter with an explicit count fills the buffer directly instead of
        # building a throwaway list of tuples first.
        positions = numpy.fromiter(
            (value for enemy in enemies for value in (enemy.pos.x, enemy.pos.y)),
            dtype=numpy.float32, count=count * 2,
        ).reshape(count, 2)

        offset_x = positions[:, 0, None] - positions[None, :, 0]
        offset_y = positions[:, 1, None] - positions[None, :, 1]
        distance_sq = offset_x * offset_x + offset_y * offset_y

        # The lower bound also excludes each enemy's distance to itself, which
        # is what the ``other is enemy`` check used to do.
        within = (distance_sq > 0.0001) & (distance_sq < radius * radius)
        distance = numpy.sqrt(distance_sq, where=within,
                              out=numpy.ones_like(distance_sq))
        scale = numpy.where(within, (1.0 - distance / radius) * force / distance, 0.0)

        push_x = (offset_x * scale).sum(axis=1)
        push_y = (offset_y * scale).sum(axis=1)

        # Clamp each push to the force cap, as the per-enemy scale_to_length did.
        magnitude = numpy.hypot(push_x, push_y)
        limit = numpy.where(magnitude > force, force / numpy.maximum(magnitude, 1e-6), 1.0)
        push_x *= limit
        push_y *= limit

        # tolist() converts the whole array to Python floats in one pass;
        # indexing numpy scalars one at a time is markedly slower.
        for enemy, x, y in zip(enemies, push_x.tolist(), push_y.tolist()):
            enemy.separation.update(x, y)

    def _update_player_projectiles(self, dt):
        for projectile in self.player_projectiles:
            if projectile.homing:
                target = self.nearest_enemy(projectile.pos, max_dist=420)
                projectile.steer_toward(target.pos if target else None, dt)

            projectile.update(dt, self.arena)
            if not projectile.alive:
                # Died to a wall or to old age — still detonates if it detonates.
                projectile.impact(self)
                continue

            for enemy in self.enemies_near(projectile.pos, projectile.radius + 40):
                if not enemy.alive or id(enemy) in projectile.hit:
                    continue
                if projectile.pos.distance_to(enemy.pos) <= projectile.radius + enemy.radius:
                    self.damage_enemy(enemy, projectile.damage, source_pos=projectile.pos,
                                      knockback=projectile.knockback,
                                      weapon_key=projectile.weapon_key)
                    if projectile.status is not None and enemy.alive:
                        enemy.apply_status(projectile.status)
                    if not projectile.on_hit(enemy):
                        projectile.impact(self)
                        break

        self.player_projectiles = [p for p in self.player_projectiles if p.alive]

    def _update_enemy_projectiles(self, dt):
        player = self.player
        for projectile in self.enemy_projectiles:
            projectile.update(dt, self.arena)
            if not projectile.alive:
                continue
            # The old build ran this collision and then threw the result away, so
            # every Sentinel, Guardian and Boss shot was purely decorative.
            if projectile.pos.distance_to(player.pos) <= projectile.radius + player.radius:
                dealt = player.take_damage(projectile.damage, projectile.pos)
                if dealt:
                    audio.play("hurt")
                    self.camera.add_trauma(0.2)
                    self.effects.burst(player.pos, (255, 120, 90), count=8, speed=200)
                projectile.kill()

        self.enemy_projectiles = [p for p in self.enemy_projectiles if p.alive]

    def _resolve_contact_damage(self):
        player = self.player
        if player.iframes > 0:
            return
        for enemy in self.enemies_near(player.pos, player.radius + 60):
            if not enemy.alive:
                continue
            if player.pos.distance_to(enemy.pos) <= player.radius + enemy.radius * 0.85:
                dealt = player.take_damage(enemy.contact_damage, enemy.pos)
                if dealt:
                    audio.play("hurt")
                    self.camera.add_trauma(0.22 + min(0.3, dealt / 90))
                    self.effects.burst(player.pos, (255, 100, 90), count=9, speed=220)
                break

    def _update_pickups(self, dt):
        player = self.player
        for pickup in self.pickups:
            if pickup.update(dt, player):
                pickup.kill()
                if isinstance(pickup, Gem):
                    player.gain_xp(pickup.xp_value)
                    audio.play("gem")
                elif isinstance(pickup, Potion):
                    healed = player.heal(player.max_health * pickup.heal_fraction)
                    if healed:
                        self.effects.heal_number(player.pos, healed)
                    audio.play("potion")
                elif isinstance(pickup, Magnet):
                    self._magnetise_all_drops()
                    audio.play("magnet")
                else:
                    player.gold += pickup.value
                    audio.play("coin")
        self.pickups = [p for p in self.pickups if p.alive]
        if len(self.pickups) > MAX_PICKUPS:
            self._fuse_distant_pickups()

    def _magnetise_all_drops(self):
        """Flag every gem and coin as attracted; ``Pickup.update`` does the rest.

        ``attracted`` never resets, so this is genuinely all it takes — the drops
        stream in from wherever you abandoned them.

        Potions are deliberately left lying. Healing you can walk to when you
        actually need it is worth more than healing yanked into you at full
        health, and a magnet that wastes your potions would be a trap.
        """
        gems = coins = gold = 0
        for pickup in self.pickups:
            if isinstance(pickup, Gem):
                pickup.attracted = True
                gems += 1
            elif isinstance(pickup, Coin):
                pickup.attracted = True
                coins += 1
                gold += pickup.value

        summary = f"{gems} gems"
        if gold:
            summary += f"   {gold} gold"

        player = self.player
        # Lifted clear of the player, otherwise the drops streaming in bury it.
        self.effects.notice(player.pos + pygame.Vector2(0, -76),
                            f"MAGNET   {summary}", (214, 178, 255), size=36)
        self.effects.shockwave(player.pos, 620, (180, 140, 255), life=0.55)
        self.effects.burst(player.pos, (196, 150, 255), count=22, speed=320, life=0.5, radius=5)
        self.camera.add_trauma(0.2)
        return gems + coins

    def _fuse_distant_pickups(self):
        """Fuse the most distant drops of each kind into one richer drop.

        Gems and coins are handled separately so a screen full of uncollected
        coins cannot starve the gem pass and let the total drift over the cap.
        """
        player_pos = self.player.pos
        for kind in (Gem, Coin):
            excess = len(self.pickups) - MAX_PICKUPS
            if excess <= 0:
                return
            group = [p for p in self.pickups if type(p) is kind]
            if len(group) < 2:
                continue

            group.sort(key=lambda p: -p.pos.distance_to(player_pos))
            doomed = group[:min(excess + 1, len(group))]
            total = sum(p.amount for p in doomed)
            # Drop the fused pickup where the closest of them was, so it stays
            # reachable and none of its value is lost.
            anchor = min(doomed, key=lambda p: p.pos.distance_to(player_pos)).pos

            doomed_ids = {id(p) for p in doomed}
            self.pickups = [p for p in self.pickups if id(p) not in doomed_ids]
            self.pickups.append(kind(anchor, total))

    def _update_interactables(self, dt, interact):
        """Altars and chests both answer E, so they are resolved together.

        Whichever is nearer wins, otherwise standing between the two would fire
        both at once or silently favour whichever happened to be checked first.
        """
        for chest in self.chests:
            chest.update(dt)
        if self.portal is not None:
            self.portal.update(dt)

        if self.altar is None:
            self.altar_cooldown -= dt
            if self.altar_cooldown <= 0:
                self.altar = Altar(self.arena.random_open_point(self.player.pos, 600))
        else:
            self.altar.update(dt)

        self.chest_timer -= dt
        if self.chest_timer <= 0:
            self.chest_timer = CHEST_INTERVAL
            self._spawn_chest()

        if not interact:
            return

        target = self.nearest_interactable()
        if target is None:
            return
        kind, thing = target
        if kind == "altar":
            self._use_altar()
        elif kind == "portal":
            self.travelling_to = thing.destination
        else:
            self._open_chest(thing)

    def _win(self, pos):
        """The Warchief falls and the run ends as a win, not a death."""
        # Clear the summon banner first — it is still on screen if the fight was
        # short, and the two headlines collide.
        self.announcement_timer = 0.0
        audio.stop_music()
        audio.play("victory")
        self.effects.notice(pos, "THE WARCHIEF FALLS", (196, 250, 255), size=46)
        self.effects.shockwave(pos, 620, (140, 220, 255), life=0.9)
        self.effects.burst(pos, (196, 250, 255), count=60, speed=460, life=1.0, radius=7)
        self.camera.add_trauma(1.0)
        self.victory = True
        self.finished = True
        self.result = self.build_result()

    def _open_portal(self, pos):
        """The summoned Warden's death tears the way onward."""
        if self.portal is not None:
            return                       # one exit per map
        if not self.map_def.has_exit:
            self.announce("Nothing lies beyond the Cinderwaste. Yet.", 3.0)
            return

        destination = maps.MAPS_BY_KEY[self.map_def.next_map]
        self.portal = Portal(pygame.Vector2(pos), destination.key)
        audio.play("portal_open")
        self.effects.shockwave(pos, 340, (170, 130, 240), life=0.7)
        self.effects.burst(pos, (180, 140, 255), count=30, speed=340, life=0.7, radius=6)
        self.camera.add_trauma(0.5)
        self.announce(f"A portal to {destination.phrase} tears open!", 3.2)

    def nearest_interactable(self):
        """The altar or chest the player would activate, with its distance."""
        player_pos = self.player.pos
        best = None
        best_distance = float("inf")

        if self.altar is not None:
            distance = player_pos.distance_to(self.altar.pos)
            if distance <= ALTAR_INTERACT_RADIUS:
                best, best_distance = ("altar", self.altar), distance

        for chest in self.chests:
            distance = player_pos.distance_to(chest.pos)
            if distance <= CHEST_INTERACT_RADIUS and distance < best_distance:
                best, best_distance = ("chest", chest), distance

        if self.portal is not None:
            distance = player_pos.distance_to(self.portal.pos)
            if distance <= PORTAL_INTERACT_RADIUS and distance < best_distance:
                best, best_distance = ("portal", self.portal), distance

        return best

    def _use_altar(self):
        self.director.spawn_boss(self, from_altar=True)
        audio.play("altar")
        audio.play("boss_roar")
        # Summoning is the one fight you choose to start, so it gets its own
        # music. Wave bosses do not: they arrive on a timer, and swapping the
        # track for something you did not opt into reads as a glitch.
        audio.play_music("boss")
        self.player.gold += ALTAR_GOLD_BONUS
        self.effects.notice(self.altar.pos, f"+{ALTAR_GOLD_BONUS} gold", COL_GOLD, size=30)
        self.altar = None
        self.altar_cooldown = ALTAR_RESPAWN_DELAY

    def next_chest_cost(self):
        return int(CHEST_BASE_COST * (CHEST_COST_GROWTH ** self.chests_opened))

    def _spawn_chest(self):
        """Place a chest in a ring around the player: near enough to be worth
        the detour, far enough that it costs you something to go and get it.

        Picking a random point anywhere in the arena and rejecting the far ones
        almost never lands a hit — the arena is 4400x2800, so nearly every
        random point is well past the maximum useful distance.
        """
        if len(self.chests) >= MAX_CHESTS:
            return

        probe = pygame.Rect(0, 0, TILE_SIZE + 12, TILE_SIZE + 12)
        for _ in range(24):
            angle = self.rng.uniform(0, 360)
            distance = self.rng.uniform(CHEST_MIN_DISTANCE, CHEST_MAX_DISTANCE)
            pos = self.player.pos + pygame.Vector2(distance, 0).rotate(angle)
            pos.x = max(TILE_SIZE * 2, min(pos.x, self.arena.width - TILE_SIZE * 2))
            pos.y = max(TILE_SIZE * 2, min(pos.y, self.arena.height - TILE_SIZE * 2))
            probe.center = (pos.x, pos.y)
            if not self.arena.rect_hits_wall(probe):
                self.chests.append(Chest(pos, self.next_chest_cost()))
                return

    def _open_chest(self, chest):
        player = self.player
        if player.gold < chest.cost:
            self.effects.notice(chest.pos, f"need {chest.cost - player.gold} more gold",
                                (230, 120, 110), size=24)
            return

        player.gold -= chest.cost
        player.gold_spent += chest.cost
        self.chests.remove(chest)
        self.chests_opened += 1

        audio.play("chest")
        reward = roll_chest_reward(player, self.rng)
        reward.apply(player)
        self.effects.notice(chest.pos, reward.title, reward.color, size=34)
        self.effects.burst(chest.pos, COL_GOLD, count=20, speed=260, life=0.5, radius=5)
        self.camera.add_trauma(0.12)
        self.announce(f"{reward.title} — {reward.detail}", 2.0)

        # Re-price the next one immediately so the prompt never lies.
        for remaining in self.chests:
            remaining.cost = self.next_chest_cost()

    def _handle_death(self):
        player = self.player
        if player.revives > 0:
            # Second Wind clears the screen and puts you back on your feet once.
            player.revives -= 1
            player.health = player.max_health
            player.iframes = 2.5
            for enemy in self.enemies:
                if not enemy.is_boss:
                    enemy.kill()
            self.enemies = [e for e in self.enemies if e.alive]
            self.camera.add_trauma(0.9)
            self.effects.notice(player.pos, "SECOND WIND", (255, 235, 140), size=44)
            self.announce("Second Wind!")
            return

        audio.stop_music()
        audio.play("death")
        self.finished = True
        self.result = self.build_result()

    def build_result(self):
        player = self.player
        return {
            "time": self.director.elapsed,
            "kills": player.kills,
            "level": player.level,
            "gold": player.gold,
            "damage": player.damage_dealt,
            "bosses": self.director.boss_number,
            "weapons": [(w.label, w.level) for w in player.weapons],
            "passives": sorted(player.passives.items()),
            "damage_by_weapon": [
                (w.label, player.damage_by_weapon.get(w.key, 0.0)) for w in player.weapons
            ],
            "kills_by_type": dict(player.kills_by_type),
            "elite_kills": player.elite_kills,
            "gold_spent": player.gold_spent,
            "chests_opened": self.chests_opened,
            "map": self.map_def.phrase,
            "maps_cleared": self.maps_cleared,
            "victory": self.victory,
        }

    # -- drawing -------------------------------------------------------------
    def draw(self, painter):
        camera = self.camera
        painter.fill((10, 10, 22))
        self.arena.draw(painter, camera)

        if self.altar is not None:
            self.altar.draw(painter, camera, self.player.pos)

        for chest in self.chests:
            chest.draw(painter, camera)

        for pickup in self.pickups:
            pickup.draw(painter, camera)

        for weapon in self.player.weapons:
            weapon.draw(painter, camera, self)

        # After the ground effects, not before them. A poison cloud or an earth
        # trail laid over the exit hid it completely, and the portal is the most
        # important thing on screen the moment it exists.
        if self.portal is not None:
            self.portal.draw(painter, camera)

        # Sort by y so things lower on screen overlap things above them.
        for enemy in sorted(self.enemies, key=lambda e: e.pos.y):
            enemy.draw(painter, camera)

        self.player.draw(painter, camera)

        for projectile in self.player_projectiles:
            projectile.draw(painter, camera)
        for projectile in self.enemy_projectiles:
            projectile.draw(painter, camera)

        self.effects.draw(painter, camera)
        self._draw_offscreen_markers(painter)

    def _draw_offscreen_markers(self, painter):
        """Edge arrows for things worth walking toward that are out of view."""
        targets = [(enemy.pos, (255, 90, 90)) for enemy in self.enemies if enemy.is_boss]
        # A chest you cannot see is a chest you will never open, and they spawn
        # deliberately far enough away to need a detour.
        targets += [(chest.pos, COL_GOLD) for chest in self.chests]
        # The altar gets a marker too — it gates the whole run, and hunting for
        # it across a 110x70 field was the single most common complaint.
        if self.altar is not None:
            targets.append((self.altar.pos, (150, 225, 240)))
        if self.portal is not None:
            targets.append((self.portal.pos, (180, 140, 255)))

        camera = self.camera
        margin = 44
        for world_pos, color in targets:
            sx, sy = camera.to_screen(world_pos)
            if margin <= sx <= SCREEN_WIDTH - margin and margin <= sy <= SCREEN_HEIGHT - margin:
                continue
            direction = pygame.Vector2(sx - SCREEN_WIDTH / 2, sy - SCREEN_HEIGHT / 2)
            if direction.length_squared() < 1:
                continue
            direction.normalize_ip()
            edge = pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2) + direction * min(
                SCREEN_WIDTH / 2 - margin, SCREEN_HEIGHT / 2 - margin
            )
            angle = math.degrees(math.atan2(direction.y, direction.x))
            points = [
                edge + pygame.Vector2(16, 0).rotate(angle),
                edge + pygame.Vector2(-10, 9).rotate(angle),
                edge + pygame.Vector2(-10, -9).rotate(angle),
            ]
            painter.polygon(color, points)
            painter.polygon((255, 245, 235), points, 2)
