import pygame
import sys
import os
import math
import random

pygame.init()

SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
TILE_SIZE = 40

TILEMAP = [
    "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW",
    "W..........................................................W",
    "W.WWWWWWWWWWWWW...............WWWWWWWWWWWWWWWW.............W",
    "W.W...........W...............W..............W.............W",
    "W.W...........W...............W..............W.............W",
    "W.W...........W...............W..............W.............W",
    "W.W...........W............................................W",
    "W.W...........W..............................W.............W",
    "W.W...........W..............................W.............W",
    "W.WWWWWW.....................................W.............W",
    "W..............................WWWWWWWWWWWWWWW.............W",
    "W..........................................................W",
    "W..........................................................W",
    "W...................WWWWWWW.WW.WWWW........................W",
    "W...................W.............W........................W",
    "W...................W.............W........................W",
    "W..........................................................W",
    "W...................W.............W........................W",
    "W...................W.............W........................W",
    "W...................W.............W........................W",
    "W...................WWWWWWW.WWWWWWW........................W",
    "W..........................................................W",
    "W..........................................................W",
    "W.WWWWWWW.WWWWWWW......................WWWWWWWWWWWWWWWWW...W",
    "W.W.............W......................................W...W",
    "W.W.............W......................................W...W",
    "W.W.............W......................................W...W",
    "W.W.............W......................................W...W",
    "W.W.............W.....................W................W...W",
    "W.W.............W.....................W................W...W",
    "W.W.............W.....................W................W...W",
    "W.WWWWWWWWWWWWWWW.....................WWWWWWWWWWWWWWWWWW...W",
    "W..........................................................W",
    "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW",
]
assert all(len(row) == len(TILEMAP[0]) for row in TILEMAP), "TILEMAP rows have inconsistent lengths!"
MAP_WIDTH = len(TILEMAP[0]) * TILE_SIZE
MAP_HEIGHT = len(TILEMAP) * TILE_SIZE

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("DungeonCrawler")

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
try:
    wall_image = pygame.image.load(os.path.join(ASSETS_DIR, "wall.png")).convert_alpha()
    floor_image = pygame.image.load(os.path.join(ASSETS_DIR, "floor.png")).convert_alpha()
    knight_image = pygame.image.load(os.path.join(ASSETS_DIR, "knight.png")).convert_alpha()    
    scout_image = pygame.image.load(os.path.join(ASSETS_DIR, "enemy_scout.png")).convert_alpha()
    sentinel_image = pygame.image.load(os.path.join(ASSETS_DIR, "enemy_sentinel.png")).convert_alpha()
    guardian_image = pygame.image.load(os.path.join(ASSETS_DIR, "enemy_guardian.png")).convert_alpha()
    boss_image = pygame.image.load(os.path.join(ASSETS_DIR, "enemy_boss.png")).convert_alpha()
    gem_image = pygame.image.load(os.path.join(ASSETS_DIR, "gem.png")).convert_alpha()
    boss_altar_image = pygame.image.load(os.path.join(ASSETS_DIR, "boss_altar.png")).convert_alpha()
except pygame.error as e:
    print(f"Could not load asset images: {e}")
    pygame.quit()
    sys.exit()

FACING_ANGLES = {"up": 0, "left": 90, "down": 180, "right": 270}
FACING_VECTORS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

