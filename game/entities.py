"""Player, enemies, and pickups.

Every entity stores its position as a float ``Vector2`` and derives its ``rect``
from that. The old build assigned floats straight onto ``rect.x``, which
truncates: a Guardian at speed 1 chasing you mostly-vertically had an x-step of
about 0.2px per frame, truncated to 0 every single frame, so it could never
close the horizontal gap. Float positions fix that whole class of bug at once.
"""

import math
import random
from dataclasses import dataclass, field

import pygame

from . import assets
from . import settings
from .status import BOSS_SLOW_CAP, ActiveStatus
from .config import (
    CHAOS_DAMAGE_PER_LEVEL,
    CHAOS_HEALTH_PER_LEVEL,
    CHAOS_SPAWN_PER_LEVEL,
    CHAOS_XP_PER_LEVEL,
    LUCK_DROP_BONUS,
    LUCK_EXTRA_CARD,
    COL_HP_GOOD,
    COL_HP_LOW,
    COL_HP_MID,
    ELITE_DAMAGE_MULT,
    ELITE_HEALTH_MULT,
    ELITE_SCALE,
    ELITE_XP_MULT,
    ENEMY_DAMAGE_SCALE_PER_MIN,
    ENEMY_HEALTH_SCALE_PER_MIN,
    ENEMY_SPEED_SCALE_CAP,
    ENEMY_SPEED_SCALE_PER_MIN,
    LEVEL_UP_HEAL,
    PLAYER_BASE_HEALTH,
    PLAYER_BASE_PICKUP_RADIUS,
    PLAYER_BASE_SPEED,
    PLAYER_IFRAMES,
    XP_FIRST_LEVEL,
    XP_GROWTH,
)

FACING_ANGLES = {"up": 0, "left": 90, "down": 180, "right": 270}
HIT_FLASH_TIME = 0.09


def health_bar_color(ratio):
    if ratio > 0.5:
        return COL_HP_GOOD
    if ratio > 0.25:
        return COL_HP_MID
    return COL_HP_LOW


def draw_bar(painter, x, y, width, height, ratio, fill_color, border=True):
    ratio = max(0.0, min(1.0, ratio))
    painter.rect((28, 28, 38), (x, y, width, height))
    if ratio > 0:
        painter.rect(fill_color, (x, y, int(width * ratio), height))
    if border:
        painter.rect((8, 8, 12), (x, y, width, height), 1)


class Entity:
    """Anything with a float position and a rect derived from it."""

    def __init__(self, pos, size):
        self.pos = pygame.Vector2(pos)
        self.size = size
        self.alive = True

    @property
    def rect(self):
        rect = pygame.Rect(0, 0, self.size, self.size)
        rect.center = (int(self.pos.x), int(self.pos.y))
        return rect

    @property
    def radius(self):
        return self.size * 0.5

    def kill(self):
        self.alive = False


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

# Each passive maps to a per-level bonus. Meta (permanent) upgrades use the same
# keys so a saved +might stacks additively with an in-run +might.
PASSIVE_EFFECTS = {
    "might":    0.10,   # +10% all damage per level
    "health":   22,     # +22 max HP per level
    "speed":    0.07,   # +7% move speed per level
    "magnet":   0.28,   # +28% pickup radius per level
    "crit":     0.05,   # +5 percentage points crit chance per level
    "savagery": 0.25,   # +25% crit damage per level
    "armor":    1.6,    # flat damage reduction per level
    "regen":    0.5,    # HP per second per level
    "wisdom":   0.12,   # +12% XP gain per level
    "haste":    0.06,   # -6% weapon cooldown per level
    # These three store the level itself; the rates that turn a level into an
    # effect live in config, because they touch systems outside the player.
    "volley":   1,      # +1 projectile per level, on weapons that fire them
    "chaos":    1,
    "luck":     1,
}


