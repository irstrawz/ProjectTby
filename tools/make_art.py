"""Generate the game's pixel art from editable pixel maps.

    python tools/make_art.py            write every sprite into assets/
    python tools/make_art.py --preview  also write a contact sheet to preview

Sprites are authored as lists of strings, one character per pixel, mapped
through a palette. That is what "8-bit art in code" means here: to change the
wizard's hat, edit the characters in WIZARD_DOWN. Nothing is drawn with
anti-aliasing or gradients, so the result stays crisp when scaled.

Existing files are never overwritten in place — anything already in assets/ with
a colliding name is moved to assets/old/ first, so the original art survives.
"""

import argparse
import math
import os
import random
import shutil

import pygame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
BACKUP = os.path.join(ASSETS, "old")

TILE = 40          # world tile size
SPRITE = 40        # character/enemy sprite size

# --- palette ----------------------------------------------------------------
# Two characters would be more flexible, but one keeps the pixel maps readable
# as pictures in the source, which is the whole point.
# Authored as pairs, not a dict literal, so a repeated character is caught
# instead of silently overwritten. Reusing "L" for a crystal highlight once
# turned every tree canopy in the forest pale lavender.
_PALETTE_ENTRIES = [
    ("g", (48, 88, 50)),  # grass mid
    ("G", (60, 107, 58)),  # grass light
    ("h", (37, 70, 42)),  # grass dark
    ("d", (94, 74, 48)),  # dirt
    ("D", (116, 92, 58)),  # dirt light
    ("y", (150, 168, 74)),  # dry blade
    ("t", (58, 40, 28)),  # trunk dark
    ("T", (86, 60, 40)),  # trunk light
    ("f", (36, 78, 44)),  # leaf dark
    ("F", (52, 106, 56)),  # leaf mid
    ("L", (74, 138, 70)),  # leaf light
    ("s", (36, 40, 44)),  # stone dark
    ("S", (92, 98, 104)),  # stone light
    ("M", (128, 134, 140)),  # stone highlight
    ("k", (44, 48, 62)),  # armour shadow
    ("K", (108, 118, 140)),  # armour mid
    ("W", (176, 188, 208)),  # armour light
    ("c", (150, 42, 42)),  # cloth/plume dark
    ("C", (206, 66, 58)),  # cloth/plume light
    ("e", (24, 26, 34)),  # visor / outline
    ("b", (196, 168, 92)),  # brass trim
    ("n", (222, 196, 140)),  # skin
    # Seven slots freed when the Scout, Sentinel, Guardian and Warden were
    # redrawn as a goblin, a ghost, a stone golem and a troll. Kept rather than
    # deleted because every letter is otherwise taken, and these are the only
    # single-character keys left for the next sprite that needs one.
    ("R", (206, 78, 58)),  # free — was scout red, light
    ("p", (78, 48, 118)),  # free — was sentinel purple, dark
    ("P", (128, 84, 176)),  # free — was sentinel purple, light
    # The wizard's robe. Blue rather than the obvious purple: purple is already
    # the Warding Sigils orbs, which orbit the player constantly, and a player
    # sprite the same colour as an effect circling it is a player you lose track
    # of in a crowd. Nothing else on screen is this blue.
    ("u", (40, 54, 116)),  # robe dark
    ("U", (84, 108, 200)),  # robe mid
    ("r", (134, 160, 240)),  # robe light / hat band
    ("o", (150, 96, 26)),  # free — was warden amber, dark
    ("O", (232, 156, 48)),  # boss light
    ("x", (250, 226, 150)),  # glow
    ("1", (46, 42, 46)),  # ash mid
    ("2", (58, 53, 55)),  # ash light
    ("3", (35, 32, 36)),  # ash dark
    ("4", (92, 52, 34)),  # scorched earth
    ("5", (128, 74, 42)),  # scorched light
    ("6", (196, 88, 36)),  # ember
    ("7", (255, 156, 62)),  # ember hot
    # Cinderwaste obstacles, all pushed well clear of the ash they stand on.
    # The old obsidian mid was (56, 47, 72) against ash light at (58, 53, 55):
    # the same brightness, a few points apart in one channel. On a dark map that
    # is not "subtle", it is invisible — you found the shards by walking into
    # them. Same failure as the Greenwood trees, same fix.
    ("8", (12, 10, 18)),  # obsidian outline, near black
    ("9", (84, 70, 118)),  # obsidian mid
    ("0", (150, 130, 194)),  # obsidian light
    ("!", (216, 204, 246)),  # obsidian glint
    ("@", (22, 17, 15)),  # char outline, near black
    ("(", (74, 60, 46)),  # char mid
    ("#", (112, 94, 72)),  # char light
    (")", (22, 20, 22)),  # ground shadow cast on ash
    ("Q", (24, 22, 38)),  # void stone dark
    ("q", (34, 31, 52)),  # void stone mid
    ("w", (48, 44, 72)),  # void stone light
    ("z", (11, 10, 20)),  # abyss
    ("Z", (70, 200, 226)),  # rune glow
    ("Y", (196, 250, 255)),  # rune bright
    ("j", (48, 38, 88)),  # crystal dark
    ("J", (98, 78, 158)),  # crystal mid
    ("l", (168, 146, 232)),  # crystal light
    ("^", (226, 214, 255)),  # crystal glint
    # Flagstone lit by a spire standing on it. These replaced the runes that
    # used to be scattered across every floor tile: the same blue, but pooled
    # around the thing that emits it instead of speckled over the whole arena.
    ("[", (52, 58, 92)),  # void stone, faintly lit
    ("]", (72, 92, 134)),  # void stone, lit
    # Pillar masonry. Grey rather than another shade of the floor: with the
    # runes gone the flagstones are uniformly dark blue-black, and a column
    # drawn in floor colours plus an outline turned into a thin dark sliver —
    # less visible than what it replaced. Grey also keeps it from reading as a
    # short crystal, which is the other obstacle on this map.
    ("{", (84, 88, 116)),  # pillar mid
    ("}", (134, 140, 170)),  # pillar light
    ("a", (36, 132, 150)),
    ("A", (86, 214, 226)),
    ("i", (198, 250, 255)),
    ("v", (72, 52, 96)),
    ("V", (126, 96, 158)),

    # Canopy colours pushed well clear of the grass beneath. The old leaf mid
    # was (52, 106, 56) against grass at (48, 88, 50) — eighteen points apart in
    # one channel, which is why the trees read as texture rather than obstacles.
    ("N", (116, 190, 96)),  # leaf bright
    ("E", (14, 34, 20)),  # canopy outline, near black
    ("H", (30, 56, 34)),  # ground shadow cast by canopy and rock

    ("I", (22, 24, 30)),  # rock crack / facet edge

    # Goblin
    ("m", (54, 92, 44)),  # goblin skin dark
    ("X", (98, 150, 62)),  # goblin skin mid
    ("B", (140, 194, 92)),  # goblin skin light
    ("%", (74, 50, 34)),  # rag dark
    ("&", (116, 82, 52)),  # rag light
    ("*", (240, 238, 214)),  # tooth
    ("+", (246, 206, 72)),  # goblin eye

    # Every letter of the alphabet is now spoken for in both cases, so new
    # colours have to be punctuation. That is a sign this scheme is near its
    # limit: the next batch of art should probably move to two-character keys
    # and give up some of the "the source looks like the picture" readability
    # that single characters buy.
    ("-", (86, 128, 172)),  # spectral dark
    ("=", (150, 200, 232)),  # spectral mid
    ("$", (226, 248, 255)),  # spectral bright
    ("<", (62, 84, 52)),  # troll hide dark
    (">", (104, 128, 74)),  # troll hide mid
    ("?", (146, 170, 104)),  # troll hide light
]

