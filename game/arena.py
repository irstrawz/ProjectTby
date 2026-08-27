"""The arena: an open field with scattered cover, plus camera and collision.

The old hand-authored dungeon fought the genre — corridors let you funnel the
horde into a single-file line, and the sealed rooms silently swallowed spawns
that could never reach you. This is a large open field with small convex
obstacle clusters: the swarm can always surround you, and every tile of open
floor is reachable from every other.
"""

import math
import random

import pygame

from . import assets
from . import settings
from .config import SCREEN_HEIGHT, SCREEN_WIDTH, TILE_SIZE
from .maps import GREENWOOD

WALL = 1
FLOOR = 0


class Arena:
    def __init__(self, rng=None, map_def=None):
        self.rng = rng or random.Random()
        self.map_def = map_def or GREENWOOD
        self.cols = self.map_def.cols
        self.rows = self.map_def.rows
        self.width = self.map_def.width
        self.height = self.map_def.height

        self.grid = [[FLOOR] * self.cols for _ in range(self.rows)]
        self._build_border()
        self._scatter_obstacles()
        self._pick_variants()
        self._flatten()
        self.center = pygame.Vector2(self.width / 2, self.height / 2)
        self._ground = None          # built lazily; see ``draw``

    # -- generation ----------------------------------------------------------
    def _build_border(self):
        for col in range(self.cols):
            self.grid[0][col] = WALL
            self.grid[self.rows - 1][col] = WALL
        for row in range(self.rows):
            self.grid[row][0] = WALL
            self.grid[row][self.cols - 1] = WALL

    def _scatter_obstacles(self):
        spec = self.map_def
        clear_tiles = spec.spawn_clear_radius / TILE_SIZE
        mid_col, mid_row = self.cols / 2, self.rows / 2

        for _ in range(spec.obstacle_clusters):
            col = self.rng.randint(3, self.cols - 4)
            row = self.rng.randint(3, self.rows - 4)
            if math.hypot(col - mid_col, row - mid_row) < clear_tiles:
                continue

            size = self.rng.randint(spec.cluster_min, spec.cluster_max)
            for _ in range(size):
                if 2 <= col < self.cols - 2 and 2 <= row < self.rows - 2:
                    self.grid[row][col] = WALL
                # Random walk keeps clusters blobby rather than wall-like.
                col += self.rng.choice((-1, 0, 1))
                row += self.rng.choice((-1, 0, 1))

    def _pick_variants(self):
        """Choose which grass or tree sprite each tile uses.

        Decided once at generation rather than per frame, so the ground does not
        shimmer as the camera moves and drawing stays a plain lookup.
        """
        spec = self.map_def
        self.variants = [[0] * self.cols for _ in range(self.rows)]

        # A map with ``patch_tiles`` set takes its last floor variant out of the
        # per-tile draw and lays it in connected groups afterwards instead.
        patch_index = None
        if spec.patch_tiles > 1 and len(spec.floor_keys) > 1:
            patch_index = len(spec.floor_keys) - 1

        floor_weights = spec.floor_weights
        if patch_index is not None:
            floor_weights = floor_weights[:patch_index]

        for row in range(self.rows):
            for col in range(self.cols):
                if self.grid[row][col] == WALL:
                    weights = spec.wall_weights
                else:
                    weights = floor_weights
                self.variants[row][col] = self.rng.choices(
                    range(len(weights)), weights=weights, k=1
                )[0]

        if patch_index is not None:
            self._scatter_patches(patch_index,
                                  spec.floor_weights[patch_index],
                                  spec.patch_tiles ** 2)

    def _scatter_patches(self, index, share, tiles_each):
        """Lay the patch floor tile in blobs of ``tiles_each`` connected tiles.

        Choosing it per tile, which is what every map did before, gives a field
        of isolated 40px speckles — the tile art is a patch of burnt ground, but
        one tile of it is a dot. Grouping the tiles is what turns them into
        something the eye reads as a feature of the terrain.

        The blob grows by repeatedly attaching a random neighbour rather than
        stamping a square. Four tiles in a square is a square, and a floor
        strewn with identical squares looks authored; the same four tiles as an
        L or an S or a line look like ground. Walls are written over freely —
        they keep their own wall variant, so a blob that runs into an obstacle
        simply flows around it, which is exactly what a scorch mark would do.

        Coverage is held at roughly the weight the map asked for: one blob
        covers ``tiles_each`` tiles, so the number of blobs is the share of the
        arena divided by that.
        """
        blobs = int(round(self.cols * self.rows * share / tiles_each))
        for _ in range(max(1, blobs)):
            col = self.rng.randint(1, self.cols - 2)
            row = self.rng.randint(1, self.rows - 2)
            chosen = {(col, row)}
            frontier = [(col, row)]
            # Bounded rather than "until it fits": near an arena edge the walk
            # can run out of legal neighbours, and an unbounded loop would spin
            # there forever.
            for _ in range(tiles_each * 8):
                if len(chosen) >= tiles_each:
                    break
                fx, fy = self.rng.choice(frontier)
                dx, dy = self.rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
                spot = (fx + dx, fy + dy)
                if spot in chosen:
                    continue
                if not (1 <= spot[0] < self.cols - 1 and 1 <= spot[1] < self.rows - 1):
                    continue
                chosen.add(spot)
                frontier.append(spot)
            for spot_col, spot_row in chosen:
                if self.grid[spot_row][spot_col] == FLOOR:
                    self.variants[spot_row][spot_col] = index

    def _flatten(self):
        """Pack the wall map into one flat ``bytes`` for fast collision tests.

        ``bytes`` rather than a numpy array, which is the obvious guess and the
        wrong one here. Collision rects span one or two tiles, so each test
        touches a couple of bytes; at that size numpy's per-call overhead costs
        more than the vectorised compare saves. numpy wins on the separation
        pass because that is one call doing 78,000 comparisons — the opposite
        shape of work.

        What this actually buys is the removal of a function call. Profiling
        showed ``is_wall_tile`` running 1,574 times a frame, and in Python the
        call itself outweighs the array lookup inside it. Slicing a bytes object
        and testing membership does the same work in one C-level operation.
        """
        self._solid = bytes(
            1 if self.grid[row][col] == WALL else 0
            for row in range(self.rows) for col in range(self.cols)
        )

    # -- queries -------------------------------------------------------------
    def is_wall_tile(self, col, row):
        if row < 0 or row >= self.rows or col < 0 or col >= self.cols:
            return True
        return self._solid[row * self.cols + col] == WALL

    def is_wall_point(self, x, y):
        return self.is_wall_tile(int(x // TILE_SIZE), int(y // TILE_SIZE))

    def rect_hits_wall(self, rect):
        """Test every tile the rect overlaps, not just one corner.

        The old ``is_wall(new_x, self.rect.y)`` only sampled the top-left pixel,
        which let 40px sprites wedge a whole tile deep into a 40px wall.
        """
        cols = self.cols
        left = rect.left // TILE_SIZE
        right = (rect.right - 1) // TILE_SIZE
        top = rect.top // TILE_SIZE
        bottom = (rect.bottom - 1) // TILE_SIZE

        # Anything reaching outside the grid is a wall, matching what
        # is_wall_tile reports for an off-grid tile. Checked up front so the
        # inner loop can slice without guarding every index.
        if left < 0 or top < 0 or right >= cols or bottom >= self.rows:
            return True

        solid = self._solid
        for row in range(top, bottom + 1):
            base = row * cols
            if 1 in solid[base + left:base + right + 1]:
                return True
        return False

    def move_and_slide(self, pos, half_w, half_h, delta):
        """Move ``pos`` by ``delta``, resolving each axis separately.

        Separating the axes is what produces sliding: running into a wall at an
        angle keeps the component parallel to the wall instead of dead-stopping.
        Returns (new_pos, blocked_x, blocked_y).
        """
        box = pygame.Rect(0, 0, half_w * 2, half_h * 2)
        blocked_x = blocked_y = False

        new_x = pos.x + delta.x
        if delta.x:
            box.center = (new_x, pos.y)
            if self.rect_hits_wall(box):
                new_x = pos.x
                blocked_x = True

        new_y = pos.y + delta.y
        if delta.y:
            box.center = (new_x, new_y)
            if self.rect_hits_wall(box):
                new_y = pos.y
                blocked_y = True

        return pygame.Vector2(new_x, new_y), blocked_x, blocked_y

    def random_open_point(self, min_dist_from=None, min_dist=0.0, attempts=200):
        """Find an open spot, optionally away from a given point."""
        for _ in range(attempts):
            x = self.rng.uniform(TILE_SIZE * 2, self.width - TILE_SIZE * 2)
            y = self.rng.uniform(TILE_SIZE * 2, self.height - TILE_SIZE * 2)
            probe = pygame.Rect(0, 0, TILE_SIZE + 16, TILE_SIZE + 16)
            probe.center = (x, y)
            if self.rect_hits_wall(probe):
                continue
            if min_dist_from is not None and pygame.Vector2(x, y).distance_to(min_dist_from) < min_dist:
                continue
            return pygame.Vector2(x, y)
        return pygame.Vector2(self.center)

    # -- drawing -------------------------------------------------------------
    def _build_ground(self):
        """Render the entire arena floor and walls into one surface, once.

        Drawing the visible tiles every frame meant roughly 600 blits, which
        profiling showed was around 60% of every blit the game made. The tiles
        never change — variants are chosen at generation precisely so the ground
        stays static — so all of that was the same work repeated sixty times a
        second.

        Cost is memory: the largest arena is 4400x2800, about 49MB at 32bpp.
        That is a real number but a fine trade on a desktop, and only one arena
        exists at a time — travelling through a portal builds a new World and
        drops the old one. Built lazily so headless tools that never draw, the
        self-test and the balance benches among them, never pay for it.
        """
        surface = assets.convert(pygame.Surface((self.width, self.height)), alpha=False)
        floors = [assets.images[key] for key in self.map_def.floor_keys]
        walls = [assets.images[key] for key in self.map_def.wall_keys]

        blit = surface.blit
        for row in range(self.rows):
            grid_row = self.grid[row]
            variant_row = self.variants[row]
            y = row * TILE_SIZE
            for col in range(self.cols):
                images = walls if grid_row[col] == WALL else floors
                blit(images[variant_row[col]], (col * TILE_SIZE, y))
        return surface

    def draw(self, painter, camera):
        """Blit the visible slice of the pre-rendered ground.

        Alignment is the whole difficulty. Everything else on screen is placed
        by ``Camera.to_screen``, which returns a float that pygame truncates at
        blit time — so a sprite at world x lands at ``floor(x - camera.x)``. The
        ground has to land on exactly the same pixel, or the two layers shear
        apart and the scene shimmers as the camera moves.

        The trick is that for integer x, ``floor(x - camera.x)`` equals
        ``x - ceil(camera.x)``: a *uniform integer shift*, which is precisely
        what one blit of a source rect can express. So the source starts at
        ``ceil`` of the camera position and the destination is a whole number.

        Carrying the fraction on the destination instead is the obvious approach
        and does not work — pygame truncates the destination too, so the
        fraction is silently discarded and the ground ends up a pixel out. That
        version passed the self-test and was caught only by diffing its output
        against the per-tile renderer.

        Diffing also turned up a small bug in the renderer this replaces.
        pygame truncates a blit destination *toward zero*, which is a floor for
        positive coordinates but not for negative ones, so the one tile drawn at
        a negative offset — the partially visible column and row at the leading
        edge — landed a pixel away from where the same maths put every sprite.
        This version is uniform, and therefore correct in that band too; outside
        it the two renderers are pixel-identical.
        """
        if self._ground is None:
            self._ground = self._build_ground()

        left = math.ceil(camera.x)
        top = math.ceil(camera.y)
        wanted = pygame.Rect(left, top, SCREEN_WIDTH, SCREEN_HEIGHT)
        source = wanted.clip(self._ground.get_rect())
        if not source.width or not source.height:
            return
        painter.blit(self._ground, (source.x - left, source.y - top), source)


class Camera:
    """Follows the player, clamps to the arena, and adds trauma-based shake."""

    def __init__(self):
        self.offset = pygame.Vector2()
        self.trauma = 0.0
        self._shake = pygame.Vector2()

    def add_trauma(self, amount):
        # Scaled here rather than at the ~15 call sites that add trauma: one
        # place to honour the setting, and no way for a new effect to forget.
        self.trauma = min(1.0, self.trauma + amount * settings.current.screen_shake)

    def update(self, target_pos, dt, rng, bounds=None):
        width, height = bounds if bounds else (GREENWOOD.width, GREENWOOD.height)
        self.offset.x = target_pos.x - SCREEN_WIDTH / 2
        self.offset.y = target_pos.y - SCREEN_HEIGHT / 2
        self.offset.x = max(0.0, min(self.offset.x, width - SCREEN_WIDTH))
        self.offset.y = max(0.0, min(self.offset.y, height - SCREEN_HEIGHT))

        self.trauma = max(0.0, self.trauma - dt * 1.9)
        if self.trauma > 0:
            # Squaring the trauma makes small hits subtle and big ones punchy.
            magnitude = 16.0 * self.trauma * self.trauma
            self._shake.x = rng.uniform(-magnitude, magnitude)
            self._shake.y = rng.uniform(-magnitude, magnitude)
        else:
            self._shake.update(0, 0)

    @property
    def x(self):
        return self.offset.x + self._shake.x

    @property
    def y(self):
        return self.offset.y + self._shake.y

    def to_screen(self, world_pos):
        return (world_pos[0] - self.x, world_pos[1] - self.y)