class Player(Entity):
    def __init__(self, pos, meta=None):
        # Four authored facings rather than one sprite rotated four ways: a
        # top-down figure turned 90 degrees reads as one lying down.
        self.sprites = {
            facing: assets.images[f"wizard_{facing}"]
            for facing in ("up", "down", "left", "right")
        }
        super().__init__(pos, self.sprites["down"].get_width())
        self.facing_name = "down"
        self.facing = pygame.Vector2(0, 1)
        # Where directional weapons point. Recomputed each frame to track the
        # nearest enemy, falling back to movement facing when nothing is close.
        # Tying melee to movement facing alone punishes kiting, which is the one
        # thing this genre asks you to do constantly.
        self.aim = pygame.Vector2(0, 1)

        self.meta = meta or {}
        self.passives = {}
        self.weapons = []

        self.max_health = PLAYER_BASE_HEALTH + self.meta_bonus("health")
        self.health = float(self.max_health)
        self.iframes = 0.0
        self.knockback = pygame.Vector2()

        self.level = 1
        self.xp = 0.0
        self.xp_to_next = XP_FIRST_LEVEL
        self.pending_level_ups = 0

        self.gold = 0
        self.gold_spent = 0
        self.kills = 0
        self.damage_dealt = 0.0
        self.damage_by_weapon = {}
        self.kills_by_type = {}
        self.elite_kills = 0
        self.revives = int(self.meta.get("revive", 0))

        # Level-up charges, bought in the Sanctum and refilled per run. They
        # live on the player rather than on the Game so they survive stepping
        # through a portal — ``World(carry=...)`` hands the same player to the
        # next arena, and a run's worth of rerolls that silently reset on the
        # second map would be a nasty surprise.
        self.rerolls = int(self.meta.get("reroll", 0))
        self.skips = int(self.meta.get("skip", 0))

    # -- derived stats -------------------------------------------------------
    def meta_bonus(self, key):
        return PASSIVE_EFFECTS.get(key, 0) * self.meta.get(key, 0)

    def passive_total(self, key):
        return PASSIVE_EFFECTS[key] * self.passives.get(key, 0) + self.meta_bonus(key)

    @property
    def damage_mult(self):
        return 1.0 + self.passive_total("might")

    @property
    def move_speed(self):
        return PLAYER_BASE_SPEED * (1.0 + self.passive_total("speed"))

    @property
    def pickup_radius(self):
        return PLAYER_BASE_PICKUP_RADIUS * (1.0 + self.passive_total("magnet"))

    @property
    def crit_chance(self):
        return min(0.85, self.passive_total("crit"))

    @property
    def crit_damage(self):
        return 1.6 + self.passive_total("savagery")

    @property
    def armor(self):
        return self.passive_total("armor")

    @property
    def regen(self):
        return self.passive_total("regen")

    @property
    def xp_mult(self):
        return 1.0 + self.passive_total("wisdom")

    @property
    def cooldown_mult(self):
        return max(0.35, 1.0 - self.passive_total("haste"))

    @property
    def bonus_projectiles(self):
        return int(self.passive_total("volley"))

    @property
    def chaos(self):
        return self.passive_total("chaos")

    @property
    def luck(self):
        return self.passive_total("luck")

    @property
    def drop_mult(self):
        return 1.0 + self.luck * LUCK_DROP_BONUS

    @property
    def extra_card_chance(self):
        return min(0.8, self.luck * LUCK_EXTRA_CARD)

    @property
    def chaos_health_mult(self):
        return 1.0 + self.chaos * CHAOS_HEALTH_PER_LEVEL

    @property
    def chaos_damage_mult(self):
        return 1.0 + self.chaos * CHAOS_DAMAGE_PER_LEVEL

    @property
    def chaos_spawn_mult(self):
        return 1.0 + self.chaos * CHAOS_SPAWN_PER_LEVEL

    @property
    def chaos_xp_mult(self):
        return 1.0 + self.chaos * CHAOS_XP_PER_LEVEL

    # -- progression ---------------------------------------------------------
    def add_passive(self, key, levels=1):
        """Add levels of a passive. The per-passive cap is enforced by the offer
        that granted it, so this just applies what it is handed."""
        self.passives[key] = self.passives.get(key, 0) + levels
        if key == "health":
            gained = PASSIVE_EFFECTS["health"] * levels
            self.max_health += gained
            self.health += gained

    def gain_xp(self, amount):
        self.xp += amount * self.xp_mult
        while self.xp >= self.xp_to_next:
            self.xp -= self.xp_to_next
            self.level += 1
            self.xp_to_next = int(self.xp_to_next * XP_GROWTH)
            self.pending_level_ups += 1
            # A partial top-up, not a full refill. Chip damage accumulating over
            # a run is the whole tension of the genre; the old full heal on every
            # level-up erased it.
            self.health = min(self.max_health, self.health + self.max_health * LEVEL_UP_HEAL)

    # -- combat --------------------------------------------------------------
    def take_damage(self, amount, source_pos=None):
        if self.iframes > 0:
            return 0.0
        dealt = max(1.0, amount - self.armor)
        self.health -= dealt
        self.iframes = PLAYER_IFRAMES
        if source_pos is not None:
            away = self.pos - source_pos
            if away.length_squared() > 0:
                self.knockback = away.normalize() * 210.0
        return dealt

    def heal(self, amount):
        before = self.health
        self.health = min(self.max_health, self.health + amount)
        return self.health - before

    # -- update --------------------------------------------------------------
    def update(self, dt, move_input, arena):
        self.iframes = max(0.0, self.iframes - dt)
        if self.regen:
            self.health = min(self.max_health, self.health + self.regen * dt)

        if move_input.length_squared() > 0:
            # Normalising is what stops diagonal movement being 41% faster than
            # cardinal movement, which the old input handler allowed.
            direction = move_input.normalize()
            self.facing = direction
            self.facing_name = self._facing_name(direction)
        else:
            direction = pygame.Vector2()

        delta = direction * self.move_speed * dt
        if self.knockback.length_squared() > 1:
            delta += self.knockback * dt
            self.knockback *= max(0.0, 1.0 - 7.0 * dt)
        else:
            self.knockback.update(0, 0)

        half = self.size * 0.42
        self.pos, _, _ = arena.move_and_slide(self.pos, half, half, delta)

    @staticmethod
    def _facing_name(direction):
        if abs(direction.x) > abs(direction.y):
            return "right" if direction.x > 0 else "left"
        return "down" if direction.y > 0 else "up"

    def draw(self, painter, camera):
        # Blink during invulnerability so the i-frame window is readable.
        if self.iframes > 0 and int(self.iframes * 20) % 2 == 0:
            return
        image = self.sprites[self.facing_name]
        painter.blit(image, image.get_rect(center=camera.to_screen(self.pos)))


