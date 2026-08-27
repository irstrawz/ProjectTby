"""Weapons and player projectiles.

Weapons are objects with a level, not a pile of ``has_x`` flags and ``lvl_x``
counters on the player. Adding a sixth weapon is now one class plus one entry in
``WEAPON_TYPES`` — the upgrade pool picks it up automatically.
"""

import math

import pygame

from . import audio
from .entities import Entity
from .status import BURN, CHILL, POISON, StatusSpec

# Level every ingredient must reach before its fusion is offered.
#
# A stated design decision rather than a side effect of per-weapon tuning, and
# the four ingredient classes take their ``max_level`` from it. That coupling is
# deliberate: a fusion offer replaces the entire pool once earned, so an
# ingredient allowed to level *past* this number could never actually do it —
# every level-up from here on shows the fusion instead. Capping at the threshold
# means no unreachable levels by construction.
#
# ``_validate_evolutions`` asserts every ingredient can reach it, so lowering a
# cap below this fails loudly rather than silently deleting a fusion from the
# game.
#
# Tried at 10; measured across 20 paired seeds, that took runs reaching a fusion
# from 1-in-20 to 0-in-20, because a fusion-hunting bot needs about 257s to get
# one weapon to level 10 and runs end around 135s. At 8 it is roughly 145s,
# which is at least in reach of a good run.
FUSION_LEVEL = 8


