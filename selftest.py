"""Headless checks for the game's state machine and progression wiring.

    python selftest.py

Drives the real ``Game`` loop with synthetic events, so it exercises the same
event/update/draw path the windowed game uses. Runs against a throwaway save
file, so your real progress is never touched.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from game import save as save_module
from game import assets, config, maps, ui, upgrades, weapons
from main import PAUSE_OPTIONS, PAUSE_TOP, SUMMARY_OPTIONS, TITLE_OPTIONS, Game

PASS = []
FAIL = []


def check(label, condition, detail=""):
    (PASS if condition else FAIL).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"  {mark}  {label:42s}{detail}")


def _shake_scales(game):
    from game.settings import current as live
    camera = game.world.camera
    was = live.screen_shake
    results = []
    for level in (1.0, 0.5, 0.0):
        live.screen_shake = level
        camera.trauma = 0.0
        camera.add_trauma(0.4)
        results.append(round(camera.trauma, 6))
    live.screen_shake = was
    camera.trauma = 0.0
    return results == [0.4, 0.2, 0.0]


def _numbers_respect_setting(game):
    from game.settings import current as live
    world = game.world
    from game.entities import ARCHETYPES, Enemy
    was = live.damage_numbers
    counts = []
    for value in (True, False):
        live.damage_numbers = value
        world.effects.texts.clear()
        victim = Enemy(ARCHETYPES["goblin"], world.player.pos + pygame.Vector2(300, 0), 0.0)
        victim.max_health = victim.health = 5000.0
        world.damage_enemy(victim, 10)
        counts.append(len(world.effects.texts))
    live.damage_numbers = was
    world.effects.texts.clear()
    return counts[0] > 0 and counts[1] == 0


def main():
    scratch = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_selftest_save.json")
    save_module.SAVE_PATH = scratch
    if os.path.exists(scratch):
        os.remove(scratch)

    game = Game(headless=True, seed=11, use_gpu=False)
    dt = 1.0 / 60

    def click(pos):
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))

    def key(code):
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=code, unicode="", mod=0))

    def step(times=1):
        for _ in range(times):
            game.handle_events()
            game.update(dt)
            game.draw()

    print("\nmenus and meta progression")
    step()
    check("boots to the title screen", game.state == "title")

    def title_button(label):
        rects = ui.button_rects(len(TITLE_OPTIONS), top=270)
        return rects[TITLE_OPTIONS.index(label)].center

    def pause_button(label):
        rects = ui.button_rects(len(PAUSE_OPTIONS), top=PAUSE_TOP)
        return rects[PAUSE_OPTIONS.index(label)].center

    click(title_button("Sanctum"))
    step()
    check("title opens the Sanctum", game.state == "shop")

    game.save.gold = 5000
    before = game.save.level_of("health")
    click(ui.shop_rects()[0].center)
    step()
    check("a purchase applies", game.save.level_of("health") == before + 1)
    check("a purchase writes the save file", os.path.exists(scratch))

    click(ui.shop_back_rect().center)
    step()
    check("the Sanctum returns to the title", game.state == "title")

    click(title_button("Start Run"))
    step()
    check("Start Run opens weapon selection", game.state == "choose_weapon")

    picked = weapons.WEAPON_TYPES[2]
    click(ui.weapon_select_rects(len(weapons.WEAPON_TYPES))[2].center)
    step()
    check("choosing a weapon starts the run", game.state == "playing")
    check("every run begins in the first map",
          game.world.map_def.key == maps.DEFAULT_MAP, f"  {game.world.map_def.label}")
    check("the run opens with the chosen weapon",
          [w.key for w in game.world.player.weapons] == [picked.key],
          f"  {picked.label}")
    check("permanent upgrades reach the run", game.world.player.max_health > 100,
          f"  {game.world.player.max_health} max hp")

    print("\npause and level-up")
    key(pygame.K_ESCAPE)
    step()
    check("escape pauses", game.state == "paused")
    paused_at = game.world.director.elapsed
    step(60)
    check("pausing freezes the run timer", game.world.director.elapsed == paused_at,
          f"  held at {paused_at:.2f}s")

    click(pause_button("Continue"))
    step()
    check("continue resumes", game.state == "playing")

    game.world.player.pending_level_ups = 2
    step()
    check("a pending level opens the menu", game.state == "level_up")
    held = len(game.world.enemies)
    step(30)
    check("the level-up menu freezes the world", len(game.world.enemies) == held,
          f"  {held} enemies held")

    key(pygame.K_1)
    step()
    check("a second pending level re-opens the menu", game.state == "level_up")
    click(ui.level_up_card_rects(len(game.offers))[0].center)
    step()
    check("clicking a card resumes play", game.state == "playing")

    print("\nslot caps")
    game.state = "playing"
    player = game.world.player
    player.weapons.clear()
    player.passives.clear()
    for _ in range(60):
        offers = upgrades.roll_offers(player, game.world.rng)
        offers[0].apply(player)
    check("weapons never exceed the cap", len(player.weapons) <= config.MAX_WEAPONS,
          f"  {len(player.weapons)}/{config.MAX_WEAPONS}")
    check("passives never exceed the cap", len(player.passives) <= config.MAX_PASSIVES,
          f"  {len(player.passives)}/{config.MAX_PASSIVES}")

    print("\npickup magnetism")
    from game.entities import Gem

    world = game.world
    world.pickups.clear()
    world.player.pos.update(world.arena.center)
    for index in range(24):
        angle = 360 * index / 24
        world.pickups.append(Gem(world.player.pos + pygame.Vector2(60, 0).rotate(angle), 20))
    for pickup in world.pickups:
        pickup.attracted = True

    # Strafing is what used to induce orbits, so collect while moving.
    strafe = pygame.Vector2(1, 0)
    for tick in range(120):
        world.player.pos += strafe.rotate(tick * 1.2) * 300 * (1 / 60)
        world._update_pickups(1 / 60)
        if not world.pickups:
            break
    check("magnetised drops are collected, not orbited", not world.pickups,
          f"  {tick / 60:.2f}s to clear 24 drops while moving")

    # Those gems granted XP, which queues level-ups; clear them so the checks
    # below see "playing" rather than being redirected into the card screen.
    world.player.pending_level_ups = 0
    game.state = "playing"

    print("\nstatus effects")
    from game.entities import ARCHETYPES, Enemy
    from game.status import BURN, CHILL, StatusSpec

    victim = Enemy(ARCHETYPES["goblin"], world.player.pos + pygame.Vector2(400, 0), 0.0)
    victim.max_health = victim.health = 10_000.0
    world.enemies = [victim]
    world._rebuild_grid()

    # Clear passives so damage_mult is exactly 1.0 and the tick maths is checkable.
    world.player.passives.clear()
    victim.apply_status(StatusSpec(key=BURN, duration=4.0, dps=100.0, interval=0.5,
                                   weapon_key="testburn"))
    before = victim.health
    for _ in range(75):                     # 1.25s => ticks at 0.5s and 1.0s
        world._tick_statuses(1 / 60)
    dealt = before - victim.health
    check("burn ticks the right damage", abs(dealt - 100.0) < 1e-6,
          f"  {dealt:.0f} damage over 1.25s at 100 dps (2 ticks x 50)")
    check("damage-over-time is attributed to its weapon",
          world.player.damage_by_weapon.get("testburn", 0) > 0)

    victim.apply_status(StatusSpec(key=BURN, duration=2.0, dps=40.0, weapon_key="weak"))
    check("re-applying keeps the stronger tick", victim.statuses[BURN].dps == 100.0,
          f"  stayed at {victim.statuses[BURN].dps:.0f} dps")

    victim.statuses.clear()
    victim.apply_status(StatusSpec(key=CHILL, duration=2.0, slow=0.5))
    check("chill halves movement speed", abs(victim.speed_scale - 0.5) < 1e-6)
    victim.apply_status(StatusSpec(key=CHILL, duration=2.0, slow=1.0))
    check("a full freeze stops movement", victim.speed_scale == 0.0)

    boss = Enemy(ARCHETYPES["boss"], world.player.pos + pygame.Vector2(500, 0), 0.0)
    boss.apply_status(StatusSpec(key=CHILL, duration=2.0, slow=1.0))
    check("bosses resist being frozen solid", boss.speed_scale > 0.0,
          f"  capped at {boss.speed_scale:.0%} speed")

    for _ in range(180):
        world._tick_statuses(1 / 60)
    check("statuses expire", not victim.statuses)

    world.enemies.clear()
    world.player.pending_level_ups = 0

    print("\narc coil bolts and chaining")
    coil = weapons.ArcCoil()
    check("arc coil fires one bolt at first", coil.count == 1)
    coil.level = coil.max_level
    check("arc coil caps at two bolts", coil.count == 2, f"  {coil.count} at max level")

    world.enemies.clear()
    world.player_projectiles.clear()
    world.player.weapons = [coil]
    world.player.pos.update(world.arena.center)
    # A line of enemies within jump range of each other, for the chain to walk.
    line = []
    for step_index in range(6):
        foe = Enemy(ARCHETYPES["goblin"],
                    world.player.pos + pygame.Vector2(150 + step_index * 90, 0), 0.0)
        foe.max_health = foe.health = 100_000.0
        foe.speed = 0.0
        line.append(foe)
    world.enemies = list(line)
    world._rebuild_grid()
    world.player.aim = pygame.Vector2(1, 0)

    coil.timer = 0.0
    coil.fire(world)
    check("firing puts real projectiles in the world",
          len(world.player_projectiles) == 2, f"  {len(world.player_projectiles)} bolts")
    check("the bolt travels rather than hitting instantly",
          all(f.health == 100_000.0 for f in line))

    for _ in range(120):
        world._rebuild_grid()
        world._update_player_projectiles(1 / 60)
        if any(f.health < 100_000.0 for f in line):
            break
    hurt = [f for f in line if f.health < 100_000.0]
    check("the bolt chains through several enemies on impact", len(hurt) >= 3,
          f"  {len(hurt)} of 6 hit")

    damages = [100_000.0 - f.health for f in hurt]
    check("each jump lands softer than the last", damages[0] > damages[-1],
          f"  {damages[0]:.0f} down to {damages[-1]:.0f}")

    world.enemies.clear()
    world.player_projectiles.clear()
    world.player.pending_level_ups = 0

    print("\npotions and chests")
    from game.entities import ARCHETYPES, Chest, Enemy, Potion

    world.pickups.clear()
    world.player.health = world.player.max_health * 0.4
    hurt = world.player.health
    world.pickups.append(Potion(world.player.pos, config.POTION_HEAL_FRACTION))
    world.pickups[0].attracted = True
    for _ in range(60):
        world._update_pickups(1 / 60)
        if not world.pickups:
            break
    check("a potion is picked up and heals", world.player.health > hurt,
          f"  {hurt:.0f} -> {world.player.health:.0f} hp")
    check("a potion never overheals", world.player.health <= world.player.max_health)

    world.chests.clear()
    world.chests_opened = 0
    world.player.gold = 0
    world.player.gold_spent = 0
    cost = world.next_chest_cost()
    chest = Chest(world.player.pos, cost)
    world.chests.append(chest)

    world._open_chest(chest)
    check("a chest you cannot afford stays shut",
          world.chests_opened == 0 and chest in world.chests, f"  costs {cost}")

    world.player.gold = cost + 25
    weapons_before = len(world.player.weapons)
    passives_before = len(world.player.passives)
    world._open_chest(chest)
    check("paying opens the chest", world.chests_opened == 1 and chest not in world.chests)
    check("the cost is deducted", world.player.gold == 25 and world.player.gold_spent == cost,
          f"  paid {cost}, {world.player.gold} left")
    check("the chest grants an upgrade",
          len(world.player.weapons) > weapons_before
          or len(world.player.passives) > passives_before
          or any(w.level > 1 for w in world.player.weapons))
    check("the next chest costs more", world.next_chest_cost() > cost,
          f"  {cost} -> {world.next_chest_cost()}")

    # Nothing left to learn: the chest must still pay out something.
    maxed = game.world.player
    owned = {w.key for w in maxed.weapons}
    for cls in weapons.WEAPON_TYPES:
        if cls.key not in owned:
            maxed.weapons.append(cls())
    for weapon in maxed.weapons:
        weapon.level = weapon.max_level
    for passive in upgrades.PASSIVE_DEFS:
        maxed.passives[passive.key] = passive.max_level
    for _ in range(len(weapons.EVOLUTIONS) + 1):
        reward = upgrades.roll_chest_reward(maxed, world.rng)
        if reward.kind != "fusion":
            break
        reward.apply(maxed)
        for weapon in maxed.weapons:
            weapon.level = weapon.max_level
    kinds = {upgrades.roll_chest_reward(maxed, world.rng).kind for _ in range(40)}
    check("a maxed-out chest pays health or gold", kinds == {"heal", "gold"},
          f"  saw {sorted(kinds)}")

    world.chests.clear()
    world.pickups.clear()
    world.player.pending_level_ups = 0

    print("\nxp magnet and gem sparkle")
    from game.entities import SPARKLE_CYCLE, SPARKLE_FLASH, Coin, Gem, Magnet

    world.pickups.clear()
    world.player.pos.update(world.arena.center)
    far_gems = [Gem(world.player.pos + pygame.Vector2(1400, 0).rotate(i * 40), 20)
                for i in range(9)]
    far_coins = [Coin(world.player.pos + pygame.Vector2(1200, 0).rotate(i * 60), 3)
                 for i in range(6)]
    stray_potion = Potion(world.player.pos + pygame.Vector2(1300, 0),
                          config.POTION_HEAL_FRACTION)
    world.pickups.extend(far_gems + far_coins + [stray_potion])
    check("distant drops start unattracted",
          not any(p.attracted for p in far_gems + far_coins))

    pulled = world._magnetise_all_drops()
    check("a magnet attracts every gem on the map", all(g.attracted for g in far_gems))
    check("a magnet attracts the coins too", all(c.attracted for c in far_coins),
          f"  {len(far_coins)} coins worth {sum(c.value for c in far_coins)} gold")
    check("the pulled count covers both", pulled == len(far_gems) + len(far_coins),
          f"  {pulled} drops")
    check("potions are left where they lie", not stray_potion.attracted)

    before = far_gems[0].pos.distance_to(world.player.pos)
    coin_before = far_coins[0].pos.distance_to(world.player.pos)
    for _ in range(60):
        for drop in far_gems + far_coins:
            drop.update(1 / 60, world.player)
    check("magnetised gems actually travel toward you",
          far_gems[0].pos.distance_to(world.player.pos) < before,
          f"  {before:.0f}px -> {far_gems[0].pos.distance_to(world.player.pos):.0f}px")
    check("magnetised coins travel too",
          far_coins[0].pos.distance_to(world.player.pos) < coin_before,
          f"  {coin_before:.0f}px -> {far_coins[0].pos.distance_to(world.player.pos):.0f}px")

    world.pickups.clear()
    world.pickups.append(Magnet(world.player.pos))
    world.pickups[0].attracted = True
    for _ in range(60):
        world._update_pickups(1 / 60)
        if not world.pickups:
            break
    check("the magnet item is consumed on pickup", not world.pickups)

    gems = [Gem(world.player.pos, 20) for _ in range(200)]
    phases = {round(g.phase, 3) for g in gems}
    check("gems get staggered sparkle phases", len(phases) > 150,
          f"  {len(phases)} distinct phases across 200 gems")
    lit = sum(1 for g in gems if (g.age + g.phase) % SPARKLE_CYCLE < SPARKLE_FLASH)
    share = lit / len(gems)
    check("only a fraction sparkle at once", 0.05 < share < 0.30,
          f"  {share:.0%} lit, expected about {SPARKLE_FLASH / SPARKLE_CYCLE:.0%}")

    world.pickups.clear()
    world.player.pending_level_ups = 0

    print("\nvolley, chaos and fortune")
    from game.entities import ARCHETYPES, Enemy

    player = world.player
    player.passives.clear()
    player.weapons = [weapons.HomingBolts()]
    world.player_projectiles.clear()
    world.enemies = [Enemy(ARCHETYPES["goblin"], player.pos + pygame.Vector2(200, 0), 0.0)]
    world._rebuild_grid()
    player.aim = pygame.Vector2(1, 0)

    player.weapons[0].fire(world)
    base_shots = len(world.player_projectiles)
    world.player_projectiles.clear()
    player.add_passive("volley")
    player.weapons[0].fire(world)
    check("volley adds a projectile", len(world.player_projectiles) == base_shots + 1,
          f"  {base_shots} -> {len(world.player_projectiles)} bolts")

    sigils = weapons.WardingSigils()
    orbs = len(sigils.positions(player))
    player.add_passive("volley")
    check("volley reaches orbiting wards too", len(sigils.positions(player)) == orbs + 1,
          f"  {orbs} -> {len(sigils.positions(player))} wards")
    world.player_projectiles.clear()

    player.passives.clear()
    calm = Enemy(ARCHETYPES["goblin"], player.pos, 60.0, chaos=0)
    wild = Enemy(ARCHETYPES["goblin"], player.pos, 60.0, chaos=3)
    check("chaos makes enemies tougher", wild.max_health > calm.max_health,
          f"  {calm.max_health:.0f} -> {wild.max_health:.0f} hp")
    check("chaos makes enemies hit harder", wild.contact_damage > calm.contact_damage)
    check("chaos pays out more experience", wild.xp_value > calm.xp_value,
          f"  {calm.xp_value:.0f} -> {wild.xp_value:.0f} xp")

    calm_rate = world.director.spawn_rate(1.0)
    for _ in range(3):
        player.add_passive("chaos")
    check("chaos raises the spawn rate",
          world.director.spawn_rate(player.chaos_spawn_mult) > calm_rate,
          f"  {calm_rate:.2f}/s -> {world.director.spawn_rate(player.chaos_spawn_mult):.2f}/s")

    player.passives.clear()
    check("no fortune means exactly three cards",
          all(upgrades.offer_count(player, world.rng) == 3 for _ in range(40)))
    base_drop = player.drop_mult
    for _ in range(5):
        player.add_passive("luck")
    check("fortune improves drop rates", player.drop_mult > base_drop,
          f"  x{base_drop:.2f} -> x{player.drop_mult:.2f}")
    counts = {upgrades.offer_count(player, world.rng) for _ in range(200)}
    check("fortune sometimes grants a fourth card", counts == {3, 4}, f"  saw {sorted(counts)}")

    for n in (3, 4):
        rects = ui.level_up_card_rects(n)
        check(f"{n} level-up cards fit on screen",
              all(0 <= r.left and r.right <= config.SCREEN_WIDTH for r in rects)
              and not any(a.colliderect(b) for i, a in enumerate(rects) for b in rects[i + 1:]),
              f"  card width {rects[0].width}")

    player.passives.clear()
    world.enemies.clear()
    player.pending_level_ups = 0

    print("\nmaps")
    from game.entities import ARCHETYPES, Enemy
    from game.world import World

    check("every map is bigger than the window",
          all(m.width > config.SCREEN_WIDTH and m.height > config.SCREEN_HEIGHT
              for m in maps.MAPS))
    check("map tilesets are fully weighted",
          all(len(m.floor_keys) == len(m.floor_weights)
              and len(m.wall_keys) == len(m.wall_weights) for m in maps.MAPS))
    missing = [k for m in maps.MAPS for k in m.floor_keys + m.wall_keys
               if k not in assets.images]
    check("every map tile has an image", not missing, f"  missing {missing}")
    check("the first map is where runs begin", maps.MAPS[0].key == maps.DEFAULT_MAP)
    check("maps form a chain, not a menu",
          maps.GREENWOOD.next_map == maps.CINDERWASTE.key)
    check("every declared exit points at a real map",
          all(m.next_map in maps.MAPS_BY_KEY for m in maps.MAPS if m.next_map))

    built = {}
    for spec in maps.MAPS:
        other = World({}, seed=5, map_key=spec.key)
        built[spec.key] = other
        check(f"{spec.label} generates at its own size",
              other.arena.cols == spec.cols and other.arena.rows == spec.rows,
              f"  {other.arena.cols}x{other.arena.rows}")

    sizes = {w.arena.width * w.arena.height for w in built.values()}
    check("the maps are genuinely different sizes", len(sizes) == len(built),
          f"  {sorted(sizes)}")

    ash = built[maps.CINDERWASTE.key]
    plain = Enemy(ARCHETYPES["goblin"], ash.player.pos, 60.0)
    tough = Enemy(ARCHETYPES["goblin"], ash.player.pos, 60.0)
    ash.apply_map_modifiers(tough)
    check("Cinderwaste toughens its enemies", tough.max_health > plain.max_health,
          f"  {plain.max_health:.0f} -> {tough.max_health:.0f} hp")
    check("Cinderwaste pays more experience", tough.xp_value > plain.xp_value,
          f"  {plain.xp_value:.0f} -> {tough.xp_value:.0f} xp")
    check("Cinderwaste enemies are still alive at full health",
          tough.health == tough.max_health)

    green = built[maps.GREENWOOD.key]
    untouched = Enemy(ARCHETYPES["goblin"], green.player.pos, 60.0)
    before = untouched.max_health
    green.apply_map_modifiers(untouched)
    check("the default map leaves enemies alone", untouched.max_health == before)



    print("\nfinding the altar")
    game.start_run("sword")
    world = game.world
    check("a run starts with an altar", world.altar is not None)
    check("the altar is the biggest thing on the ground",
          world.altar.size >= 60, f"  {world.altar.size}px")

    world.player.pos.update(world.altar.pos)
    check("standing on it reads as fully near", world.altar.nearness(world.player.pos) == 1.0)
    target = world.nearest_interactable()
    check("standing on it offers the altar", target is not None and target[0] == "altar")

    edge = world.altar.pos + pygame.Vector2(world.altar.aura_radius - 10, 0)
    mid = world.altar.pos + pygame.Vector2(world.altar.aura_radius / 2, 0)
    check("the aura fades with distance",
          0 < world.altar.nearness(edge) < world.altar.nearness(mid) < 1.0,
          f"  edge {world.altar.nearness(edge):.2f} < mid {world.altar.nearness(mid):.2f}")
    far = world.altar.pos + pygame.Vector2(world.altar.aura_radius * 2, 0)
    check("the aura ends", world.altar.nearness(far) == 0.0)

    check("the aura reaches further than you can interact",
          world.altar.aura_radius > 110, f"  aura {world.altar.aura_radius}px vs 110px reach")

    # The aura surface is cached, not rebuilt every frame.
    from game.entities import _aura_surface
    first = _aura_surface(world.altar.aura_radius, world.altar.aura_color)
    second = _aura_surface(world.altar.aura_radius, world.altar.aura_color)
    check("the aura surface is cached", first is second)

    world.player.pos.update(world.arena.center)
    world.altar.pos.update(world.player.pos + pygame.Vector2(4000, 0))
    world.camera.update(world.player.pos, 1 / 60, world.rng,
                        (world.arena.width, world.arena.height))
    before = game.painter.to_surface()
    world._draw_offscreen_markers(game.painter)
    check("an off-screen altar gets an edge marker",
          pygame.image.tostring(game.painter.to_surface(), "RGB")
          != pygame.image.tostring(before, "RGB"))

    print("\nportals and travel")

    game.start_run("sword")
    world = game.world
    check("a run starts with no portal", world.portal is None)

    # A timed boss wave must not open the way — only the one you summon.
    timed = world.director.spawn_boss(world, from_altar=False)
    check("timed boss waves are not summoned", not timed.from_altar)
    timed.health = -1
    world.damage_enemy(timed, 1.0)
    check("a timed Warden opens no portal", world.portal is None)

    summoned = world.director.spawn_boss(world, from_altar=True)
    check("the altar marks its Warden", summoned.from_altar)
    summoned.health = -1
    world.damage_enemy(summoned, 1.0)
    check("killing the summoned Warden opens a portal", world.portal is not None)
    check("the portal leads where the map says",
          world.portal.destination == world.map_def.next_map,
          f"  {world.map_def.label} -> {world.portal.destination}")

    another = world.director.spawn_boss(world, from_altar=True)
    another.health = -1
    first = world.portal
    world.damage_enemy(another, 1.0)
    check("a second summon does not stack portals", world.portal is first)

    world.player.pos.update(world.portal.pos)
    target = world.nearest_interactable()
    check("standing on the portal offers it", target is not None and target[0] == "portal")

    world.update(1 / 60, pygame.Vector2(), interact=True)
    check("interacting sets the destination", world.travelling_to == world.map_def.next_map)

    # Carry the run through and confirm nothing was lost.
    before = world
    before.player.level = 9
    before.player.gold = 250
    before.chests_opened = 4
    before.director.elapsed = 305.0
    weapon_keys = [w.key for w in before.player.weapons]

    game.travel(before.travelling_to)
    after = game.world
    check("travel lands on the next map",
          after.map_def.key == before.map_def.next_map, f"  {after.map_def.label}")
    check("the player carries through", after.player is before.player)
    check("level and gold carry through",
          after.player.level == 9 and after.player.gold == 250)
    check("weapons carry through", [w.key for w in after.player.weapons] == weapon_keys)
    check("elapsed time carries through", after.director.elapsed == 305.0,
          "  difficulty keeps scaling instead of resetting")
    check("chest prices carry through", after.chests_opened == 4,
          f"  next chest {after.next_chest_cost()} gold")
    check("the new map counts as progress", after.maps_cleared == 1)
    check("the new map has its own arena",
          after.arena.cols == after.map_def.cols and after.arena is not before.arena)
    check("the player is placed in the new arena",
          after.player.pos == after.arena.center)
    check("the new map starts without a portal", after.portal is None)

    print("\nthe final map")
    final = [m for m in maps.MAPS if m.is_final]
    check("exactly one map ends the chain", len(final) == 1, f"  {final[0].label}")
    check("the final map leads nowhere", final[0].next_map is None)

    reached, cursor = [], maps.MAPS_BY_KEY[maps.DEFAULT_MAP]
    while cursor is not None:
        reached.append(cursor.key)
        cursor = maps.MAPS_BY_KEY.get(cursor.next_map) if cursor.next_map else None
    check("every map is reachable from the start",
          set(reached) == {m.key for m in maps.MAPS}, "  " + " -> ".join(reached))
    check("map phrases never double an article",
          not any(m.phrase.lower().startswith("the the") for m in maps.MAPS),
          "  " + ", ".join(m.phrase for m in maps.MAPS))

    # Every arena must be walkable end to end; a sealed pocket would strand the
    # player away from the altar with no way to progress.
    from collections import deque
    from game.arena import Arena, FLOOR
    import random as _random

    worst = 1.0
    for spec in maps.MAPS:
        for seed in range(6):
            arena = Arena(_random.Random(seed), spec)
            floors = {(c, r) for r in range(arena.rows) for c in range(arena.cols)
                      if arena.grid[r][c] == FLOOR}
            origin = (arena.cols // 2, arena.rows // 2)
            if origin not in floors:
                continue
            seen, queue = {origin}, deque([origin])
            while queue:
                c, r = queue.popleft()
                for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    step_to = (c + dc, r + dr)
                    if step_to in floors and step_to not in seen:
                        seen.add(step_to)
                        queue.append(step_to)
            worst = min(worst, len(seen) / len(floors))
    check("no arena has sealed-off pockets", worst > 0.98,
          f"  worst case {worst:.1%} of open ground reachable")

    game.start_run("sword")
    world = game.world
    world.map_def = final[0]

    ordinary = world.director.spawn_boss(world, from_altar=False)
    check("timed waves on the final map are still Wardens",
          not ordinary.archetype.is_final, f"  {ordinary.archetype.label}")
    ordinary.kill()
    world.enemies = [e for e in world.enemies if e.alive]

    king = world.director.spawn_boss(world, from_altar=True)
    check("the final altar summons the Warchief", king.archetype.is_final,
          f"  {king.archetype.label}")
    check("the King is far tougher than a Warden",
          king.max_health > ordinary.max_health * 2,
          f"  {ordinary.max_health:.0f} vs {king.max_health:.0f} hp")

    check("the run is not won yet", not world.victory)
    king.health = -1
    world.damage_enemy(king, 1.0)
    check("killing the King wins the run", world.victory and world.finished)
    check("victory opens no portal", world.portal is None)
    check("the result records the win", world.result.get("victory") is True)

    before_wins = game.save.wins
    game.finish_run()
    check("a win is banked", game.save.wins == before_wins + 1,
          f"  {game.save.wins} win(s)")
    check("depth is banked", game.save.deepest >= 1, f"  reached {game.save.deepest} map(s)")

    # A win must not be overwritten by dying in the same frame.
    game.start_run("sword")
    world = game.world
    world.map_def = final[0]
    slain = world.director.spawn_boss(world, from_altar=True)
    slain.health = -1
    world.player.health = -5
    world.damage_enemy(slain, 1.0)
    world.update(1 / 60, pygame.Vector2())
    check("dying on the killing blow still counts as a win", world.victory,
          "  victory survives a simultaneous death")

    game.start_run("sword")
    world = game.world

    print("\nrarity tiers")
    from game import rarity as rarities

    player = game.world.player
    player.weapons = [weapons.Sword()]
    player.passives.clear()
    player.weapons[0].level = 1

    tiers = {rarities.roll(world.rng, 0.0).key for _ in range(3000)}
    check("all five tiers can be rolled", tiers == {r.key for r in rarities.RARITIES},
          f"  {len(tiers)} distinct")

    plain = rarities.chance_of(rarities.LEGENDARY, 0.0)
    lucky = rarities.chance_of(rarities.LEGENDARY, 5.0)
    check("fortune makes legendaries likelier", lucky > plain * 2,
          f"  {plain:.2%} -> {lucky:.2%} at Fortune 5")
    check("fortune raises the average payout",
          rarities.expected_levels(5.0) > rarities.expected_levels(0.0),
          f"  {rarities.expected_levels(0.0):.2f} -> {rarities.expected_levels(5.0):.2f} levels")

    sword = player.weapons[0]
    offer = [o for o in upgrades._weapon_offers(player) if o.kind == "weapon"][0]
    offer.rarity = rarities.BY_KEY["rare"]
    offer.rng = world.rng
    offer.apply(player)
    check("a rare weapon card grants three levels", sword.level == 4,
          f"  level 1 -> {sword.level}")

    sword.level = sword.max_level - 1
    offer = [o for o in upgrades._weapon_offers(player) if o.kind == "weapon"][0]
    offer.rarity = rarities.LEGENDARY
    offer.rng = world.rng
    check("levels are clamped to the cap", offer.levels == 1 and offer.capped,
          f"  legendary at level {sword.level}/{sword.max_level} gives {offer.levels}")
    offer.apply(player)
    check("a clamped card never overshoots the cap", sword.level == sword.max_level)

    player.passives.clear()
    offer = [o for o in upgrades._passive_offers(player) if o.title == "Vitality"][0]
    offer.rarity = rarities.BY_KEY["epic"]
    offer.rng = world.rng
    before_hp = player.max_health
    offer.apply(player)
    check("an epic passive grants four levels", player.passives["health"] == 4,
          f"  +{player.max_health - before_hp:.0f} max hp")

    player.weapons = [weapons.Sword()]
    fresh = [o for o in upgrades._weapon_offers(player) if o.kind == "new_weapon"][0]
    fresh.rarity = rarities.BY_KEY["rare"]
    fresh.rng = world.rng
    fresh.apply(player)
    check("a rare new weapon arrives already levelled",
          player.weapons[-1].level == 3, f"  starts at level {player.weapons[-1].level}")

    player.passives.clear()
    legend = [o for o in upgrades._passive_offers(player) if o.title == "Might"][0]
    legend.rarity = rarities.LEGENDARY
    legend.rng = world.rng
    legend.apply(player)
    check("legendary grants its own levels", player.passives.get("might") == 5)
    check("legendary also grants a bonus passive", len(player.passives) == 2,
          f"  {sorted(player.passives)}")

    player.weapons = [weapons.Sword()]
    player.passives.clear()
    for _ in range(60):
        for offer in upgrades.roll_offers(player, world.rng, 3):
            if offer.kind in ("fusion", "heal", "gold"):
                check("fusion and consolation cards stay common",
                      offer.rarity is rarities.COMMON)
                break
    check("every rolled card carries a tier",
          all(o.rarity is not None for o in upgrades.roll_offers(player, world.rng, 3)))

    player.weapons = [weapons.Sword()]
    player.passives.clear()
    player.pending_level_ups = 0

    print("\nfont coverage")
    # A "Level 1 → 2" arrow shipped as an empty box for a while. Font.metrics()
    # is no help — it happily reports the arrow as present. The only reliable
    # test is to render it and compare against a private-use codepoint no font
    # defines: whatever *that* draws is this font's missing-glyph box.

    probe_player = game.world.player
    probe_player.weapons = [cls() for cls in weapons.WEAPON_TYPES[:3]]
    probe_player.passives.clear()
    strings = set()
    for offer in upgrades._weapon_offers(probe_player) + upgrades._passive_offers(probe_player):
        strings.update((offer.title, offer.subtitle, offer.detail))
    for cls in weapons.WEAPON_TYPES + weapons.EVOLVED_TYPES:
        strings.update((cls.label, cls.description))
        strings.add(cls().upgrade_text())
    strings.update({
        "Press  E  to open  —  30 gold", "Locked  —  30 gold  (you have 0)",
        "Press  E  to summon a Warden early  (+gold)", "WASD move    E interact    ESC pause",
    })

    font = assets.get_font(24)

    def rendered(character):
        surface = font.render(character, True, (255, 255, 255))
        return pygame.image.tostring(surface, "RGBA")

    tofu = rendered("")
    used = {ch for s in strings for ch in s if ord(ch) > 127}
    missing = sorted(hex(ord(ch)) for ch in used if rendered(ch) == tofu)
    check("every character in the UI has a glyph", not missing,
          f"  {len(strings)} strings, {len(used)} non-ascii chars"
          if not missing else f"  renders as boxes: {missing}")

    print("\nweapon fusions")
    check("fusions are never offered as a starting weapon",
          not any(c.evolved for c in weapons.WEAPON_TYPES))
    check("every fusion ingredient is a real base weapon",
          all(k in {c.key for c in weapons.WEAPON_TYPES}
              for e in weapons.EVOLUTIONS for k in e.ingredients))

    evolution = weapons.EVOLUTIONS[0]
    player = world.player
    player.weapons = [weapons.WEAPONS_BY_KEY[k]() for k in evolution.ingredients]
    check("an unfinished pair offers no fusion", not evolution.available_for(player))

    for weapon in player.weapons:
        weapon.level = weapon.max_level - 1
    check("one level short still offers no fusion", not evolution.available_for(player))

    for weapon in player.weapons:
        weapon.level = weapon.max_level
    check("maxing both ingredients unlocks the fusion", evolution.available_for(player))

    offers = upgrades.roll_offers(player, world.rng)
    check("an earned fusion is the only thing offered",
          len(offers) == 1 and offers[0].kind == "fusion",
          f"  {offers[0].title}")

    slots_before = len(player.weapons)
    offers[0].apply(player)
    keys = [w.key for w in player.weapons]
    check("fusing consumes both ingredients",
          not any(k in keys for k in evolution.ingredients))
    check("fusing grants the combined weapon", evolution.key in keys)
    check("fusing frees a weapon slot", len(player.weapons) == slots_before - 1,
          f"  {slots_before} -> {len(player.weapons)}")

    check("the fusion is not offered twice",
          not any(o.kind == "fusion" for o in upgrades.roll_offers(player, world.rng)))

    print("\nweapon select layout")
    rects = ui.weapon_select_rects(len(weapons.WEAPON_TYPES))
    check("every weapon card fits on screen",
          all(0 <= r.left and r.right <= config.SCREEN_WIDTH
              and r.top >= 0 and r.bottom <= config.SCREEN_HEIGHT for r in rects),
          f"  {len(rects)} cards, bottom edge {max(r.bottom for r in rects)}")
    check("weapon cards do not overlap",
          not any(a.colliderect(b) for i, a in enumerate(rects) for b in rects[i + 1:]))

    world.player.pending_level_ups = 0

    print("\ndeath, revive, and the offer pool")
    game.world.player.revives = 1
    game.world.player.health = -1
    step()
    check("second wind survives a lethal hit", game.state == "playing")
    check("second wind restores full health",
          game.world.player.health == game.world.player.max_health)

    game.world.player.revives = 0
    game.world.player.health = -1
    runs_before = game.save.runs
    step()
    check("death opens the summary", game.state == "summary")
    # Relative, not absolute: earlier sections bank runs of their own, and an
    # absolute count silently breaks whenever a new one is added above.
    check("the run is recorded", game.save.runs == runs_before + 1,
          f"  {game.save.runs} total, {game.save.gold} gold banked")

    player = game.world.player
    owned = {w.key for w in player.weapons}
    for cls in weapons.WEAPON_TYPES:
        if cls.key not in owned:
            player.weapons.append(cls())
    for weapon in player.weapons:
        weapon.level = weapon.max_level
    for passive in upgrades.PASSIVE_DEFS:
        player.passives[passive.key] = passive.max_level
    # Take every fusion first, otherwise this measures the fusion path rather
    # than the nothing-left-to-learn path it is meant to cover.
    for _ in range(len(weapons.EVOLUTIONS) + 1):
        offers = upgrades.roll_offers(player, game.world.rng)
        if not offers or offers[0].kind != "fusion":
            break
        offers[0].apply(player)
        for weapon in player.weapons:
            weapon.level = weapon.max_level

    offers = upgrades.roll_offers(player, game.world.rng)
    check("a player with nothing left to learn still gets an offer",
          len(offers) == 1 and offers[0].kind == "heal",
          f"  {offers[0].title if offers else 'none'}")
    if offers:
        hurt = player.max_health * 0.5
        player.health = hurt
        offers[0].apply(player)
        check("the fallback offer heals and pays out", player.health > hurt)

    click(ui.button_row_rects(3, top=544)[2].center)
    step()
    check("the summary returns to the title", game.state == "title")
    check("summary buttons fit on screen",
          all(0 <= r.left and r.right <= config.SCREEN_WIDTH and r.bottom <= config.SCREEN_HEIGHT
              for r in ui.button_row_rects(len(SUMMARY_OPTIONS), top=544)))

    print("\nsound")
    from game import audio

    # Every cue must have at least one file, and every file must belong to a
    # cue. A typo in either direction is silent — literally — and would only
    # show up as a sound that mysteriously never plays.
    sfx = [f[:-4] for f in os.listdir(audio.SFX_DIR) if f.endswith(".wav")]
    families = set()
    for name in sfx:
        stem = name.rsplit("_", 1)[0]
        families.add(stem if (stem in audio.CUES and name[-1].isdigit()) else name)
    check("every cue has a sound file", not (set(audio.CUES) - families),
          f"  missing {sorted(set(audio.CUES) - families)}")
    check("every sound file has a cue", not (families - set(audio.CUES)),
          f"  orphans {sorted(families - set(audio.CUES))}")
    check("frequent cues have variants",
          all(sum(1 for n in sfx if n.rsplit('_', 1)[0] == cue) >= 3
              for cue in ("hit", "kill", "gem")))
    check("every map has a music track",
          all(os.path.exists(os.path.join(audio.MUSIC_DIR, f"{audio.MAP_TRACKS[m.key]}.wav"))
              for m in maps.MAPS))
    check("the menu track exists",
          os.path.exists(os.path.join(audio.MUSIC_DIR, "menu.wav")))

    # A track nobody plays is dead weight that still ships. The boss theme was
    # written and then left unreachable until this check went in.
    import re
    played = set(re.findall(r'play_music\("(\w+)"', open("game/world.py", encoding="utf-8").read()
                            + open("main.py", encoding="utf-8").read()))
    played |= set(audio.MAP_TRACKS.values())
    on_disk = {f[:-4] for f in os.listdir(audio.MUSIC_DIR) if f.endswith(".wav")}
    check("every music track is reachable", not (on_disk - played),
          f"  unused {sorted(on_disk - played)}")
    check("every track referenced in code exists", not (played - on_disk),
          f"  missing {sorted(played - on_disk)}")

    # The rate gate is the whole reason this module exists, so test it against
    # a controlled clock rather than hoping. Driving simulated time also keeps
    # the check deterministic — a wall-clock version would pass or fail
    # depending on how fast the machine running it happens to be.
    now = [0.0]
    audio.set_clock(lambda: now[0])
    audio._mixer.ready = True                    # gate runs without a device
    audio._mixer.sounds = {"hit": [None], "levelup": [None]}
    accepted = []
    real_pick, real_res = audio._mixer._pick_variant, audio._mixer._reserved_channel

    class _FakeChannel:
        def set_volume(self, *_):
            pass

    class _FakeSound:
        def get_num_channels(self):
            return 0

        def play(self):
            return _FakeChannel()

    audio._mixer._pick_variant = lambda name, variants, cue, since: _FakeSound()
    try:
        for tick in range(200):                  # 2 simulated seconds at 100Hz
            now[0] = tick * 0.01
            if audio.play("hit"):
                accepted.append(now[0])
    finally:
        audio._mixer._pick_variant = real_pick
        audio._mixer._reserved_channel = real_res
        audio._mixer.ready = False
        audio._mixer.sounds = {}
        audio._mixer.last_played.clear()
        audio.set_clock(None)

    gap = audio.CUES["hit"].gap
    check("the rate gate throttles a flood",
          len(accepted) <= 2.0 / gap + 1,
          f"  {len(accepted)} plays from 200 requests over 2s (cap {int(2.0 / gap) + 1})")
    check("the gate never plays two inside one gap",
          all(b - a >= gap - 1e-9 for a, b in zip(accepted, accepted[1:])))
    check("important cues are marked priority",
          all(audio.CUES[c].priority for c in
              ("hurt", "death", "levelup", "victory", "portal_open", "chest")))
    check("chatter is not marked priority",
          not any(audio.CUES[c].priority for c in ("hit", "kill", "gem", "slash")))
    check("reserved channels are fewer than total", audio.RESERVED < audio.CHANNELS)
    check("master headroom leaves room to sum", 0.0 < audio.MASTER_SFX <= 1.0)

    # Continuous weapons must stay silent or the run becomes a drone.
    from game.weapons import PoisonAura, RadiantBeam, WardingSigils
    check("continuous weapons have no fire cue",
          all(w.sound is None for w in (PoisonAura, RadiantBeam, WardingSigils)))
    check("discrete weapons do have one",
          all(w.sound for w in (weapons.Sword, weapons.Fireball, weapons.LightningStrike)))

    check("volume survives a save round trip",
          save_module.SaveData({"settings": {"sfx_volume": 0.3}})
          .as_dict()["settings"]["sfx_volume"] == 0.3)
    check("a corrupt volume falls back rather than muting",
          save_module.SaveData({"settings": {"sfx_volume": "loud"}}).sfx_volume == 0.7)
    # Saves written before the settings menu existed keep their audio.
    legacy = save_module.SaveData({"sfx_volume": 0.3, "music_volume": 0.0})
    check("a pre-settings save keeps its volumes",
          (legacy.sfx_volume, legacy.music_volume) == (0.3, 0.0),
          f"  {legacy.sfx_volume}, {legacy.music_volume}")

    print("\nrendering backends")
    from game import render

    check("the software painter is the default",
          isinstance(game.painter, render.SoftwarePainter))
    # Both backends must offer the same surface, or a draw method that works on
    # one will crash on the other — and only in a state nobody tested.
    api = [name for name in dir(render.Painter)
           if not name.startswith("_") and callable(getattr(render.Painter, name))]
    check("both backends implement the whole painter API",
          all(hasattr(render.SoftwarePainter, n) and hasattr(render.GpuPainter, n)
              for n in api), f"  {len(api)} methods")

    # Drawing must never touch the world. A draw call that mutated state would
    # make the game depend on whether a frame was rendered, which headless
    # tooling never does.
    world = game.world
    def snapshot():
        p = world.player
        return (len(world.enemies), len(world.pickups), p.kills, p.gold,
                round(p.pos.x, 4), round(p.pos.y, 4),
                round(sum(e.pos.x + e.pos.y for e in world.enemies), 4))
    game.state = "playing"
    world.player.pending_level_ups = 0
    before_draw = snapshot()
    for _ in range(4):
        world.draw(game.painter)
    check("drawing does not mutate the world", snapshot() == before_draw)

    surface = game.painter.ui_target()
    check("the software ui target is the screen itself",
          surface is game.painter.surface)

    print("\nsettings")
    from game import settings as settings_module

    game.state = "title"
    click(title_button("Settings"))
    step()
    check("the title opens settings", game.state == "settings")

    rows = ui.settings_row_rects(len(settings_module.OPTIONS))
    keys = [option.key for option in settings_module.OPTIONS]
    check("every declared option gets a row", len(rows) == len(keys))
    check("the settings rows fit above the buttons",
          rows[-1].bottom < ui.settings_reset_rect().top,
          f"  last row {rows[-1].bottom}px, buttons {ui.settings_reset_rect().top}px")

    # Press, drag, release — the gesture the player actually makes.
    track = ui.settings_slider_rect(rows[keys.index("sfx_volume")])
    click((track.x + int(track.width * 0.25), track.centery))
    step()
    check("clicking a slider sets it and starts a drag",
          abs(game.settings.sfx_volume - 0.25) < 0.02 and game.dragging == "sfx_volume",
          f"  {game.settings.sfx_volume:.2f}")

    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION,
                                         pos=(track.right + 200, track.centery),
                                         rel=(0, 0), buttons=(1, 0, 0)))
    step()
    check("dragging past the end clamps at full", game.settings.sfx_volume == 1.0)

    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION,
                                         pos=(track.x + int(track.width * 0.5), track.centery),
                                         rel=(0, 0), buttons=(1, 0, 0)))
    step()
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)))
    step()
    check("releasing ends the drag", game.dragging is None)
    check("the released value persisted",
          abs(save_module.load().settings.sfx_volume - game.settings.sfx_volume) < 0.001)

    was = game.settings.show_fps
    click(rows[keys.index("show_fps")].center)
    step()
    check("clicking a toggle flips it", game.settings.show_fps is not was)

    before_renderer = game.settings.renderer
    click(rows[keys.index("renderer")].center)
    step()
    check("clicking a choice cycles it", game.settings.renderer != before_renderer,
          f"  {before_renderer} -> {game.settings.renderer}")

    click(ui.settings_reset_rect().center)
    step()
    check("reset restores every default",
          all(game.settings.get(o.key) == o.default for o in settings_module.OPTIONS))

    # Settings opened from a paused run must go back to the run, not the title:
    # returning to the title would silently discard it.
    game.state = "playing"
    game.state = "paused"
    step()
    click(pause_button("Settings"))
    step()
    check("pausing into settings remembers the run", game.return_to == "paused")
    key(pygame.K_ESCAPE)
    step()
    check("leaving settings returns to the paused run",
          game.state == "paused" and game.world is not None)
    game.state = "playing"

    check("screen shake scales trauma at one place",
          _shake_scales(game))
    check("turning damage numbers off stops them", _numbers_respect_setting(game))

    print("\nHUD layout and fusion gating")
    from game.weapons import EVOLUTIONS, FUSION_LEVEL, WEAPONS_BY_KEY

    # The health bar used to be 250px wide inside a 190px backdrop, so it hung
    # out into the world. Everything in the left cluster must fit its panel.
    panel = pygame.Rect(ui.HUD_LEFT, 16, ui.HUD_PANEL_WIDTH, 400)
    bar = pygame.Rect(ui.HUD_CONTENT_LEFT, 50, ui.HUD_CONTENT_WIDTH, 20)
    chip = pygame.Rect(ui.HUD_CONTENT_LEFT, 90, ui.HUD_CONTENT_WIDTH, 24)
    check("the health bar fits inside its HUD panel",
          panel.left <= bar.left and bar.right <= panel.right,
          f"  bar {bar.left}-{bar.right}, panel {panel.left}-{panel.right}")
    check("weapon chips fit inside the same panel",
          panel.left <= chip.left and chip.right <= panel.right)
    check("the slot counter is right-aligned to the content edge",
          ui.HUD_CONTENT_RIGHT == ui.HUD_CONTENT_LEFT + ui.HUD_CONTENT_WIDTH)

    # A fusion ingredient capped below FUSION_LEVEL could never qualify, and the
    # only symptom would be a fusion that silently never appears.
    check("every fusion ingredient can reach the fusion level",
          all(WEAPONS_BY_KEY[k].max_level >= FUSION_LEVEL
              for e in EVOLUTIONS for k in e.ingredients),
          f"  need level {FUSION_LEVEL}")

    fusion_player = game.world.player
    evolution = EVOLUTIONS[0]
    fusion_player.weapons = [WEAPONS_BY_KEY[k]() for k in evolution.ingredients]
    for weapon in fusion_player.weapons:
        weapon.level = FUSION_LEVEL - 1
    below = [upgrades.roll_offers(fusion_player, game.world.rng) for _ in range(25)]
    check("a fusion is not offered one level short",
          not any(o.kind == "fusion" for batch in below for o in batch))

    for weapon in fusion_player.weapons:
        weapon.level = FUSION_LEVEL
    at = [upgrades.roll_offers(fusion_player, game.world.rng) for _ in range(25)]
    check("a fusion is offered every time once earned",
          all(any(o.kind == "fusion" for o in batch) for batch in at),
          "  25/25 rolls")
    check("the fusion offer appears alone", all(len(batch) == 1 for batch in at))

    earned, needed = evolution.progress(fusion_player)
    check("fusion progress reports both parts", (earned, needed) ==
          (FUSION_LEVEL * len(evolution.ingredients), FUSION_LEVEL * len(evolution.ingredients)))

    slots = len(fusion_player.weapons)
    next(o for o in at[0] if o.kind == "fusion").apply(fusion_player)
    check("fusing consumes both parts and frees a slot",
          len(fusion_player.weapons) == slots - 1
          and [w.key for w in fusion_player.weapons] == [evolution.key])

    print("\npackaging and updates")
    import hashlib as _hashlib
    import io as _io
    import json as _json
    import shutil as _shutil
    import tempfile as _tempfile
    import zipfile as _zipfile
    from game import paths, updater
    from game import version as version_module

    check("versions compare as numbers, not strings",
          version_module.is_newer("0.10.0", "0.9.0")
          and not version_module.is_newer("0.9.0", "0.10.0"),
          "  0.10.0 > 0.9.0")
    check("the same version is not newer", not version_module.is_newer(
        version_module.VERSION, version_module.VERSION))
    # is_newer's "current" resolves inside the call, not as a default argument.
    # A default is evaluated once at import, which would freeze whatever VERSION
    # was then and quietly ignore any later change — invisible in production,
    # and it made the live update path untestable.
    _real = version_module.VERSION
    try:
        version_module.VERSION = "0.1.0"
        check("is_newer follows VERSION rather than a frozen default",
              version_module.is_newer("0.2.0"))
    finally:
        version_module.VERSION = _real

    # The save must never live inside the folder an update replaces.
    frozen_app = os.path.join(_tempfile.gettempdir(), "pretend-install")
    real_frozen, real_exe = paths.is_frozen, sys.executable
    paths.is_frozen = lambda: True
    sys.executable = os.path.join(frozen_app, "ProjectTby.exe")
    try:
        data_dir = paths.user_data_dir()
        inside = os.path.commonpath([os.path.realpath(data_dir),
                                     os.path.realpath(frozen_app)]) == os.path.realpath(frozen_app)
        check("packaged saves live outside the app folder", not inside, f"  {data_dir}")
    finally:
        paths.is_frozen, sys.executable = real_frozen, real_exe

    # A whole publish/check/download/stage cycle against a local fetcher. The
    # transport is injected rather than bypassed, so the https rule below is
    # still the one that ships.
    work = _tempfile.mkdtemp(prefix="selftest-update-")
    try:
        published = os.path.join(work, "pub")
        os.makedirs(published)
        archive_path = os.path.join(published, "app-9.9.9.zip")
        with _zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("ProjectTby.exe", "new build")
            archive.writestr("_internal/assets/new.png", "new asset")
        digest = _hashlib.sha256(open(archive_path, "rb").read()).hexdigest()
        _json.dump({"version": "9.9.9", "url": "app-9.9.9.zip", "sha256": digest,
                    "size": os.path.getsize(archive_path)},
                   open(os.path.join(published, "manifest.json"), "w"))

        class _Response(_io.BytesIO):
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()

        def local_fetch(url):
            body = open(os.path.join(published, url.rsplit("/", 1)[-1]), "rb").read()
            response = _Response(body)
            response.headers = {"Content-Length": str(len(body))}
            return response

        found = updater.check("https://example.invalid/manifest.json", fetch=local_fetch)
        check("a newer manifest is offered", found is not None and found.version == "9.9.9")
        check("a bare filename resolves against the manifest",
              found.url == "https://example.invalid/app-9.9.9.zip", f"  {found.url}")

        downloaded = updater.download(found, fetch=local_fetch)
        check("a matching checksum is accepted", os.path.exists(downloaded))

        install = os.path.join(work, "app")
        os.makedirs(install)
        staged = updater.stage(downloaded, app_dir=install)
        check("the archive stages into the app folder",
              os.path.exists(os.path.join(staged, "ProjectTby.exe")))
        os.unlink(downloaded)

        # Release zips wrap everything in a folder so a human extracting one by
        # hand gets a tidy directory instead of an exe and 200 DLLs loose in
        # their Downloads. The updater has to strip that wrapper, or an update
        # installs into app/ProjectTby/ instead of over app/.
        wrapped = os.path.join(work, "wrapped.zip")
        with _zipfile.ZipFile(wrapped, "w") as archive:
            archive.writestr("ProjectTby/ProjectTby.exe", "exe")
            archive.writestr("ProjectTby/_internal/thing.dll", "dll")
        unwrapped = updater.stage(wrapped, app_dir=install)
        check("a wrapped release zip has its folder stripped",
              os.path.exists(os.path.join(unwrapped, "ProjectTby.exe"))
              and not os.path.isdir(os.path.join(unwrapped, "ProjectTby")))
        check("a flat zip still stages correctly",
              updater._common_root(["a.exe", "_internal/b.dll"]) is None)
        check("an archive with several roots is left alone",
              updater._common_root(["A/x", "B/y"]) is None)

        tampered = updater.Update("9.9.9", "https://example.invalid/app-9.9.9.zip",
                                  "b" * 64, found.size)
        try:
            updater.download(tampered, fetch=local_fetch)
            check("a tampered download is refused", False)
        except updater.UpdateError:
            check("a tampered download is refused", True)
        check("no partial download is left behind",
              not [f for f in os.listdir(_tempfile.gettempdir())
                   if f.startswith("projecttby-download-")])

        evil = os.path.join(work, "evil.zip")
        with _zipfile.ZipFile(evil, "w") as archive:
            archive.writestr("../../escaped.txt", "no")
        try:
            updater.stage(evil, app_dir=install)
            check("a path-traversal archive is refused", False)
        except updater.UpdateError:
            check("a path-traversal archive is refused", True)

        try:
            updater.check("http://example.invalid/manifest.json")
            check("plain http is refused", False)
        except updater.UpdateError:
            check("plain http is refused", True)

        for label, payload in (("no version", {"url": "x.zip", "sha256": "a" * 64}),
                               ("no checksum", {"version": "9.9.9", "url": "x.zip"})):
            _json.dump(payload, open(os.path.join(published, "manifest.json"), "w"))
            try:
                updater.check("https://example.invalid/manifest.json", fetch=local_fetch)
                check(f"a manifest with {label} is refused", False)
            except updater.UpdateError:
                check(f"a manifest with {label} is refused", True)
    finally:
        _shutil.rmtree(work, ignore_errors=True)

    swap = updater.SWAP_SCRIPT.format(staging="S", app="A", exe="E", log="L")
    commands = [line.strip() for line in swap.splitlines()
                if line.strip() and not line.strip().lower().startswith(("rem", "@"))]
    # A detached, windowless script has no console, so "pause" would hang a
    # hidden process forever with no way to dismiss it.
    check("the swap script never pauses", not any(c.lower() == "pause" for c in commands))
    # Synchronisation is robocopy's retries, not process polling. Waiting on a
    # process id meant parsing tasklist output, which was observed wedging
    # forever when the filter did not apply and "N" matched a memory column.
    check("the swap script retries locked files instead of polling a pid",
          "/R:20 /W:2" in swap
          and not any("tasklist" in line for line in swap.splitlines()
                      if not line.strip().startswith("rem")))
    check("the swap script purges files a new build drops", "/mir" in swap)
    check("the swap script does not mirror away its own staging", '/xd "S"' in swap)
    check("the swap script restarts the game on both paths",
          swap.count('start "" "E"') == 2)

    if os.path.exists(scratch):
        os.remove(scratch)
    pygame.quit()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for label in FAIL:
        print(f"  failed: {label}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
