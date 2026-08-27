"""Project Tby — entry point and state machine.

    python main.py                 play
    python main.py --smoke 180     headless 180-second simulation, prints a report

The smoke mode exists so balance and crash-safety can be checked without sitting
through a ten-minute run by hand.
"""

import argparse
import os
import random
import threading

import pygame

from game import assets, audio, render, save, settings, ui, updater, upgrades
from game import version as version_module
from game.config import (
    CAPTION,
    FPS,
    GOLD_PER_MINUTE_SURVIVED,
    MAX_DT,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from game import maps
from game.weapons import STARTING_WEAPON, WEAPON_TYPES
from game.world import World

TITLE_OPTIONS = ["Start Run", "Sanctum", "Settings", "Quit"]
PAUSE_OPTIONS = ["Continue", "Settings", "Restart", "Main Menu", "Quit"]
# Five buttons no longer clear the volume readout at the bottom of the pause
# screen, so the stack starts higher. Defined once because draw and click
# both need it and a mismatch means buttons that highlight one row and
# activate another.
PAUSE_TOP = 196
SUMMARY_OPTIONS = ["Run Again", "Sanctum", "Main Menu"]

MOVE_KEYS = {
    pygame.K_a: (-1, 0), pygame.K_LEFT: (-1, 0),
    pygame.K_d: (1, 0), pygame.K_RIGHT: (1, 0),
    pygame.K_w: (0, -1), pygame.K_UP: (0, -1),
    pygame.K_s: (0, 1), pygame.K_DOWN: (0, 1),
}


def read_movement(keys):
    move = pygame.Vector2()
    for key, (dx, dy) in MOVE_KEYS.items():
        if keys[key]:
            move.x += dx
            move.y += dy
    return move


class Game:
    def __init__(self, headless=False, seed=None, use_gpu=None):
        pygame.init()
        # The save loads first: it carries the renderer choice, and the window
        # cannot be opened twice to change its mind afterwards.
        self.save = save.load()
        self.settings = self.save.settings

        # ``use_gpu=None`` means "whatever the player picked". Software is the
        # default because it is measurably faster at the entity counts this game
        # reaches — see game/render.py for the crossover. The GPU backend owns
        # its own SDL window, so ``screen`` is None on that path.
        if use_gpu is None:
            use_gpu = self.settings.renderer == "gpu"
        self.painter, self.screen = render.create(
            (SCREEN_WIDTH, SCREEN_HEIGHT), use_gpu=use_gpu, hidden=headless)
        if self.screen is not None:
            pygame.display.set_caption(CAPTION)
        assets.load_images()

        self.clock = pygame.time.Clock()
        self.rng = random.Random(seed)
        self.headless = headless

        # Headless runs — the self-test, the DPS bench, the smoke simulation —
        # have no audio device and no listener. Skipping init there keeps them
        # fast and avoids opening a device on machines running batch jobs;
        # audio degrades to no-ops, so nothing downstream needs to know.
        if not headless:
            audio.init(self.save.sfx_volume, self.save.music_volume)
            audio.play_music("menu")

        self.state = "title"
        self.world = None
        self.offers = []
        self.result = None
        self.earned_gold = 0
        self.starting_weapon = STARTING_WEAPON
        self.running = True
        self.muted = False
        self.hovered = None
        # Which setting the mouse is currently dragging, and whether anything
        # changed since the last write. Settings are saved on mouse-up rather
        # than on every motion event — dragging a slider across the screen would
        # otherwise write the save file a hundred times in a second.
        self.dragging = None
        self.settings_dirty = False
        self.return_to = "title"

        # Update state. The check runs on a worker thread and writes here; the
        # draw loop only reads it, so a slow or dead server never stalls a frame.
        self.update_available = None
        self.update_note = ""
        self.update_stage = ""
        self.update_progress = 0.0
        if not headless and version_module.UPDATE_MANIFEST_URL:
            updater.check_in_background(self._on_update_checked)

    # -- updates -------------------------------------------------------------
    def _on_update_checked(self, update, error):
        """Called from the worker thread — assignment only, no drawing."""
        self.update_available = update
        # A failed check is worth a quiet line on the title screen and nothing
        # more. Being unable to reach a release server is not the player's
        # problem and must never block starting a run.
        self.update_note = error or ""

    def start_update(self):
        """Download, verify, stage, then hand off and quit.

        Runs on a worker thread so the progress bar keeps drawing. The handoff
        script is already waiting on this process id by the time ``running`` is
        cleared, so the exit has to actually happen.
        """
        update = self.update_available
        if update is None:
            return
        self.state = "updating"
        self.update_stage = f"Downloading {update.version}..."
        self.update_progress = 0.0

        def work():
            try:
                archive = updater.download(
                    update, on_progress=lambda f: setattr(self, "update_progress", f))
                self.update_stage = "Checking and unpacking..."
                self.update_progress = 1.0
                staging = updater.stage(archive)
                os.unlink(archive)
                self.update_stage = "Restarting..."
                updater.apply_and_restart(staging)
                self.running = False
            except updater.UpdateError as exc:
                self.update_note = str(exc)
                self.update_available = None
                self.state = "title"

        threading.Thread(target=work, name="update-install", daemon=True).start()

    # -- run lifecycle -------------------------------------------------------
    def choose_starting_weapon(self):
        self.state = "choose_weapon"

    def start_run(self, starting_weapon=None):
        self.starting_weapon = starting_weapon or self.starting_weapon
        self.world = World(self.save.upgrades, seed=self.rng.random(),
                           starting_weapon=self.starting_weapon,
                           map_key=maps.DEFAULT_MAP)
        self.offers = []
        audio.music_for_map(maps.DEFAULT_MAP)
        self.state = "playing"

    def travel(self, map_key):
        """Step through a portal, carrying the run into the next arena."""
        self.world = World(self.save.upgrades, seed=self.rng.random(),
                           map_key=map_key, carry=self.world)
        self.offers = []
        audio.play("portal_enter")
        audio.music_for_map(map_key)
        self.state = "playing"

    def finish_run(self):
        result = self.world.result
        self.earned_gold = result["gold"] + int(result["time"] / 60 * GOLD_PER_MINUTE_SURVIVED)
        self.save.record_run(result, self.earned_gold)
        self.result = result
        audio.play_music("menu")
        self.state = "summary"

    def open_level_up(self):
        audio.play("levelup")
        self.roll_level_up_offers()
        self.state = "level_up"

    def roll_level_up_offers(self):
        player = self.world.player
        count = upgrades.offer_count(player, self.world.rng)
        self.offers = upgrades.roll_offers(player, self.world.rng, count)

    def can_reroll(self):
        return (self.state == "level_up"
                and self.world.player.rerolls > 0
                and upgrades.can_reroll(self.offers))

    def can_skip(self):
        return self.state == "level_up" and self.world.player.skips > 0

    def reroll_offers(self):
        """Spend a charge for a fresh hand. Same level-up, new cards."""
        if not self.can_reroll():
            return False
        self.world.player.rerolls -= 1
        audio.play("ui_select")
        self.roll_level_up_offers()
        return True

    def skip_offer(self):
        """Spend a charge to take nothing.

        Worth having because weapon and passive slots are finite: once they are
        full, every card on offer either deepens something or wastes the slot,
        and refusing all three is sometimes the strongest move — particularly
        when a fusion needs two specific weapons kept at the top of the list.
        """
        if not self.can_skip():
            return False
        self.world.player.skips -= 1
        audio.play("ui_select")
        self.world.player.pending_level_ups -= 1
        self.offers = []
        self.state = "playing"
        return True

    def choose_offer(self, index):
        if not (0 <= index < len(self.offers)):
            return
        audio.play("ui_select")
        self.offers[index].apply(self.world.player)
        self.world.player.pending_level_ups -= 1
        self.offers = []
        self.state = "playing"

    # -- events --------------------------------------------------------------
    def handle_events(self):
        mouse_pos = pygame.mouse.get_pos()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                self.on_keydown(event)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.on_click(event.pos, mouse_pos)

            elif event.type == pygame.MOUSEMOTION and self.dragging:
                self.drag_setting(event.pos)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                # Held-and-dragged is one edit, so the save happens here rather
                # than on every motion event along the way.
                self.dragging = None
                if self.settings_dirty:
                    self.save.save()
                    self.settings_dirty = False

    def adjust_volume(self, kind, delta):
        """Nudge a volume and persist it.

        The stored value is never zeroed by muting — mute is a separate flag
        applied on top. Folding the two together would make unmuting restore
        whatever silence it had overwritten, which is the classic way a mute
        button eats a setting.
        """
        if kind == "sfx":
            self.save.sfx_volume = max(0.0, min(1.0, self.save.sfx_volume + delta))
        else:
            self.save.music_volume = max(0.0, min(1.0, self.save.music_volume + delta))
        self.muted = False
        self.apply_volumes()
        self.save.save()
        if kind == "sfx":
            audio.play("ui_move")

    def toggle_mute(self):
        self.muted = not self.muted
        self.apply_volumes()

    def apply_volumes(self):
        scale = 0.0 if self.muted else 1.0
        audio.set_sfx_volume(self.save.sfx_volume * scale)
        audio.set_music_volume(self.save.music_volume * scale)

    VOLUME_KEYS = {
        pygame.K_MINUS: ("sfx", -0.1), pygame.K_KP_MINUS: ("sfx", -0.1),
        pygame.K_EQUALS: ("sfx", 0.1), pygame.K_KP_PLUS: ("sfx", 0.1),
        pygame.K_LEFTBRACKET: ("music", -0.1),
        pygame.K_RIGHTBRACKET: ("music", 0.1),
    }

    def on_keydown(self, event):
        # Volume is checked first so it works in every state, including mid-run.
        if event.key in self.VOLUME_KEYS:
            self.adjust_volume(*self.VOLUME_KEYS[event.key])
            return
        if event.key == pygame.K_m:
            self.toggle_mute()
            return

        if event.key == pygame.K_ESCAPE:
            if self.state == "playing":
                self.state = "paused"
            elif self.state == "paused":
                self.state = "playing"
            elif self.state == "settings":
                self.save.save()
                self.settings_dirty = False
                self.state = self.return_to
            elif self.state in ("shop", "choose_weapon"):
                self.state = "title"
            return

        if self.state == "level_up":
            if pygame.K_1 <= event.key <= pygame.K_4:
                self.choose_offer(event.key - pygame.K_1)
            elif event.key == pygame.K_r:
                self.reroll_offers()
            elif event.key == pygame.K_x:
                # X rather than the obvious S. S is "walk down", and a player
                # still holding it when the level-up opens is one keystroke away
                # from throwing the level-up away by accident — for a charge
                # they paid gold for, with no undo.
                self.skip_offer()

    def on_click(self, pos, mouse_pos):
        if self.state == "settings":
            self.click_settings(pos)
            return
        if self.state == "updating":
            return                    # nothing to click; the swap is already queued

        if self.state == "title":
            if self.update_available and ui.update_banner_rect().collidepoint(pos):
                audio.play("ui_select")
                self.start_update()
                return
            for label, rect in zip(TITLE_OPTIONS, ui.button_rects(len(TITLE_OPTIONS), top=270)):
                if rect.collidepoint(pos):
                    if label == "Start Run":
                        self.choose_starting_weapon()
                    elif label == "Sanctum":
                        self.state = "shop"
                    elif label == "Settings":
                        self.open_settings()
                    else:
                        self.running = False
                    return

        elif self.state == "choose_weapon":
            for cls, rect in zip(WEAPON_TYPES, ui.weapon_select_rects(len(WEAPON_TYPES))):
                if rect.collidepoint(pos):
                    self.start_run(cls.key)
                    return

        elif self.state == "shop":
            for entry, rect in zip(save.SHOP_ENTRIES, ui.shop_rects()):
                if rect.collidepoint(pos):
                    self.save.purchase(entry)
                    return
            if ui.shop_back_rect().collidepoint(pos):
                self.state = "title"

        elif self.state == "level_up":
            for index, rect in enumerate(ui.level_up_card_rects(len(self.offers))):
                if rect.collidepoint(pos):
                    self.choose_offer(index)
                    return
            reroll, skip = ui.level_up_action_rects()
            if reroll.collidepoint(pos):
                self.reroll_offers()
            elif skip.collidepoint(pos):
                self.skip_offer()

        elif self.state == "paused":
            for label, rect in zip(PAUSE_OPTIONS, ui.button_rects(len(PAUSE_OPTIONS), top=PAUSE_TOP)):
                if rect.collidepoint(pos):
                    if label == "Continue":
                        self.state = "playing"
                    elif label == "Settings":
                        self.open_settings()
                    elif label == "Restart":
                        self.choose_starting_weapon()
                    elif label == "Main Menu":
                        self.state = "title"
                    else:
                        self.running = False
                    return

        elif self.state == "summary":
            for label, rect in zip(SUMMARY_OPTIONS,
                                   ui.button_row_rects(len(SUMMARY_OPTIONS), top=544)):
                if rect.collidepoint(pos):
                    if label == "Run Again":
                        self.choose_starting_weapon()
                    elif label == "Sanctum":
                        self.state = "shop"
                    else:
                        self.state = "title"
                    return

    # -- update --------------------------------------------------------------
    def update(self, dt, keys=None):
        if self.state != "playing":
            return

        # Open the level-up screen *before* simulating, and return immediately.
        # The old loop set the state and then ran a full frame of combat anyway.
        if self.world.player.pending_level_ups > 0:
            self.open_level_up()
            return

        keys = keys if keys is not None else pygame.key.get_pressed()
        move = read_movement(keys)
        self.world.update(dt, move, interact=keys[pygame.K_e])

        if self.world.travelling_to:
            self.travel(self.world.travelling_to)
            return
        if self.world.finished:
            self.finish_run()

    # -- settings ------------------------------------------------------------
    def apply_setting(self, key, value):
        """Write a setting and make it take effect now, where it can."""
        result = self.settings.set(key, value)
        if key in settings.AUDIO_KEYS:
            self.muted = False
            self.apply_volumes()
        self.settings_dirty = True
        return result

    def drag_setting(self, pos):
        """Follow the mouse while a slider is held."""
        option = settings.OPTIONS_BY_KEY.get(self.dragging)
        if option is None or option.kind != settings.SLIDER:
            return
        index = settings.OPTIONS.index(option)
        row = ui.settings_row_rects(len(settings.OPTIONS))[index]
        self.apply_setting(option.key, ui.slider_value_at(row, pos[0]))

    def open_settings(self):
        # Remembered so Back returns where you came from — leaving a paused run
        # by way of the settings screen and landing on the title would throw the
        # run away.
        self.return_to = self.state if self.state in ("title", "paused") else "title"
        self.state = "settings"

    def click_settings(self, pos):
        if ui.settings_back_rect().collidepoint(pos):
            audio.play("ui_select")
            self.save.save()
            self.settings_dirty = False
            self.state = self.return_to
            return
        if ui.settings_reset_rect().collidepoint(pos):
            audio.play("ui_select")
            self.settings.reset()
            self.apply_volumes()
            self.settings_dirty = True
            return

        rows = ui.settings_row_rects(len(settings.OPTIONS))
        for option, row in zip(settings.OPTIONS, rows):
            if not row.collidepoint(pos):
                continue
            if option.kind == settings.SLIDER:
                # Clicking the track jumps to that value and begins a drag, so
                # a click and a click-and-hold are the same gesture.
                self.dragging = option.key
                self.apply_setting(option.key, ui.slider_value_at(row, pos[0]))
            elif option.kind == settings.TOGGLE:
                audio.play("ui_select")
                self.apply_setting(option.key, not self.settings.get(option.key))
            else:
                audio.play("ui_select")
                self.settings.cycle(option.key)
                self.settings_dirty = True
            return

    def clickable_rects(self):
        """Rects the mouse can act on in the current state, or None.

        Shares the ui geometry functions with ``on_click`` rather than having
        draw() hand back what it laid out. Two sources for the same rectangles
        can drift apart, and a hover sound that highlights a different button
        than the click hits is worse than no hover sound.
        """
        if self.state == "title":
            rects = ui.button_rects(len(TITLE_OPTIONS), top=270)
            return ([ui.update_banner_rect()] + rects) if self.update_available else rects
        if self.state == "choose_weapon":
            return ui.weapon_select_rects(len(WEAPON_TYPES))
        if self.state == "shop":
            return list(ui.shop_rects()) + [ui.shop_back_rect()]
        if self.state == "level_up":
            return ui.level_up_card_rects(len(self.offers)) + ui.level_up_action_rects()
        if self.state == "paused":
            return ui.button_rects(len(PAUSE_OPTIONS), top=PAUSE_TOP)
        if self.state == "settings":
            return (ui.settings_row_rects(len(settings.OPTIONS))
                    + [ui.settings_reset_rect(), ui.settings_back_rect()])
        if self.state == "summary":
            return ui.button_row_rects(len(SUMMARY_OPTIONS), top=544)
        return None

    def note_hover(self, mouse_pos):
        """Tick once when the mouse moves onto a different clickable thing."""
        rects = self.clickable_rects()
        hovered = None
        if rects:
            for index, rect in enumerate(rects):
                if rect.collidepoint(mouse_pos):
                    hovered = (self.state, index)
                    break
        if hovered != self.hovered:
            self.hovered = hovered
            if hovered is not None:
                audio.play("ui_move")

    # -- draw ----------------------------------------------------------------
    def draw(self):
        """World through the painter, interface onto a plain surface over it.

        ``ui_target`` is called exactly once a frame because it clears the
        overlay: calling it again mid-frame would wipe whatever had just been
        drawn on it.
        """
        mouse_pos = pygame.mouse.get_pos()
        painter = self.painter
        self.note_hover(mouse_pos)

        if self.state in ("title", "choose_weapon", "shop", "summary", "settings",
                          "updating"):
            painter.fill((10, 10, 22))
            surface = painter.ui_target()
            if self.state == "settings":
                ui.draw_settings(surface, settings.OPTIONS, self.settings.as_dict(),
                                 mouse_pos, self.dragging)
            elif self.state == "updating":
                ui.draw_updating(surface, self.update_stage, self.update_progress)
            elif self.state == "title":
                ui.draw_title(surface, self.save, TITLE_OPTIONS, mouse_pos,
                              version=version_module.VERSION,
                              update=self.update_available,
                              update_note=self.update_note)
            elif self.state == "choose_weapon":
                ui.draw_weapon_select(surface, WEAPON_TYPES, mouse_pos)
            elif self.state == "shop":
                ui.draw_shop(surface, self.save, mouse_pos)
            else:
                ui.draw_summary(surface, self.result, self.earned_gold,
                                SUMMARY_OPTIONS, mouse_pos)
        else:
            self.world.draw(painter)
            surface = painter.ui_target()
            ui.draw_hud(surface, self.world)
            if self.state == "level_up":
                ui.draw_level_up(surface, self.offers, mouse_pos,
                                 self.world.player.pending_level_ups,
                                 rerolls=self.world.player.rerolls,
                                 skips=self.world.player.skips,
                                 reroll_ok=upgrades.can_reroll(self.offers))
            elif self.state == "paused":
                ui.draw_pause(surface, PAUSE_OPTIONS, mouse_pos,
                              self.settings.sfx_volume, self.settings.music_volume,
                              self.muted, top=PAUSE_TOP)

        if self.settings.show_fps:
            ui.draw_fps(surface, self.clock.get_fps())

        painter.flush_ui()
        painter.present()

    # -- main loop -----------------------------------------------------------
    def run(self):
        while self.running:
            dt = min(self.clock.tick(FPS) / 1000.0, MAX_DT)
            self.handle_events()
            self.update(dt)
            self.draw()
        pygame.quit()


# ---------------------------------------------------------------------------
# Headless smoke test
# ---------------------------------------------------------------------------

def _bot_move(world, step):
    """A rough approximation of a competent player: keep circling, keep away.

    Balance numbers read from a bot that walks into the horde are meaningless,
    so the bot kites — it drifts along a wide arc and steers off the local
    centre of mass of anything close.
    """
    import math

    player = world.player
    drift = pygame.Vector2(math.cos(step * 0.006), math.sin(step * 0.006))

    threat = pygame.Vector2()
    nearby = world.enemies_near(player.pos, 260)
    for enemy in nearby:
        offset = player.pos - enemy.pos
        distance = offset.length()
        if 0.001 < distance < 260:
            threat += offset.normalize() * (1.0 - distance / 260)

    if threat.length_squared() > 0.01:
        # Weave rather than flat-out flee: a bot that only runs never engages,
        # and the balance numbers it produces are useless.
        move = drift * 1.0 + threat.normalize() * 0.75
    else:
        move = drift

    # Head for the portal once it opens — otherwise the bot never sees the
    # second map and the chain goes untested.
    if world.portal is not None:
        toward = world.portal.pos - player.pos
        if toward.length() > 1:
            move += toward.normalize() * 1.8

    # Detour toward an affordable chest, so runs actually exercise them.
    chest = _bot_chest_target(world)
    if chest is not None:
        toward = chest.pos - player.pos
        if toward.length() > 1:
            move += toward.normalize() * 1.4

    # Steer back toward the middle when the arena wall is closing in behind us.
    to_center = world.arena.center - player.pos
    if to_center.length() > 1100:
        move += to_center.normalize() * 0.8

    return move if move.length_squared() > 0.001 else drift


def _bot_chest_target(world):
    affordable = [c for c in world.chests if world.player.gold >= c.cost]
    if not affordable:
        return None
    return min(affordable, key=lambda c: c.pos.distance_to(world.player.pos))


DEFENSIVE = {"Vitality", "Regrowth", "Plating"}


def _bot_pick(offers, player, rng):
    """Pick like a player who knows the genre: weapons first, defence when hurt."""
    if player.health / player.max_health < 0.55:
        defensive = [i for i, o in enumerate(offers) if o.title in DEFENSIVE]
        if defensive:
            return rng.choice(defensive)

    # Unknown kinds default to mid priority rather than raising: a new offer
    # kind should not crash a balance run before anyone notices it exists.
    priority = {"fusion": 4, "new_weapon": 3, "weapon": 2, "passive": 1, "heal": 0}
    best = max(priority.get(o.kind, 2) for o in offers)
    candidates = [i for i, o in enumerate(offers) if priority.get(o.kind, 2) == best]
    return rng.choice(candidates)


def smoke(duration, seed=7, verbose=True, immortal=False, weapon=None, map_key=None):
    """Simulate a run with a scripted player and report what happened.

    ``immortal`` keeps the bot alive so late-game enemy counts and frame costs
    can be measured without a competent player to reach them.
    """
    import time

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    # The simulation never shows a frame, so a GPU context would be pure
    # setup cost.
    game = Game(headless=True, seed=seed, use_gpu=False)
    rng = random.Random(seed)
    # Vary the opener across seeds so no single weapon defines the sample.
    opener = weapon or WEAPON_TYPES[seed % len(WEAPON_TYPES)].key
    game.start_run(opener)
    if map_key and map_key != maps.DEFAULT_MAP:
        # Runs always begin in Greenwood now, so simulating a later map means
        # dropping the bot straight into it rather than picking it up front.
        game.travel(map_key)

    dt = 1.0 / FPS
    steps = int(duration * FPS)
    peak_enemies = 0
    peak_frame_ms = 0.0
    total_ms = 0.0
    samples = []

    for step in range(steps):
        if game.state == "level_up":
            game.choose_offer(_bot_pick(game.offers, game.world.player, rng))
        if game.state == "summary":
            break

        move = _bot_move(game.world, step)

        started = time.perf_counter()
        if game.world.player.pending_level_ups > 0:
            game.open_level_up()
            continue
        # Only reach for chests, never the altar. Summoning a Warden early is a
        # deliberate player gamble, and a bot that always takes it makes the
        # survival numbers useless.
        target = game.world.nearest_interactable()
        # The bot takes chests it can pay for, and always takes a portal. It
        # still never touches altars — summoning a Warden early is a gamble a
        # bot would make badly, and it would poison the survival numbers.
        wants = target is not None and (
            target[0] == "portal"
            or (target[0] == "chest" and game.world.player.gold >= target[1].cost)
        )
        game.world.update(dt, move, interact=wants)
        if game.world.travelling_to:
            game.travel(game.world.travelling_to)
            continue
        if immortal:
            game.world.player.health = game.world.player.max_health
            game.world.finished = False
        if game.world.finished:
            game.finish_run()
        frame_ms = (time.perf_counter() - started) * 1000
        total_ms += frame_ms
        peak_frame_ms = max(peak_frame_ms, frame_ms)
        peak_enemies = max(peak_enemies, len(game.world.enemies))

        if step % (FPS * 30) == 0 and step:
            world = game.world
            samples.append(
                (world.director.elapsed, world.player.level, len(world.enemies),
                 int(world.player.health), world.player.kills)
            )

    world = game.world
    player = world.player
    report = {
        "survived": world.director.elapsed,
        "died": game.state == "summary",
        "level": player.level,
        "kills": player.kills,
        "gold": player.gold,
        "peak_enemies": peak_enemies,
        "avg_frame_ms": total_ms / max(1, steps),
        "peak_frame_ms": peak_frame_ms,
        "weapons": [(w.label, w.level) for w in player.weapons],
        "passives": dict(player.passives),
        "bosses": world.director.boss_number,
        "opener": opener,
        "chests_opened": world.chests_opened,
        "map": world.map_def.label,
        "maps_cleared": world.maps_cleared,
        "gold_spent": player.gold_spent,
        "chests_on_map": len(world.chests),
        "damage_by_weapon": dict(player.damage_by_weapon),
        "kills_by_type": dict(player.kills_by_type),
    }

    if verbose:
        print(f"\n--- smoke: seed {seed}, {duration}s on {game.world.map_def.label}, "
              f"opening with {opener} ---")
        print(f"survived {report['survived']:.1f}s  died={report['died']}  "
              f"level {report['level']}  kills {report['kills']}  bosses {report['bosses']}")
        print(f"peak enemies {report['peak_enemies']}   "
              f"frame avg {report['avg_frame_ms']:.2f}ms   peak {report['peak_frame_ms']:.2f}ms")
        print(f"ended in the {report['map']} after {report['maps_cleared']} portal(s)")
        print(f"chests opened {report['chests_opened']} ({report['gold_spent']} gold spent), "
              f"{report['chests_on_map']} still on the map, {report['gold']} gold held")
        print(f"weapons {report['weapons']}")
        print(f"passives {report['passives']}")
        total_damage = sum(report["damage_by_weapon"].values()) or 1
        share = sorted(report["damage_by_weapon"].items(), key=lambda kv: -kv[1])
        print("damage share " + "  ".join(
            f"{key} {value / total_damage * 100:.0f}%" for key, value in share))
        if samples:
            print("  t     lv  enemies  hp   kills")
            for elapsed, level, enemies, health, kills in samples:
                print(f"  {elapsed:5.0f} {level:3d} {enemies:7d} {health:5d} {kills:7d}")

    pygame.quit()
    return report


def main():
    parser = argparse.ArgumentParser(description="Project Tby")
    parser.add_argument("--smoke", type=float, metavar="SECONDS",
                        help="run a headless simulation instead of playing")
    parser.add_argument("--seed", type=int, default=7, help="seed for --smoke")
    parser.add_argument("--runs", type=int, default=1, help="how many seeds to simulate")
    parser.add_argument("--immortal", action="store_true",
                        help="keep the bot alive, for late-game pacing and perf checks")
    parser.add_argument("--weapon", help="force the bot's starting weapon by key")
    parser.add_argument("--gpu", action="store_true",
                        help="draw through the SDL2 GPU renderer (faster only "
                             "past ~1200 enemies; software wins below that)")
    parser.add_argument("--map", dest="map_key", choices=[m.key for m in maps.MAPS],
                        help="which arena to simulate in")
    args = parser.parse_args()

    if args.smoke:
        for offset in range(args.runs):
            smoke(args.smoke, seed=args.seed + offset, immortal=args.immortal,
                  weapon=args.weapon, map_key=args.map_key)
        return

    Game(use_gpu=args.gpu).run()


if __name__ == "__main__":
    main()