class Player(pygame.sprite.Sprite):
    def __init__(self, x, y, image, speed):
        super().__init__()
        self.rotated_images = {
            facing: pygame.transform.rotate(image, angle)
            for facing, angle in FACING_ANGLES.items()
        }
        self.facing = "down"
        self.image = self.rotated_images[self.facing]
        self.rect = self.image.get_rect(topleft=(x, y))
        self.speed = speed
        self.health = 100
        self.max_health = 100
        self.invincible_timer = 0
        self.facing = "down"
        self.attack_cooldown = 0
        self.attack_duration = 10   
        self.attack_timer = 0
        self.attack_range = 40
        self.attack_damage = 25
        self.level = 1
        self.xp = 0
        self.xp_to_next_level = 100
        self.knockback_x = 0
        self.knockback_y = 0
        self.knockback_timer = 0
        self.enemies_hit_this_attack = set()
        self.auto_attack_timer = 0
        self.auto_attack_interval = 60
        self.has_longbow = False
        self.has_sword = True
        self.ranged_attack_timer = 0
        self.ranged_attack_interval = 60
        self.ranged_damage = 15
        self.pending_level_ups = 0
        self.upgrade_choices = []
        self.pierce_count = 0
        self.ranged_projectile_speed = 8
        self.ranged_shot_count = 1
        self.lvl_rapid_fire = 0
        self.lvl_sharp_bolts = 0
        self.lvl_swift_bolts = 0
        self.lvl_multi_shot = 0
        self.lvl_swift_strikes = 0
        self.lvl_sharpen_sword = 0
        self.lvl_phantom_sword = 0
        self.lvl_max_health = 0
        self.lvl_global_damage = 0
        self.has_rapier = False
        self.rapier_damage = 12
        self.rapier_attack_interval = 45
        self.rapier_attack_timer = 0
        self.rapier_thrust_count = 3
        self.rapier_thrust_length = 50
        self.rapier_speed = 12
        self.lvl_rapier_damage = 0
        self.lvl_rapier_count = 0
        self.lvl_rapier_speed = 0
        self.lvl_rapier_size = 0

    def gain_xp(self, amount):
        self.xp += amount
        while self.xp >= self.xp_to_next_level:
            self.xp -= self.xp_to_next_level
            self.level += 1
            self.xp_to_next_level = int(self.xp_to_next_level * 1.3)

            self.max_health += 15
            self.attack_damage += 5
            self.health = self.max_health   
            self.pending_level_ups += 1     

    def attack(self):
        if self.attack_cooldown == 0:
            self.attack_timer = self.attack_duration
            self.attack_cooldown = 30
            self.enemies_hit_this_attack = set()  

    def get_attack_rect(self):
        if self.attack_timer <= 0:
            return None

        if self.facing == "up":
            return pygame.Rect(self.rect.centerx - 20, self.rect.top - self.attack_range, 40, self.attack_range)
        elif self.facing == "down":
            return pygame.Rect(self.rect.centerx - 20, self.rect.bottom, 40, self.attack_range)
        elif self.facing == "left":
            return pygame.Rect(self.rect.left - self.attack_range, self.rect.centery - 20, self.attack_range, 40)
        elif self.facing == "right":
            return pygame.Rect(self.rect.right, self.rect.centery - 20, self.attack_range, 40)

    def apply_knockback(self, source_rect, strength=8):
        dx = self.rect.centerx - source_rect.centerx
        dy = self.rect.centery - source_rect.centery
        distance = max((dx**2 + dy**2) ** 0.5, 1)
        self.knockback_x = (dx / distance) * strength
        self.knockback_y = (dy / distance) * strength
        self.knockback_timer = 10

    def handle_input(self, keys):
        if self.knockback_timer > 0:
            new_x = self.rect.x + self.knockback_x
            new_y = self.rect.y + self.knockback_y
            self.knockback_x *= 0.85   
            self.knockback_y *= 0.85

            if self.knockback_x > 0:
                if not is_wall(new_x + self.rect.width - 1, self.rect.y):
                    self.rect.x = new_x
            elif self.knockback_x < 0:
                if not is_wall(new_x, self.rect.y):
                    self.rect.x = new_x

            if self.knockback_y > 0:
                if not is_wall(self.rect.x, new_y + self.rect.height - 1):
                    self.rect.y = new_y
            elif self.knockback_y < 0:
                if not is_wall(self.rect.x, new_y):
                    self.rect.y = new_y
            return   
        
        new_x, new_y = self.rect.x, self.rect.y

        if keys[pygame.K_a]:
            new_x -= self.speed
            self.facing = "left"
        if keys[pygame.K_d]:
            new_x += self.speed
            self.facing = "right"
        if keys[pygame.K_w]:
            new_y -= self.speed
            self.facing = "up"
        if keys[pygame.K_s]:
            new_y += self.speed
            self.facing = "down"

        if keys[pygame.K_d]:
            if not is_wall(new_x + self.rect.width - 1, self.rect.y):
                self.rect.x = new_x
        elif keys[pygame.K_a]:
            if not is_wall(new_x, self.rect.y):
                self.rect.x = new_x

        if keys[pygame.K_s]:
            if not is_wall(self.rect.x, new_y + self.rect.height - 1):
                self.rect.y = new_y
        elif keys[pygame.K_w]:
            if not is_wall(self.rect.x, new_y):
                self.rect.y = new_y

    def update(self):
        if self.invincible_timer > 0:
            self.invincible_timer -= 1
        if self.attack_cooldown > 0:
            self.attack_cooldown -= 1
        if self.attack_timer > 0:
            self.attack_timer -= 1
        if self.knockback_timer > 0:
            self.knockback_timer -= 1

        self.auto_attack_timer += 1
        if self.auto_attack_timer >= self.auto_attack_interval:
            self.auto_attack_timer = 0
            self.attack()
        if self.has_longbow and self.ranged_attack_timer > 0:
            self.ranged_attack_timer -= 1
        if self.has_rapier and self.rapier_attack_timer > 0:
            self.rapier_attack_timer -= 1

    def draw(self, screen, camera_x, camera_y):
        if self.invincible_timer == 0 or self.invincible_timer % 10 < 5:
            self.image = self.rotated_images[self.facing]
            screen.blit(self.image, (self.rect.x - camera_x, self.rect.y - camera_y))

        attack_rect = self.get_attack_rect()
        if attack_rect:
            alpha = int(255 * (self.attack_timer / self.attack_duration))
            flash_surface = pygame.Surface((attack_rect.width, attack_rect.height), pygame.SRCALPHA)
            flash_surface.fill((255, 255, 100, alpha))
            screen.blit(flash_surface, (attack_rect.x - camera_x, attack_rect.y - camera_y))
class Enemy(pygame.sprite.Sprite):
    def __init__(self, x, y, image, speed, health, xp_reward=10):
        super().__init__()
        self.image = image
        self.rect = self.image.get_rect(topleft=(x, y))
        self.speed = speed
        self.health = health
        self.max_health = health
        self.xp_reward = xp_reward   
        self.hit_flash_timer = 0
        self.hit_flash_duration = 8

    def chase(self, player_rect):
        dx = player_rect.centerx - self.rect.centerx
        dy = player_rect.centery - self.rect.centery
        distance = max((dx**2 + dy**2) ** 0.5, 1)

        move_x = (dx / distance) * self.speed
        move_y = (dy / distance) * self.speed

        new_x = self.rect.x + move_x
        new_y = self.rect.y + move_y

        if move_x > 0:
            if not is_wall(new_x + self.rect.width - 1, self.rect.y):
                self.rect.x = new_x
        elif move_x < 0:
            if not is_wall(new_x, self.rect.y):
                self.rect.x = new_x

        if move_y > 0:
            if not is_wall(self.rect.x, new_y + self.rect.height - 1):
                self.rect.y = new_y
        elif move_y < 0:
            if not is_wall(self.rect.x, new_y):
                self.rect.y = new_y

    def take_damage(self, amount):
        self.health -= amount
        self.hit_flash_timer = self.hit_flash_duration
        if self.health <= 0:
            self.kill()

    def update(self):
        if self.hit_flash_timer > 0:
            self.hit_flash_timer -= 1

    def draw(self, screen, camera_x, camera_y):
        screen.blit(self.image, (self.rect.x - camera_x, self.rect.y - camera_y))
        if self.hit_flash_timer > 0:
            flash_surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
            flash_surface.fill((255, 255, 255, 150))
            screen.blit(flash_surface, (self.rect.x - camera_x, self.rect.y - camera_y))

        bar_x = self.rect.x - camera_x
        bar_y = self.rect.y - camera_y - 10
        draw_health_bar(screen, bar_x, bar_y, self.rect.width, 5, self.health, self.max_health)