# ---------------------------------------------------------------------------
# Enemies
# ---------------------------------------------------------------------------

@dataclass
class ShootPattern:
    interval: float
    speed: float
    damage: float
    burst: int = 1
    burst_delay: float = 0.12
    fan: int = 0
    fan_spread: float = 30.0
    range: float = 900.0


@dataclass
class Archetype:
    key: str
    label: str
    image_key: str
    speed: float
    health: float
    contact_damage: float
    xp: float
    weight: float = 1.0
    unlock_time: float = 0.0
    shoot: ShootPattern = None
    is_boss: bool = False
    is_final: bool = False
    tint: tuple = field(default=None)


# Trash speed sits at roughly 65% of player speed. Much slower and you outrun the
# horde forever; much faster and kiting stops working at all.
ARCHETYPES = {
    "goblin": Archetype(
        key="goblin", label="Goblin", image_key="goblin",
        speed=150, health=30, contact_damage=6, xp=12, weight=6.0,
    ),
    "ghost": Archetype(
        key="ghost", label="Ghost", image_key="ghost",
        speed=126, health=62, contact_damage=9, xp=24, weight=2.4, unlock_time=40,
        shoot=ShootPattern(interval=2.6, speed=250, damage=9),
    ),
    "guardian": Archetype(
        key="guardian", label="Guardian", image_key="guardian",
        speed=98, health=150, contact_damage=14, xp=46, weight=1.6, unlock_time=85,
        shoot=ShootPattern(interval=3.4, speed=230, damage=11, burst=3, burst_delay=0.14),
    ),
    "king": Archetype(
        key="king", label="Goblin Warchief", image_key="king",
        speed=118, health=9000, contact_damage=34, xp=4000, weight=0.0,
        shoot=ShootPattern(interval=1.9, speed=320, damage=22, burst=5, burst_delay=0.09,
                           fan=7, fan_spread=22),
        is_boss=True, is_final=True,
    ),
    "boss": Archetype(
        key="boss", label="Warden", image_key="boss",
        speed=126, health=2100, contact_damage=24, xp=650, weight=0.0,
        shoot=ShootPattern(interval=2.4, speed=290, damage=16, burst=4, burst_delay=0.11,
                           fan=5, fan_spread=26),
        is_boss=True,
    ),
}