PALETTE = {}
for _char, _color in _PALETTE_ENTRIES:
    assert _char not in PALETTE, f"palette character {_char!r} defined twice"
    assert len(_char) == 1, f"palette key {_char!r} must be a single character"
    PALETTE[_char] = _color


def render(rows, scale=1):
    """Turn a pixel map into a Surface."""
    height = len(rows)
    width = len(rows[0])
    assert all(len(r) == width for r in rows), "pixel map rows differ in length"

    # Reject look-alike characters from other alphabets. This has caught real
    # bugs twice: a Cyrillic "е" (U+0435) is indistinguishable from a Latin "e"
    # in every editor and font, so the only symptom is a transparent hole in the
    # sprite where an outline pixel should be — which reads as an art mistake,
    # not an encoding one, and sends you looking in entirely the wrong place.
    for index, row in enumerate(rows):
        for column, char in enumerate(row):
            assert ord(char) < 128, (
                f"row {index} column {column} is {char!r} (U+{ord(char):04X}), not ASCII — "
                f"almost certainly a look-alike letter from another alphabet"
            )

    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            color = PALETTE.get(char)
            if color is not None:
                surface.set_at((x, y), color)
    if scale != 1:
        surface = pygame.transform.scale(surface, (width * scale, height * scale))
    return surface


# ---------------------------------------------------------------------------
# The player — 20x20 authored, scaled 2x to 40x40. One map per facing, because a
# top-down character rotated 90 degrees reads as a character lying on its side.
#
# A wizard: pointed hat, robe, staff. The hat is doing most of the work — a wide
# brim under a tall cone is one of the few silhouettes that survives being 40
# pixels tall and still says exactly what it is. The staff is held out from the
# body with a hand bridging the gap, because drawn flush against the robe it
# read as a stripe on the sleeve rather than an object being carried.
# ---------------------------------------------------------------------------


def mirrored(rows):
    """Flip a pixel map left-to-right.

    The left-facing sprite is the right-facing one reversed rather than a fifth
    hand-authored map. Two maps of the same pose drift apart the moment one is
    edited, and the only visible consequence of mirroring is that the staff
    changes hands, which nobody has ever noticed in a top-down game.
    """
    return [row[::-1] for row in rows]


# Facing the camera: face under the brim, beard, sash.
WIZARD_DOWN = [
    ".......ee...........",
    "......euue..........",
    "......eUUe..........",
    ".....eUUUUe.....eYe.",
    ".....eUUUUe.....eAe.",
    "....eUUUUUUe....eAe.",
    "...eUUUUUUUUe...eTe.",
    ".eeeUUUUUUUUeee.eTe.",
    "euuUUUUUUUUUUuueeTe.",
    ".eeennnnnneee...eTe.",
    "...ennnnnnne....eTe.",
    "...eneenenee...enTe.",
    "...ennnnnnne...enTe.",
    "...eWWWWWWWe....eTe.",
    "..eUWWWWWWWUe...eTe.",
    "..eUUbbbbbbUe...ete.",
    "..eUUUUUUUUUe...ete.",
    ".eUUUUUUUUUUUe..ete.",
    ".eUUUUUUUUUUUe..ete.",
    "..eeeeeeeeeee...ete.",
]

# Facing away: hat and robe only, no face.
WIZARD_UP = [
    ".......ee...........",
    "......euue..........",
    "......eUUe..........",
    ".....eUUUUe.....eYe.",
    ".....eUUUUe.....eAe.",
    "....eUUUUUUe....eAe.",
    "...eUUUUUUUUe...eTe.",
    ".eeeUUUUUUUUeee.eTe.",
    "euuUUUUUUUUUUuueeTe.",
    ".eeeUUUUUUUeee..eTe.",
    "...eUUUUUUUe....eTe.",
    "...eUUUUUUUe...eUTe.",
    "...eUUUUUUUe...eUTe.",
    "...eUUUUUUUe....eTe.",
    "..eUUUUUUUUUe...eTe.",
    "..eUUbbbbbbUe...ete.",
    "..eUUUUUUUUUe...ete.",
    ".eUUUUUUUUUUUe..ete.",
    ".eUUUUUUUUUUUe..ete.",
    "..eeeeeeeeeee...ete.",
]

# Urofile, staff held forward.
WIZARD_RIGHT = [
    "....ee..............",
    "...euue.............",
    "...eUUe.............",
    "..eUUUUe........eYe.",
    "..eUUUUe........eAe.",
    ".eUUUUUUe.......eAe.",
    "eUUUUUUUUe......eTe.",
    "eUUUUUUUUeeee...eTe.",
    "eUUUUUUUUUUuue..eTe.",
    "eeennnnnnnee....eTe.",
    "..ennnnnnnne....eTe.",
    "..ennennnnne...enTe.",
    "..ennnnnnnne...enTe.",
    "..eWWWWWWWWe....eTe.",
    ".eUWWWWWWWUe....eTe.",
    ".eUUbbbbbUUe....ete.",
    ".eUUUUUUUUUe....ete.",
    ".eUUUUUUUUUUe...ete.",
    ".eUUUUUUUUUUe...ete.",
    "..eeeeeeeeee....ete.",
]

WIZARD_LEFT = mirrored(WIZARD_RIGHT)


# ---------------------------------------------------------------------------
# Enemies — 20x20 authored, scaled 2x
# ---------------------------------------------------------------------------

