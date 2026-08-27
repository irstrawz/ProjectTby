"""HUD, menus, level-up cards, run summary and shop.

Every draw function that has clickable regions returns the rects it drew, so the
main loop hit-tests against exactly what is on screen instead of recomputing
layout maths in two places and hoping they agree.
"""

import pygame

from . import assets
from .config import (
    COL_BORDER,
    COL_BORDER_HL,
    COL_DIM,
    COL_GOLD,
    COL_PANEL,
    COL_PANEL_HL,
    COL_TEXT,
    COL_XP,
    MAX_PASSIVES,
    MAX_WEAPONS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from . import maps
from .entities import ARCHETYPES, draw_bar, health_bar_color
from .render import SoftwarePainter
from .save import SHOP_ENTRIES
from .upgrades import PASSIVES_BY_KEY


def format_time(seconds):
    return f"{int(seconds) // 60:d}:{int(seconds) % 60:02d}"


def text(surface, string, pos, size=24, color=COL_TEXT, bold=False, anchor="topleft"):
    label = assets.get_font(size, bold).render(string, True, color)
    surface.blit(label, label.get_rect(**{anchor: pos}))
    return label.get_rect(**{anchor: pos})


def panel(surface, rect, hovered=False, radius=8):
    pygame.draw.rect(surface, COL_PANEL_HL if hovered else COL_PANEL, rect, border_radius=radius)
    pygame.draw.rect(surface, COL_BORDER_HL if hovered else COL_BORDER, rect, 2, border_radius=radius)


def dim(surface, alpha=185):
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((6, 6, 14, alpha))
    surface.blit(overlay, (0, 0))


def hud_backdrop(surface, rect, alpha=130, radius=8):
    """Darken behind a HUD cluster so text stays legible over the map.

    The HUD palette was chosen against a near-black background. Once the ground
    became bright green grass, the dim labels all but disappeared.
    """
    pad = pygame.Rect(rect.x - 6, rect.y - 5, rect.width + 12, rect.height + 10)
    panel_surface = pygame.Surface(pad.size, pygame.SRCALPHA)
    pygame.draw.rect(panel_surface, (8, 10, 16, alpha),
                     panel_surface.get_rect(), border_radius=radius)
    surface.blit(panel_surface, pad.topleft)


# ---------------------------------------------------------------------------
# In-run HUD
# ---------------------------------------------------------------------------

# The left HUD cluster is laid out from these rather than from numbers spelled
# out at each call site. The health bar used to be 250px wide inside a 190px
# backdrop, so it hung ~60px out into the world — visible as a bar that outgrew
# its box the moment max health rose. One width, shared by the bar, the chips
# and the panel, is what stops that happening again.
HUD_LEFT = 10                 # backdrop
HUD_CONTENT_LEFT = 14         # everything drawn inside it
HUD_CONTENT_WIDTH = 250
HUD_PANEL_WIDTH = HUD_CONTENT_WIDTH + (HUD_CONTENT_LEFT - HUD_LEFT) * 2
HUD_CONTENT_RIGHT = HUD_CONTENT_LEFT + HUD_CONTENT_WIDTH


def draw_hud(surface, world):
    player = world.player

    # XP across the top: the bar you actually watch, so it gets the full width.
    # draw_bar belongs to the world layer and speaks to a painter. The HUD
    # draws on a plain surface, so wrap it — SoftwarePainter is a thin
    # forwarder, and this keeps one bar implementation instead of two that
    # drift apart.
    bars = SoftwarePainter(surface)
    draw_bar(bars, 0, 0, SCREEN_WIDTH, 12, player.xp / player.xp_to_next, COL_XP, border=False)

    # Backdrops first, sized to the clusters they sit behind.
    loadout_height = 104 + 27 * len(player.weapons) + 20 * len(player.passives)
    hud_backdrop(surface, pygame.Rect(HUD_LEFT, 16, HUD_PANEL_WIDTH, loadout_height))
    hud_backdrop(surface, pygame.Rect(SCREEN_WIDTH - 210, 18,
                                      196, 96 if player.revives else 74))
    hud_backdrop(surface, pygame.Rect(SCREEN_WIDTH // 2 - 88, 14, 176, 58))
    hud_backdrop(surface, pygame.Rect(10, SCREEN_HEIGHT - 30, 268, 22), alpha=110)

    text(surface, f"LV {player.level}", (14, 20), 30, COL_TEXT, bold=True)

    ratio = player.health / player.max_health
    draw_bar(bars, HUD_CONTENT_LEFT, 50, HUD_CONTENT_WIDTH, 20, ratio,
             health_bar_color(ratio))
    text(surface, f"{int(max(0, player.health))} / {int(player.max_health)}",
         (HUD_CONTENT_LEFT + HUD_CONTENT_WIDTH // 2, 60), 20, COL_TEXT,
         bold=True, anchor="center")

    text(surface, format_time(world.director.elapsed),
         (SCREEN_WIDTH // 2, 30), 44, COL_TEXT, bold=True, anchor="center")
    text(surface, world.map_def.label.upper(), (SCREEN_WIDTH // 2, 58), 20,
         world.map_def.accent, bold=True, anchor="center")

    right = SCREEN_WIDTH - 14
    text(surface, f"{player.gold} gold", (right, 22), 26, COL_GOLD, bold=True, anchor="topright")
    text(surface, f"{player.kills} kills", (right, 48), 22, COL_DIM, anchor="topright")
    text(surface, f"{len(world.enemies)} on field", (right, 70), 20, COL_DIM, anchor="topright")
    if player.revives:
        text(surface, f"Second Wind x{player.revives}", (right, 92), 20, (255, 235, 140),
             anchor="topright")

    _draw_loadout(surface, player)

    if world.announcement_timer > 0:
        alpha = min(1.0, world.announcement_timer / 0.5)
        label = assets.get_font(52, bold=True).render(world.announcement, True, COL_GOLD)
        label.set_alpha(int(255 * alpha))
        surface.blit(label, label.get_rect(center=(SCREEN_WIDTH // 2, 120)))

    _draw_interact_prompt(surface, world)

    text(surface, "WASD move    E interact    ESC pause",
         (14, SCREEN_HEIGHT - 26), 19, (146, 150, 172))


def _draw_interact_prompt(surface, world):
    target = world.nearest_interactable()
    if target is None:
        return
    kind, thing = target

    if kind == "altar":
        message, color = "Press  E  to summon a Warden early  (+gold)", COL_GOLD
    elif kind == "portal":
        destination = maps.MAPS_BY_KEY[thing.destination]
        message = f"Press  E  to enter {destination.phrase}"
        color = destination.accent
    else:
        affordable = world.player.gold >= thing.cost
        message = f"Press  E  to open  —  {thing.cost} gold"
        # Red when you cannot pay, so the answer is readable before you press.
        color = COL_GOLD if affordable else (228, 118, 108)
        if not affordable:
            message = f"Locked  —  {thing.cost} gold  (you have {world.player.gold})"

    label = assets.get_font(28, True).render(message, True, color)
    box = label.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 52))
    hud_backdrop(surface, box, alpha=150)
    surface.blit(label, box)


def _slot_header(surface, label, used, total, y):
    """Row heading that makes the slot cap visible while you are choosing."""
    text(surface, label, (16, y), 17, (154, 158, 186), bold=True)
    full = used >= total
    text(surface, f"{used}/{total}", (HUD_CONTENT_RIGHT, y), 17,
         COL_GOLD if full else (154, 158, 186), bold=True, anchor="topright")
    return y + 18


def _draw_loadout(surface, player):
    """Weapon and passive chips down the left edge."""
    y = _slot_header(surface, "WEAPONS", len(player.weapons), MAX_WEAPONS, 84)
    for weapon in player.weapons:
        chip = pygame.Rect(HUD_CONTENT_LEFT, y, HUD_CONTENT_WIDTH, 24)
        pygame.draw.rect(surface, (24, 24, 38), chip, border_radius=5)
        pygame.draw.rect(surface, weapon.color, chip, 1, border_radius=5)
        text(surface, weapon.label, (chip.x + 8, chip.y + 5), 20, weapon.color)
        text(surface, f"{weapon.level}", (chip.right - 9, chip.y + 5), 20, COL_TEXT,
             bold=True, anchor="topright")
        y += 27

    y = _slot_header(surface, "PASSIVES", len(player.passives), MAX_PASSIVES, y + 8)
    for key, level in sorted(player.passives.items()):
        passive = PASSIVES_BY_KEY[key]
        text(surface, f"{passive.label}  {level}", (18, y), 19, passive.color)
        y += 20


def draw_updating(surface, stage_text, progress):
    """Full-screen progress while an update installs.

    Deliberately a dead-end screen with no way back: once the swap script has
    been handed the process id there is nothing sensible to cancel into, and
    offering a button that cannot work is worse than offering none.
    """
    surface.fill((10, 10, 22))
    text(surface, "UPDATING", (SCREEN_WIDTH // 2, 250), 62, COL_GOLD, bold=True,
         anchor="center")
    text(surface, stage_text, (SCREEN_WIDTH // 2, 312), 26, COL_TEXT, anchor="center")

    track = pygame.Rect(SCREEN_WIDTH // 2 - 240, 350, 480, 18)
    pygame.draw.rect(surface, (44, 44, 58), track, border_radius=9)
    if progress > 0:
        filled = track.copy()
        filled.width = max(8, int(track.width * min(1.0, progress)))
        pygame.draw.rect(surface, COL_GOLD, filled, border_radius=9)
    pygame.draw.rect(surface, (96, 96, 118), track, 1, border_radius=9)
    text(surface, "the game will restart itself when it is done",
         (SCREEN_WIDTH // 2, 396), 20, COL_DIM, anchor="center")


# ---------------------------------------------------------------------------
# Level-up
# ---------------------------------------------------------------------------

CARD_WIDTH = 340
CARD_HEIGHT = 300
CARD_GAP = 26


def level_up_card_rects(count):
    """Cards shrink to fit. Fortune can produce a fourth, and four cards at the
    full 340px width would run 158px past the edge of the screen."""
    width = min(CARD_WIDTH, (SCREEN_WIDTH - 80 - (count - 1) * CARD_GAP) // max(1, count))
    total = count * width + (count - 1) * CARD_GAP
    start_x = SCREEN_WIDTH // 2 - total // 2
    top = SCREEN_HEIGHT // 2 - CARD_HEIGHT // 2 + 24
    return [
        pygame.Rect(start_x + i * (width + CARD_GAP), top, width, CARD_HEIGHT)
        for i in range(count)
    ]


def rect_wrap_width(pixel_width):
    """Characters that fit across a card. Cards shrink when a fourth appears,
    so the wrap point has to shrink with them or the text runs off the edge."""
    return int((pixel_width - 32) / 10.6)


def draw_level_up(surface, offers, mouse_pos, pending):
    dim(surface)
    text(surface, "LEVEL UP", (SCREEN_WIDTH // 2, 108), 74, COL_GOLD, bold=True, anchor="center")
    subtitle = "Choose an upgrade" if pending <= 1 else f"Choose an upgrade  ({pending} pending)"
    text(surface, subtitle, (SCREEN_WIDTH // 2, 156), 28, COL_DIM, anchor="center")

    rects = level_up_card_rects(len(offers))
    wrap_at = max(20, rect_wrap_width(rects[0].width))

    for index, (offer, rect) in enumerate(zip(offers, rects)):
        hovered = rect.collidepoint(mouse_pos)
        tier = getattr(offer, "rarity", None)

        pygame.draw.rect(surface, COL_PANEL_HL if hovered else COL_PANEL, rect,
                         border_radius=12)
        # The border carries the tier, so which card is the good one is obvious
        # from across the screen before you read a word of it.
        border = tier.color if tier and not tier.is_common else (
            COL_BORDER_HL if hovered else COL_BORDER)
        pygame.draw.rect(surface, border, rect, 4 if tier and not tier.is_common else 2,
                         border_radius=12)
        pygame.draw.rect(surface, offer.color, (rect.x + 3, rect.y + 3, rect.width - 6, 6))

        text(surface, f"{index + 1}", (rect.x + 16, rect.y + 24), 26, COL_DIM, bold=True)
        if tier is not None:
            text(surface, tier.label.upper(), (rect.centerx, rect.y + 26), 22, tier.color,
                 bold=True, anchor="center")

        text(surface, offer.title, (rect.centerx, rect.y + 68), 36, offer.color,
             bold=True, anchor="center")
        text(surface, offer.subtitle, (rect.centerx, rect.y + 108), 23, COL_DIM,
             anchor="center")

        # Four wrapped lines is the most that fits above the footer; a longer
        # description used to run its last line straight through "grants N levels".
        for line_index, line in enumerate(_wrap(offer.detail, wrap_at)[:4]):
            text(surface, line, (rect.centerx, rect.y + 148 + line_index * 24), 23,
                 COL_TEXT, anchor="center")

        levels = getattr(offer, "levels", 1)
        if levels > 1:
            text(surface, f"grants {levels} levels", (rect.centerx, rect.bottom - 48),
                 24, tier.color if tier else COL_GOLD, bold=True, anchor="center")
        if tier is not None and tier.bonus_passive:
            text(surface, "and a bonus passive", (rect.centerx, rect.bottom - 22),
                 22, tier.color, anchor="center")

    keys = " / ".join(str(i + 1) for i in range(len(offers)))
    text(surface, f"Click a card or press {keys}",
         (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 70), 24, COL_DIM, anchor="center")
    return rects


def _wrap(string, width):
    words, lines, current = string.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Button menus
# ---------------------------------------------------------------------------

def button_rects(count, width=340, height=58, gap=16, top=None):
    total = count * height + (count - 1) * gap
    start_y = top if top is not None else SCREEN_HEIGHT // 2 - total // 2 + 40
    return [
        pygame.Rect(SCREEN_WIDTH // 2 - width // 2, start_y + i * (height + gap), width, height)
        for i in range(count)
    ]


def draw_buttons(surface, labels, mouse_pos, top=None):
    rects = button_rects(len(labels), top=top)
    for label, rect in zip(labels, rects):
        hovered = rect.collidepoint(mouse_pos)
        panel(surface, rect, hovered)
        text(surface, label, rect.center, 32, COL_TEXT if hovered else (206, 210, 230),
             bold=hovered, anchor="center")
    return rects


def button_row_rects(count, width=300, height=58, gap=20, top=548):
    """Side-by-side buttons, for screens where a vertical stack will not fit."""
    total = count * width + (count - 1) * gap
    start_x = SCREEN_WIDTH // 2 - total // 2
    return [
        pygame.Rect(start_x + i * (width + gap), top, width, height)
        for i in range(count)
    ]


def draw_button_row(surface, labels, mouse_pos, top=548):
    rects = button_row_rects(len(labels), top=top)
    for label, rect in zip(labels, rects):
        hovered = rect.collidepoint(mouse_pos)
        panel(surface, rect, hovered)
        text(surface, label, rect.center, 30, COL_TEXT if hovered else (206, 210, 230),
             bold=hovered, anchor="center")
    return rects


def update_banner_rect():
    """Where the "an update is available" strip sits on the title screen.

    Its own geometry function, hit-tested before the menu buttons, rather than a
    fifth entry in TITLE_OPTIONS — the buttons are addressed by index in several
    places, and a row that only sometimes exists would shift all of them.
    """
    return pygame.Rect(SCREEN_WIDTH // 2 - 260, 214, 520, 44)


def draw_title(surface, save, labels, mouse_pos, version=None, update=None,
               update_note=""):
    surface.fill((10, 10, 22))
    text(surface, "PROJECT TBY", (SCREEN_WIDTH // 2, 140), 92, (110, 200, 255),
         bold=True, anchor="center")
    text(surface, "survive the arena", (SCREEN_WIDTH // 2, 200), 30, COL_DIM, anchor="center")

    if update is not None:
        banner = update_banner_rect()
        hovered = banner.collidepoint(mouse_pos)
        pygame.draw.rect(surface, (32, 54, 40) if hovered else (24, 42, 32), banner,
                         border_radius=8)
        pygame.draw.rect(surface, (120, 220, 140) if hovered else (70, 140, 90), banner,
                         2, border_radius=8)
        size = f"  ({update.size_mb:.0f} MB)" if update.size_mb >= 1 else ""
        text(surface, f"Update to {update.version} available{size}  —  click to install",
             banner.center, 24, (170, 240, 180) if hovered else (130, 200, 150),
             bold=hovered, anchor="center")
    elif update_note:
        text(surface, update_note, (SCREEN_WIDTH // 2, 232), 20, COL_DIM, anchor="center")

    rects = draw_buttons(surface, labels, mouse_pos, top=270)

    if version:
        text(surface, f"v{version}", (14, SCREEN_HEIGHT - 26), 20, COL_DIM)

    text(surface, f"{save.gold} gold", (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 96), 32,
         COL_GOLD, bold=True, anchor="center")
    if save.runs:
        text(surface,
             f"best {format_time(save.best_time)}    {save.best_kills} kills    {save.runs} runs",
             (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 58), 24, COL_DIM, anchor="center")
        depth = f"reached {save.deepest} of {len(maps.MAPS)} arenas"
        if save.wins:
            depth += f"    {save.wins} run(s) completed"
        text(surface, depth, (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 32), 22,
             (150, 235, 255) if save.wins else COL_DIM, anchor="center")
    return rects


# ---------------------------------------------------------------------------
# Starting weapon selection
# ---------------------------------------------------------------------------

SELECT_COLS = 4
SELECT_WIDTH = 288
SELECT_GAP = 14
SELECT_TOP = 148
SELECT_BOTTOM = 636
SELECT_MAX_HEIGHT = 168


def weapon_select_rects(count):
    """Lay the roster out in a grid that always fits on screen.

    Card height is derived from the row count rather than fixed: the roster
    grows every time a weapon is added, and a fixed height silently pushed the
    bottom row off the screen at eleven weapons.
    """
    rows = max(1, -(-count // SELECT_COLS))
    available = SELECT_BOTTOM - SELECT_TOP
    height = min(SELECT_MAX_HEIGHT, (available - (rows - 1) * SELECT_GAP) // rows)

    rects = []
    for index in range(count):
        col, row = index % SELECT_COLS, index // SELECT_COLS
        # Centre each row independently, so a partly-filled last row sits in the
        # middle instead of hugging the left edge.
        in_row = min(SELECT_COLS, count - row * SELECT_COLS)
        row_width = in_row * SELECT_WIDTH + (in_row - 1) * SELECT_GAP
        start_x = SCREEN_WIDTH // 2 - row_width // 2
        rects.append(
            pygame.Rect(
                start_x + col * (SELECT_WIDTH + SELECT_GAP),
                SELECT_TOP + row * (height + SELECT_GAP),
                SELECT_WIDTH,
                height,
            )
        )
    return rects


def draw_weapon_select(surface, weapon_types, mouse_pos):
    surface.fill((10, 10, 22))
    text(surface, "CHOOSE YOUR WEAPON", (SCREEN_WIDTH // 2, 54), 58, (110, 200, 255),
         bold=True, anchor="center")
    text(surface, "everything else you find along the way",
         (SCREEN_WIDTH // 2, 100), 25, COL_DIM, anchor="center")

    rects = weapon_select_rects(len(weapon_types))
    for cls, rect in zip(weapon_types, rects):
        hovered = rect.collidepoint(mouse_pos)
        panel(surface, rect, hovered, radius=10)
        pygame.draw.rect(surface, cls.color, (rect.x, rect.y, rect.width, 5),
                         border_top_left_radius=10, border_top_right_radius=10)
        text(surface, cls.label, (rect.centerx, rect.y + 24), 30, cls.color,
             bold=True, anchor="center")
        for line_index, line in enumerate(_wrap(cls.description, 30)):
            text(surface, line, (rect.centerx, rect.y + 66 + line_index * 23), 20,
                 COL_TEXT if hovered else COL_DIM, anchor="center")

    text(surface, "Six weapon slots, six passive slots. Max two weapons to fuse them.",
         (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 62), 23, COL_DIM, anchor="center")
    text(surface, "Esc to go back", (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 32), 21,
         (110, 114, 140), anchor="center")
    return rects


def draw_pause(surface, labels, mouse_pos, sfx_volume=None, music_volume=None,
               muted=False, top=230):
    dim(surface)
    text(surface, "PAUSED", (SCREEN_WIDTH // 2, 118), 70, COL_GOLD, bold=True, anchor="center")
    rects = draw_buttons(surface, labels, mouse_pos, top=top)
    if sfx_volume is not None:
        draw_volume(surface, sfx_volume, music_volume, muted)
    return rects


def draw_volume(surface, sfx_volume, music_volume, muted):
    """Volume readout and its keys, shown on the pause screen.

    Bound keys nobody knows about are the same as no keys at all, so the levels
    and the bindings are drawn together — this is the only place in the game
    that documents them.
    """
    base = SCREEN_HEIGHT - 132
    label_color = (150, 150, 165) if muted else COL_TEXT
    for row, (name, value, keys) in enumerate((
        ("SOUND", sfx_volume, "- / ="),
        ("MUSIC", music_volume, "[ / ]"),
    )):
        y = base + row * 30
        text(surface, name, (SCREEN_WIDTH // 2 - 210, y), 24, label_color, anchor="midleft")

        track = pygame.Rect(SCREEN_WIDTH // 2 - 120, y - 7, 200, 14)
        pygame.draw.rect(surface, (48, 48, 62), track, border_radius=7)
        if value > 0 and not muted:
            filled = track.copy()
            filled.width = max(4, int(track.width * value))
            pygame.draw.rect(surface, COL_GOLD, filled, border_radius=7)
        pygame.draw.rect(surface, (90, 90, 110), track, 1, border_radius=7)

        shown = "muted" if muted else f"{int(round(value * 100))}%"
        text(surface, shown, (track.right + 16, y), 24, label_color, anchor="midleft")
        text(surface, keys, (track.right + 84, y), 22, (130, 130, 145), anchor="midleft")

    text(surface, "M mutes  —  Settings for the rest", (SCREEN_WIDTH // 2, base + 66), 22,
         (130, 130, 145), anchor="center")


def draw_fps(surface, fps):
    """Frame counter, bottom right, behind its own backdrop so it stays legible.

    Coloured against the 60fps target rather than shown as a bare number: the
    useful question is "am I dropping frames", not "what is the number".
    """
    label = f"{fps:5.1f} fps"
    colour = (150, 230, 150) if fps >= 55 else ((235, 210, 120) if fps >= 40 else (235, 120, 110))
    box = pygame.Rect(SCREEN_WIDTH - 108, SCREEN_HEIGHT - 30, 94, 20)
    hud_backdrop(surface, box, alpha=140)
    text(surface, label, box.center, 20, colour, bold=True, anchor="center")


# ---------------------------------------------------------------------------
# Run summary
# ---------------------------------------------------------------------------

def draw_summary(surface, result, earned_gold, labels, mouse_pos):
    surface.fill((10, 10, 22))
    won = result.get("victory")
    title = "THE WARCHIEF FALLS" if won else "RUN OVER"
    text(surface, title, (SCREEN_WIDTH // 2, 48), 62,
         (150, 235, 255) if won else (255, 90, 90), bold=True, anchor="center")

    # Headline numbers across the top.
    headline = [
        ("SURVIVED", format_time(result["time"]), COL_TEXT),
        ("LEVEL", str(result["level"]), COL_TEXT),
        ("KILLS", str(result["kills"]), COL_TEXT),
        ("WARDENS", str(result["bosses"]), COL_TEXT),
        ("CHESTS", str(result.get("chests_opened", 0)), COL_TEXT),
        ("MAPS", str(result.get("maps_cleared", 0) + 1), COL_TEXT),
        ("GOLD", str(earned_gold), COL_GOLD),
    ]
    strip = pygame.Rect(60, 92, SCREEN_WIDTH - 120, 78)
    panel(surface, strip, radius=10)
    for index, (label, value, color) in enumerate(headline):
        cx = strip.x + strip.width * (index + 0.5) / len(headline)
        text(surface, label, (cx, strip.y + 12), 20, COL_DIM, bold=True, anchor="center")
        text(surface, value, (cx, strip.y + 36), 38, color, bold=True, anchor="center")

    where = result.get("map")
    if where:
        line = f"cleared {where}" if won else f"fell in {where}"
        text(surface, line, (SCREEN_WIDTH // 2, strip.bottom + 8), 21,
             (150, 235, 255) if won else COL_DIM, anchor="center")

    spent = result.get("gold_spent", 0)
    if spent:
        text(surface, f"{spent} gold spent on chests during the run",
             (SCREEN_WIDTH // 2, strip.bottom + 30), 21, COL_DIM, anchor="center")

    _draw_damage_panel(surface, result, pygame.Rect(60, 194, 596, 320))
    _draw_kills_panel(surface, result, pygame.Rect(674, 194, 546, 320))

    return draw_button_row(surface, labels, mouse_pos, top=544)


def _draw_damage_panel(surface, result, box):
    panel(surface, box, radius=10)
    text(surface, "DAMAGE BY WEAPON", (box.x + 18, box.y + 14), 22, COL_DIM, bold=True)

    rows = sorted(result.get("damage_by_weapon", []), key=lambda item: -item[1])
    total = sum(value for _, value in rows)
    if not rows or total <= 0:
        text(surface, "no damage recorded", (box.centerx, box.centery), 24, COL_DIM,
             anchor="center")
        return

    peak = max(value for _, value in rows)
    y = box.y + 48
    for label, value in rows[:8]:
        share = value / total
        text(surface, label, (box.x + 18, y), 22, COL_TEXT)
        text(surface, f"{int(value):,}", (box.right - 84, y), 22, COL_TEXT, anchor="topright")
        text(surface, f"{share * 100:4.1f}%", (box.right - 18, y), 22,
             COL_GOLD if share > 0.35 else COL_DIM, anchor="topright")
        bar_width = int((box.width - 36) * (value / peak))
        pygame.draw.rect(surface, (52, 56, 84), (box.x + 18, y + 24, box.width - 36, 7),
                         border_radius=3)
        if bar_width > 0:
            pygame.draw.rect(surface, COL_XP, (box.x + 18, y + 24, bar_width, 7),
                             border_radius=3)
        y += 38


def _draw_kills_panel(surface, result, box):
    panel(surface, box, radius=10)
    text(surface, "KILLS BY ENEMY", (box.x + 18, box.y + 14), 22, COL_DIM, bold=True)

    by_type = result.get("kills_by_type", {})
    rows = [
        (ARCHETYPES[key].label, count)
        for key, count in sorted(by_type.items(), key=lambda item: -item[1])
        if key in ARCHETYPES
    ]
    if not rows:
        text(surface, "no kills recorded", (box.centerx, box.centery), 24, COL_DIM,
             anchor="center")
        return

    total = sum(count for _, count in rows)
    peak = max(count for _, count in rows)
    y = box.y + 48
    for label, count in rows:
        text(surface, label, (box.x + 18, y), 22, COL_TEXT)
        text(surface, str(count), (box.right - 84, y), 22, COL_TEXT, anchor="topright")
        text(surface, f"{count / total * 100:4.1f}%", (box.right - 18, y), 22, COL_DIM,
             anchor="topright")
        bar_width = int((box.width - 36) * (count / peak))
        pygame.draw.rect(surface, (52, 56, 84), (box.x + 18, y + 24, box.width - 36, 7),
                         border_radius=3)
        if bar_width > 0:
            pygame.draw.rect(surface, (220, 110, 100), (box.x + 18, y + 24, bar_width, 7),
                             border_radius=3)
        y += 38

    elites = result.get("elite_kills", 0)
    text(surface, f"of which {elites} were elites", (box.x + 18, box.bottom - 32), 21,
         (255, 150, 150) if elites else COL_DIM)


# ---------------------------------------------------------------------------
# Shop
# ---------------------------------------------------------------------------

SHOP_COLS = 3
SHOP_CARD = (380, 118)


def shop_rects():
    rects = []
    total_width = SHOP_COLS * SHOP_CARD[0] + (SHOP_COLS - 1) * 18
    start_x = SCREEN_WIDTH // 2 - total_width // 2
    for index in range(len(SHOP_ENTRIES)):
        col, row = index % SHOP_COLS, index // SHOP_COLS
        rects.append(
            pygame.Rect(
                start_x + col * (SHOP_CARD[0] + 18),
                150 + row * (SHOP_CARD[1] + 16),
                *SHOP_CARD,
            )
        )
    return rects


def shop_back_rect():
    return pygame.Rect(SCREEN_WIDTH // 2 - 130, SCREEN_HEIGHT - 82, 260, 54)


def draw_shop(surface, save, mouse_pos):
    surface.fill((10, 10, 22))
    text(surface, "SANCTUM", (SCREEN_WIDTH // 2, 58), 62, COL_GOLD, bold=True, anchor="center")
    text(surface, f"{save.gold} gold", (SCREEN_WIDTH // 2, 106), 30, COL_GOLD, anchor="center")

    rects = shop_rects()
    for entry, rect in zip(SHOP_ENTRIES, rects):
        level = save.level_of(entry.key)
        maxed = level >= entry.max_level
        affordable = save.can_afford(entry)
        hovered = rect.collidepoint(mouse_pos) and affordable

        panel(surface, rect, hovered)
        title_color = COL_DIM if maxed else COL_TEXT
        text(surface, entry.label, (rect.x + 16, rect.y + 14), 30, title_color, bold=True)
        text(surface, entry.description, (rect.x + 16, rect.y + 46), 22, COL_DIM)

        pip_x = rect.x + 16
        for pip in range(entry.max_level):
            color = COL_GOLD if pip < level else (58, 58, 78)
            pygame.draw.rect(surface, color, (pip_x + pip * 16, rect.y + 82, 11, 11),
                             border_radius=2)

        if maxed:
            label, color = "MAX", COL_GOLD
        else:
            label = f"{entry.cost(level)} g"
            color = COL_GOLD if affordable else (120, 100, 70)
        text(surface, label, (rect.right - 16, rect.y + 78), 28, color, bold=True,
             anchor="topright")

    back = shop_back_rect()
    panel(surface, back, back.collidepoint(mouse_pos))
    text(surface, "Back", back.center, 30, COL_TEXT, anchor="center")
    return rects, back


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

SETTINGS_ROW_HEIGHT = 56
SETTINGS_ROW_GAP = 10
SETTINGS_TOP = 138
SETTINGS_WIDTH = 720
# Where the control sits inside a row. Sliders and toggles share it so the
# column of values lines up down the screen instead of stepping about.
CONTROL_LEFT = 380
CONTROL_WIDTH = 250


def settings_row_rects(count):
    left = SCREEN_WIDTH // 2 - SETTINGS_WIDTH // 2
    return [
        pygame.Rect(left, SETTINGS_TOP + index * (SETTINGS_ROW_HEIGHT + SETTINGS_ROW_GAP),
                    SETTINGS_WIDTH, SETTINGS_ROW_HEIGHT)
        for index in range(count)
    ]


def settings_slider_rect(row):
    """The draggable track inside a row.

    Deliberately taller than it looks: the painted groove is 14px, but a 14px
    grab target is a miserable thing to hit with a mouse, so the rect the drag
    code tests against covers the row's full height.
    """
    return pygame.Rect(row.x + CONTROL_LEFT, row.y + 8, CONTROL_WIDTH,
                       SETTINGS_ROW_HEIGHT - 16)


def slider_value_at(row, mouse_x):
    """Where along a row's slider a given screen x falls, as 0..1."""
    track = settings_slider_rect(row)
    if track.width <= 0:
        return 0.0
    return max(0.0, min(1.0, (mouse_x - track.x) / track.width))


def settings_back_rect():
    return pygame.Rect(SCREEN_WIDTH // 2 - 130, SCREEN_HEIGHT - 74, 260, 50)


def settings_reset_rect():
    return pygame.Rect(SCREEN_WIDTH // 2 - 400, SCREEN_HEIGHT - 74, 220, 50)


def draw_settings(surface, options, values, mouse_pos, dragging=None):
    """Draw every setting from its declaration and return the row rects.

    Rows are generated from ``options`` rather than written out, so a new
    setting appears here the moment it is declared in game/settings.py.
    """
    surface.fill((10, 10, 22))
    text(surface, "SETTINGS", (SCREEN_WIDTH // 2, 58), 62, COL_GOLD, bold=True, anchor="center")
    text(surface, "click and drag the bars", (SCREEN_WIDTH // 2, 104), 22, COL_DIM,
         anchor="center")

    rects = settings_row_rects(len(options))
    for option, row in zip(options, rects):
        hovered = row.collidepoint(mouse_pos) or dragging == option.key
        panel(surface, row, hovered, radius=8)
        text(surface, option.label, (row.x + 18, row.y + 10), 26,
             COL_TEXT if hovered else (206, 210, 230), bold=hovered)
        text(surface, option.description, (row.x + 18, row.y + 33), 18, COL_DIM)

        value = values[option.key]
        if option.kind == "slider":
            _draw_slider(surface, row, value, hovered)
        elif option.kind == "toggle":
            _draw_toggle(surface, row, value, hovered)
        else:
            _draw_choice(surface, row, option, value, hovered)

        if option.restart:
            # Left of the control, not in the right-hand value column — that
            # column already carries the current value and the two collided.
            text(surface, "takes effect on restart",
                 (row.x + CONTROL_LEFT - 16, row.centery), 18, (168, 152, 108),
                 anchor="midright")

    for rect, label in ((settings_back_rect(), "Back"),
                        (settings_reset_rect(), "Reset to defaults")):
        hovered = rect.collidepoint(mouse_pos)
        panel(surface, rect, hovered)
        text(surface, label, rect.center, 26, COL_TEXT if hovered else (206, 210, 230),
             bold=hovered, anchor="center")
    return rects


def _draw_slider(surface, row, value, hovered):
    track = settings_slider_rect(row)
    groove = pygame.Rect(track.x, track.centery - 7, track.width, 14)
    pygame.draw.rect(surface, (44, 44, 58), groove, border_radius=7)
    if value > 0:
        filled = groove.copy()
        filled.width = max(6, int(groove.width * value))
        pygame.draw.rect(surface, COL_GOLD if hovered else (176, 148, 66), filled,
                         border_radius=7)
    pygame.draw.rect(surface, (96, 96, 118), groove, 1, border_radius=7)

    # The knob is what tells you the bar is draggable at all.
    knob_x = groove.x + int(groove.width * value)
    knob = pygame.Rect(0, 0, 14, 26)
    knob.center = (knob_x, groove.centery)
    pygame.draw.rect(surface, (232, 226, 200) if hovered else (196, 190, 168), knob,
                     border_radius=4)
    pygame.draw.rect(surface, (28, 28, 38), knob, 1, border_radius=4)

    text(surface, f"{int(round(value * 100))}%", (row.right - 16, row.centery), 24,
         COL_TEXT if hovered else COL_DIM, bold=hovered, anchor="midright")


def _draw_toggle(surface, row, value, hovered):
    track = settings_slider_rect(row)
    box = pygame.Rect(track.x, track.centery - 14, 64, 28)
    pygame.draw.rect(surface, (58, 104, 62) if value else (58, 44, 48), box,
                     border_radius=14)
    pygame.draw.rect(surface, (110, 110, 132), box, 1, border_radius=14)
    knob = pygame.Rect(0, 0, 22, 22)
    knob.center = (box.right - 14 if value else box.x + 14, box.centery)
    pygame.draw.rect(surface, (226, 232, 226) if hovered else (190, 196, 190), knob,
                     border_radius=11)
    text(surface, "on" if value else "off", (row.right - 16, row.centery), 24,
         COL_TEXT if hovered else COL_DIM, bold=hovered, anchor="midright")


def _draw_choice(surface, row, option, value, hovered):
    track = settings_slider_rect(row)
    label = str(value).upper()
    box = pygame.Rect(track.x, track.centery - 15, 150, 30)
    pygame.draw.rect(surface, (34, 34, 48), box, border_radius=6)
    pygame.draw.rect(surface, COL_BORDER_HL if hovered else COL_BORDER, box, 1,
                     border_radius=6)
    text(surface, label, box.center, 22, COL_TEXT if hovered else (206, 210, 230),
         bold=hovered, anchor="center")
    text(surface, "click to change", (row.right - 16, row.centery), 20,
         COL_TEXT if hovered else COL_DIM, anchor="midright")