_sprite_cache = assets.register_cache({})
_flash_cache = assets.register_cache({})
_silhouette_cache = assets.register_cache({})


def enemy_sprite(archetype, elite):
    key = (archetype.image_key, elite)
    if key not in _sprite_cache:
        image = assets.images[archetype.image_key]
        if elite:
            image = assets.scaled(image, ELITE_SCALE)
            image = assets.tint(image, (255, 130, 130), alpha=255)
        _sprite_cache[key] = image
    return _sprite_cache[key]


def enemy_flash(archetype, elite):
    """A white silhouette of the sprite, cached.

    Filling the sprite's *bounding rect* with white — which is what the original
    hit flash did — paints the transparent corners too, so a struck enemy reads
    as a solid white square rather than a lit-up silhouette. Adding white to the
    RGB channels while leaving alpha at zero keeps the shape intact.
    """
    key = (archetype.image_key, elite)
    if key not in _flash_cache:
        flash = enemy_sprite(archetype, elite).copy()
        flash.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGBA_ADD)
        _flash_cache[key] = flash
    return _flash_cache[key]


def enemy_silhouette(archetype, elite, color):
    """A flat ``color`` silhouette of the sprite, for status tinting."""
    key = (archetype.image_key, elite, color)
    if key not in _silhouette_cache:
        shape = enemy_sprite(archetype, elite).copy()
        # Multiply to black keeps the alpha channel but clears the colour, then
        # additive gives a flat silhouette in exactly the colour we asked for.
        shape.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MULT)
        shape.fill((*color, 0), special_flags=pygame.BLEND_RGBA_ADD)
        _silhouette_cache[key] = shape
    return _silhouette_cache[key]