# The scout is a goblin: the weakest thing in the game, so it should look like
# something you could kick over rather than an abstract red diamond. Read as a
# creature at 40x40 by leaning on silhouette — the ears break the outline on
# both sides, which is what makes it identifiable at a glance in a crowd of two
# hundred.
GOBLIN = [
    "....................",
    "........eeee........",
    "......eemmmmee......",
    "eee..emXXXXXXme..eee",
    "emme.mXXBBBBXXm.emme",
    ".emmemXBBBBBBXmemme.",
    "..emmmXBXXXXBXmmme..",
    "...emmXXXXXXXXmme...",
    "...emX++XXXX++Xme...",
    "...emXBBXXXXBBXme...",
    "....emXXX**XXXme....",
    ".....emmXXXXmme.....",
    "......eemmmmee......",
    "....ee%%&&&&%%ee....",
    "...e%%&&&&&&&&%%e...",
    "...e%&&%%%%%%&&%e...",
    "...em&&%e..e%&&me...",
    "....emm%e..e%mme....",
    ".....ee......ee.....",
    "....................",
]

# The Ghost, formerly the Sentinel. A ranged attacker that drifts rather than
# walks, so it gets no legs and a torn hem — the silhouette should say "this
# thing floats" before you notice what it is doing.
GHOST = [
    ".......eeeee........",
    ".....ee-----ee......",
    "....e--=======e.....",
    "...e--=========e....",
    "...e-===========e...",
    "..e-=============e..",
    "..e-==$$$$$$$$$==-e.",
    "..e-=$$$$$$$$$$$$-e.",
    "..e-=$$eee$$eee$$-e.",
    "..e-=$$eAe$$eAe$$-e.",
    "..e-=$$eee$$eee$$-e.",
    "..e-=$$$$$$$$$$$$-e.",
    "..e-=$$$$$$$$$$$$-e.",
    "..e-==$$$$$$$$$$=-e.",
    "..e-===$$$$$$$$==-e.",
    "..e-=e=$$$$$$$$=e=-e",
    "..e-e.e=$$$$$$=e.e-e",
    "..ee...e=$$$$=e...ee",
    "........ee==ee......",
    "..........ee........",
]

# A stone golem. Wide and stepped rather than tall and rounded: the earlier
# attempt gave it slim arms, which at 40x40 collapsed into ears and made it read
# as a small animal. Mass and square corners are what say "carved rock".
GOLEM = [
    "..eeee........eeee..",
    ".efFSSe......eSSfFe.",
    ".eSSSSSeeeeeeSSSSSe.",
    ".eSSSSSSSSSSSSSSSSe.",
    "eeSSMMSSSSSSSSMMSSee",
    "eSSMMSSMMMMMMSSMMSSe",
    "eSSSSSSMSSSSMSSSSSSe",
    "eSSIISSMZZZZMSSIISSe",
    "eSSIISSMZZZZMSSIISSe",
    "eSSSSSSMSSSSMSSSSSSe",
    "eSSMMSSMMMMMMSSMMSSe",
    "eSSMMSSSSIISSSSMMSSe",
    "eeSSSSSSSIISSSSSSSee",
    ".eSSSSSSSSSSSSSSSSe.",
    ".eeSSSSSSSSSSSSSSee.",
    "...eeSSSSSSSSSSee...",
    "....eSSSSeeSSSSe....",
    "....eSSSe..eSSSe....",
    "....eSSSe..eSSSe....",
    "....eeeee..eeeee....",
]

# The Warden, drawn as a troll: hunched, tusked, and wider than it is tall.
# Rendered at 3x so it towers over the goblins it arrives with.
TROLL = [
    "....ee..........ee..",
    "...e<<e........e<<e.",
    "..e<<<<eeeeeeee<<<<e",
    "..e<<>>>>>>>>>>>><<e",
    ".e<<>>>>>>>>>>>>>><e",
    ".e<>>>??????????>><e",
    ".e<>>?????????????<e",
    ".e<>>??eee??eee??>>e",
    ".e<>>?e+e??e+e?>>>>e",
    ".e<>>??eee??eee??>>e",
    ".e<>>>???????????>>e",
    ".e<>>>?**??**?>>>>>e",
    "..e<>>>>>>>>>>>>>>e.",
    "..e<<>>>>>>>>>>>><e.",
    "..ee<<%%%%%%%%%%<ee.",
    "...e<%%&&&&&&%%<<e..",
    "...e<<%&&&&&&%<<e...",
    "..e<<<e%%%%%%e<<<e..",
    "..e<<e..eeee..e<<e..",
    "..eee..........eee..",
]

CHEST = [
    "....................",
    "....................",
    "....................",
    "..eeeeeeeeeeeeeeee..",
    "..ebbbbbbbbbbbbbbe..",
    "..ebTTTTTTTTTTTTbe..",
    "..ebTtTTTTTTTTtTbe..",
    "..ebTtTTTTTTTTtTbe..",
    "..ebbbbbbbbbbbbbbe..",
    "..ebbbbbbbbbbbbbbe..",
    "..ebTTTTbxxbTTTTbe..",
    "..ebTTTTbxxbTTTTbe..",
    "..ebTtTTbbbbTTtTbe..",
    "..ebTTTTTTTTTTTTbe..",
    "..ebTtTTTTTTTTtTbe..",
    "..ebbbbbbbbbbbbbbe..",
    "..eeeeeeeeeeeeeeee..",
    "....................",
    "....................",
    "....................",
]

PORTAL = [
    "......eeeeeeee......",
    "....eevVVVVVVvee....",
    "...evVVVvvvvVVVve...",
    "..evVVvxxxxxxvVVve..",
    "..eVVvxxAAAAxxvVVe..",
    ".eVVvxxAAiiiiAxxvVe.",
    ".eVvxxAAiiiiiiAxxvVe",
    "eVVvxAAiiiiiiiiAxvVe",
    "eVvxxAAiiiiiiiiAxxve",
    "eVvxxAAiiiiiiiiAxxve",
    "eVvxxAAiiiiiiiiAxxve",
    "eVVvxAAiiiiiiiiAxvVe",
    ".eVvxxAAiiiiiiAxxvVe",
    ".eVVvxxAAiiiiAxxvVe.",
    "..eVVvxxAAAAxxvVVe..",
    "..evVVvxxxxxxvVVve..",
    "...evVVVvvvvVVVve...",
    "....eevVVVVVVvee....",
    "......eeeeeeee......",
    "....................",
]