class Boss(Enemy):
    def __init__(self, x, y, image, speed, health, xp_reward=10):
        super().__init__(x, y, image, speed, health, xp_reward)
        self.special_cooldown = 0
        self.special_interval = 150
        self.current_special = "fan"   # which one fires next; alternates after each use
        self.burst_shots_left = 0
        self.burst_delay = 8
        self.burst_timer = 0

    def update(self):
        super().update()
        if self.special_cooldown > 0:
            self.special_cooldown -= 1
        if self.burst_timer > 0:
            self.burst_timer -= 1

    def try_special_attack(self, player_rect, projectile_group):
        if self.special_cooldown == 0 and self.burst_shots_left == 0:
            if self.current_special == "fan":
                self._fire_fan(player_rect, projectile_group)
                self.current_special = "burst"
            else:
                self.burst_shots_left = 3
                self.current_special = "fan"
            self.special_cooldown = self.special_interval

        if self.burst_shots_left > 0 and self.burst_timer == 0:
            self._fire_single(player_rect, projectile_group)
            self.burst_shots_left -= 1
            self.burst_timer = self.burst_delay

    def _fire_single(self, player_rect, projectile_group):
        dx = player_rect.centerx - self.rect.centerx
        dy = player_rect.centery - self.rect.centery
        distance = max((dx**2 + dy**2) ** 0.5, 1)
        projectile_group.add(Projectile(self.rect.centerx, self.rect.centery, dx/distance, dy/distance, speed=6, damage=20))

    def _fire_fan(self, player_rect, projectile_group):
        dx = player_rect.centerx - self.rect.centerx
        dy = player_rect.centery - self.rect.centery
        distance = max((dx**2 + dy**2) ** 0.5, 1)
        base_dx, base_dy = dx / distance, dy / distance

        for angle_deg in [-30, -10, 10, 30]:
            angle = math.radians(angle_deg)
            rdx = base_dx * math.cos(angle) - base_dy * math.sin(angle)
            rdy = base_dx * math.sin(angle) + base_dy * math.cos(angle)
            projectile_group.add(Projectile(self.rect.centerx, self.rect.centery, rdx, rdy, speed=6, damage=20))

class Guardian(Enemy):
    def __init__(self, x, y, image, speed, health, xp_reward=10):
        super().__init__(x, y, image, speed, health, xp_reward)
        self.special_cooldown = 0
        self.special_interval = 150
        self.burst_shots_left = 0
        self.burst_delay = 8   # frames between each shot in the burst
        self.burst_timer = 0

    def update(self):
        super().update()
        if self.special_cooldown > 0:
            self.special_cooldown -= 1
        if self.burst_timer > 0:
            self.burst_timer -= 1

    def try_special_attack(self, player_rect, projectile_group):
        if self.special_cooldown == 0 and self.burst_shots_left == 0:
            self.burst_shots_left = 3
            self.special_cooldown = self.special_interval

        if self.burst_shots_left > 0 and self.burst_timer == 0:
            dx = player_rect.centerx - self.rect.centerx
            dy = player_rect.centery - self.rect.centery
            distance = max((dx**2 + dy**2) ** 0.5, 1)
            projectile_group.add(Projectile(self.rect.centerx, self.rect.centery, dx/distance, dy/distance, speed=5, damage=15))
            self.burst_shots_left -= 1
            self.burst_timer = self.burst_delay

class Sentinel(Enemy):
    def __init__(self, x, y, image, speed, health, xp_reward=10):
        super().__init__(x, y, image, speed, health, xp_reward)
        self.special_cooldown = 0
        self.special_interval = 120   

    def update(self):
        super().update()   
        if self.special_cooldown > 0:
            self.special_cooldown -= 1

    def try_special_attack(self, player_rect, projectile_group):
        if self.special_cooldown == 0:
            dx = player_rect.centerx - self.rect.centerx
            dy = player_rect.centery - self.rect.centery
            distance = max((dx**2 + dy**2) ** 0.5, 1)
            projectile_group.add(Projectile(self.rect.centerx, self.rect.centery, dx/distance, dy/distance, speed=4, damage=15))
            self.special_cooldown = self.special_interval

def find_nearest_enemy(player_rect, enemy_group):
    nearest = None
    nearest_distance = float("inf")
    for e in enemy_group:
        dx = e.rect.centerx - player_rect.centerx
        dy = e.rect.centery - player_rect.centery
        distance = (dx**2 + dy**2) ** 0.5
        if distance < nearest_distance:
            nearest_distance = distance
            nearest = e
    return nearest

def draw_tilemap(surface, camera_x, camera_y):
    for row_index, row in enumerate(TILEMAP):
        for col_index, tile_char in enumerate(row):
            world_x = col_index * TILE_SIZE
            world_y = row_index * TILE_SIZE
            screen_x = world_x - camera_x
            screen_y = world_y - camera_y

            if -TILE_SIZE <= screen_x < SCREEN_WIDTH and -TILE_SIZE <= screen_y < SCREEN_HEIGHT:
                if tile_char == "W":
                    surface.blit(wall_image, (screen_x, screen_y))
                else:
                    surface.blit(floor_image, (screen_x, screen_y))