class Enemy(Entity):
    def __init__(self, archetype, pos, elapsed, elite=False, chaos=0.0):
        self.archetype = archetype
        self.elite = elite
        self.image = enemy_sprite(archetype, elite)
        super().__init__(pos, self.image.get_width())

        minutes = elapsed / 60.0
        health_mult = 1.0 + minutes * ENEMY_HEALTH_SCALE_PER_MIN
        damage_mult = 1.0 + minutes * ENEMY_DAMAGE_SCALE_PER_MIN
        speed_mult = min(ENEMY_SPEED_SCALE_CAP, 1.0 + minutes * ENEMY_SPEED_SCALE_PER_MIN)

        if elite:
            health_mult *= ELITE_HEALTH_MULT
            damage_mult *= ELITE_DAMAGE_MULT

        # Chaos is baked in at spawn, so raising it mid-run makes the *next*
        # wave nastier rather than retroactively buffing everything on screen.
        health_mult *= 1.0 + chaos * CHAOS_HEALTH_PER_LEVEL
        damage_mult *= 1.0 + chaos * CHAOS_DAMAGE_PER_LEVEL

        self.max_health = archetype.health * health_mult
        self.health = self.max_health
        self.contact_damage = archetype.contact_damage * damage_mult
        self.speed = archetype.speed * speed_mult
        self.xp_value = (archetype.xp * (ELITE_XP_MULT if elite else 1.0)
                         * (1.0 + chaos * CHAOS_XP_PER_LEVEL))
        self.damage_mult = damage_mult

        self.hit_flash = 0.0
        self.knockback = pygame.Vector2()
        self.separation = pygame.Vector2()
        self.statuses = {}
        self.from_altar = False      # set by the director for summoned Wardens

        self.shoot_timer = 0.0
        self.burst_left = 0
        self.burst_timer = 0.0
        self.use_fan = False
        if archetype.shoot:
            # Stagger initial cooldowns so a wave does not volley in lockstep.
            self.shoot_timer = archetype.shoot.interval * 0.5

    @property
    def is_boss(self):
        return self.archetype.is_boss

    # -- statuses ------------------------------------------------------------
    def apply_status(self, spec):
        existing = self.statuses.get(spec.key)
        if existing is None:
            self.statuses[spec.key] = ActiveStatus(spec)
        else:
            existing.refresh(spec)

    @property
    def speed_scale(self):
        """Movement multiplier after the strongest active slow."""
        if not self.statuses:
            return 1.0
        slow = max(s.slow for s in self.statuses.values())
        if self.is_boss:
            slow = min(slow, BOSS_SLOW_CAP)
        return max(0.0, 1.0 - slow)

    def dominant_status(self):
        """The status with the most time left — the one worth showing."""
        if not self.statuses:
            return None
        return max(self.statuses.values(), key=lambda s: s.remaining)

    def take_damage(self, amount, knockback_from=None, knockback_force=140.0):
        self.health -= amount
        self.hit_flash = HIT_FLASH_TIME
        if knockback_from is not None and not self.is_boss:
            away = self.pos - knockback_from
            if away.length_squared() > 0:
                force = knockback_force * (0.35 if self.elite else 1.0)
                self.knockback += away.normalize() * force
        if self.health <= 0:
            self.kill()
        return amount

    def update(self, dt, player_pos, arena, projectiles, rng):
        self.hit_flash = max(0.0, self.hit_flash - dt)

        to_player = player_pos - self.pos
        distance = to_player.length()
        direction = to_player / distance if distance > 0.001 else pygame.Vector2()

        velocity = direction * (self.speed * self.speed_scale) + self.separation
        if self.knockback.length_squared() > 1:
            velocity += self.knockback
            self.knockback *= max(0.0, 1.0 - 8.0 * dt)
        else:
            self.knockback.update(0, 0)

        half = self.size * 0.4
        self.pos, blocked_x, blocked_y = arena.move_and_slide(self.pos, half, half, velocity * dt)
        # Nudge along the wall when a cluster blocks the direct line, so enemies
        # round obstacles instead of grinding into them forever.
        if blocked_x and abs(direction.y) < 0.25:
            self.pos.y += math.copysign(self.speed * dt * 0.8, direction.y or 1)
        if blocked_y and abs(direction.x) < 0.25:
            self.pos.x += math.copysign(self.speed * dt * 0.8, direction.x or 1)

        self.separation.update(0, 0)

        if self.archetype.shoot:
            self._update_shooting(dt, player_pos, distance, projectiles)

    def _update_shooting(self, dt, player_pos, distance, projectiles):
        pattern = self.archetype.shoot
        self.shoot_timer -= dt
        self.burst_timer -= dt

        if self.burst_left > 0:
            if self.burst_timer <= 0:
                self._fire(player_pos, projectiles, pattern, spread=0.0)
                self.burst_left -= 1
                self.burst_timer = pattern.burst_delay
            return

        if self.shoot_timer <= 0 and distance <= pattern.range:
            if self.is_boss and self.use_fan:
                self._fire_fan(player_pos, projectiles, pattern)
                self.use_fan = False
            else:
                self.burst_left = pattern.burst
                self.burst_timer = 0.0
                self.use_fan = True
            self.shoot_timer = pattern.interval

    def _aim(self, player_pos):
        to_player = player_pos - self.pos
        if to_player.length_squared() < 0.001:
            return pygame.Vector2(0, 1)
        return to_player.normalize()

    def _fire(self, player_pos, projectiles, pattern, spread=0.0):
        direction = self._aim(player_pos)
        if spread:
            direction = direction.rotate(spread)
        projectiles.append(
            EnemyProjectile(self.pos, direction, pattern.speed, pattern.damage * self.damage_mult)
        )

    def _fire_fan(self, player_pos, projectiles, pattern):
        count = pattern.fan or 3
        for i in range(count):
            offset = (i - (count - 1) / 2) * pattern.fan_spread
            self._fire(player_pos, projectiles, pattern, spread=offset)

    def draw(self, painter, camera):
        screen_pos = camera.to_screen(self.pos)
        rect = self.image.get_rect(center=screen_pos)
        painter.blit(self.image, rect)

        status = self.dominant_status()
        if status is not None:
            tintmap = enemy_silhouette(self.archetype, self.elite, status.color)
            # Pulse so a burning enemy reads as burning rather than repainted,
            # and fade out as the effect expires.
            pulse = 0.72 + 0.28 * math.sin(status.remaining * 11.0)
            tintmap.set_alpha(int(120 * pulse * min(1.0, status.remaining / 0.35)))
            painter.blit(tintmap, rect)

        if self.hit_flash > 0:
            flash = enemy_flash(self.archetype, self.elite)
            flash.set_alpha(int(210 * min(1.0, self.hit_flash / HIT_FLASH_TIME)))
            painter.blit(flash, rect)

        # Health bars only for the things worth tracking. Drawing one over every
        # trash mob turns a 200-enemy screen into unreadable noise.
        if (self.elite or self.is_boss) and settings.current.health_bars:
            ratio = self.health / self.max_health
            width = rect.width + 8
            draw_bar(painter, rect.centerx - width // 2, rect.top - 9, width, 5,
                     ratio, health_bar_color(ratio))


