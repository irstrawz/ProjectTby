"""The arenas you can run in.

A map is data: how big it is, which tiles it is built from, how thickly it is
littered with cover, and what it does to the enemies that spawn there. Adding a
third is one entry in ``MAPS`` plus its tiles in ``tools/make_art.py`` — the
selection screen, the arena generator and the wave director all read from here.

Arena dimensions live on the map rather than in config, because that is the
whole point: a smaller field with more cover plays nothing like an open one,
even with identical enemies.

Maps form a chain rather than a menu. Every run opens in Greenwood; summoning
the altar Warden and killing it opens a portal onward. That makes the altar the
gate to progression instead of an optional side-fight, and means the deeper maps
are something you reach rather than something you pick.
"""

from dataclasses import dataclass, field

from .config import TILE_SIZE


@dataclass(frozen=True)
class MapDef:
    key: str
    label: str
    description: str
    accent: tuple

    cols: int
    rows: int

    floor_keys: tuple
    floor_weights: tuple
    wall_keys: tuple
    wall_weights: tuple

    obstacle_clusters: int
    cluster_min: int = 2
    cluster_max: int = 6
    spawn_clear_radius: float = 260.0

    enemy_health_mult: float = 1.0
    enemy_speed_mult: float = 1.0
    spawn_mult: float = 1.0
    xp_mult: float = 1.0

    next_map: str = None             # where this map's portal leads
    is_final: bool = False           # its altar summons the Warchief
    modifier_notes: tuple = field(default=())

    @property
    def width(self):
        return self.cols * TILE_SIZE

    @property
    def height(self):
        return self.rows * TILE_SIZE

    @property
    def has_exit(self):
        return self.next_map is not None

    @property
    def phrase(self):
        """The label with an article, for use mid-sentence.

        "The Hollow" already carries one, so blindly prefixing produced
        "the The Hollow" on the victory screen.
        """
        return self.label if self.label.lower().startswith("the ") else f"the {self.label}"


GREENWOOD = MapDef(
    key="greenwood",
    label="Greenwood",
    description="Open forest. Room to run, and little to hide behind.",
    accent=(96, 186, 92),
    cols=110, rows=70,
    floor_keys=("floor_grass_0", "floor_grass_1", "floor_grass_2", "floor_dirt"),
    floor_weights=(0.32, 0.30, 0.28, 0.10),
    wall_keys=("wall_tree_0", "wall_tree_1", "wall_rock"),
    wall_weights=(0.40, 0.36, 0.24),
    obstacle_clusters=90,
    next_map="cinderwaste",
)

CINDERWASTE = MapDef(
    key="cinderwaste",
    label="Cinderwaste",
    description="Burnt ground, thick with obsidian. Tighter, meaner, richer.",
    accent=(214, 108, 60),
    # Smaller and far more cluttered: you cannot simply outrun the horde here,
    # you have to read the gaps between the shards.
    cols=88, rows=56,
    floor_keys=("floor_ash_0", "floor_ash_1", "floor_ash_2", "floor_scorch"),
    floor_weights=(0.31, 0.29, 0.27, 0.13),
    wall_keys=("wall_obsidian_0", "wall_obsidian_1", "wall_stump"),
    wall_weights=(0.38, 0.34, 0.28),
    obstacle_clusters=150,
    cluster_max=5,
    enemy_health_mult=1.18,
    enemy_speed_mult=1.05,
    spawn_mult=1.15,
    xp_mult=1.35,
    next_map="hollow",
    modifier_notes=(
        "+18% enemy health",
        "+15% spawn rate",
        "+35% experience",
    ),
)

HOLLOW = MapDef(
    key="hollow",
    label="The Hollow",
    description="A broken citadel over the dark. Nowhere left to run.",
    accent=(126, 214, 240),
    # The smallest and most cluttered arena in the game. By the time you reach
    # it you should be strong enough that space, not damage, is the constraint.
    cols=80, rows=52,
    floor_keys=("floor_void_0", "floor_void_1", "floor_void_2", "floor_abyss"),
    floor_weights=(0.32, 0.30, 0.26, 0.12),
    wall_keys=("wall_spire_0", "wall_spire_1", "wall_pillar"),
    wall_weights=(0.36, 0.34, 0.30),
    obstacle_clusters=165,
    cluster_max=5,
    enemy_health_mult=1.45,
    enemy_speed_mult=1.1,
    spawn_mult=1.3,
    xp_mult=1.8,
    next_map=None,                   # the chain ends here
    is_final=True,
    modifier_notes=(
        "+45% enemy health",
        "+30% spawn rate",
        "+80% experience",
    ),
)

MAPS = (GREENWOOD, CINDERWASTE, HOLLOW)
MAPS_BY_KEY = {m.key: m for m in MAPS}
DEFAULT_MAP = GREENWOOD.key


def _validate():
    for map_def in MAPS:
        if map_def.next_map is not None:
            assert map_def.next_map in MAPS_BY_KEY, (
                f"{map_def.key} points at unknown map {map_def.next_map!r}"
            )
        assert len(map_def.floor_keys) == len(map_def.floor_weights), map_def.key
        assert len(map_def.wall_keys) == len(map_def.wall_weights), map_def.key
        # The camera clamps to the arena, so a map smaller than the window would
        # produce a negative clamp range and jitter at the edges.
        assert map_def.width > 1280 and map_def.height > 720, (
            f"{map_def.key} is smaller than the window"
        )
    finals = [m for m in MAPS if m.is_final]
    assert len(finals) == 1, "exactly one map must end the chain"
    assert finals[0].next_map is None, "the final map cannot lead anywhere"

    # Every map must be reachable by walking the chain from the start.
    seen, cursor = set(), MAPS_BY_KEY[DEFAULT_MAP]
    while cursor is not None and cursor.key not in seen:
        seen.add(cursor.key)
        cursor = MAPS_BY_KEY.get(cursor.next_map) if cursor.next_map else None
    unreachable = {m.key for m in MAPS} - seen
    assert not unreachable, f"unreachable maps: {sorted(unreachable)}"


_validate()