class PlayerProjectile(Entity):
    def __init__(self, pos, direction, speed, damage, pierce=0, color=(90, 190, 255),
                 radius=7, homing=0.0, life=2.5, knockback=140.0, weapon_key=None,
                 status=None):
        super().__init__(pos, radius * 2)
        self.vel = pygame.Vector2(direction) * speed
        self.speed = speed
        self.damage = damage
        self.pierce = pierce
        self.color = color
        self.draw_radius = radius
        self.homing = homing          # degrees per second of steering
        self.life = life
        self.knockback = knockback
        self.weapon_key = weapon_key
        self.status = status          # StatusSpec applied on hit, if any
        self.hit = set()

    def steer_toward(self, target_pos, dt):
        if not self.homing or target_pos is None:
            return
        desired = target_pos - self.pos
        if desired.length_squared() < 1:
            return
        current_angle = math.degrees(math.atan2(self.vel.y, self.vel.x))
        target_angle = math.degrees(math.atan2(desired.y, desired.x))
        diff = (target_angle - current_angle + 180) % 360 - 180
        turn = max(-self.homing * dt, min(self.homing * dt, diff))
        self.vel = self.vel.rotate(turn)

    def update(self, dt, arena):
        self.pos += self.vel * dt
        self.life -= dt
        if self.life <= 0 or arena.is_wall_point(self.pos.x, self.pos.y):
            self.kill()

    def on_hit(self, enemy):
        """Return True if the projectile should keep going."""
        self.hit.add(id(enemy))
        if self.pierce > 0:
            self.pierce -= 1
            return True
        self.kill()
        return False

    def impact(self, world):
        """Called once when the projectile stops, for splash and similar."""

    def draw(self, painter, camera):
        sx, sy = camera.to_screen(self.pos)
        painter.circle(self.color, (int(sx), int(sy)), self.draw_radius)
        painter.circle((240, 250, 255), (int(sx), int(sy)), max(1, self.draw_radius // 3))


class ThrustProjectile(PlayerProjectile):
    """A short piercing lance that expires after a fixed travel distance."""

    def __init__(self, pos, direction, speed, damage, length, max_travel, weapon_key=None):
        super().__init__(pos, direction, speed, damage, pierce=99,
                         color=(225, 230, 255), radius=6, life=1.2, knockback=70.0,
                         weapon_key=weapon_key)
        self.length = length
        self.size = max(16, int(length * 0.5))
        self.traveled = 0.0
        self.max_travel = max_travel
        base = pygame.Surface((length, 9), pygame.SRCALPHA)
        pygame.draw.rect(base, (235, 238, 255, 225), (0, 0, length, 9), border_radius=4)
        pygame.draw.rect(base, (150, 175, 235, 255), (0, 0, length, 9), 1, border_radius=4)
        angle = math.degrees(math.atan2(-direction.y, direction.x))
        self.image = pygame.transform.rotate(base, angle)

    def update(self, dt, arena):
        super().update(dt, arena)
        self.traveled += self.speed * dt
        if self.traveled >= self.max_travel:
            self.kill()

    def draw(self, painter, camera):
        painter.blit(self.image, self.image.get_rect(center=camera.to_screen(self.pos)))


# ---------------------------------------------------------------------------
# Weapons
# ---------------------------------------------------------------------------

class Weapon:
    key = "weapon"
    label = "Weapon"
    description = "Does something"
    max_level = 8
    color = (220, 220, 220)
    evolved = False          # fusions set this; they are never offered directly

    # Cue played when this weapon fires, or None for silence. Silence is the
    # right answer for anything continuous — an aura that ticks twice a second
    # and a beam that never stops sweeping would each become a drone you cannot
    # switch off, and with six weapons equipped the drones stack. Those weapons
    # are audible through the enemies they kill instead.
    sound = None

    def __init__(self):
        self.level = 1
        self.timer = 0.0

    def upgrade_text(self):
        """What the next level gives. Shown on the level-up card."""
        return "Improve this weapon"

    def cooldown(self, player):
        return self.base_cooldown * player.cooldown_mult

    def shot_count(self, world, base=None):
        """This weapon's instance count, including the global Volley bonus.

        Read at fire time rather than folded into each weapon's ``count``
        property, because those properties have no access to the player and
        threading one through all sixteen would be a far wider change than the
        feature deserves. Weapons that fire nothing countable — beams, arcs,
        ground trails — simply never call this.
        """
        base = self.count if base is None else base
        return base + world.player.bonus_projectiles

    def update(self, dt, world):
        self.timer -= dt
        if self.timer <= 0:
            self.fire(world)
            # One hook covers every weapon that fires on a timer. The three that
            # override update() and never call fire() — Warding Sigils, Poison
            # Aura, Radiant Beam — are precisely the continuous ones that should
            # stay silent, so the structure of the class hierarchy already draws
            # the line in the right place.
            if self.sound:
                audio.play(self.sound)
            self.timer = self.cooldown(world.player)

    def fire(self, world):
        raise NotImplementedError

    def draw(self, painter, camera, world):
        pass


class Sword(Weapon):
    key = "sword"
    sound = "slash"
    label = "Short Sword"
    description = "Slashes an arc in the direction you are facing."
    max_level = 8
    color = (240, 228, 195)
    base_cooldown = 0.75

    def __init__(self):
        super().__init__()
        self.slashes = []          # [angle_center, arc, reach, life, max_life]

    @property
    def damage(self):
        return 34 + 10 * (self.level - 1)

    @property
    def reach(self):
        return 105 + 8 * (self.level - 1)

    @property
    def arc(self):
        return 150 + 9 * (self.level - 1)

    def cooldown(self, player):
        return max(0.26, (self.base_cooldown - 0.05 * (self.level - 1))) * player.cooldown_mult

    def upgrade_text(self):
        bits = ["+10 damage", "+8 reach", "wider arc", "faster swing"]
        if self.level + 1 == 5:
            bits.append("adds a backswing")
        return ", ".join(bits)

    def fire(self, world):
        player = world.player
        # Aim, not movement facing: you spend this genre running away from things,
        # so a swing locked to your travel direction would hit nothing but air.
        aim_angle = math.degrees(math.atan2(player.aim.y, player.aim.x))
        angles = [aim_angle]
        if self.level >= 5:
            angles.append(aim_angle + 180)   # backswing covers your rear

        for angle in angles:
            self.slashes.append([angle, self.arc, self.reach, 0.18, 0.18])
            self._strike(world, angle)

    def _strike(self, world, center_angle):
        player = world.player
        reach_sq = (self.reach + 20) ** 2
        half_arc = self.arc * 0.5

        for enemy in world.enemies_near(player.pos, self.reach + 40):
            offset = enemy.pos - player.pos
            if offset.length_squared() > reach_sq:
                continue
            angle = math.degrees(math.atan2(offset.y, offset.x))
            if abs((angle - center_angle + 180) % 360 - 180) <= half_arc:
                world.damage_enemy(enemy, self.damage, source_pos=player.pos, knockback=200,
                                   weapon_key=self.key)

    def update(self, dt, world):
        super().update(dt, world)
        for slash in self.slashes:
            slash[3] -= dt
        self.slashes = [s for s in self.slashes if s[3] > 0]

    def draw(self, painter, camera, world):
        player = world.player
        origin = pygame.Vector2(camera.to_screen(player.pos))

        for center_angle, arc, reach, life, max_life in self.slashes:
            fade = max(0.0, life / max_life)
            steps = 14
            rim = [
                origin + pygame.Vector2(reach, 0).rotate(center_angle - arc / 2 + arc * i / steps)
                for i in range(steps + 1)
            ]
            points = [origin] + rim

            # Scratch surface sized to the arc, not the screen: a full 1280x720
            # SRCALPHA allocation per slash per frame is ~3.5MB of churn.
            bounds = pygame.Rect(min(p.x for p in points), min(p.y for p in points), 0, 0)
            bounds.width = max(p.x for p in points) - bounds.x + 2
            bounds.height = max(p.y for p in points) - bounds.y + 2
            if bounds.width < 1 or bounds.height < 1:
                continue

            scratch = pygame.Surface(bounds.size)
            local = [(p.x - bounds.x, p.y - bounds.y) for p in points]
            # Additive blending, so the slash reads as light on the dark floor
            # instead of a grey wash over it.
            pygame.draw.polygon(scratch, (int(120 * fade), int(104 * fade), int(46 * fade)), local)
            painter.blit(scratch, bounds.topleft, flags=pygame.BLEND_RGB_ADD)

            painter.lines((255, 245, 205), False,
                              [(p.x, p.y) for p in rim], max(1, int(3 * fade)))


class HomingBolts(Weapon):
    key = "bolts"
    sound = "shot"
    label = "Homing Bolts"
    description = "Fires seeking bolts at the nearest enemy."
    max_level = 8
    color = (90, 190, 255)
    base_cooldown = 0.7

    @property
    def damage(self):
        return 26 + 8 * (self.level - 1)

    @property
    def count(self):
        # Starts at two. A single bolt every 0.9s was by far the weakest opener
        # in the game, and it is now something you can pick at run start.
        return 2 + (self.level >= 4) + (self.level >= 7)

    @property
    def pierce(self):
        # Bolt count and pierce multiply together, so both scaling steeply put
        # this weapon 3x above everything else by level 8.
        return (self.level >= 3) + (self.level >= 6)

    def cooldown(self, player):
        return max(0.2, self.base_cooldown - 0.045 * (self.level - 1)) * player.cooldown_mult

    def upgrade_text(self):
        next_level = self.level + 1
        bits = ["+8 damage", "faster fire rate"]
        if next_level in (4, 7):
            bits.append("+1 bolt")
        if next_level in (3, 6):
            bits.append("+1 pierce")
        return ", ".join(bits)

    def fire(self, world):
        player = world.player
        target = world.nearest_enemy(player.pos)
        if target is None:
            return
        base = target.pos - player.pos
        if base.length_squared() < 1:
            return
        base = base.normalize()

        count = self.shot_count(world)
        for i in range(count):
            spread = (i - (count - 1) / 2) * 13
            world.player_projectiles.append(
                PlayerProjectile(
                    player.pos, base.rotate(spread), 430, self.damage,
                    pierce=self.pierce, color=self.color, radius=7, homing=260,
                    weapon_key=self.key,
                )
            )


class Rapier(Weapon):
    key = "rapier"
    sound = "slash"
    label = "Rapier"
    description = "Rapid piercing thrusts fanning out ahead of you."
    max_level = 8
    color = (185, 205, 240)
    base_cooldown = 0.75

    @property
    def damage(self):
        return 15 + 6 * (self.level - 1)

    @property
    def count(self):
        return 3 + (self.level >= 3) + (self.level >= 5) + (self.level >= 7)

    @property
    def length(self):
        return 55 + 8 * (self.level - 1)

    def cooldown(self, player):
        return max(0.2, self.base_cooldown - 0.06 * (self.level - 1)) * player.cooldown_mult

    def upgrade_text(self):
        bits = ["+5 damage", "+8 reach", "faster thrusts"]
        if self.level + 1 in (3, 5, 7):
            bits.append("+1 thrust")
        return ", ".join(bits)

    def fire(self, world):
        player = world.player
        base = pygame.Vector2(player.aim)
        if base.length_squared() < 0.001:
            base = pygame.Vector2(0, 1)

        count = self.shot_count(world)
        for i in range(count):
            spread = (i - (count - 1) / 2) * 19
            world.player_projectiles.append(
                ThrustProjectile(
                    player.pos, base.rotate(spread), 640, self.damage,
                    length=self.length, max_travel=self.length + 55,
                    weapon_key=self.key,
                )
            )


class WardingSigils(Weapon):
    key = "sigils"
    label = "Warding Sigils"
    description = "Orbiting wards that grind down anything you touch."
    max_level = 8
    color = (190, 140, 255)

    def __init__(self):
        super().__init__()
        self.angle = 0.0
        self.hit_cooldowns = {}     # id(enemy) -> seconds until it can be hit again

    @property
    def damage(self):
        return 22 + 9 * (self.level - 1)

    @property
    def count(self):
        return 2 + (self.level >= 2) + (self.level >= 4) + (self.level >= 6) + (self.level >= 8)

    @property
    def orbit_radius(self):
        # Barely grows. Pushing the orbit outward with level was actively making
        # the weapon worse — the wards swept past anything pressed against you
        # and only clipped a thin band at exactly that distance.
        return 80 + 3 * (self.level - 1)

    @property
    def orb_radius(self):
        """The wards themselves get fatter, which is what widens their coverage."""
        return 18 + 4 * (self.level - 1)

    @property
    def spin_speed(self):
        # An orbiting weapon only ever touches a thin annulus, so how *often* a
        # ward sweeps past is most of its damage.
        return 170 + 14 * (self.level - 1)

    def upgrade_text(self):
        bits = ["+9 damage", "larger wards", "faster spin"]
        if self.level + 1 in (2, 4, 6, 8):
            bits.append("+1 ward")
        return ", ".join(bits)

    def positions(self, player):
        # This one takes the player directly rather than the world, so it reads
        # the Volley bonus off the player instead of going through shot_count.
        count = self.count + player.bonus_projectiles
        return [
            player.pos + pygame.Vector2(self.orbit_radius, 0).rotate(self.angle + i * 360 / count)
            for i in range(count)
        ]

    def update(self, dt, world):
        self.angle = (self.angle + self.spin_speed * dt) % 360

        for key in list(self.hit_cooldowns):
            self.hit_cooldowns[key] -= dt
            if self.hit_cooldowns[key] <= 0:
                del self.hit_cooldowns[key]

        player = world.player
        orb_radius = self.orb_radius
        for orb_pos in self.positions(player):
            for enemy in world.enemies_near(orb_pos, orb_radius + 34):
                if id(enemy) in self.hit_cooldowns:
                    continue
                if orb_pos.distance_to(enemy.pos) <= orb_radius + enemy.radius:
                    world.damage_enemy(enemy, self.damage, source_pos=player.pos, knockback=160,
                                       weapon_key=self.key)
                    self.hit_cooldowns[id(enemy)] = 0.35

    def draw(self, painter, camera, world):
        radius = int(self.orb_radius)
        for orb_pos in self.positions(world.player):
            sx, sy = camera.to_screen(orb_pos)
            painter.circle((150, 100, 235), (int(sx), int(sy)), radius)
            painter.circle((225, 195, 255), (int(sx), int(sy)), radius, 2)
            painter.circle((245, 230, 255),
                               (int(sx) - radius // 4, int(sy) - radius // 3),
                               max(2, radius // 4))


CHAIN_FALLOFF = 0.82        # each jump lands a little softer than the last


class ArcCoilProjectile(PlayerProjectile):
    """A bolt that flies, then discharges into a chain where it lands."""

    def __init__(self, pos, direction, damage, chains, jump_range, weapon_key, color):
        super().__init__(pos, direction, speed=560, damage=damage, pierce=0,
                         color=color, radius=8, homing=300, life=2.0,
                         knockback=90.0, weapon_key=weapon_key)
        self.chains = chains
        self.jump_range = jump_range
        self.struck = None
        self.discharged = False
        self.spun = 0.0

    def update(self, dt, arena):
        super().update(dt, arena)
        self.spun += dt

    def on_hit(self, enemy):
        # Remember what we landed on: the chain starts from there, not from the
        # projectile's own position, so the arcs read as leaping between bodies.
        self.struck = enemy
        return super().on_hit(enemy)

    def impact(self, world):
        if self.discharged:
            return
        self.discharged = True

        if self.struck is None:
            # Fizzled against a wall or ran out of life; no chain.
            world.effects.burst(self.pos, self.color, count=5, speed=150, life=0.2, radius=3)
            return

        origin = pygame.Vector2(self.struck.pos)
        struck_ids = {id(self.struck)}
        damage = self.damage * CHAIN_FALLOFF

        for _ in range(self.chains):
            target = world.nearest_enemy(origin, max_dist=self.jump_range, exclude=struck_ids)
            if target is None:
                break
            world.effects.beam(origin, target.pos, self.color, life=0.16, width=4)
            world.effects.burst(target.pos, (200, 240, 255), count=4, speed=150,
                                life=0.22, radius=3)
            world.damage_enemy(target, damage, source_pos=origin, knockback=90,
                               weapon_key=self.weapon_key)
            struck_ids.add(id(target))
            origin = pygame.Vector2(target.pos)
            damage *= CHAIN_FALLOFF

    def draw(self, painter, camera):
        sx, sy = camera.to_screen(self.pos)
        jitter = math.sin(self.spun * 55) * 3
        painter.circle((140, 120, 30), (int(sx), int(sy)), 10)
        painter.circle(self.color, (int(sx + jitter), int(sy - jitter)), 7)
        painter.circle((255, 255, 235), (int(sx), int(sy)), 3)


class ArcCoil(Weapon):
    key = "coil"
    sound = "zap"
    label = "Arc Coil"
    description = "Hurls a bolt that leaps between nearby enemies where it lands."
    max_level = FUSION_LEVEL   # fusion ingredient (coil)
    color = (255, 245, 120)
    base_cooldown = 1.25

    @property
    def damage(self):
        return 36 + 12 * (self.level - 1)

    @property
    def count(self):
        """Bolts in the air. Capped at two — they multiply with the chain."""
        return 1 + (self.level >= 4)

    @property
    def chains(self):
        # One fewer than the old hitscan version: the bolt itself now lands a
        # direct hit before the chain starts, so total hits are unchanged.
        return 1 + self.level

    @property
    def jump_range(self):
        return 210 + 14 * (self.level - 1)

    def cooldown(self, player):
        return max(0.45, self.base_cooldown - 0.1 * (self.level - 1)) * player.cooldown_mult

    def upgrade_text(self):
        bits = ["+15 damage", "+1 chain", "longer jumps", "faster arcs"]
        if self.level + 1 == 4:
            bits.append("+1 bolt")
        return ", ".join(bits)

    def fire(self, world):
        player = world.player
        base = pygame.Vector2(player.aim)
        target = world.nearest_enemy(player.pos, max_dist=560)
        if target is not None:
            offset = target.pos - player.pos
            if offset.length_squared() > 1:
                base = offset.normalize()
        if base.length_squared() < 0.001:
            base = pygame.Vector2(0, 1)

        count = self.shot_count(world)
        for i in range(count):
            spread = (i - (count - 1) / 2) * 20
            world.player_projectiles.append(
                ArcCoilProjectile(
                    player.pos, base.rotate(spread), self.damage,
                    chains=self.chains, jump_range=self.jump_range,
                    weapon_key=self.key, color=self.color,
                )
            )


class FireballProjectile(PlayerProjectile):
    """Detonates on impact, damaging everything in a radius."""

    def __init__(self, pos, direction, speed, damage, splash_radius, splash_damage,
                 burn, weapon_key):
        super().__init__(pos, direction, speed, damage, pierce=0, color=(255, 150, 60),
                         radius=10, life=2.2, knockback=170.0, weapon_key=weapon_key,
                         status=burn)
        self.splash_radius = splash_radius
        self.splash_damage = splash_damage
        self.burn = burn
        self.spun = 0.0
        self.detonated = False

    def update(self, dt, arena):
        super().update(dt, arena)
        self.spun += dt

    def impact(self, world):
        if self.detonated:
            return
        self.detonated = True

        world.effects.burst(self.pos, (255, 170, 70), count=16,
                            speed=self.splash_radius * 3.4, life=0.34, radius=6)
        world.effects.shockwave(self.pos, self.splash_radius, (255, 160, 70))
        world.camera.add_trauma(0.07)

        for enemy in world.enemies_near(self.pos, self.splash_radius + 40):
            if not enemy.alive:
                continue
            distance = self.pos.distance_to(enemy.pos)
            if distance > self.splash_radius + enemy.radius:
                continue
            # Full damage at the centre, tapering to 45% at the rim.
            falloff = 1.0 - 0.55 * min(1.0, distance / max(1.0, self.splash_radius))
            world.damage_enemy(enemy, self.splash_damage * falloff, source_pos=self.pos,
                               knockback=180, weapon_key=self.weapon_key)
            if self.burn is not None and enemy.alive and world.rng.random() < self.burn_chance:
                enemy.apply_status(self.burn)

    # Set by the weapon at fire time so the roll uses the current level.
    burn_chance = 0.0

    def draw(self, painter, camera):
        sx, sy = camera.to_screen(self.pos)
        flicker = 9 + int(2 * math.sin(self.spun * 40))
        painter.circle((170, 50, 20), (int(sx), int(sy)), flicker + 3)
        painter.circle((255, 140, 50), (int(sx), int(sy)), flicker)
        painter.circle((255, 235, 170), (int(sx), int(sy)), max(2, flicker // 2))


class Fireball(Weapon):
    key = "fireball"
    sound = "cast"
    label = "Fireball"
    description = "Lobs a bomb that explodes for splash damage and sets things alight."
    max_level = 8
    color = (255, 150, 60)
    base_cooldown = 1.2

    @property
    def damage(self):
        return 34 + 12 * (self.level - 1)

    @property
    def splash_damage(self):
        return 44 + 16 * (self.level - 1)

    @property
    def splash_radius(self):
        return 78 + 7 * (self.level - 1)

    @property
    def burn_chance(self):
        return min(1.0, 0.30 + 0.09 * (self.level - 1))

    @property
    def burn_dps(self):
        return 12 + 6 * (self.level - 1)

    @property
    def count(self):
        return 1 + (self.level >= 4) + (self.level >= 7)

    def cooldown(self, player):
        return max(0.55, self.base_cooldown - 0.1 * (self.level - 1)) * player.cooldown_mult

    def upgrade_text(self):
        bits = ["+13 splash damage", "wider blast", "stronger burn"]
        if self.level + 1 in (4, 7):
            bits.append("+1 bomb")
        return ", ".join(bits)

    def burn_spec(self):
        return StatusSpec(key=BURN, duration=3.0, dps=self.burn_dps, interval=0.5,
                          weapon_key=self.key)

    def fire(self, world):
        player = world.player
        target = world.nearest_enemy(player.pos, max_dist=560)
        base = pygame.Vector2(player.aim)
        if target is not None:
            offset = target.pos - player.pos
            if offset.length_squared() > 1:
                base = offset.normalize()

        burn = self.burn_spec()
        count = self.shot_count(world)
        for i in range(count):
            spread = (i - (count - 1) / 2) * 16
            bomb = FireballProjectile(
                player.pos, base.rotate(spread), 380, self.damage,
                splash_radius=self.splash_radius, splash_damage=self.splash_damage,
                burn=burn, weapon_key=self.key,
            )
            bomb.burn_chance = self.burn_chance
            world.player_projectiles.append(bomb)


class PoisonAura(Weapon):
    key = "poison"
    label = "Poison Aura"
    description = "A constant cloud around you that corrodes anything standing in it."
    max_level = 8
    color = (130, 225, 95)

    def __init__(self):
        super().__init__()
        self.pulse = 0.0

    @property
    def damage(self):
        return 9 + 4 * (self.level - 1)

    @property
    def radius(self):
        return 108 + 13 * (self.level - 1)

    @property
    def tick_interval(self):
        return max(0.25, 0.6 - 0.04 * (self.level - 1))

    @property
    def poison_chance(self):
        return min(1.0, 0.25 + 0.08 * (self.level - 1))

    @property
    def poison_dps(self):
        return 8 + 4 * (self.level - 1)

    def upgrade_text(self):
        return "+4 damage, wider cloud, faster ticks, stronger poison"

    def update(self, dt, world):
        self.pulse += dt
        self.timer -= dt
        if self.timer > 0:
            return
        self.timer = self.tick_interval * world.player.cooldown_mult

        player = world.player
        radius = self.radius
        poison = StatusSpec(key=POISON, duration=3.5, dps=self.poison_dps, interval=0.5,
                            weapon_key=self.key)

        for enemy in world.enemies_near(player.pos, radius + 40):
            if not enemy.alive:
                continue
            if player.pos.distance_to(enemy.pos) <= radius + enemy.radius:
                world.damage_enemy(enemy, self.damage, knockback=0.0, weapon_key=self.key)
                if enemy.alive and world.rng.random() < self.poison_chance:
                    enemy.apply_status(poison)

    def draw(self, painter, camera, world):
        radius = int(self.radius)
        breath = 1.0 + 0.04 * math.sin(self.pulse * 2.4)
        size = int(radius * breath)
        cloud = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
        pygame.draw.circle(cloud, (70, 190, 80, 46), (size, size), size)
        pygame.draw.circle(cloud, (150, 240, 120, 96), (size, size), size, 3)
        painter.blit(cloud, cloud.get_rect(center=camera.to_screen(world.player.pos)))


class FrostOrb(Weapon):
    key = "frost"
    sound = "frost"
    label = "Frost Orb"
    description = "Wide orbs that chill everything they roll over, then linger."
    max_level = 8
    color = (120, 235, 255)
    base_cooldown = 1.9

    # Orbs are owned by the weapon rather than the world projectile list because
    # they damage an area continuously instead of colliding once.
    def __init__(self):
        super().__init__()
        self.orbs = []          # [pos, vel, travel_left, linger_left, hit_cooldowns]

    # Frost Orb is a control weapon, not a damage weapon. Its per-enemy hit
    # cooldown is the real throttle: at 0.4s, four large orbs re-hit a packed
    # swarm often enough to out-damage everything else in the game by 10x.
    hit_cooldown = 0.8

    @property
    def damage(self):
        return 28 + 9 * (self.level - 1)

    @property
    def orb_radius(self):
        return 44 + 4 * (self.level - 1)

    @property
    def count(self):
        return 1 + (self.level >= 3) + (self.level >= 5) + (self.level >= 7)

    @property
    def freezes(self):
        """The top rank stops things outright rather than just slowing them."""
        return self.level >= self.max_level

    @property
    def slow(self):
        return 1.0 if self.freezes else min(0.62, 0.28 + 0.05 * (self.level - 1))

    def cooldown(self, player):
        return max(0.65, self.base_cooldown - 0.14 * (self.level - 1)) * player.cooldown_mult

    def upgrade_text(self):
        if self.level + 1 == self.max_level:
            return "+8 damage, bigger orbs, and the chill becomes a full freeze"
        bits = ["+8 damage", "bigger orbs", "stronger slow", "faster casts"]
        if self.level + 1 in (3, 5, 7):
            bits.append("+1 orb")
        return ", ".join(bits)

    def fire(self, world):
        player = world.player
        base = pygame.Vector2(player.aim)
        if base.length_squared() < 0.001:
            base = pygame.Vector2(0, 1)

        count = self.shot_count(world)
        for i in range(count):
            spread = (i - (count - 1) / 2) * 26
            self.orbs.append({
                "pos": pygame.Vector2(player.pos),
                "vel": base.rotate(spread) * 330,
                "travel": 0.95,
                "linger": 0.5,
                "cooldowns": {},
            })

    def update(self, dt, world):
        super().update(dt, world)

        chill = StatusSpec(key=CHILL, duration=1.6 if self.freezes else 2.4,
                           slow=self.slow, weapon_key=self.key)
        radius = self.orb_radius

        for orb in self.orbs:
            if orb["travel"] > 0:
                orb["travel"] -= dt
                orb["pos"] += orb["vel"] * dt
                if orb["travel"] <= 0:
                    orb["vel"].update(0, 0)
            else:
                orb["linger"] -= dt

            cooldowns = orb["cooldowns"]
            for key in list(cooldowns):
                cooldowns[key] -= dt
                if cooldowns[key] <= 0:
                    del cooldowns[key]

            for enemy in world.enemies_near(orb["pos"], radius + 40):
                if not enemy.alive or id(enemy) in cooldowns:
                    continue
                if orb["pos"].distance_to(enemy.pos) <= radius + enemy.radius:
                    world.damage_enemy(enemy, self.damage, source_pos=orb["pos"],
                                       knockback=60, weapon_key=self.key)
                    if enemy.alive:
                        enemy.apply_status(chill)
                    cooldowns[id(enemy)] = self.hit_cooldown

        self.orbs = [o for o in self.orbs if o["linger"] > 0]

    def draw(self, painter, camera, world):
        radius = int(self.orb_radius)
        for orb in self.orbs:
            fade = 1.0 if orb["travel"] > 0 else max(0.25, orb["linger"] / 0.5)
            disc = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(disc, (90, 170, 255, int(60 * fade)), (radius, radius), radius)
            pygame.draw.circle(disc, (190, 235, 255, int(150 * fade)), (radius, radius), radius, 3)
            pygame.draw.circle(disc, (235, 250, 255, int(190 * fade)),
                               (radius, radius), max(3, radius // 4))
            painter.blit(disc, disc.get_rect(center=camera.to_screen(orb["pos"])))


def strongest_targets(world, origin, count, max_dist, exclude=None):
    """Pick the toughest distinct enemies in range.

    Targeting by remaining health rather than proximity gives single-hit
    weapons a niche the AOE weapons cannot fill: they answer the elite standing
    in the middle of the swarm instead of shaving the trash around it.
    """
    candidates = [
        (e, origin.distance_to(e.pos)) for e in world.enemies_near(origin, max_dist)
        if e.alive and (not exclude or id(e) not in exclude)
    ]
    # Distance breaks ties. Without it a screen full of equally-healthy trash
    # resolves in spatial-hash order, which clumps every strike into one far
    # corner instead of spreading them around the player.
    candidates = [(e, d) for e, d in candidates if d <= max_dist]
    candidates.sort(key=lambda item: (-item[0].health, item[1]))
    return [e for e, _ in candidates[:count]]


# Bolts descend from just above the impact point. Long enough to read as coming
# from the sky, short enough to stay on screen.
STRIKE_DROP = pygame.Vector2(0, -340)


class LightningStrike(Weapon):
    key = "strike"
    sound = "thunder"
    label = "Lightning Strike"
    description = "Calls a bolt down onto the toughest enemy near you."
    max_level = FUSION_LEVEL   # fusion ingredient (strike)
    color = (195, 205, 255)
    base_cooldown = 2.0

    @property
    def damage(self):
        return 105 + 40 * (self.level - 1)

    @property
    def strikes(self):
        # 1 / 2 / 3 / 4 at levels 1 / 3 / 5 / 7.
        return 1 + (self.level - 1) // 2

    @property
    def blast_radius(self):
        return 44 + 4 * (self.level - 1)

    def cooldown(self, player):
        return max(0.7, self.base_cooldown - 0.16 * (self.level - 1)) * player.cooldown_mult

    def upgrade_text(self):
        bits = ["+40 damage", "faster calls"]
        if self.level + 1 in (3, 5, 7):
            bits.append("+1 strike")
        return ", ".join(bits)

    def fire(self, world):
        player = world.player
        targets = strongest_targets(world, player.pos, self.shot_count(world, self.strikes), 420)
        for target in targets:
            self.call_down(world, pygame.Vector2(target.pos))

    def call_down(self, world, point):
        """Damage everything inside the blast, and sell it visually."""
        world.effects.beam(point + STRIKE_DROP, point, self.color, life=0.2, width=7)
        world.effects.shockwave(point, self.blast_radius, (215, 225, 255), life=0.3)
        world.effects.burst(point, (225, 235, 255), count=12,
                            speed=self.blast_radius * 3.0, life=0.3, radius=5)
        world.camera.add_trauma(0.08)

        for enemy in world.enemies_near(point, self.blast_radius + 40):
            if not enemy.alive:
                continue
            distance = point.distance_to(enemy.pos)
            if distance <= self.blast_radius + enemy.radius:
                world.damage_enemy(enemy, self.damage, source_pos=point, knockback=190,
                                   weapon_key=self.key)


class SolarBeam(Weapon):
    """Shared body for the two axis-aligned beams.

    H and V differ only in which way the arms point, so the hit test, the
    scaling and the drawing all live here and the subclasses supply directions.
    """

    max_level = FUSION_LEVEL   # fusion ingredient (solar_h and solar_v)
    base_cooldown = 1.6
    directions = ()

    def __init__(self):
        super().__init__()
        self.flashes = []          # [life, max_life]

    @property
    def damage(self):
        return 33 + 14 * (self.level - 1)

    @property
    def thickness(self):
        return 48 + 8 * (self.level - 1)

    @property
    def length(self):
        return 620 + 45 * (self.level - 1)

    def cooldown(self, player):
        return max(0.55, self.base_cooldown - 0.13 * (self.level - 1)) * player.cooldown_mult

    def upgrade_text(self):
        return "+15 damage, wider and longer beam, faster fire rate"

    def fire(self, world):
        player = world.player
        half = self.thickness * 0.5
        length = self.length
        self.flashes.append([0.22, 0.22])
        world.effects.burst(player.pos, self.color, count=8, speed=200, life=0.25, radius=4)

        for enemy in world.enemies_near(player.pos, length):
            if not enemy.alive:
                continue
            offset = enemy.pos - player.pos
            for direction in self.directions:
                along = offset.dot(direction)
                across = abs(offset.x * -direction.y + offset.y * direction.x)
                if 0 <= along <= length and across <= half + enemy.radius:
                    world.damage_enemy(enemy, self.damage, source_pos=player.pos,
                                       knockback=150, weapon_key=self.key)
                    break

    def update(self, dt, world):
        super().update(dt, world)
        for flash in self.flashes:
            flash[0] -= dt
        self.flashes = [f for f in self.flashes if f[0] > 0]

    def draw(self, painter, camera, world):
        if not self.flashes:
            return
        player_pos = world.player.pos
        half = self.thickness * 0.5
        length = self.length

        for life, max_life in self.flashes:
            fade = max(0.0, life / max_life)
            for direction in self.directions:
                far = player_pos + direction * length
                across = pygame.Vector2(-direction.y, direction.x) * half
                corners = [
                    camera.to_screen(player_pos + across),
                    camera.to_screen(far + across),
                    camera.to_screen(far - across),
                    camera.to_screen(player_pos - across),
                ]
                xs = [p[0] for p in corners]
                ys = [p[1] for p in corners]
                bounds = pygame.Rect(min(xs), min(ys),
                                     max(xs) - min(xs) + 2, max(ys) - min(ys) + 2)
                if bounds.width < 1 or bounds.height < 1:
                    continue
                scratch = pygame.Surface(bounds.size)
                local = [(x - bounds.x, y - bounds.y) for x, y in corners]
                tint = (int(self.color[0] * 0.45 * fade),
                        int(self.color[1] * 0.42 * fade),
                        int(self.color[2] * 0.24 * fade))
                pygame.draw.polygon(scratch, tint, local)
                painter.blit(scratch, bounds.topleft, flags=pygame.BLEND_RGB_ADD)
                painter.lines((255, 250, 225), False,
                                  [corners[0], corners[1]], max(1, int(2 * fade)))
                painter.lines((255, 250, 225), False,
                                  [corners[3], corners[2]], max(1, int(2 * fade)))


class SolarBeamH(SolarBeam):
    key = "solar_h"
    sound = "beam"
    label = "Solar Beam H"
    description = "A beam of light lances out to your left and right."
    color = (255, 214, 110)
    directions = (pygame.Vector2(1, 0), pygame.Vector2(-1, 0))


class SolarBeamV(SolarBeam):
    key = "solar_v"
    sound = "beam"
    label = "Solar Beam V"
    description = "A beam of light lances out above and below you."
    color = (255, 176, 96)
    directions = (pygame.Vector2(0, 1), pygame.Vector2(0, -1))


class TrailPatch:
    """A lingering damaging area dropped in the player's wake."""

    __slots__ = ("pos", "radius", "life", "max_life", "cooldowns", "erupt_in", "seed")

    def __init__(self, pos, radius, life, erupt_in=None, seed=0):
        self.pos = pygame.Vector2(pos)
        self.radius = radius
        self.life = life
        self.max_life = life
        self.cooldowns = {}
        self.erupt_in = erupt_in
        self.seed = seed


class TrailWeapon(Weapon):
    """Base for weapons that lay damaging ground behind you as you move.

    These are the only weapons whose output depends on the player moving, which
    matters for the DPS bench — measured standing still they stack every patch
    on one spot and read as a single small area.
    """

    max_level = FUSION_LEVEL   # fusion ingredient (earth and fire)
    needs_movement = True
    tick = 0.5
    knockback = 0.0
    status_chance = 0.0

    def __init__(self):
        super().__init__()
        self.patches = []
        self._dropped = 0

    # -- per-weapon knobs ----------------------------------------------------
    @property
    def patch_life(self):
        return 3.0

    def status_for(self):
        return None

    def cooldown(self, player):
        return self.drop_interval * player.cooldown_mult

    # -- lifecycle -----------------------------------------------------------
    def fire(self, world):
        self._dropped += 1
        self.patches.append(
            TrailPatch(world.player.pos, self.radius, self.patch_life,
                       erupt_in=self.erupt_delay, seed=self._dropped)
        )

    erupt_delay = None

    def update(self, dt, world):
        super().update(dt, world)          # timer -> fire() drops a patch
        self._tick_patches(dt, world)

    def _tick_patches(self, dt, world):
        status = self.status_for()
        for patch in self.patches:
            patch.life -= dt

            for key in list(patch.cooldowns):
                patch.cooldowns[key] -= dt
                if patch.cooldowns[key] <= 0:
                    del patch.cooldowns[key]

            if patch.erupt_in is not None:
                patch.erupt_in -= dt
                if patch.erupt_in <= 0:
                    patch.erupt_in = None
                    self.erupt(world, patch)
                    patch.life = min(patch.life, 0.3)
                    continue

            for enemy in world.enemies_near(patch.pos, patch.radius + 40):
                if not enemy.alive or id(enemy) in patch.cooldowns:
                    continue
                if patch.pos.distance_to(enemy.pos) <= patch.radius + enemy.radius:
                    world.damage_enemy(enemy, self.damage, source_pos=patch.pos,
                                       knockback=self.knockback, weapon_key=self.key)
                    if status is not None and enemy.alive and world.rng.random() < self.status_chance:
                        enemy.apply_status(status)
                    patch.cooldowns[id(enemy)] = self.tick

        self.patches = [p for p in self.patches if p.life > 0]

    def erupt(self, world, patch):
        """Only Walking Eruption uses this."""

    # -- drawing -------------------------------------------------------------
    inner_color = (120, 90, 60)
    outer_color = (180, 140, 90)

    def draw(self, painter, camera, world):
        for patch in self.patches:
            fade = max(0.0, min(1.0, patch.life / patch.max_life))
            radius = int(patch.radius)
            if radius < 1:
                continue
            disc = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(disc, (*self.inner_color, int(105 * fade)),
                               (radius, radius), radius)
            pygame.draw.circle(disc, (*self.outer_color, int(170 * fade)),
                               (radius, radius), radius, 3)
            # A few speckles so the patch reads as ground, not a flat disc.
            for index in range(4):
                angle = (patch.seed * 57 + index * 91) % 360
                spot = pygame.Vector2(radius * 0.55, 0).rotate(angle)
                pygame.draw.circle(disc, (*self.outer_color, int(150 * fade)),
                                   (radius + int(spot.x), radius + int(spot.y)),
                                   max(2, radius // 7))
            painter.blit(disc, disc.get_rect(center=camera.to_screen(patch.pos)))


class EarthTrail(TrailWeapon):
    key = "earth"
    label = "Earth Trail"
    description = "Broken ground erupts in your wake, battering whatever stands in it."
    color = (186, 142, 86)
    inner_color = (108, 78, 48)
    outer_color = (196, 150, 92)
    knockback = 130.0
    # Patch lifetime divided by drop interval is how many patches are alive at
    # once, and every one of them ticks independently on every enemy standing in
    # it. Sixteen overlapping patches put this three times above the strongest
    # weapon in the game, so both numbers are held deliberately tight.
    tick = 0.7

    @property
    def damage(self):
        return 14 + 9 * (self.level - 1)

    @property
    def radius(self):
        return 44 + 4 * (self.level - 1)

    @property
    def drop_interval(self):
        return max(0.32, 0.55 - 0.025 * (self.level - 1))

    @property
    def patch_life(self):
        return 2.2 + 0.14 * (self.level - 1)

    def upgrade_text(self):
        return "+9 damage, wider rubble, laid faster, lingers longer"


class FireTrail(TrailWeapon):
    key = "fire"
    label = "Fire Trail"
    description = "You leave a line of flame that sets pursuers alight."
    color = (255, 138, 62)
    inner_color = (150, 58, 24)
    outer_color = (255, 148, 70)
    tick = 0.55

    @property
    def damage(self):
        return 9 + 6 * (self.level - 1)

    @property
    def radius(self):
        return 38 + 4 * (self.level - 1)

    @property
    def drop_interval(self):
        return max(0.26, 0.44 - 0.018 * (self.level - 1))

    @property
    def patch_life(self):
        return 1.9 + 0.12 * (self.level - 1)

    @property
    def status_chance(self):
        return min(1.0, 0.35 + 0.08 * (self.level - 1))

    @property
    def burn_dps(self):
        return 10 + 5 * (self.level - 1)

    def status_for(self):
        return StatusSpec(key=BURN, duration=2.5, dps=self.burn_dps, interval=0.5,
                          weapon_key=self.key)

    def upgrade_text(self):
        return "+6 damage, wider flames, laid faster, stronger burn"


# ---------------------------------------------------------------------------
# Fusions — reached by maxing two weapons, never offered or picked directly
# ---------------------------------------------------------------------------

class RadiantBeam(Weapon):
    key = "radiant"
    label = "Radiant Beam"
    description = "Both solar beams fused into a cross of light that sweeps around you."
    max_level = 6
    color = (255, 236, 150)
    evolved = True

    def __init__(self):
        super().__init__()
        self.angle = 0.0
        self.hit_cooldowns = {}

    @property
    def damage(self):
        # Tuned so a fresh fusion already beats the two maxed beams it ate,
        # without ending up four times stronger than anything else in the game.
        return 145 + 20 * (self.level - 1)

    @property
    def thickness(self):
        return 62 + 5 * (self.level - 1)

    @property
    def length(self):
        return 520 + 25 * (self.level - 1)

    @property
    def spin_speed(self):
        return 52 + 7 * (self.level - 1)

    @property
    def arms(self):
        return 4

    def upgrade_text(self):
        return "+22 damage, thicker and longer arms, faster sweep"

    def arm_directions(self):
        return [
            pygame.Vector2(1, 0).rotate(self.angle + i * (360 / self.arms))
            for i in range(self.arms)
        ]

    def update(self, dt, world):
        # Continuous sweep rather than a triggered cast: it never stops burning.
        self.angle = (self.angle + self.spin_speed * dt) % 360

        for key in list(self.hit_cooldowns):
            self.hit_cooldowns[key] -= dt
            if self.hit_cooldowns[key] <= 0:
                del self.hit_cooldowns[key]

        player = world.player
        half = self.thickness * 0.5
        length = self.length
        directions = self.arm_directions()

        for enemy in world.enemies_near(player.pos, length):
            if not enemy.alive or id(enemy) in self.hit_cooldowns:
                continue
            offset = enemy.pos - player.pos
            for direction in directions:
                along = offset.dot(direction)
                across = abs(offset.x * -direction.y + offset.y * direction.x)
                if 0 <= along <= length and across <= half + enemy.radius:
                    world.damage_enemy(enemy, self.damage, source_pos=player.pos,
                                       knockback=120, weapon_key=self.key)
                    self.hit_cooldowns[id(enemy)] = 0.5 * player.cooldown_mult
                    break

    def draw(self, painter, camera, world):
        player_pos = world.player.pos
        half = self.thickness * 0.5
        length = self.length

        for direction in self.arm_directions():
            far = player_pos + direction * length
            across = pygame.Vector2(-direction.y, direction.x) * half
            corners = [
                camera.to_screen(player_pos + across),
                camera.to_screen(far + across),
                camera.to_screen(far - across),
                camera.to_screen(player_pos - across),
            ]
            xs = [p[0] for p in corners]
            ys = [p[1] for p in corners]
            bounds = pygame.Rect(min(xs), min(ys),
                                 max(xs) - min(xs) + 2, max(ys) - min(ys) + 2)
            if bounds.width < 1 or bounds.height < 1:
                continue
            scratch = pygame.Surface(bounds.size)
            local = [(x - bounds.x, y - bounds.y) for x, y in corners]
            pygame.draw.polygon(scratch, (92, 80, 34), local)
            painter.blit(scratch, bounds.topleft, flags=pygame.BLEND_RGB_ADD)
            painter.line((255, 250, 220), corners[0], corners[1], 2)
            painter.line((255, 250, 220), corners[3], corners[2], 2)


class Tempest(Weapon):
    key = "tempest"
    sound = "gust"
    label = "Tempest"
    description = "Called bolts that leap onward through everything nearby."
    max_level = 6
    color = (215, 230, 255)
    base_cooldown = 1.15
    evolved = True

    @property
    def damage(self):
        return 410 + 45 * (self.level - 1)

    @property
    def strikes(self):
        # Flat. Strikes multiply against chains and damage, and letting all three
        # grow put this five times above its own ingredients by max level.
        return 3

    @property
    def chains(self):
        # Held flat. Strikes, chains and damage all scaling together compounds
        # into roughly 10x across six levels, which no other weapon comes near.
        return 6

    @property
    def blast_radius(self):
        return 52 + 5 * (self.level - 1)

    @property
    def jump_range(self):
        return 240 + 16 * (self.level - 1)

    def cooldown(self, player):
        return max(0.85, self.base_cooldown - 0.05 * (self.level - 1)) * player.cooldown_mult

    def upgrade_text(self):
        return "+45 damage, wider blast, longer jumps, faster calls"

    def fire(self, world):
        player = world.player
        struck_ids = set()
        for target in strongest_targets(world, player.pos, self.shot_count(world, self.strikes), 440):
            point = pygame.Vector2(target.pos)
            self._call_down(world, point)
            struck_ids.add(id(target))
            self._chain_from(world, point, struck_ids)

    def _call_down(self, world, point):
        world.effects.beam(point + STRIKE_DROP, point, self.color, life=0.2, width=8)
        world.effects.shockwave(point, self.blast_radius, (215, 230, 255), life=0.3)
        world.camera.add_trauma(0.1)
        for enemy in world.enemies_near(point, self.blast_radius + 40):
            if enemy.alive and point.distance_to(enemy.pos) <= self.blast_radius + enemy.radius:
                world.damage_enemy(enemy, self.damage, source_pos=point, knockback=200,
                                   weapon_key=self.key)

    def _chain_from(self, world, origin, struck_ids):
        damage = self.damage * CHAIN_FALLOFF
        for _ in range(self.chains):
            target = world.nearest_enemy(origin, max_dist=self.jump_range, exclude=struck_ids)
            if target is None:
                break
            world.effects.beam(origin, target.pos, self.color, life=0.16, width=4)
            world.damage_enemy(target, damage, source_pos=origin, knockback=110,
                               weapon_key=self.key)
            struck_ids.add(id(target))
            origin = pygame.Vector2(target.pos)
            damage *= CHAIN_FALLOFF


class WalkingEruption(TrailWeapon):
    key = "eruption"
    label = "Walking Eruption"
    description = "Molten ground that detonates a moment after you walk over it."
    max_level = 6
    color = (255, 168, 70)
    inner_color = (142, 52, 22)
    outer_color = (255, 176, 78)
    evolved = True
    tick = 0.4

    @property
    def damage(self):
        return 90 + 10 * (self.level - 1)

    @property
    def blast_damage(self):
        # Flat-ish on purpose. A fusion must already beat its ingredients at
        # level 1, which caps how much room is left to grow before it dwarfs
        # everything else — all three fusions land near 2.2x across their range.
        return 520 + 45 * (self.level - 1)

    @property
    def radius(self):
        return 56 + 2 * (self.level - 1)

    @property
    def blast_radius(self):
        return self.radius * 1.7

    @property
    def drop_interval(self):
        return max(0.28, 0.34 - 0.006 * (self.level - 1))

    @property
    def patch_life(self):
        return 2.6

    @property
    def erupt_delay(self):
        # Long enough that you can walk clear and watch it go off behind you.
        return 0.9

    @property
    def burn_dps(self):
        return 22 + 9 * (self.level - 1)

    def status_for(self):
        return StatusSpec(key=BURN, duration=2.5, dps=self.burn_dps, interval=0.5,
                          weapon_key=self.key)

    status_chance = 0.5

    def upgrade_text(self):
        return "+45 blast damage, wider eruptions, laid faster, stronger burn"

    def erupt(self, world, patch):
        radius = self.blast_radius
        # Hooked to the eruption, not to laying the patch. The patch is dropped
        # silently under your feet and goes off a beat later, so a cue at drop
        # time would land before the blast it is describing.
        audio.play("erupt")
        world.effects.shockwave(patch.pos, radius, (255, 170, 80), life=0.32)
        world.effects.burst(patch.pos, (255, 190, 110), count=18, speed=radius * 3.2,
                            life=0.4, radius=6)
        world.camera.add_trauma(0.09)

        burn = self.status_for()
        for enemy in world.enemies_near(patch.pos, radius + 40):
            if not enemy.alive:
                continue
            distance = patch.pos.distance_to(enemy.pos)
            if distance > radius + enemy.radius:
                continue
            falloff = 1.0 - 0.5 * min(1.0, distance / max(1.0, radius))
            world.damage_enemy(enemy, self.blast_damage * falloff, source_pos=patch.pos,
                               knockback=210, weapon_key=self.key)
            if enemy.alive:
                enemy.apply_status(burn)

    def draw(self, painter, camera, world):
        super().draw(painter, camera, world)
        # A brightening core warns that a patch is about to go off.
        for patch in self.patches:
            if patch.erupt_in is None:
                continue
            charge = 1.0 - max(0.0, patch.erupt_in / self.erupt_delay)
            core = int(patch.radius * (0.2 + 0.55 * charge))
            if core < 1:
                continue
            sx, sy = camera.to_screen(patch.pos)
            painter.circle((255, int(120 + 110 * charge), 60),
                               (int(sx), int(sy)), core)
            painter.circle((255, 240, 200), (int(sx), int(sy)),
                               max(1, core // 3))


class FrostfireOrb(Weapon):
    """Fireball + Frost Orb. Rolls, freezes, then shatters and burns.

    Built on Frost Orb's shape rather than Fireball's because the orb is the
    more interesting half: a slow projectile that holds an area is something no
    other weapon does, while a lobbed bomb is close to what Lightning Strike and
    Walking Eruption already deliver. So the orb keeps rolling and keeps
    freezing, and Fireball's contribution is what happens when it dies.

    The freeze is the reason to build this. Frost Orb only stops things outright
    at level 8, its very last rank; the fusion does it from level 1, which is
    the payoff for having taken both weapons all the way there.
    """

    key = "frostfire"
    sound = "frost"
    label = "Frostfire Orb"
    description = "Orbs that freeze whatever they roll over, then shatter into burning shards."
    max_level = 6
    color = (176, 216, 255)
    base_cooldown = 1.5
    evolved = True

    def __init__(self):
        super().__init__()
        # Same shape as FrostOrb's: the weapon owns them because they damage an
        # area over time rather than colliding once.
        self.orbs = []

    # Tighter than Frost Orb's 0.8. The per-enemy hit cooldown, not the damage
    # number, is what decides how much this actually does to a packed swarm —
    # Frost Orb's own comment records finding that out the hard way.
    hit_cooldown = 0.5

    # **These numbers look wrong next to the other fusions, and are not.** The
    # bar a fusion has to clear is the pair it eats, and this pair is by far the
    # strongest in the game: Fireball and Frost Orb maxed measure 5,765 DPS
    # together, against 3,177 for the two Solar Beams, 3,298 for the trails and
    # 3,937 for Strike + Coil. The first draft of this weapon was written to
    # look like Walking Eruption's numbers and measured 0.47x its ingredients at
    # level 1 — a fusion that made you weaker for taking it, and the only reason
    # anyone would have known is that the bench says so. Retune against
    # ``tools/dps_bench.py``, not against the class above.
    @property
    def damage(self):
        return 230 + 9 * (self.level - 1)

    @property
    def burst_damage(self):
        # Held near-flat, like the other three fusions: a fusion has to beat its
        # ingredients on the level it arrives at, which leaves little room to
        # grow before it dwarfs the rest of the game. All four now land between
        # 1.2x and 1.3x at level 1 and 2.5x to 2.7x at level 6.
        return 660 + 45 * (self.level - 1)

    @property
    def orb_radius(self):
        return 84 + 2 * (self.level - 1)

    @property
    def burst_radius(self):
        return self.orb_radius * 1.8

    @property
    def count(self):
        # Flat. Orb count multiplies against radius and against the shatter,
        # and letting all three grow is how Tempest ended up five times its own
        # ingredients before its strikes were pinned down.
        return 3

    @property
    def burn_dps(self):
        return 75 + 8 * (self.level - 1)

    def cooldown(self, player):
        return max(0.80, self.base_cooldown - 0.08 * (self.level - 1)) * player.cooldown_mult

    def upgrade_text(self):
        return "+45 shatter damage, bigger orbs, hotter burn, faster casts"

    def burn_spec(self):
        return StatusSpec(key=BURN, duration=3.0, dps=self.burn_dps, interval=0.5,
                          weapon_key=self.key)

    def chill_spec(self):
        # A full stop, not a slow. Short, because a permanent freeze on three
        # orbs this size would simply switch the enemies off.
        return StatusSpec(key=CHILL, duration=1.5, slow=1.0, weapon_key=self.key)

    def fire(self, world):
        player = world.player
        base = pygame.Vector2(player.aim)
        if base.length_squared() < 0.001:
            base = pygame.Vector2(0, 1)

        count = self.shot_count(world)
        for index in range(count):
            spread = (index - (count - 1) / 2) * 30
            self.orbs.append({
                "pos": pygame.Vector2(player.pos),
                "vel": base.rotate(spread) * 320,
                "travel": 0.95,
                "linger": 0.6,
                "cooldowns": {},
            })

    def update(self, dt, world):
        super().update(dt, world)

        chill = self.chill_spec()
        radius = self.orb_radius

        for orb in self.orbs:
            if orb["travel"] > 0:
                orb["travel"] -= dt
                orb["pos"] += orb["vel"] * dt
                if orb["travel"] <= 0:
                    orb["vel"].update(0, 0)
            else:
                orb["linger"] -= dt

            cooldowns = orb["cooldowns"]
            for key in list(cooldowns):
                cooldowns[key] -= dt
                if cooldowns[key] <= 0:
                    del cooldowns[key]

            for enemy in world.enemies_near(orb["pos"], radius + 40):
                if not enemy.alive or id(enemy) in cooldowns:
                    continue
                if orb["pos"].distance_to(enemy.pos) <= radius + enemy.radius:
                    world.damage_enemy(enemy, self.damage, source_pos=orb["pos"],
                                       knockback=70, weapon_key=self.key)
                    if enemy.alive:
                        enemy.apply_status(chill)
                    cooldowns[id(enemy)] = self.hit_cooldown

        spent = [orb for orb in self.orbs if orb["linger"] <= 0]
        for orb in spent:
            self.shatter(world, orb["pos"])
        if spent:
            self.orbs = [orb for orb in self.orbs if orb["linger"] > 0]

    def shatter(self, world, point):
        """The Fireball half: everything the orb froze now gets set alight."""
        radius = self.burst_radius
        audio.play("erupt")
        world.effects.shockwave(point, radius, (200, 230, 255), life=0.3)
        world.effects.burst(point, (255, 190, 130), count=16, speed=radius * 3.0,
                            life=0.38, radius=5)
        world.camera.add_trauma(0.07)

        burn = self.burn_spec()
        for enemy in world.enemies_near(point, radius + 40):
            if not enemy.alive:
                continue
            distance = point.distance_to(enemy.pos)
            if distance > radius + enemy.radius:
                continue
            falloff = 1.0 - 0.5 * min(1.0, distance / max(1.0, radius))
            world.damage_enemy(enemy, self.burst_damage * falloff, source_pos=point,
                               knockback=200, weapon_key=self.key)
            if enemy.alive:
                enemy.apply_status(burn)

    def draw(self, painter, camera, world):
        radius = int(self.orb_radius)
        for orb in self.orbs:
            # The orb visibly heats up as its linger runs out, so the shatter is
            # something you can see coming and walk enemies into rather than a
            # surprise going off behind you.
            settling = orb["travel"] <= 0
            charge = 1.0 - max(0.0, min(1.0, orb["linger"] / 0.6)) if settling else 0.0
            disc = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            centre = (radius, radius)
            pygame.draw.circle(disc, (90, 170, 255, 62), centre, radius)
            pygame.draw.circle(disc, (190, 235, 255, 155), centre, radius, 3)
            if charge > 0:
                # Small and opaque rather than large and translucent. A wide
                # half-transparent orange over the blue fill averages out to
                # brown and reads as a patch of dirt on the ground; a tighter
                # core at high alpha reads as fire inside ice, which is the
                # whole idea of the weapon.
                pygame.draw.circle(disc, (255, 128, 38, int(90 + 150 * charge)),
                                   centre, max(2, int(radius * (0.16 + 0.32 * charge))))
            pygame.draw.circle(disc, (255, 245, 235, 200), centre, max(3, radius // 5))
            painter.blit(disc, disc.get_rect(center=camera.to_screen(orb["pos"])))


# Base weapons: offerable at level-up and pickable as a starting weapon.
WEAPON_TYPES = [Sword, HomingBolts, Rapier, WardingSigils, ArcCoil,
                Fireball, PoisonAura, FrostOrb,
                LightningStrike, SolarBeamH, SolarBeamV,
                EarthTrail, FireTrail]

# Fusions: only reachable by maxing both ingredients.
EVOLVED_TYPES = [RadiantBeam, Tempest, WalkingEruption, FrostfireOrb]


class Evolution:
    """Two weapons at FUSION_LEVEL fuse into one, freeing a slot."""

    __slots__ = ("result", "ingredients")

    def __init__(self, result, ingredients):
        self.result = result
        self.ingredients = tuple(ingredients)

    @property
    def key(self):
        return self.result.key

    @property
    def label(self):
        return self.result.label

    @property
    def color(self):
        return self.result.color

    @property
    def description(self):
        return self.result.description

    def ingredient_labels(self, by_key):
        return [by_key[k].label for k in self.ingredients if k in by_key]

    def available_for(self, player):
        """True when the player carries every ingredient at FUSION_LEVEL."""
        owned = {w.key: w for w in player.weapons}
        return all(
            key in owned and owned[key].level >= FUSION_LEVEL
            for key in self.ingredients
        )

    def progress(self, player):
        """(levels earned, levels needed) — for showing how close a fusion is."""
        owned = {w.key: w for w in player.weapons}
        earned = sum(min(owned[k].level, FUSION_LEVEL) if k in owned else 0
                     for k in self.ingredients)
        return earned, FUSION_LEVEL * len(self.ingredients)

    def apply(self, player):
        # Consuming both ingredients is what keeps fusion a real decision: it
        # frees a slot, so a fused build can reach further than an unfused one.
        player.weapons = [w for w in player.weapons if w.key not in self.ingredients]
        player.weapons.append(self.result())


EVOLUTIONS = [
    Evolution(RadiantBeam, ("solar_h", "solar_v")),
    Evolution(Tempest, ("strike", "coil")),
    Evolution(WalkingEruption, ("earth", "fire")),
    Evolution(FrostfireOrb, ("fireball", "frost")),
]

WEAPONS_BY_KEY = {cls.key: cls for cls in WEAPON_TYPES + EVOLVED_TYPES}
STARTING_WEAPON = "sword"


def _validate_evolutions():
    for evolution in EVOLUTIONS:
        for key in evolution.ingredients:
            assert key in WEAPONS_BY_KEY, f"{evolution.label}: unknown ingredient {key!r}"
            assert not WEAPONS_BY_KEY[key].evolved, (
                f"{evolution.label}: ingredient {key!r} is itself a fusion"
            )
            # An ingredient capped below FUSION_LEVEL can never qualify, and the
            # symptom would be a fusion that simply never appears — no error, no
            # crash, just a feature quietly missing from the game.
            assert WEAPONS_BY_KEY[key].max_level >= FUSION_LEVEL, (
                f"{evolution.label}: ingredient {key!r} caps at level "
                f"{WEAPONS_BY_KEY[key].max_level}, below FUSION_LEVEL "
                f"({FUSION_LEVEL}), so this fusion could never be offered"
            )
        assert evolution.result.evolved, f"{evolution.label}: result is not marked evolved"


_validate_evolutions()