def draw_health_bar(screen, x, y, width, height, current, maximum, color_by_health=True, fixed_color=(60, 200, 90)):
    ratio = max(0, current) / maximum

    if color_by_health:
        if ratio > 0.5:
            fill_color = (60, 200, 90)
        elif ratio > 0.25:
            fill_color = (230, 200, 60)
        else:
            fill_color = (220, 60, 60)
    else:
        fill_color = fixed_color

    pygame.draw.rect(screen, (40, 40, 40), (x, y, width, height))
    pygame.draw.rect(screen, fill_color, (x, y, int(width * ratio), height))
    pygame.draw.rect(screen, (10, 10, 10), (x, y, width, height), 1)  

class Gem(pygame.sprite.Sprite):
    def __init__(self, x, y, xp_value, image):
        super().__init__()
        size = min(36, 14 + xp_value // 5)
        self.image = pygame.transform.scale(image, (size, size))
        self.rect = self.image.get_rect(center=(x, y))
        self.xp_value = xp_value
        self.pull_speed = 7

    def update(self, player_rect, magnet_radius):
        dx = player_rect.centerx - self.rect.centerx
        dy = player_rect.centery - self.rect.centery
        distance = (dx**2 + dy**2) ** 0.5

        if 0 < distance <= magnet_radius:
            self.rect.x += (dx / distance) * self.pull_speed
            self.rect.y += (dy / distance) * self.pull_speed

def upgrade_unlock_rapier(player):
    player.has_rapier = True

def upgrade_rapier_damage(player):
    player.rapier_damage += 5
    player.lvl_rapier_damage += 1

def upgrade_rapier_count(player):
    player.rapier_thrust_count += 1
    player.lvl_rapier_count += 1

def upgrade_rapier_speed(player):
    player.rapier_attack_interval = max(12, player.rapier_attack_interval - 5)
    player.lvl_rapier_speed += 1

def upgrade_rapier_size(player):
    player.rapier_thrust_length += 12
    player.lvl_rapier_size += 1

def upgrade_swift_strikes(player):
    player.auto_attack_interval = max(20, player.auto_attack_interval - 10)
    player.lvl_swift_strikes +=1

def upgrade_sharpen_sword(player):
    player.attack_damage += 6
    player.lvl_sharpen_sword +=1

def upgrade_phantom_sword(player):
    player.attack_range += 8
    player.lvl_phantom_sword += 1

def upgrade_unlock_sword(player):
    player.has_sword = True

def upgrade_health(player):
    player.max_health += 20
    player.health = player.max_health
    player.lvl_max_health += 1

def upgrade_damage(player):
    player.attack_damage += 6
    player.ranged_damage += 6
    player.lvl_global_damage += 1

def upgrade_unlock_ranged(player):
    player.has_longbow = True

def upgrade_rapid_fire(player):
    player.ranged_attack_interval = max(15, player.ranged_attack_interval - 8)
    player.lvl_rapid_fire += 1

def upgrade_sharp_bolts(player):
    player.ranged_damage += 6
    player.lvl_sharp_bolts += 1

def upgrade_swift_bolts(player):
    player.ranged_projectile_speed += 2
    player.lvl_swift_bolts += 1

def upgrade_multi_shot(player):
    player.ranged_shot_count += 1
    player.lvl_multi_shot += 1

def upgrade_pierce(player):
    player.pierce_count = min(player.pierce_count + 1, 5)


UPGRADE_POOL = [
    {"name": "Short Sword", "description": "Slash infront of you dealing damage",
     "apply": upgrade_unlock_sword, "unlocks_flag": "has_sword"},
    {"name": "Swift Strikes", "description": "Faster attacks", "apply": upgrade_swift_strikes,
     "requires_flag": "has_sword", "level_attr": "lvl_swift_strikes", "max_level": 10},
    {"name": "Sharpen Sword", "description": "Increases attack damage", "apply": upgrade_sharpen_sword,
     "requires_flag": "has_sword", "level_attr": "lvl_sharpen_sword", "max_level": 10},
    {"name": "Phantom Sword", "description": "Increases the range the sword strikes", "apply": upgrade_phantom_sword,
     "requires_flag": "has_sword", "level_attr": "lvl_phantom_sword", "max_level": 10},

    {"name": "+20 Max Health", "description": "Increase max health and heal", "apply": upgrade_health,
     "level_attr": "lvl_max_health", "max_level": 20},
    {"name": "+6 Global Damage", "description": "Increase global damage", "apply": upgrade_damage,
     "level_attr": "lvl_global_damage", "max_level": 20},

    {"name": "Homing Shot", "description": "Auto-fires at the nearest enemy",
     "apply": upgrade_unlock_ranged, "unlocks_flag": "has_longbow"},
    {"name": "Rapid Fire", "description": "Homing shots fire faster", "apply": upgrade_rapid_fire,
     "requires_flag": "has_longbow", "level_attr": "lvl_rapid_fire", "max_level": 10},
    {"name": "Sharpened Bolts", "description": "Homing shots deal more damage", "apply": upgrade_sharp_bolts,
     "requires_flag": "has_longbow", "level_attr": "lvl_sharp_bolts", "max_level": 10},
    {"name": "Swift Bolts", "description": "Homing shots travel faster", "apply": upgrade_swift_bolts,
     "requires_flag": "has_longbow", "level_attr": "lvl_swift_bolts", "max_level": 10},
    {"name": "Multi Shot", "description": "Fire an additional homing shot", "apply": upgrade_multi_shot,
     "requires_flag": "has_longbow", "level_attr": "lvl_multi_shot", "max_level": 5},
    {"name": "Piercing Shot", "description": "Homing shots pass through more enemies", "apply": upgrade_pierce,
     "requires_flag": "has_longbow", "level_attr": "pierce_count", "max_level": 5},

    {"name": "Rapier", "description": "Rapid thrusts that fan out ahead of you",
     "apply": upgrade_unlock_rapier, "unlocks_flag": "has_rapier"},
    {"name": "Honed Point", "description": "Thrusts deal more damage", "apply": upgrade_rapier_damage,
     "requires_flag": "has_rapier", "level_attr": "lvl_rapier_damage", "max_level": 10},
    {"name": "Flurry", "description": "Add another thrust to the fan", "apply": upgrade_rapier_count,
     "requires_flag": "has_rapier", "level_attr": "lvl_rapier_count", "max_level": 5},
    {"name": "Quickstep", "description": "Thrust more frequently", "apply": upgrade_rapier_speed,
     "requires_flag": "has_rapier", "level_attr": "lvl_rapier_speed", "max_level": 6},
    {"name": "Extended Reach", "description": "Thrusts strike further", "apply": upgrade_rapier_size,
     "requires_flag": "has_rapier", "level_attr": "lvl_rapier_size", "max_level": 8},
]

def _validate_upgrade_pool():
    probe = Player(0, 0, knight_image, speed=5)
    for upgrade in UPGRADE_POOL:
        for key in ("requires_flag", "unlocks_flag", "level_attr"):
            attr = upgrade.get(key)
            if attr:
                assert hasattr(probe, attr), f"{upgrade['name']}: '{attr}' is not a Player attribute"
        if upgrade.get("level_attr"):
            assert "max_level" in upgrade, f"{upgrade['name']}: has level_attr but no max_level"

_validate_upgrade_pool()

def get_available_upgrades(player):
    available = []
    for upgrade in UPGRADE_POOL:
        required = upgrade.get("requires_flag")
        if required and not getattr(player, required):
            continue

        unlocks = upgrade.get("unlocks_flag")
        if unlocks and getattr(player, unlocks):
            continue

        level_attr = upgrade.get("level_attr")
        if level_attr and getattr(player, level_attr) >= upgrade["max_level"]:
            continue

        available.append(upgrade)
    return available

def get_upgrade_option_rect(index):
    y = 280 + index * 100
    return pygame.Rect(SCREEN_WIDTH // 2 - 250, y, 500, 80)

class Projectile(pygame.sprite.Sprite):
    def __init__(self, x, y, dir_x, dir_y, speed, damage, color=(255, 90, 60, 255), pierce=0):
        super().__init__()
        self.image = pygame.Surface((14, 14), pygame.SRCALPHA)
        pygame.draw.circle(self.image, color, (7, 7), 7)
        self.rect = self.image.get_rect(center=(x, y))
        self.dir_x = dir_x
        self.dir_y = dir_y
        self.speed = speed
        self.damage = damage
        self.pierce = pierce
        self.enemies_hit = set()

    def update(self):
        self.rect.x += self.dir_x * self.speed
        self.rect.y += self.dir_y * self.speed
        if is_wall(self.rect.centerx, self.rect.centery):
            self.kill()   

class Thrust(Projectile):
    def __init__(self, x, y, dir_x, dir_y, speed, damage, length, max_travel):
        super().__init__(x, y, dir_x, dir_y, speed, damage,
                         color=(230, 230, 255, 220), pierce=99)
        base = pygame.Surface((length, 10), pygame.SRCALPHA)
        pygame.draw.rect(base, (235, 235, 255, 220), (0, 0, length, 10))
        pygame.draw.rect(base, (150, 170, 230, 255), (0, 0, length, 10), 1)
        angle = math.degrees(math.atan2(-dir_y, dir_x))
        self.image = pygame.transform.rotate(base, angle)
        self.rect = self.image.get_rect(center=(x, y))
        self.traveled = 0
        self.max_travel = max_travel

    def update(self):
        super().update()
        self.traveled += self.speed
        if self.traveled >= self.max_travel:
            self.kill()

def get_camera_offset(player_rect):
    camera_x = player_rect.centerx - SCREEN_WIDTH // 2
    camera_y = player_rect.centery - SCREEN_HEIGHT // 2

    camera_x = max(0, min(camera_x, MAP_WIDTH - SCREEN_WIDTH))
    camera_y = max(0, min(camera_y, MAP_HEIGHT - SCREEN_HEIGHT))

    return camera_x, camera_y

def is_wall(world_x, world_y):
    col = int(world_x // TILE_SIZE)
    row = int(world_y // TILE_SIZE)
    if row < 0 or row >= len(TILEMAP) or col < 0 or col >= len(TILEMAP[0]):
        return True
    return TILEMAP[row][col] == "W"

def get_menu_button_rect(index, total, button_width=300, button_height=60, gap=20):
    total_height = total * button_height + (total - 1) * gap
    start_y = SCREEN_HEIGHT // 2 - total_height // 2
    x = SCREEN_WIDTH // 2 - button_width // 2
    y = start_y + index * (button_height + gap)
    return pygame.Rect(x, y, button_width, button_height)

def draw_button_menu(title, options, title_color):
    title_font = pygame.font.SysFont(None, 72)
    title_text = title_font.render(title, True, title_color)
    screen.blit(title_text, title_text.get_rect(center=(SCREEN_WIDTH // 2, 150)))

    button_font = pygame.font.SysFont(None, 40)
    mouse_pos = pygame.mouse.get_pos()
    for i, label in enumerate(options):
        rect = get_menu_button_rect(i, len(options))
        is_hovered = rect.collidepoint(mouse_pos)
        box_color = (55, 55, 80) if is_hovered else (40, 40, 60)
        border_color = (255, 220, 80) if is_hovered else (200, 200, 220)
        pygame.draw.rect(screen, box_color, rect)
        pygame.draw.rect(screen, border_color, rect, 2)
        label_text = button_font.render(label, True, (255, 255, 255))
        screen.blit(label_text, label_text.get_rect(center=rect.center))

clock = pygame.time.Clock()

PAUSE_OPTIONS = ["Continue", "Restart", "Back to Main Menu", "Quit"]
START_OPTIONS = ["Start Game", "Quit Game"]
GAME_OVER_OPTIONS = ["Restart", "Back to Main Menu"]

ENEMY_TYPES = {
    "scout":    {"type": Enemy,    "image": scout_image,    "speed": 2, "health": 50, "xp_reward": 30},
    "sentinel": {"type": Sentinel, "image": sentinel_image, "speed": 2, "health": 75, "xp_reward": 45},
    "guardian": {"type": Guardian, "image": guardian_image, "speed": 1, "health": 120, "xp_reward": 75},
    "boss":     {"type": Boss,     "image": boss_image,     "speed": 2, "health": 200, "xp_reward": 150},
}


MIN_SPAWN_DISTANCE = 250   
MAX_SPAWN_DISTANCE = 600   

def random_spawn_position(player_rect):
    for _ in range(50):
        x = random.randint(TILE_SIZE, MAP_WIDTH - TILE_SIZE * 2)
        y = random.randint(TILE_SIZE, MAP_HEIGHT - TILE_SIZE * 2)

        dx = x - player_rect.centerx
        dy = y - player_rect.centery
        distance = (dx**2 + dy**2) ** 0.5

        if MIN_SPAWN_DISTANCE <= distance <= MAX_SPAWN_DISTANCE:
            if not is_wall(x, y) and not is_wall(x + TILE_SIZE, y + TILE_SIZE):
                return x, y

    return 23 * TILE_SIZE, 15 * TILE_SIZE  

def spawn_enemy_batch(spawn_list):
    for type_name, count in spawn_list:
        info = ENEMY_TYPES[type_name]
        for _ in range(count):
            x, y = random_spawn_position(player.rect)
            enemy_group.add(info["type"](x, y, info["image"], info["speed"], info["health"], info["xp_reward"]))

wave_announcement = ""
wave_announcement_timer = 0

SENTINEL_UNLOCK_TIME = 30    # seconds
GUARDIAN_UNLOCK_TIME = 45    # seconds
GUARDIAN_SPAWN_INTERVAL = 45 * 60   # frames between guardian waves, once unlocked

next_wave_timer = 0
scout_wave_count = 0         # grows every regular wave
guardian_spawn_timer = 0
sentinels_unlocked = False
guardians_unlocked = False
boss_active = False
boss_defeated = False

game_state = "start"
game_start_time = pygame.time.get_ticks()
pause_start_time = 0
final_message = ""

player = Player(2 * TILE_SIZE + 40, 2 * TILE_SIZE + 40, knight_image, speed=5)  
enemy_group = pygame.sprite.Group()
projectile_group = pygame.sprite.Group()
player_projectile_group = pygame.sprite.Group()
gem_group = pygame.sprite.Group()
MAGNET_RADIUS = TILE_SIZE + max(player.rect.width, player.rect.height) // 2
ALTAR_INTERACT_RADIUS = 70
boss_altar_rect = None

def place_boss_altar():
    for _ in range(50):
        x = random.randint(TILE_SIZE, MAP_WIDTH - TILE_SIZE * 2)
        y = random.randint(TILE_SIZE, MAP_HEIGHT - TILE_SIZE * 2)
        if not is_wall(x, y) and not is_wall(x + 48, y + 48):
            return pygame.Rect(x, y, 48, 48)
    return pygame.Rect(23 * TILE_SIZE, 15 * TILE_SIZE, 48, 48)


def reset_game():
    global player, next_wave_timer, scout_wave_count, guardian_spawn_timer
    global sentinels_unlocked, guardians_unlocked, boss_active, boss_altar_rect, game_start_time, boss_defeated
    next_wave_timer = random.randint(120, 180)
    scout_wave_count = 0
    guardian_spawn_timer = GUARDIAN_SPAWN_INTERVAL
    sentinels_unlocked = False
    guardians_unlocked = False
    boss_active = False
    boss_defeated = False
    boss_altar_rect = place_boss_altar()
    game_start_time = pygame.time.get_ticks()
    player.has_sword = True
    player.has_longbow = False

    player = Player(2 * TILE_SIZE + 40, 2 * TILE_SIZE + 40, knight_image, speed=5)

    projectile_group.empty()
    enemy_group.empty()
    player_projectile_group.empty()
    gem_group.empty()



running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if game_state == "playing":
                    game_state = "paused"
                    pause_start_time = pygame.time.get_ticks()
                elif game_state == "paused":
                    game_start_time += pygame.time.get_ticks() - pause_start_time
                    game_state = "playing"
            if game_state == "level_up" and event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                index = event.key - pygame.K_1
                if index < len(player.upgrade_choices):
                    chosen = player.upgrade_choices[index]
                    chosen["apply"](player)
                    player.pending_level_ups -= 1
                    game_state = "playing"

        if event.type == pygame.KEYDOWN and event.key == pygame.K_e:
            if game_state == "playing" and not boss_active and boss_altar_rect:
                if player.rect.colliderect(boss_altar_rect.inflate(ALTAR_INTERACT_RADIUS, ALTAR_INTERACT_RADIUS)):
                    info = ENEMY_TYPES["boss"]
                    enemy_group.add(info["type"](boss_altar_rect.centerx, boss_altar_rect.centery, info["image"], info["speed"], info["health"], info["xp_reward"]))
                    boss_active = True
                    wave_announcement = "The Boss has awakened!"
                    wave_announcement_timer = 120

        if game_state == "level_up" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i in range(len(player.upgrade_choices)):
                if get_upgrade_option_rect(i).collidepoint(event.pos):
                    chosen = player.upgrade_choices[i]
                    chosen["apply"](player)
                    player.pending_level_ups -= 1
                    game_state = "playing"
                    break

        if game_state == "start" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, label in enumerate(START_OPTIONS):
                if get_menu_button_rect(i, len(START_OPTIONS)).collidepoint(event.pos):
                    if label == "Start Game":
                        reset_game()
                        game_state = "playing"
                    elif label == "Quit Game":
                        running = False
                    break

        if game_state == "game_over" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, label in enumerate(GAME_OVER_OPTIONS):
                if get_menu_button_rect(i, len(GAME_OVER_OPTIONS)).collidepoint(event.pos):
                    if label == "Restart":
                        reset_game()
                        game_state = "playing"
                    elif label == "Back to Main Menu":
                        game_state = "start"
                    break

        if game_state == "paused" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, label in enumerate(PAUSE_OPTIONS):
                if get_menu_button_rect(i, len(PAUSE_OPTIONS)).collidepoint(event.pos):
                    if label == "Continue":
                        game_start_time += pygame.time.get_ticks() - pause_start_time
                        game_state = "playing"
                    elif label == "Restart":
                        reset_game()
                        game_state = "playing"
                    elif label == "Back to Main Menu":
                        game_state = "start"
                    elif label == "Quit":
                        running = False
                    break

    if game_state == "playing":               # NEW — 4 spaces
        if player.pending_level_ups > 0:      # line 749, already 8 spaces
            available = get_available_upgrades(player)
            if available:
                player.upgrade_choices = random.sample(available, min(3, len(available)))
                game_state = "level_up"
            else:
                player.pending_level_ups -= 1   # nothing left to offer; skip the menu
        else:

            elapsed_seconds = (pygame.time.get_ticks() - game_start_time) / 1000

            if not sentinels_unlocked and elapsed_seconds >= SENTINEL_UNLOCK_TIME:
                sentinels_unlocked = True
                wave_announcement = "Sentinels have joined the fight!"
                wave_announcement_timer = 120

            if not guardians_unlocked and elapsed_seconds >= GUARDIAN_UNLOCK_TIME:
                guardians_unlocked = True
                wave_announcement = "Guardians are approaching..."
                wave_announcement_timer = 120

            next_wave_timer -= 1
            if next_wave_timer <= 0:
                scout_wave_count = min(scout_wave_count + 3, 25)
                spawn_list = [("scout", random.randint(scout_wave_count, scout_wave_count + 3))]
                if sentinels_unlocked:
                    spawn_list.append(("sentinel", random.randint(1, 3)))
                spawn_enemy_batch(spawn_list)
                next_wave_timer = random.randint(420, 600)

            if guardians_unlocked:
                guardian_spawn_timer -= 1
                if guardian_spawn_timer <= 0:
                    spawn_enemy_batch([("guardian", random.randint(2, 4))])
                    guardian_spawn_timer = GUARDIAN_SPAWN_INTERVAL
            
        if boss_defeated:
            game_state = "game_over"
            final_message = "Victory!"

        keys = pygame.key.get_pressed()
        player.handle_input(keys)
        player.update()

        for e in enemy_group:
            e.chase(player.rect)
            e.update()
            if isinstance(e, Boss):
                e.try_special_attack(player.rect, projectile_group)
            if isinstance(e, Guardian):
                e.try_special_attack(player.rect, projectile_group)
            if isinstance(e, Sentinel):
                e.try_special_attack(player.rect, projectile_group)

        if player.has_longbow and player.ranged_attack_timer == 0:
            target = find_nearest_enemy(player.rect, enemy_group)
            if target:
                dx = target.rect.centerx - player.rect.centerx
                dy = target.rect.centery - player.rect.centery
                distance = max((dx**2 + dy**2) ** 0.5, 1)
                for i in range(player.ranged_shot_count):
                    spread = (i - (player.ranged_shot_count - 1) / 2) * 0.15
                    sdx = dx / distance * math.cos(spread) - dy / distance * math.sin(spread)
                    sdy = dx / distance * math.sin(spread) + dy / distance * math.cos(spread)
                    player_projectile_group.add(Projectile(
                        player.rect.centerx, player.rect.centery, sdx, sdy,
                        speed=player.ranged_projectile_speed, damage=player.ranged_damage,
                        color=(80, 180, 255, 255), pierce=player.pierce_count
                    ))
                player.ranged_attack_timer = player.ranged_attack_interval

        if player.has_rapier and player.rapier_attack_timer == 0:
            bx, by = FACING_VECTORS[player.facing]
            for i in range(player.rapier_thrust_count):
                spread = (i - (player.rapier_thrust_count - 1) / 2) * 0.35
                sdx = bx * math.cos(spread) - by * math.sin(spread)
                sdy = bx * math.sin(spread) + by * math.cos(spread)
                player_projectile_group.add(Thrust(
                    player.rect.centerx, player.rect.centery, sdx, sdy,
                    speed=player.rapier_speed,
                    damage=player.rapier_damage,
                    length=player.rapier_thrust_length,
                    max_travel=player.rapier_thrust_length + 40,
                ))
            player.rapier_attack_timer = player.rapier_attack_interval

        gem_group.update(player.rect, MAGNET_RADIUS)

        collected_gems = pygame.sprite.spritecollide(player, gem_group, dokill=True)
        for gem in collected_gems:
            player.gain_xp(gem.xp_value)
        player_projectile_group.update()
        projectile_group.update()
        proj_hits = pygame.sprite.spritecollide(player, projectile_group, dokill=True)
        for proj in player_projectile_group:
            hit_enemy = pygame.sprite.spritecollideany(proj, enemy_group)
            if hit_enemy and hit_enemy not in proj.enemies_hit:
                hit_enemy.take_damage(proj.damage)
                proj.enemies_hit.add(hit_enemy)
                if hit_enemy.health <= 0:
                    gem_group.add(Gem(hit_enemy.rect.centerx, hit_enemy.rect.centery, hit_enemy.xp_reward, gem_image))
                    if isinstance(hit_enemy, Boss):
                        boss_defeated = True
                if proj.pierce > 0:
                    proj.pierce -= 1
                else:
                    proj.kill()
                           
        attack_rect = player.get_attack_rect()
        if attack_rect:
            for e in enemy_group:
                if e not in player.enemies_hit_this_attack and attack_rect.colliderect(e.rect):
                    e.take_damage(player.attack_damage)
                    player.enemies_hit_this_attack.add(e)
                    if e.health <= 0:
                        gem_group.add(Gem(e.rect.centerx, e.rect.centery, e.xp_reward, gem_image))
                        if isinstance(e, Boss):
                            boss_defeated = True

        hits = pygame.sprite.spritecollide(player, enemy_group, dokill=False)
        if hits and player.invincible_timer == 0:
            player.health -= 10
            player.invincible_timer = 20
            player.apply_knockback(hits[0].rect)

        if player.health <= 0:
            game_state = "game_over"
            final_message = "You Died"

    screen.fill((10, 10, 30))

    if game_state == "start":
        draw_button_menu("Project Tby", START_OPTIONS, (0, 200, 255))

    elif game_state == "playing":
        camera_x, camera_y = get_camera_offset(player.rect)
        draw_tilemap(screen, camera_x, camera_y)
        player.draw(screen, camera_x, camera_y)
        for p in player_projectile_group:
            screen.blit(p.image, (p.rect.x - camera_x, p.rect.y - camera_y))
        for p in projectile_group:
            screen.blit(p.image, (p.rect.x - camera_x, p.rect.y - camera_y))
        for e in enemy_group:
            e.draw(screen, camera_x, camera_y)
        hp_font = pygame.font.SysFont(None, 36)
        for g in gem_group:
            screen.blit(g.image, (g.rect.x - camera_x, g.rect.y - camera_y))
        if wave_announcement_timer > 0:
            wave_font = pygame.font.SysFont(None, 60)
            wave_text = wave_font.render(wave_announcement, True, (255, 220, 80))
            screen.blit(wave_text, wave_text.get_rect(center=(SCREEN_WIDTH // 2, 80)))
        draw_health_bar(screen, 10, 10, 200, 24, player.health, player.max_health)
        hp_font = pygame.font.SysFont(None, 28)
        hp_text = hp_font.render(f"{player.health}/{player.max_health}", True, (255, 255, 255))
        screen.blit(hp_text, (15, 12))
        level_text = hp_font.render(f"Lv. {player.level}", True, (255, 255, 255))
        screen.blit(level_text, (10, 40))
        draw_health_bar(screen, 10, 65, 200, 16, player.xp, player.xp_to_next_level, color_by_health=False)
        xp_font = pygame.font.SysFont(None, 22)
        xp_text = xp_font.render(f"{player.xp}/{player.xp_to_next_level} XP", True, (255, 255, 50))
        screen.blit(xp_text, xp_text.get_rect(center=(10 + 100, 65 + 8)))
        seconds_survived = (pygame.time.get_ticks() - game_start_time) // 1000
        time_font = pygame.font.SysFont(None, 32)
        time_text = time_font.render(f"Time: {seconds_survived}s", True, (255, 255, 255))
        screen.blit(time_text, time_text.get_rect(topright=(SCREEN_WIDTH - 10, 10)))
        if boss_altar_rect and not boss_active:
            screen.blit(boss_altar_image, (boss_altar_rect.x - camera_x, boss_altar_rect.y - camera_y))
            if player.rect.colliderect(boss_altar_rect.inflate(ALTAR_INTERACT_RADIUS, ALTAR_INTERACT_RADIUS)):
                prompt_font = pygame.font.SysFont(None, 28)
                prompt_text = prompt_font.render("Press E to summon the Boss", True, (255, 220, 80))
                screen.blit(prompt_text, prompt_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 60)))

    
    elif game_state == "level_up":
        camera_x, camera_y = get_camera_offset(player.rect)
        draw_tilemap(screen, camera_x, camera_y)
        player.draw(screen, camera_x, camera_y)
        for e in enemy_group:
            e.draw(screen, camera_x, camera_y)

        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))

        title_font = pygame.font.SysFont(None, 60)
        title_text = title_font.render("LEVEL UP! Choose an upgrade", True, (255, 220, 80))
        screen.blit(title_text, title_text.get_rect(center=(SCREEN_WIDTH // 2, 150)))

        option_font = pygame.font.SysFont(None, 36)
        mouse_pos = pygame.mouse.get_pos()
        for i, choice in enumerate(player.upgrade_choices):
            rect = get_upgrade_option_rect(i)
            is_hovered = rect.collidepoint(mouse_pos)

            box_color = (55, 55, 80) if is_hovered else (40, 40, 60)
            border_color = (255, 220, 80) if is_hovered else (200, 200, 220)

            pygame.draw.rect(screen, box_color, rect)
            pygame.draw.rect(screen, border_color, rect, 2)

            name_text = option_font.render(f"{i+1}. {choice['name']}", True, (255, 255, 255))
            desc_text = option_font.render(choice['description'], True, (200, 200, 200))
            screen.blit(name_text, (rect.x + 20, rect.y + 10))
            screen.blit(desc_text, (rect.x + 20, rect.y + 45))

    elif game_state == "paused":
        camera_x, camera_y = get_camera_offset(player.rect)
        draw_tilemap(screen, camera_x, camera_y)
        player.draw(screen, camera_x, camera_y)
        for e in enemy_group:
            e.draw(screen, camera_x, camera_y)

        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))

        draw_button_menu("PAUSED", PAUSE_OPTIONS, (255, 220, 80))

    elif game_state == "game_over":
        draw_button_menu(final_message, GAME_OVER_OPTIONS, (255, 60, 60))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()