MAGNET = [
    "..eeeeeeee..",
    ".eCCCeeCCCe.",
    "eCCCCeeCCCCe",
    "eCCeeeeeeCCe",
    "eCCe....eCCe",
    "eCCe....eCCe",
    "eCCe....eCCe",
    "eCCe....eCCe",
    "eWWe....eWWe",
    "eWWe....eWWe",
    "eMMe....eMMe",
    ".ee......ee.",
]

POTION = [
    "....TTTT....",
    "....TttT....",
    "....eWWe....",
    "...eWCCWe...",
    "..eWCCCCWe..",
    ".eWCCCCCCWe.",
    ".eWCcccccWe.",
    ".eWCcccccWe.",
    ".eWCcccccWe.",
    "..eWccccWe..",
    "...eWWWWe...",
    "....eeee....",
]

# The Warchief: the Warden's silhouette, but crowned and lit from inside.
# Deliberately built on the same frame so it reads as the same lineage, with
# the crown and the cold palette saying which one you should be afraid of.
# The Goblin Warchief — the same green as the rank-and-file goblins so
# the connection reads, but crowned, armoured and three times the size.
WARCHIEF = [
    "..e..eeeee..eeeee.e.",
    ".eOe.eCCCe..eCCCe.Oe",
    ".eOOeebbbeeebbbee.Oe",
    "..eOOebbbbbbbbbeOOe.",
    "...eebXXXXXXXXbee...",
    "...emXXXXXXXXXXme...",
    "eee.mXXBBBBBBXXm.eee",
    "emmemXBBBBBBBBXmemme",
    "emmmXB+BBBB+BBXmmmme",
    ".emmXBBeBBBBeBBXmme.",
    "..emXXBBBBBBBBXXme..",
    "..emXX**XXXX**XXme..",
    "..eemXXXXXXXXXXmee..",
    ".eKKebbbbbbbbbbeKKe.",
    "eKKWebCCCCCCCCbeWKKe",
    "eKWWebCCCCCCCCbeWWKe",
    ".eKKe%%&&&&&&%%eKKe.",
    "..ee.%&&%%%%&&%.ee..",
    ".....e%%e..e%%e.....",
    "......ee....ee......",
]

GEM = [
    "....iiii....",
    "...iAAAAi...",
    "..iAAAAAAi..",
    ".iAAAiiAAAi.",
    "iAAAiiiiAAAi",
    "iAAAiiiiAAAi",
    "iAAAAAAAAAAi",
    ".iAaaaaaaai.",
    "..iaaaaaai..",
    "...iaaaai...",
    "....iaai....",
    ".....ii.....",
]

# A plinth with a crystal floating over it, drawn at 3x so it is the biggest
# thing on the ground. The old flat slab read as scenery and players walked past
# it without noticing the one object that gates the whole run.
ALTAR = [
    "........eeee........",
    ".......eiiiie.......",
    "......eiAAAAie......",
    ".....eiAAAAAAie.....",
    ".....eAAAaaAAAe.....",
    ".....eAAaaaaAAe.....",
    "......eAaaaaAe......",
    ".......eAaaAe.......",
    "........eAAe........",
    ".........ee.........",
    "....eeeeeeeeeeee....",
    "...eVVVVVVVVVVVVe...",
    "..eVvvvvvvvvvvvvVe..",
    "..eVvSSSSSSSSSSvVe..",
    ".eVvSSMMMMMMMMSSvVe.",
    ".eVSSMMMMMMMMMMSSVe.",
    "eVvSSMMMMMMMMMMSSvVe",
    "eVSSSSSSSSSSSSSSSSVe",
    ".eeeeeeeeeeeeeeeeee.",
    "..ssssssssssssssss..",
]


# ---------------------------------------------------------------------------
# Ground and obstacles — authored at full 40x40, procedurally speckled
# ---------------------------------------------------------------------------

