"""Image loading and a font cache.

The old build called ``pygame.font.SysFont`` roughly eight times per frame while
drawing the HUD. Font construction hits the filesystem, so that was pure waste —
``get_font`` hands back a shared instance instead.
"""

import os
import sys

import pygame

from . import paths

ASSETS_DIR = paths.resource_path("assets")

IMAGE_FILES = {
    "wizard_down": "wizard_down.png",
    "wizard_up": "wizard_up.png",
    "wizard_left": "wizard_left.png",
    "wizard_right": "wizard_right.png",
    "goblin": "enemy_goblin.png",
    "ghost": "enemy_ghost.png",
    "guardian": "enemy_guardian.png",
    "boss": "enemy_boss.png",
    "gem": "gem.png",
    "altar": "boss_altar.png",
    "chest": "chest.png",
    "potion": "potion.png",
    "magnet": "magnet.png",
    "portal": "portal.png",
    "floor_grass_0": "floor_grass_0.png",
    "floor_grass_1": "floor_grass_1.png",
    "floor_grass_2": "floor_grass_2.png",
    "floor_dirt": "floor_dirt.png",
    "wall_tree_0": "wall_tree_0.png",
    "wall_tree_1": "wall_tree_1.png",
    "wall_rock": "wall_rock.png",
    "floor_ash_0": "floor_ash_0.png",
    "floor_ash_1": "floor_ash_1.png",
    "floor_ash_2": "floor_ash_2.png",
    "floor_scorch": "floor_scorch.png",
    "wall_obsidian_0": "wall_obsidian_0.png",
    "wall_obsidian_1": "wall_obsidian_1.png",
    "wall_stump": "wall_stump.png",
    "floor_void_0": "floor_void_0.png",
    "floor_void_1": "floor_void_1.png",
    "floor_void_2": "floor_void_2.png",
    "floor_abyss": "floor_abyss.png",
    "wall_spire_0": "wall_spire_0.png",
    "wall_spire_1": "wall_spire_1.png",
    "wall_pillar": "wall_pillar.png",
    "king": "enemy_king.png",
}
# Which tiles belong to which arena lives in game/maps.py — a tileset is part of
# a map's identity, not a global default.

images = {}
_font_cache = {}

# ``convert``/``convert_alpha`` require a display mode. The GPU renderer never
# sets one — it owns an SDL window directly — and does not need them either,
# since uploading to a texture does its own format conversion. Software blitting
# genuinely does need them (unconverted surfaces blit several times slower), so
# this is a flag rather than a deletion. ``game.render`` sets it.
convert_enabled = True


def convert(surface, alpha=True):
    """Match a surface to the display format, when there is one to match."""
    if not convert_enabled:
        return surface
    return surface.convert_alpha() if alpha else surface.convert()

# Surfaces and fonts are tied to the SDL video context. Tooling that builds
# several games in one process (the DPS bench, screenshot scripts) tears that
# context down and rebuilds it, which leaves every cached Surface and Font
# pointing at freed memory — the symptom is a baffling "Text has zero width"
# from a perfectly ordinary string. Modules register their caches here and
# ``load_images`` empties them on each fresh context.
surface_caches = []


def register_cache(cache):
    surface_caches.append(cache)
    return cache


def load_images():
    """Load every sprite. Must run after ``pygame.display.set_mode``."""
    _font_cache.clear()
    for cache in surface_caches:
        cache.clear()
    try:
        for key, filename in IMAGE_FILES.items():
            path = os.path.join(ASSETS_DIR, filename)
            images[key] = convert(pygame.image.load(path))
    except pygame.error as exc:
        print(f"Could not load asset images: {exc}", file=sys.stderr)
        pygame.quit()
        sys.exit(1)
    return images


def get_font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        _font_cache[key] = pygame.font.SysFont(None, size, bold=bold)
    return _font_cache[key]


def tint(surface, color, alpha=150):
    """Return a copy of ``surface`` washed with ``color``, keeping its silhouette."""
    result = surface.copy()
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((*color, alpha))
    result.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return result


def scaled(surface, factor):
    w, h = surface.get_size()
    return pygame.transform.smoothscale(surface, (int(w * factor), int(h * factor)))