class EnemyProjectile(Entity):
    def __init__(self, pos, direction, speed, damage):
        super().__init__(pos, 14)
        self.vel = pygame.Vector2(direction) * speed
        self.damage = damage
        self.life = 4.0

    def update(self, dt, arena):
        self.pos += self.vel * dt
        self.life -= dt
        if self.life <= 0 or arena.is_wall_point(self.pos.x, self.pos.y):
            self.kill()

    def draw(self, painter, camera):
        sx, sy = camera.to_screen(self.pos)
        painter.circle((255, 110, 80), (int(sx), int(sy)), 7)
        painter.circle((255, 210, 170), (int(sx), int(sy)), 3)


# ---------------------------------------------------------------------------
# Pickups
# ---------------------------------------------------------------------------

class Pickup(Entity):
    """Base for magnetised drops. Homes straight in once you come near.

    Deliberately *not* a velocity-and-acceleration model. Steering a stored
    velocity vector toward a moving target is orbital mechanics: every frame the
    player strafes, the drop banks a little sideways velocity, and with nothing
    to cancel it the drop settles into a stable orbit and circles forever. That
    is exactly the "gems ring around me instead of being collected" behaviour.

    Moving straight down the line to the player each frame, at a speed that only
    ramps up, cannot accumulate a tangential component — so capture is
    guaranteed rather than merely likely.
    """

    pull_start = 190.0
    pull_accel = 2600.0
    max_pull = 950.0

    def __init__(self, pos, size):
        super().__init__(pos, size)
        self.speed = 0.0
        self.attracted = False
        self.age = 0.0

    def update(self, dt, player):
        self.age += dt
        offset = player.pos - self.pos
        distance = offset.length()

        if distance <= player.pickup_radius:
            self.attracted = True
        if not self.attracted:
            return False

        if distance <= player.radius + self.radius:
            return True

        self.speed = min(self.max_pull, max(self.speed, self.pull_start) + self.pull_accel * dt)
        step = self.speed * dt
        # Collect rather than overshoot when a single step would carry the drop
        # past the player — otherwise fast drops can tunnel straight through.
        if step >= distance:
            return True

        self.pos += offset / distance * step
        return False


# A gem glints briefly, then waits. Each gem gets a random phase so a field of
# two hundred shimmers instead of pulsing in unison, and only about a sixth are
# lit at any moment — the effect should read as scattered treasure catching the
# light, not as a strobe.
SPARKLE_CYCLE = 2.2
SPARKLE_FLASH = 0.34


