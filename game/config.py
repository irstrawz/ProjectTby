"""All tunable numbers live here.

Everything is in seconds and pixels — no frame counts. If you want to change how
the game feels, this is the file to open first.
"""

# --- Display -----------------------------------------------------------------
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60
CAPTION = "Project Tby"

# Largest timestep we will ever simulate. If the machine hitches, we slow the
# game down rather than let entities teleport through walls.
MAX_DT = 1 / 20

# --- Arena -------------------------------------------------------------------
TILE_SIZE = 40
ARENA_COLS = 110
ARENA_ROWS = 70
ARENA_WIDTH = ARENA_COLS * TILE_SIZE
ARENA_HEIGHT = ARENA_ROWS * TILE_SIZE

# Obstacle clusters are small and convex so enemies can always slide around them
# and no pocket is ever sealed off.
OBSTACLE_CLUSTERS = 90
OBSTACLE_CLUSTER_MIN = 2
OBSTACLE_CLUSTER_MAX = 6
# Nothing spawns inside this radius of the arena centre, so you always start clear.
SPAWN_CLEAR_RADIUS = 260

# --- Player ------------------------------------------------------------------
PLAYER_BASE_SPEED = 230.0        # px/sec
PLAYER_BASE_HEALTH = 100
PLAYER_BASE_PICKUP_RADIUS = 70.0
PLAYER_IFRAMES = 0.6             # seconds of invulnerability after a hit
PLAYER_CONTACT_KNOCKBACK = 210.0

# Rarity hands out about 1.47 levels per pick instead of 1, which pushed bot
# survival up ~18%. Levels cost a little more to claw most of that back
# without neutering the reward that rarity is supposed to be.
XP_FIRST_LEVEL = 68
XP_GROWTH = 1.18                 # each level costs this much more than the last
LEVEL_UP_HEAL = 0.15             # heal 15% of max HP, not a full refill

# Six slots each, the Vampire Survivors convention. Once a row is full the
# level-up pool stops offering new entries for it and only offers levels in what
# you already carry, so a run commits to a build instead of sprawling.
MAX_WEAPONS = 6
MAX_PASSIVES = 6

# --- Enemy scaling -----------------------------------------------------------
# Enemy stats grow with elapsed run time so your compounding damage does not
# outrun the threat. Multiplier at t minutes = 1 + t * RATE.
ENEMY_HEALTH_SCALE_PER_MIN = 0.62
ENEMY_DAMAGE_SCALE_PER_MIN = 0.16
ENEMY_SPEED_SCALE_PER_MIN = 0.035
ENEMY_SPEED_SCALE_CAP = 1.5

# Simulation costs ~2.3ms/frame at this count; the rest of the 16.6ms budget
# goes to drawing that many sprites.
MAX_ENEMIES = 280
# Enemies further than this from the player are recycled back into the spawn ring.
DESPAWN_DISTANCE = 1500.0

ENEMY_SEPARATION_RADIUS = 30.0
ENEMY_SEPARATION_FORCE = 190.0
SPATIAL_CELL = 64                # spatial-hash cell size for separation queries

ELITE_START_TIME = 75.0          # seconds before elites can appear
ELITE_CHANCE_PER_MIN = 0.035     # chance any given spawn is an elite, per minute
ELITE_CHANCE_CAP = 0.22
ELITE_HEALTH_MULT = 6.0
ELITE_DAMAGE_MULT = 1.6
ELITE_XP_MULT = 5.0
ELITE_SCALE = 1.45               # sprite size multiplier

# --- Wave director -----------------------------------------------------------
SPAWN_RING_MARGIN = 90.0         # how far outside the view enemies appear
BOSS_INTERVAL = 120.0            # first Warden at 2:00, then every 2:00
ALTAR_GOLD_BONUS = 25            # bonus gold for summoning a boss early

# --- Meta progression --------------------------------------------------------
# Trash gold was so thin (~10/min) that the first chest sat four minutes away
# and no realistic run ever opened one.
COIN_DROP_CHANCE = 0.08
COIN_VALUE = 2
ELITE_COIN_VALUE = 8
BOSS_COIN_VALUE = 40
GOLD_PER_MINUTE_SURVIVED = 6     # end-of-run payout

# --- Drops -------------------------------------------------------------------
POTION_DROP_CHANCE = 0.012       # per trash kill
ELITE_POTION_CHANCE = 0.25
POTION_HEAL_FRACTION = 0.28      # of max health

# Pulls every gem on the map to you. Rare on purpose — it is a payoff for
# the trail of experience you left behind while kiting, not a routine drop.
MAGNET_DROP_CHANCE = 0.006
ELITE_MAGNET_CHANCE = 0.09

# --- Chaos and Luck ----------------------------------------------------------
# Chaos is the only passive that makes the run harder. It has to pay for itself
# in experience, or nobody would ever take it.
CHAOS_HEALTH_PER_LEVEL = 0.18
CHAOS_DAMAGE_PER_LEVEL = 0.12
CHAOS_SPAWN_PER_LEVEL = 0.15
CHAOS_XP_PER_LEVEL = 0.32

# Luck has no rarity system to work against yet, so it leans on what exists:
# how often things drop, and how many choices a level-up puts in front of you.
LUCK_DROP_BONUS = 0.35           # multiplier on coin / potion / magnet chance
LUCK_EXTRA_CARD = 0.13           # chance per level of a fourth level-up option
LUCK_RARITY_BONUS = 0.10         # per level, tilts the rarity table upward
CHEST_LUCK_BONUS = 2.0           # a paid chest rolls friendlier than a level-up
MAX_LEVEL_UP_CARDS = 4

# --- Chests ------------------------------------------------------------------
# Chests spend the same gold you would otherwise bank for permanent upgrades,
# so every chest is a choice between this run and the next one.
CHEST_FIRST_DELAY = 20.0
CHEST_INTERVAL = 28.0
MAX_CHESTS = 3
# Low enough that a two-minute run can afford the first one; the growth rate
# is what makes later chests a real decision.
#
# The first chest appears 20 seconds in, and at 35 gold it was usually still
# unaffordable when you reached it — you walked the detour, read "Locked", and
# walked away. That is the worst possible first impression of a mechanic. At 16
# the opening chest is a genuine offer, and because the cost compounds the
# later ones land in nearly the same place: 16/27/46/78 against 35/59/101/171,
# so only the early game actually changes.
CHEST_BASE_COST = 16
CHEST_COST_GROWTH = 1.7
CHEST_MIN_DISTANCE = 480.0       # from the player, so it needs a detour
CHEST_MAX_DISTANCE = 1150.0
CHEST_INTERACT_RADIUS = 80.0
CHEST_FALLBACK_GOLD = 60         # paid out when there is nothing left to learn

SAVE_FILENAME = "savegame.json"

# --- Palette -----------------------------------------------------------------
COL_BG = (10, 10, 22)
COL_TEXT = (238, 240, 250)
COL_DIM = (150, 155, 175)
COL_GOLD = (255, 205, 80)
COL_XP = (110, 200, 255)
COL_HP_GOOD = (70, 205, 100)
COL_HP_MID = (232, 200, 70)
COL_HP_LOW = (222, 70, 70)
COL_PANEL = (26, 26, 42)
COL_PANEL_HL = (46, 48, 74)
COL_BORDER = (92, 96, 128)
COL_BORDER_HL = (255, 205, 80)
COL_CRIT = (255, 120, 60)
COL_DAMAGE = (255, 235, 200)
COL_HEAL = (110, 230, 140)