def grass_tile(rng, blades=14):
    """Forest floor: mottled green with a few blades and the odd pebble."""
    rows = [["g"] * TILE for _ in range(TILE)]

    # Broad patches so neighbouring tiles do not read as a flat colour field.
    for _ in range(26):
        cx, cy = rng.randrange(TILE), rng.randrange(TILE)
        radius = rng.randint(2, 5)
        shade = rng.choice("GGhh")
        for y in range(max(0, cy - radius), min(TILE, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(TILE, cx + radius + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                    rows[y][x] = shade

    for _ in range(blades):
        x, y = rng.randrange(1, TILE - 1), rng.randrange(2, TILE - 2)
        length = rng.randint(2, 3)
        for step in range(length):
            if y - step >= 0:
                rows[y - step][x] = "y" if step == length - 1 else "G"

    for _ in range(rng.randint(0, 2)):
        x, y = rng.randrange(2, TILE - 3), rng.randrange(2, TILE - 3)
        for dy in range(2):
            for dx in range(2):
                rows[y + dy][x + dx] = "S" if (dx + dy) else "M"

    return ["".join(r) for r in rows]


def dirt_patch_tile(rng):
    """A worn tile, sprinkled among the grass so the ground has variety."""
    rows = [list(row) for row in grass_tile(rng, blades=4)]
    cx, cy = TILE // 2, TILE // 2
    for y in range(TILE):
        for x in range(TILE):
            wobble = rng.randint(-3, 3)
            if (x - cx) ** 2 + (y - cy) ** 2 <= (13 + wobble) ** 2:
                rows[y][x] = "D" if rng.random() < 0.3 else "d"
    return ["".join(r) for r in rows]


def tree_tile(rng):
    """Obstacle: a leafy canopy over a visible trunk.

    Built in passes rather than as one blob — fill, then shade by light
    direction, then outline. A single circle of leaf colour reads as a green
    dot; the outline and the top-left highlight are what make it a tree.
    """
    rows = [list(row) for row in grass_tile(rng, blades=3)]

    # Trunk first, so the canopy overlaps its top.
    for y in range(25, 39):
        width = 3 if y < 34 else 4
        for x in range(20 - width, 20 + width):
            rows[y][x] = "t" if x < 19 else "T"
    for x in range(14, 27):                      # roots flaring at the base
        if abs(x - 20) > 3 and rng.random() < 0.6:
            rows[37][x] = "t"

    # Canopy as overlapping lobes, sitting high so the trunk shows beneath.
    lobes = [(20, 15, 13), (12, 13, 8), (28, 14, 8), (15, 22, 8), (26, 22, 8), (20, 8, 9)]
    canopy = set()
    for cx, cy, radius in lobes:
        for y in range(max(0, cy - radius), min(TILE, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(TILE, cx + radius + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                    canopy.add((x, y))

    # Shadow on the ground, offset down-right from the canopy and away from the
    # light. This is what separates the tree from the floor: without it the
    # canopy is a green shape on a green field no matter how its own colours are
    # tuned, because nothing says the two are at different heights.
    for x, y in canopy:
        sx, sy = x + 3, y + 4
        if 0 <= sx < TILE and 0 <= sy < TILE and (sx, sy) not in canopy:
            rows[sy][sx] = "H"

    for x, y in canopy:
        # Light from the upper left: highlight that side, shade the other.
        # Note the darkest leaf colour is not used for fill at all. "f" is
        # (36, 78, 44), which is *darker than the grass* — painted across the
        # shaded half it read as a hole in the ground rather than foliage in
        # shadow, and it was most of why the canopy disappeared. The whole range
        # now sits above the floor, and only the outline goes darker.
        lit = (x - 20) + (y - 15) < -6
        shaded = (x - 20) + (y - 15) > 8
        if lit:
            rows[y][x] = "N" if rng.random() < 0.78 else "L"
        elif shaded:
            rows[y][x] = "F" if rng.random() < 0.65 else "L"
        else:
            rows[y][x] = "L" if rng.random() < 0.6 else "N"

    # Hard outline wherever the canopy meets open air, two pixels thick.
    # Near-black rather than a dark green: an outline only reads as an edge if
    # it is darker than anything it can sit against, and dark leaf colour is
    # within a few points of shaded grass. Two pixels because at 40x40 a single
    # one is a hairline that the eye averages away against busy ground.
    edge = set()
    for x, y in canopy:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) not in canopy:
                edge.add((x, y))
                break
    inner = set()
    for x, y in canopy:
        if (x, y) in edge:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) in edge:
                inner.add((x, y))
                break
    for x, y in edge | inner:
        rows[y][x] = "E"

    return ["".join(r) for r in rows]


def ash_tile(rng, embers=3):
    """Cinderwaste floor: drifted ash with the odd ember still glowing."""
    rows = [["1"] * TILE for _ in range(TILE)]

    for _ in range(30):
        cx, cy = rng.randrange(TILE), rng.randrange(TILE)
        radius = rng.randint(2, 6)
        shade = rng.choice("2233")
        for y in range(max(0, cy - radius), min(TILE, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(TILE, cx + radius + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                    rows[y][x] = shade

    # Hairline cracks, so the ground reads as baked rather than soft.
    for _ in range(rng.randint(1, 3)):
        x, y = rng.randrange(TILE), rng.randrange(TILE)
        for _ in range(rng.randint(6, 14)):
            if 0 <= x < TILE and 0 <= y < TILE:
                rows[y][x] = "3"
            x += rng.choice((-1, 0, 1))
            y += rng.choice((0, 1, 1))

    for _ in range(embers):
        x, y = rng.randrange(1, TILE - 1), rng.randrange(1, TILE - 1)
        rows[y][x] = "7"
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if 0 <= x + dx < TILE and 0 <= y + dy < TILE and rng.random() < 0.5:
                rows[y + dy][x + dx] = "6"

    return ["".join(r) for r in rows]


def scorch_tile(rng):
    """A burnt-through patch. Fills the tile, because it is laid in blocks.

    This used to be a circle of burnt earth about 24 pixels across, floating in
    the middle of an ash tile, and the arena laid one tile at a time. The result
    was a field of little brown dots rather than anything you would call a
    patch.

    Now ``Arena`` stamps several connected tiles at once (see ``patch_tiles`` in
    ``maps.py``), so this tile has to *bleed to its own edges* — a blob inset
    from the border would leave an ash seam down the middle of every patch,
    which is worse than the dots. The irregularity comes from the shape of the
    tile group instead, and from mottling the border so the outer edge is not a
    ruled line.
    """
    rows = [list(row) for row in ash_tile(rng, embers=1)]

    for y in range(TILE):
        for x in range(TILE):
            rows[y][x] = "5" if rng.random() < 0.16 else "4"

    # Darker cooler ground in blotches, so a large patch is not a flat field.
    # More of them than a single-tile blob needed: four tiles of unbroken
    # scorched earth is a lot of one colour, and the point of the change was to
    # make the patches bigger, not louder.
    for _ in range(22):
        cx, cy = rng.randrange(TILE), rng.randrange(TILE)
        radius = rng.randint(2, 6)
        for y in range(max(0, cy - radius), min(TILE, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(TILE, cx + radius + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                    rows[y][x] = "4" if rng.random() < 0.5 else "3"

    # Mottle the border. Where two scorch tiles meet this reads as cracking in
    # the middle of the burn; where one meets plain ash it softens the join.
    for y in range(TILE):
        for x in range(TILE):
            depth = min(x, y, TILE - 1 - x, TILE - 1 - y)
            if depth < 3 and rng.random() < 0.22 + (2 - depth) * 0.08:
                rows[y][x] = "3" if rng.random() < 0.6 else "1"

    # Cracks and a few surviving embers.
    for _ in range(rng.randint(2, 4)):
        x, y = rng.randrange(TILE), rng.randrange(TILE)
        for _ in range(rng.randint(6, 16)):
            if 0 <= x < TILE and 0 <= y < TILE:
                rows[y][x] = "3"
            x += rng.choice((-1, 0, 1))
            y += rng.choice((0, 1, 1))
    for _ in range(3):
        x, y = rng.randrange(4, TILE - 4), rng.randrange(4, TILE - 4)
        rows[y][x] = "7"
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if rng.random() < 0.5:
                rows[y + dy][x + dx] = "6"
    return ["".join(r) for r in rows]


def _cast_shadow(rows, body, colour, offset=(2, 3)):
    """Drop a shadow on the ground down-right of ``body``.

    Cheap, and it does more for readability than any amount of tuning the
    obstacle's own colours. A shape drawn flat on the floor is a pattern; the
    same shape with a shadow is an object standing on the floor, and the eye
    reads "I cannot walk there" from the second one without being told.
    """
    dx, dy = offset
    for x, y in body:
        sx, sy = x + dx, y + dy
        if 0 <= sx < TILE and 0 <= sy < TILE and (sx, sy) not in body:
            rows[sy][sx] = colour


def _outline(rows, body, colour, thickness=2):
    """Ring ``body`` in ``colour``, ``thickness`` pixels deep.

    Two pixels, not one. At 40x40 a single-pixel outline is a hairline that the
    eye averages into whatever it sits against, which on a dark, busy floor
    means it vanishes exactly where it is needed most.
    """
    edge = set()
    for x, y in body:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) not in body:
                edge.add((x, y))
                break
    ring = set(edge)
    for _ in range(thickness - 1):
        grown = set()
        for x, y in body:
            if (x, y) in ring:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if (x + dx, y + dy) in ring:
                    grown.add((x, y))
                    break
        ring |= grown
    for x, y in ring:
        rows[y][x] = colour
    return ring


def obsidian_tile(rng):
    """Obstacle: a shard of volcanic glass thrust up out of the ash.

    Bigger and brighter than it was. The first version was drawn as black glass
    on a near-black floor, which is what obsidian honestly is and which made it
    an invisible wall: the shards occupied about a third of their tile in
    colours within a few points of the ash. Realism loses to legibility here —
    the player has to see cover from across the screen while running from a
    horde, so the glass is lit hard from the upper left, ringed in near-black
    and given a shadow, and it now fills most of its tile.
    """
    rows = [list(row) for row in ash_tile(rng, embers=1)]

    # Angular spikes rather than a blob — glass fractures straight. Taller and
    # wider than before so the silhouette carries at a glance.
    # Jittered per tile. The fixed peak list made ``wall_obsidian_0`` and
    # ``wall_obsidian_1`` the same picture with different speckle, which is two
    # asset slots spent on one shape.
    peaks = [(20 + rng.randint(-2, 2), 3 + rng.randint(0, 3), rng.randint(10, 13)),
             (11 + rng.randint(-2, 2), 9 + rng.randint(0, 4), rng.randint(6, 9)),
             (29 + rng.randint(-2, 2), 11 + rng.randint(0, 4), rng.randint(7, 10))]
    shard = set()
    for tip_x, tip_y, half in peaks:
        height = TILE - 3 - tip_y
        for step in range(height):
            y = tip_y + step
            span = int(half * step / max(1, height - 1))
            for x in range(tip_x - span, tip_x + span + 1):
                if 0 <= x < TILE and 0 <= y < TILE:
                    shard.add((x, y))

    _cast_shadow(rows, shard, ")")

    for x, y in shard:
        # Light from the upper left, matching every other obstacle in the game.
        lit = (x - 20) + (y - 20) < -4
        shaded = (x - 20) + (y - 20) > 10
        if lit:
            rows[y][x] = "0" if rng.random() < 0.75 else "!"
        elif shaded:
            rows[y][x] = "9" if rng.random() < 0.7 else "0"
        else:
            rows[y][x] = "0" if rng.random() < 0.55 else "9"

    _outline(rows, shard, "8")

    # Glints along the lit faces, inside the outline.
    for _ in range(5):
        x, y = rng.randrange(11, 21), rng.randrange(8, 32)
        if (x, y) in shard and rows[y][x] != "8":
            rows[y][x] = "!"
    return ["".join(r) for r in rows]


def stump_tile(rng):
    """Obstacle: what is left of a tree after the fire went through.

    Charcoal on ash had the same problem the obsidian did — the old char light
    was (66, 55, 46) against ash at (46, 42, 46), which is not a contrast, it is
    a rounding error. The wood is now clearly lighter than the ground it stands
    on, outlined and shadowed like the trees in Greenwood.
    """
    rows = [list(row) for row in ash_tile(rng, embers=2)]

    trunk = set()
    for y in range(11, 37):
        width = 8 if y < 30 else 10
        for x in range(20 - width, 20 + width):
            if 0 <= x < TILE:
                trunk.add((x, y))
    # Splintered crown: a ragged top edge rather than a flat cut.
    for x in range(12, 29):
        for y in range(11 - rng.randint(0, 3), 11):
            if 0 <= y < TILE:
                trunk.add((x, y))

    _cast_shadow(rows, trunk, ")")

    for x, y in trunk:
        # Lit across most of the width, not just the left third. Charcoal is
        # dark and the ash is dark, so the only thing keeping this readable is
        # how much of it is clearly lighter than the ground — a narrow lit strip
        # left the tile averaging out to "slightly different ash".
        lit = x < 21
        rows[y][x] = ("#" if rng.random() < 0.75 else "(") if lit else (
            "(" if rng.random() < 0.6 else "@")

    # Growth rings on the cut face, so the top reads as a stump and not a post.
    for radius in (4, 8):
        for angle in range(0, 360, 6):
            x = int(20 + math.cos(math.radians(angle)) * radius)
            y = int(16 + math.sin(math.radians(angle)) * radius * 0.55)
            if (x, y) in trunk:
                rows[y][x] = "@"

    _outline(rows, trunk, "@")

    # Embers still alive down in the roots.
    for _ in range(4):
        x, y = rng.randrange(15, 26), rng.randrange(28, 35)
        if (x, y) in trunk:
            rows[y][x] = "6" if rng.random() < 0.5 else "7"
    return ["".join(r) for r in rows]


def void_tile(rng, runes=0):
    """The Hollow's floor: worked stone, dark and quiet.

    ``runes`` used to default to 1, and all three floor variants took the
    default — so roughly nine tiles in ten across the whole arena carried a
    bright cyan eight-pointed star. At 40 pixels a tile that is several hundred
    stars on screen at once, each one about the size of a projectile and about
    as bright, competing for attention with every enemy and every pickup on the
    busiest map in the game.

    The light did not go away, it moved: ``spire_tile`` now pools it around the
    crystals, which is where a light source belongs and which has the useful
    side effect of marking the obstacles. Kept as a parameter because a rune
    tile is still the right thing for a shrine or a boss floor.
    """
    rows = [["q"] * TILE for _ in range(TILE)]

    for _ in range(24):
        cx, cy = rng.randrange(TILE), rng.randrange(TILE)
        radius = rng.randint(2, 6)
        shade = rng.choice("QQww")
        for y in range(max(0, cy - radius), min(TILE, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(TILE, cx + radius + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                    rows[y][x] = shade

    # Faint flagstone seams, so it reads as built rather than natural.
    for edge in (0, TILE - 1):
        for i in range(TILE):
            rows[edge][i] = "Q"
            rows[i][edge] = "Q"

    for _ in range(runes):
        cx, cy = rng.randrange(9, TILE - 9), rng.randrange(9, TILE - 9)
        size = rng.randint(4, 6)
        for offset in range(-size, size + 1):
            rows[cy][cx + offset] = "Z"
            rows[cy + offset][cx] = "Z"
        for corner in (-1, 1):
            for step in range(1, size - 1):
                rows[cy + corner * step][cx + corner * step] = "Z"
                rows[cy + corner * step][cx - corner * step] = "Z"
        rows[cy][cx] = "Y"

    return ["".join(r) for r in rows]


def abyss_tile(rng):
    """A hole straight through the floor. Cosmetic — you can still walk it."""
    rows = [list(row) for row in void_tile(rng, runes=0)]
    cx, cy = TILE // 2, TILE // 2
    for y in range(TILE):
        for x in range(TILE):
            wobble = rng.randint(-4, 4)
            distance = (x - cx) ** 2 + (y - cy) ** 2
            if distance <= (12 + wobble) ** 2:
                rows[y][x] = "z"
            elif distance <= (15 + wobble) ** 2:
                rows[y][x] = "Q"
    # Chips of pale stone at the rim, where the floor broke through. These used
    # to be rune glow — three pixels of cyan per tile, which sounds like nothing
    # until you notice the abyss covers an eighth of the map and the whole point
    # of this pass was to get the blue speckle off the floor.
    for _ in range(3):
        angle = rng.uniform(0, 6.28)
        x = int(cx + math.cos(angle) * 8)
        y = int(cy + math.sin(angle) * 8)
        if 0 <= x < TILE and 0 <= y < TILE:
            rows[y][x] = "w"
    return ["".join(r) for r in rows]


def spire_tile(rng):
    """Obstacle: a shard of pale crystal grown up through the flagstones."""
    rows = [list(row) for row in void_tile(rng, runes=0)]

    peaks = [(20, 4, 8), (13, 13, 5), (28, 15, 6)]
    crystal = set()
    for tip_x, tip_y, half in peaks:
        height = TILE - 5 - tip_y
        for step in range(height):
            y = tip_y + step
            span = int(half * step / max(1, height - 1))
            for x in range(tip_x - span, tip_x + span + 1):
                if 0 <= x < TILE and 0 <= y < TILE:
                    crystal.add((x, y))

    # The light the floor runes used to carry, pooled around its source. Two
    # bands of falloff rather than a smooth gradient: at this size a gradient
    # over five pixels is dithering noise, while two flat steps read as a glow.
    # It stops at the tile edge, which is a real limitation of drawing the
    # ground as independent tiles — but the pool is small enough that the cut
    # lands inside the mottling and nobody reads it as a seam.
    near, far = set(), set()
    for x, y in crystal:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                spot = (x + dx, y + dy)
                if spot in crystal or not (0 <= spot[0] < TILE and 0 <= spot[1] < TILE):
                    continue
                reach = dx * dx + dy * dy
                if reach <= 4:
                    near.add(spot)
                elif reach <= 16:
                    far.add(spot)
    for x, y in far - near:
        if rng.random() < 0.75:
            rows[y][x] = "["
    for x, y in near:
        rows[y][x] = "]" if rng.random() < 0.7 else "["

    for x, y in crystal:
        lit = (x - 20) < -1
        rows[y][x] = ("l" if rng.random() < 0.6 else "J") if lit else (
            "J" if rng.random() < 0.55 else "j")
    for x, y in crystal:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) not in crystal:
                rows[y][x] = "j"
                break
    for _ in range(4):
        x, y = rng.randrange(12, 20), rng.randrange(8, 30)
        if (x, y) in crystal:
            rows[y][x] = "^"
    return ["".join(r) for r in rows]


def pillar_tile(rng):
    """Obstacle: a broken column from whatever this place used to be.

    Outlined and shadowed like everything else you can walk into. It never had
    that, and it got away with it while the floor was covered in rune-light to
    contrast against; with the runes gone the column and the flagstone under it
    are both dark grey-blue, so the edge has to be drawn explicitly.
    """
    rows = [list(row) for row in void_tile(rng, runes=0)]

    # Much wider than it was. A tile is a wall for its full 40 pixels, so a
    # 14-pixel sprite in the middle of one leaves a band of apparently-empty
    # floor you cannot walk through on every side — the invisible wall you feel
    # rather than see. Measured: the old column filled a fifth of its tile once
    # the outline had eaten into it, which is not enough to register at a
    # glance on a floor this dark.
    column = set()
    for y in range(5, 36):
        for x in range(11, 30):
            column.add((x, y))
    # Base plinth, wider than the shaft.
    for y in range(32, 38):
        for x in range(8, 33):
            column.add((x, y))
    # Ragged break across the top: bite pixels out rather than recolour them,
    # so the outline follows the broken silhouette.
    for x in range(11, 30):
        for y in range(5, 5 + rng.randint(0, 6)):
            column.discard((x, y))

    _cast_shadow(rows, column, "Q", offset=(2, 2))

    for x, y in column:
        rows[y][x] = "}" if x < 19 else "{"
    # Fluting: shallow vertical grooves, which is most of what says "column".
    # One step down the ramp, not several — cut in floor colour they stopped
    # being grooves and became dark stripes running through the shaft, which
    # measurably cost more contrast against the flagstones than the detail was
    # worth.
    for x in (15, 22, 26):
        for y in range(8, 34):
            if (x, y) in column:
                rows[y][x] = "{"
    for y in range(32, 38):
        for x in range(8, 33):
            if (x, y) in column:
                rows[y][x] = "{" if y > 35 else "}"
    # A lit seam up the shaft — the one place rune-light still belongs, because
    # here it is on the object rather than scattered over open floor.
    for y in range(14, 32, 4):
        if (19, y) in column:
            rows[y][19] = "Z"

    _outline(rows, column, "z")
    return ["".join(r) for r in rows]


def _in_polygon(x, y, points):
    """Even-odd point-in-polygon test, on pixel centres."""
    inside = False
    px, py = x + 0.5, y + 0.5
    count = len(points)
    for index in range(count):
        ax, ay = points[index]
        bx, by = points[(index + 1) % count]
        if (ay > py) != (by > py):
            crossing = ax + (py - ay) / (by - ay) * (bx - ax)
            if px < crossing:
                inside = not inside
    return inside


def rock_tile(rng):
    """Obstacle: a chunk of split stone, for variety against the trees.

    Built from one irregular polygon rather than overlapping circles. Circles
    were what made the old boulder look like a grey pillow: every silhouette
    edge curved, every shading boundary curved, and nothing anywhere in it was
    straight. Stone reads as stone because it fractures — flat faces meeting at
    hard angles — so the silhouette here is a ring of straight segments at
    jittered radii, and the shading is flat facets divided by straight ridges
    rather than a smooth gradient.
    """
    rows = [list(row) for row in grass_tile(rng, blades=3)]

    centre_x, centre_y = 20, 21
    corners = 8
    points = []
    for index in range(corners):
        angle = 2 * math.pi * index / corners + rng.uniform(-0.16, 0.16)
        # Radii vary a lot between neighbours, which is what keeps the outline
        # from settling back into a circle.
        radius = rng.uniform(12.5, 17.0)
        points.append((centre_x + math.cos(angle) * radius,
                       centre_y + math.sin(angle) * radius * 0.82))

    body = [(x, y) for y in range(TILE) for x in range(TILE)
            if _in_polygon(x, y, points)]

    # Ground shadow, so the rock sits on the grass rather than in it.
    for x, y in body:
        sx, sy = x + 2, y + 3
        if 0 <= sx < TILE and 0 <= sy < TILE and (sx, sy) not in set(body):
            rows[sy][sx] = "H"

    # Facets: split the boulder by angle into wedges and flat-shade each, so
    # neighbouring faces meet at a visible edge instead of blending.
    facet_tone = {}
    for wedge in range(corners):
        middle = 2 * math.pi * (wedge + 0.5) / corners
        # Light from the upper left again, matching the trees and the player.
        lit = math.cos(middle - math.radians(215))
        facet_tone[wedge] = "M" if lit > 0.45 else ("S" if lit > -0.35 else "s")

    for x, y in body:
        angle = math.atan2(y - centre_y, x - centre_x) % (2 * math.pi)
        wedge = int(angle / (2 * math.pi) * corners) % corners
        rows[y][x] = facet_tone[wedge]

    # Ridges along the facet boundaries and a hard outline around the whole
    # thing. Straight lines from the centre outward: these are the creases that
    # say "this broke" rather than "this eroded".
    inside = set(body)
    for index in range(corners):
        end_x, end_y = points[index]
        steps = int(max(abs(end_x - centre_x), abs(end_y - centre_y))) + 1
        for step in range(steps):
            t = step / steps
            rx = int(centre_x + (end_x - centre_x) * t)
            ry = int(centre_y + (end_y - centre_y) * t)
            if (rx, ry) in inside and t > 0.25:
                rows[ry][rx] = "I"

    for x, y in body:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) not in inside:
                rows[y][x] = "I"
                break

    return ["".join(r) for r in rows]


# ---------------------------------------------------------------------------

SPRITES = {
    "wizard_down": (WIZARD_DOWN, 2),
    "wizard_up": (WIZARD_UP, 2),
    "wizard_left": (WIZARD_LEFT, 2),
    "wizard_right": (WIZARD_RIGHT, 2),
    "enemy_goblin": (GOBLIN, 2),
    "enemy_ghost": (GHOST, 2),
    "enemy_guardian": (GOLEM, 2),
    "enemy_boss": (TROLL, 3),
    "enemy_king": (WARCHIEF, 3),
    "gem": (GEM, 2),
    "boss_altar": (ALTAR, 3),
    "chest": (CHEST, 2),
    "potion": (POTION, 2),
    "magnet": (MAGNET, 2),
    "portal": (PORTAL, 2),
}

PROCEDURAL = {
    "floor_grass_0": (grass_tile, 11),
    "floor_grass_1": (grass_tile, 27),
    "floor_grass_2": (grass_tile, 43),
    "floor_dirt": (dirt_patch_tile, 61),
    "wall_tree_0": (tree_tile, 7),
    "wall_tree_1": (tree_tile, 19),
    "wall_rock": (rock_tile, 31),

    "floor_ash_0": (ash_tile, 71),
    "floor_ash_1": (ash_tile, 83),
    "floor_ash_2": (ash_tile, 97),
    "floor_scorch": (scorch_tile, 103),
    "wall_obsidian_0": (obsidian_tile, 113),
    "wall_obsidian_1": (obsidian_tile, 127),
    "wall_stump": (stump_tile, 137),

    "floor_void_0": (void_tile, 151),
    "floor_void_1": (void_tile, 163),
    "floor_void_2": (void_tile, 179),
    "floor_abyss": (abyss_tile, 191),
    "wall_spire_0": (spire_tile, 199),
    "wall_spire_1": (spire_tile, 211),
    "wall_pillar": (pillar_tile, 223),
}


def backup_existing(names):
    """Move any colliding file aside instead of clobbering it."""
    moved = []
    for name in names:
        path = os.path.join(ASSETS, f"{name}.png")
        if os.path.exists(path):
            os.makedirs(BACKUP, exist_ok=True)
            shutil.move(path, os.path.join(BACKUP, f"{name}.png"))
            moved.append(name)
    return moved


def main():
    parser = argparse.ArgumentParser(description="Generate pixel art assets")
    parser.add_argument("--preview", action="store_true",
                        help="also write a contact sheet of everything")
    args = parser.parse_args()

    pygame.init()
    pygame.display.set_mode((320, 240), pygame.HIDDEN)

    names = list(SPRITES) + list(PROCEDURAL)
    moved = backup_existing(names)
    if moved:
        print(f"moved {len(moved)} existing file(s) to assets/old/")

    written = []
    for name, (rows, scale) in SPRITES.items():
        surface = render(rows, scale)
        pygame.image.save(surface, os.path.join(ASSETS, f"{name}.png"))
        written.append((name, surface))
        print(f"  {name:18s} {surface.get_width()}x{surface.get_height()}")

    for name, (builder, seed) in PROCEDURAL.items():
        surface = render(builder(random.Random(seed)))
        pygame.image.save(surface, os.path.join(ASSETS, f"{name}.png"))
        written.append((name, surface))
        print(f"  {name:18s} {surface.get_width()}x{surface.get_height()}")

    if args.preview:
        # Sprites are shown at 3x. At native size you cannot see whether the
        # pixels are right, which is the only reason to look at a contact sheet.
        zoom = 3
        cols = 6
        cell = 200
        rows_needed = -(-len(written) // cols)
        sheet = pygame.Surface((cols * cell, rows_needed * cell))
        sheet.fill((26, 30, 34))
        font = pygame.font.SysFont(None, 20)
        for index, (name, surface) in enumerate(written):
            col, row = index % cols, index // cols
            x, y = col * cell, row * cell
            for by in range(0, cell, 16):
                for bx in range(0, cell, 16):
                    shade = 52 if (bx // 16 + by // 16) % 2 else 40
                    sheet.fill((shade, shade, shade), (x + bx, y + by, 16, 16))
            big = pygame.transform.scale(
                surface, (surface.get_width() * zoom, surface.get_height() * zoom))
            sheet.blit(big, big.get_rect(center=(x + cell // 2, y + cell // 2 - 10)))
            label = font.render(name, True, (220, 224, 230))
            sheet.blit(label, label.get_rect(center=(x + cell // 2, y + cell - 12)))
        path = os.path.join(ROOT, "art_preview.png")
        pygame.image.save(sheet, path)
        print(f"\npreview -> {path}")

    pygame.quit()


if __name__ == "__main__":
    main()