class Gem(Pickup):
    def __init__(self, pos, xp_value):
        size = int(min(34, 14 + xp_value * 0.16))
        super().__init__(pos, size)
        self.xp_value = xp_value
        self.image = pygame.transform.smoothscale(assets.images["gem"], (size, size))
        self.phase = random.uniform(0.0, SPARKLE_CYCLE)

    @property
    def amount(self):
        return self.xp_value

    def draw(self, painter, camera):
        sx, sy = camera.to_screen(self.pos)
        painter.blit(self.image, self.image.get_rect(center=(sx, sy)))

        elapsed = (self.age + self.phase) % SPARKLE_CYCLE
        if elapsed >= SPARKLE_FLASH:
            return

        # Grow then shrink across the flash, so it twinkles rather than blinks.
        progress = elapsed / SPARKLE_FLASH
        scale = math.sin(progress * math.pi)
        arm = max(1, int(self.size * 0.42 * scale))
        cx = int(sx + self.size * 0.22)
        cy = int(sy - self.size * 0.24)
        color = (235, 252, 255)
        painter.line(color, (cx - arm, cy), (cx + arm, cy))
        painter.line(color, (cx, cy - arm), (cx, cy + arm))
        if arm > 2:
            painter.circle((255, 255, 255), (cx, cy), 1)


class Magnet(Pickup):
    """Pulls every gem on the map to you. The payoff for a long kiting trail."""

    def __init__(self, pos):
        image = assets.images["magnet"]
        super().__init__(pos, image.get_width())
        self.image = image

    @property
    def amount(self):
        return 1

    def draw(self, painter, camera):
        sx, sy = camera.to_screen(self.pos)
        bob = math.sin(self.age * 3.2) * 2.0
        halo = 10 + int(3 * math.sin(self.age * 4.0))
        painter.circle((150, 110, 210), (int(sx), int(sy + bob)),
                           self.size // 2 + halo, 2)
        painter.blit(self.image, self.image.get_rect(center=(sx, sy + bob)))


class Coin(Pickup):
    def __init__(self, pos, value):
        super().__init__(pos, 16)
        self.value = value

    @property
    def amount(self):
        return self.value

    def draw(self, painter, camera):
        sx, sy = camera.to_screen(self.pos)
        painter.circle((255, 205, 80), (int(sx), int(sy)), 8)
        painter.circle((180, 130, 30), (int(sx), int(sy)), 8, 2)
        painter.circle((255, 240, 190), (int(sx) - 2, int(sy) - 2), 2)


class Potion(Pickup):
    """Heals a slice of max health. Rare, and the only healing you find."""

    def __init__(self, pos, heal_fraction):
        image = assets.images["potion"]
        super().__init__(pos, image.get_width())
        self.image = image
        self.heal_fraction = heal_fraction

    @property
    def amount(self):
        return self.heal_fraction

    def draw(self, painter, camera):
        painter.blit(self.image, self.image.get_rect(center=camera.to_screen(self.pos)))


_aura_cache = assets.register_cache({})

# Strength is quantised into this many cached surfaces. Additive blending
# ignores per-surface alpha, so brightness has to be baked into the pixels —
# and rebuilding a 600x600 surface every frame would be a megabyte of churn.
AURA_LEVELS = 10


def _aura_surface(radius, color, level=AURA_LEVELS - 1):
    """A soft radial glow for additive blitting, built once per strength step.

    Additive rather than a translucent tint: the ground varies more between
    grass tiles (48 to 60 in the green channel) than a tint of this strength
    adds, so a tinted aura simply vanished into the terrain. Adding light
    brightens whatever is underneath and reads on every tileset.
    """
    level = max(0, min(AURA_LEVELS - 1, int(level)))
    key = (radius, color, level)
    if key not in _aura_cache:
        size = radius * 2
        # Plain surface, no alpha: black adds nothing under BLEND_RGB_ADD.
        glow = pygame.Surface((size, size))
        strength = (level + 1) / AURA_LEVELS
        # Enough steps that the concentric bands blend into a gradient; these
        # surfaces are built once, so the cost is paid at load, not per frame.
        steps = 44
        for index in range(steps):
            band = radius * (1.0 - index / steps)
            intensity = (0.10 + 0.55 * (index / steps) ** 1.6) * strength
            shade = tuple(int(channel * intensity) for channel in color)
            pygame.draw.circle(glow, shade, (radius, radius), int(band))
        _aura_cache[key] = glow
    return _aura_cache[key]


class Altar(Entity):
    """Where you summon a Warden. The gate to the whole run, so it announces
    itself: oversized, and sitting in a glow that brightens as you approach."""

    aura_radius = 300
    aura_color = (150, 210, 235)

    def __init__(self, pos):
        image = assets.images["altar"]
        super().__init__(pos, image.get_width())
        self.image = image
        self.age = 0.0

    def update(self, dt):
        self.age += dt

    def nearness(self, player_pos):
        """0 at the edge of the aura, 1 standing on it."""
        distance = player_pos.distance_to(self.pos)
        return max(0.0, 1.0 - distance / self.aura_radius)

    def draw(self, painter, camera, player_pos):
        near = self.nearness(player_pos)
        # Always faintly lit so it can be spotted from across the field, and
        # much brighter up close so "am I near it?" answers itself.
        pulse = 0.86 + 0.14 * math.sin(self.age * 2.0)
        strength = (0.30 + 0.70 * near) * pulse

        glow = _aura_surface(self.aura_radius, self.aura_color,
                             strength * (AURA_LEVELS - 1))
        painter.blit(glow, glow.get_rect(center=camera.to_screen(self.pos)),
                     flags=pygame.BLEND_RGB_ADD)

        # A ring right at the edge of interaction range, so the moment E becomes
        # available is visible rather than guessed at.
        if near > 0:
            sx, sy = camera.to_screen(self.pos)
            ring = int(self.size * 1.5)
            painter.circle((170, 230, 245), (int(sx), int(sy)), ring,
                               max(1, int(1 + 2 * near)))

        bob = math.sin(self.age * 1.8) * 2.0
        painter.blit(self.image, self.image.get_rect(center=(camera.to_screen(self.pos)[0],
                                                            camera.to_screen(self.pos)[1] + bob)))


class Portal(Entity):
    """The way onward, opened by killing the Warden you summoned at the altar."""

    def __init__(self, pos, destination):
        image = assets.images["portal"]
        super().__init__(pos, image.get_width())
        self.image = image
        self.destination = destination
        self.age = 0.0

    def update(self, dt):
        self.age += dt

    def draw(self, painter, camera):
        sx, sy = camera.to_screen(self.pos)
        centre = (int(sx), int(sy))

        # Two counter-rotating rings so it reads as active from a long way off —
        # this is the thing the player is meant to walk toward.
        for index in range(3):
            phase = self.age * (1.4 - index * 1.6) + index * 1.9
            # Rings reach well past the sprite so the exit reads as a beacon
            # from across a field full of gems and ground effects.
            radius = int(self.size * (0.75 + index * 0.42 + 0.1 * math.sin(phase)))
            width = 4 - index
            color = ((120, 226, 240), (168, 120, 235), (96, 70, 170))[index]
            painter.circle(color, centre, radius, max(1, width))

        glow = 1.0 + 0.06 * math.sin(self.age * 3.1)
        scaled = pygame.transform.scale(
            self.image, (int(self.size * glow), int(self.size * glow)))
        painter.blit(scaled, scaled.get_rect(center=centre))


class Chest(Entity):
    """A locked cache. Costs gold, gives an upgrade. Does not move or magnetise."""

    def __init__(self, pos, cost):
        image = assets.images["chest"]
        super().__init__(pos, image.get_width())
        self.image = image
        self.cost = cost
        self.bob = 0.0

    def update(self, dt):
        self.bob += dt

    def draw(self, painter, camera):
        sx, sy = camera.to_screen(self.pos)
        lift = math.sin(self.bob * 2.4) * 2.0
        painter.blit(self.image, self.image.get_rect(center=(sx, sy + lift)))
