# Project Tby

An arena survivors-like in the vein of Vampire Survivors and Megabonk. You move,
your weapons fire themselves, and the arena tries to bury you.

```bash
.\run.ps1
```

WASD or arrows to move, `E` to interact, `Esc` to pause, `1`-`4` or the mouse to
pick a level-up card.

Every run opens in the Greenwood. Find the altar, press `E` to summon a Warden,
and killing it tears open a portal to the next arena — same run, same build,
harder ground. Three arenas deep, the altar answers with the Hollow King
instead. Kill it and you have won.

    Greenwood  ->  Cinderwaste  ->  The Hollow  ->  the Hollow King

## Running it

Use **`run.cmd`**, not `run.ps1`. Windows blocks `.ps1` files by default —
`running scripts is disabled on this system` — and lifting that is a machine
security setting you should decide on deliberately, not something a project
should require. A `.cmd` file is not subject to that policy, so it works on a
fresh install with nothing configured. Both launchers work from any directory
and find the virtualenv themselves.

pygame lives in the virtualenv at `..\.venv`, not in your global Python. Running
`python main.py` from a fresh terminal gives `ModuleNotFoundError: No module
named 'pygame'` because `python` resolves to the system install.

`run.ps1` finds the venv for you and passes arguments through:

```bash
.\run.ps1 --smoke 600
```

Or activate the venv once and use plain `python` for the rest of the session:

```bash
& ..\.venv\Scripts\Activate.ps1
```

## Layout

| File | What lives there |
|---|---|
| `run.cmd` | Launcher that resolves the virtualenv for you |
| `run.ps1` | The same, for PowerShell (needs script execution enabled) |
| `main.py` | Entry point, state machine, headless smoke mode |
| `selftest.py` | Headless checks for menus, pause, level-up, death, save |
| `game/config.py` | **Every tunable number.** Start here to change how it feels |
| `game/arena.py` | Arena generation, wall collision, camera and shake |
| `game/entities.py` | Player, enemy archetypes, gems and coins |
| `game/status.py` | Burn, poison and chill — one mechanism for all of them |
| `game/rarity.py` | Common to Legendary tiers and the weighted roll |
| `game/maps.py` | The arenas: size, tileset, cover density, modifiers |
| `game/weapons.py` | The sixteen weapons, fusions and player projectiles |
| `tools/dps_bench.py` | Compares every weapon's output under identical conditions |
| `tools/make_art.py` | Draws every sprite from editable pixel maps |
| `tools/synth.py` | Oscillators, envelopes and filters — the audio equivalent |
| `tools/make_sound.py` | Every sound effect, as an editable recipe |
| `tools/make_music.py` | Five looping tracks, written as tracker patterns |
| `tools/audio_mix_check.py` | Measures the combat mix for clipping and mush |
| `tools/gpu_spike.py` | Benchmarks GPU vs software sprite drawing |
| `game/render.py` | Painter abstraction: software and SDL2 GPU backends |
| `game/settings.py` | Every player-facing setting, declared as data |
| `tools/make_art.py` | Sprites and tiles, as editable pixel maps |
| `requirements.txt` | pygame, numpy, and PyInstaller for builds |
| `game/paths.py` | Where files live, from source or from a build |
| `game/version.py` | The build number and the update URL |
| `game/updater.py` | Check, download, verify, and swap in a new build |
| `tools/build_exe.py` | Produces the app folder, its zip, and a manifest |
| `game/audio.py` | Playback, rate limiting, channel priority, music |
| `game/upgrades.py` | Passive definitions and the level-up offer pool |
| `game/spawner.py` | Wave director: pacing, elites, boss waves |
| `game/world.py` | The live run — update order, damage, spatial queries |
| `game/effects.py` | Damage numbers, particles, chain-lightning beams |
| `game/ui.py` | HUD, menus, level-up cards, summary, shop |
| `game/save.py` | Persistent gold and permanent upgrades |

`DungeonCrawler.py` is the original single-file version, kept for reference. It
is not imported by anything.

## Testing without playing

```bash
.\run.ps1 selftest.py
```

Drives the real game loop with synthetic events and checks every state
transition, that pausing freezes the run timer, that the level-up menu freezes
the world, and that purchases persist.

```bash
.\run.ps1 --smoke 600 --runs 5 --seed 1
```

Simulates full runs with a scripted bot that kites and takes upgrades like a
player would, then prints survival time, level, kills, peak enemy count and
frame cost. Add `--immortal` to keep the bot alive so you can inspect late-game
pacing and performance without having to survive that long yourself.

## How the pieces fit

**Everything is in seconds and pixels.** There are no frame counters — the
simulation takes a `dt`, clamped by `MAX_DT` so a hitch slows the game rather
than teleporting things through walls.

**Positions are floats.** Entities own a `pygame.Vector2` and derive their
`rect` from it. Assigning a float to `rect.x` truncates, which silently breaks
any movement smaller than one pixel per frame.

**Enemy queries go through a spatial hash** rebuilt once per frame in
`World._rebuild_grid`. Weapons, separation and collision all use
`enemies_near`, which only walks the 64px cells that overlap the query radius.

**The upgrade pool is generated, not listed.** `upgrades.roll_offers` builds
cards from the live weapon and passive registries, so a new weapon needs one
class in `weapons.py` plus one entry in `WEAPON_TYPES` and it shows up in
level-ups *and* on the starting-weapon screen automatically.

**Fusions are data.** An `Evolution` names a result weapon and the ingredient
keys it consumes. When you carry every ingredient at max level, that fusion
becomes the *only* offer on your next level-up — burying the payoff for maxing
two weapons behind a random roll would be miserable. Taking it removes both
ingredients and adds the result, freeing a slot, so a fused build reaches
further than an unfused one. Adding a new fusion is one line in `EVOLUTIONS`;
`_validate_evolutions` fails at import if it names a weapon that does not exist.

**Status effects are one mechanism, not three.** Burn, poison and chill differ
only in how much they tick and how much they slow, so a fourth element is a
`StatusSpec` with different numbers rather than new code. Ticking happens in
`World._tick_statuses` rather than on the enemy, because a damage-over-time kill
has to run the whole death path — drops, particles, kill counts.

**The altar announces itself.** It gates the entire run, and players walked past
it. It is now the largest object on the ground, sits in an aura that brightens
as you close in, and gets an edge marker when off screen. The aura is additive,
not a translucent tint: the ground varies more between grass tiles than a tint
of that strength adds, so the first version simply vanished into the terrain.

**Pickups home, they do not steer.** `Pickup.attracted` is sticky — once a drop
starts coming to you it never gives up — and it moves straight down the line to
the player rather than accumulating a velocity vector. That is what makes the
magnet almost free: flag every gem and coin as attracted and the existing homing
does the rest. It is also the only thing keeping drops from orbiting you forever.

The magnet leaves **potions** alone on purpose. Healing you can walk to when you
need it is worth more than healing yanked into you at full health.

**Maps are a chain, not a menu.** `MapDef.next_map` names where a map's portal
leads. Only the Warden you summon at the altar opens one — the timed boss waves
stay a threat rather than a free exit — and travelling carries the player,
elapsed time, boss count and chest prices into the new world, so difficulty
keeps climbing instead of resetting. The end of the chain simply has
`next_map=None`; set it when a third map exists and the machinery lights up on
its own.

**One map ends the chain.** `is_final` marks it; its altar summons the Hollow
King rather than a Warden, and that kill wins the run instead of opening a
portal. `maps._validate` asserts at import that exactly one map is final, that
it leads nowhere, and that every map is reachable by walking the chain from the
start — a map nothing points at would be dead content nobody could ever see.

**Arena dimensions live on the map, not in config.** That is the whole point of
a second map: a smaller field with more cover plays nothing like an open one
even with identical enemies. Camera clamping, chest placement and the spawn ring
all read their bounds off `world.arena` rather than a module constant, so a new
map only has to state its own size.

**Rarity is expressed as levels, not as a second multiplier.** A Rare card gives
you three levels of the thing it names rather than one level scaled by 3x. That
means max levels still cap it, the loadout panel still shows the truth, and no
stat needs a parallel scaling path that could drift out of sync with the first.
Every card rolls its own tier, so a level-up can show a Common beside a
Legendary — which is the only reason to look at all of them.

**Damage is attributed per weapon.** Everything that deals damage passes a
`weapon_key` through `damage_enemy`, including status ticks, which is what feeds
the summary screen's breakdown and makes balancing tractable.

## Art

```bash
.\run.ps1 tools\make_art.py --preview
```

Every sprite is drawn from a pixel map in `tools/make_art.py` — lists of strings,
one character per pixel, mapped through a shared palette. To change the knight's
helmet you edit the characters in `KNIGHT_DOWN`. Ground tiles and obstacles are
built procedurally in passes (fill, shade by light direction, outline) rather
than authored by hand, because a 40x40 tile is tedious to type and the
randomised speckling is what stops a 110x70 field reading as one repeated stamp.

`--preview` writes `art_preview.png`, a contact sheet at 3x — at native size you
cannot see whether the pixels are right, which is the only reason to look.

Regenerating never destroys anything: colliding files are moved to `assets/old/`
first, so the original art is always recoverable.

Two things learned the hard way:

- **The knight needs four authored facings**, not one sprite rotated. A top-down
  character turned 90 degrees reads as a character lying on its side.
- **The palette is a list of pairs, not a dict literal.** Reusing `"L"` for a
  crystal highlight silently overwrote leaf-light and turned every tree in the
  forest pale lavender. Duplicate keys now fail loudly at import.
- **A brighter ground broke the HUD.** The interface palette was picked against
  a near-black background; over grass the dim labels vanished. Fixed on both
  ends — the greens are muted, and HUD clusters sit on translucent backdrops.

## Shipping it

```powershell
run.cmd tools\build_exe.py --version 0.2.0 --base-url https://github.com/you/repo/releases/latest/download
```

That writes three things into `dist/`: the app folder players run, a zip of it,
and `manifest.json`. Publish the zip and the manifest together and point
`UPDATE_MANIFEST_URL` in `game/version.py` at the manifest. GitHub Releases has
a `latest` alias so that URL never has to change.

**One folder, not one file.** `--onefile` looks tidier and unpacks the whole
application into a temp directory on every launch, which is slow, and makes an
update an all-or-nothing download instead of a folder copy.

**The save lives outside the app folder.** In `%LOCALAPPDATA%\ProjectTby`, not
beside the exe, because an update replaces the app folder wholesale — a save
inside it would be deleted by the first update anyone installed. A save written
by an older build is copied across rather than abandoned.

### Sending it to people

Send them **`dist/ProjectTby-<version>.zip`** and nothing else. It unpacks to a
single `ProjectTby` folder containing the exe, its `_internal` directory and a
short `README.txt`; they run `ProjectTby.exe` from inside it.

The zip is wrapped in that folder deliberately. A flat archive extracts an exe
and two hundred DLLs loose into whatever directory they were in, which looks
broken even though it works. `updater.stage` strips the wrapper when installing,
so one archive serves both the person downloading it and the updater.

Two things to warn people about:

- **Windows SmartScreen** shows a blue "Windows protected your PC" box for any
  unsigned executable. They click *More info* then *Run anyway*, once. The only
  real fix is a code-signing certificate, which costs a few hundred a year and
  is not worth it for friends.
- **Antivirus false positives** are common for PyInstaller builds, because
  "single exe that unpacks and runs Python" also describes a lot of malware.

At ~47MB the zip is too big for Discord's free upload limit, so it needs
hosting. **GitHub Releases** is the natural home: free, HTTPS, and the
`releases/latest/download/` alias gives a URL that never changes. Upload the zip
and `manifest.json` to the same release, and set `UPDATE_MANIFEST_URL` to
`https://github.com/<you>/<repo>/releases/latest/download/manifest.json`.
`--base-url` is then unnecessary — a bare filename in the manifest resolves
against wherever the manifest itself was fetched from, which is the same
release.

### How updating works

The game checks the manifest once at startup, on a worker thread so a dead
server never stalls a frame, and *only tells you*. Nothing installs unless the
player clicks the banner. Then: download, verify the SHA-256, extract to a
staging folder, and hand off to a script that waits for the game to exit before
mirroring staging over the app folder and restarting it. Windows will not let a
running exe be overwritten, which is why the swap has to outlive the process
doing it.

Three rules are enforced in code rather than documented, because this feature
downloads a zip and then runs its contents:

- **HTTPS only**, manifest and download both.
- **The checksum must match** before anything is unpacked; a partial or
  tampered file is deleted rather than used.
- **Zip entries are rejected if they escape the target folder**, so a crafted
  archive cannot write elsewhere on the disk.

None of that helps if the manifest URL itself is compromised — whoever controls
it controls what runs on your players' machines — so point it somewhere you own.
Signing the manifest is the next step up if this ever goes past friends.

The swap uses `robocopy /mir` so files a new version *drops* are purged; without
that, a file removed between releases lingers on every machine that ever had the
old one, which is how an install ends up in a state you have never seen. It also
never calls `pause` — the script runs detached and windowless, so a pause would
hang a hidden process forever with no way to dismiss it.

## Performance

Measured on a late-run crowd of 225 enemies with an interleaved A/B, so system
drift cancels rather than being mistaken for a result:

| | before | after |
|---|---|---|
| update | 3.25ms | **2.64ms** (-19%) |
| draw | 5.34ms | **4.78ms** (-10%) |
| frame | 8.59ms | **7.42ms** (-14%) |

Two changes, each aimed at something profiling actually flagged.

**Separation runs all-pairs through numpy.** It was 26% of the whole update as a
bucketed Python loop. The spatial hash existed to avoid ~45,000 interpreted
distance checks, and numpy does those 45,000 in compiled code faster than Python
can walk the buckets that avoid them. The hash stays for `enemies_near` and
`nearest_enemy`, which are real range queries.

**The ground is pre-rendered once.** Redrawing the visible tiles was ~600 blits a
frame, about 60% of every blit the game made, for a layer that never changes.
Costs ~47MB for the largest arena.

**GPU rendering was built, measured, and left switched off.** `game/render.py`
routes world drawing through a `Painter` with a software and an SDL2 GPU
backend, and `--gpu` selects the latter. It is not the default because it is
slower here:

| enemies | software | GPU | winner |
|---|---|---|---|
| 250 | 1.79ms | 3.18ms | software |
| 1000 | 3.64ms | 3.91ms | software |
| 2000 | 6.04ms | 5.06ms | GPU |

The GPU path carries ~3ms of fixed cost that barely grows with the scene — the
HUD has to be uploaded as a texture every frame, because SDL2's renderer has no
rounded rectangle and no text — while software grows linearly. Crossover is
around 1,200-1,500 sprites; `MAX_ENEMIES` is 280. An idealised benchmark had
promised 12-22x, a realistic mixed workload gave 2.25x, and the finished
integration gave less than 1x. The backend is kept because it is correct,
pixel-diffed against software, and it is the right answer the day the horde
gets five times bigger.

Both were verified by differing against the code they replaced rather than by
trusting the tests: 173,136 collision queries with zero mismatches, and a
pixel-diff of the ground against the per-tile renderer across 78 camera
positions. That diff earned its keep — it caught a one-pixel misalignment the
self-test happily passed, and then a pre-existing edge-band bug in the renderer
being replaced.

`tools/gpu_spike.py` measures what moving sprites onto the GPU would buy before
anyone pays for the port.

## The bestiary

| enemy | drawn as | role |
|---|---|---|
| Goblin | goblin | fast, weak, arrives in numbers |
| Ghost | spectre | drifts and shoots; no legs, torn hem |
| Guardian | stone golem | slow, tanky, bursts of fire |
| Warden | troll | the altar boss, at 3x sprite scale |
| Goblin Warchief | crowned goblin | the final boss, armoured and three times the size |

The player is a wizard: pointed hat, robe, staff. The hat does most of the work
— a wide brim under a tall cone is one of the few silhouettes that survives at
40 pixels and still says exactly what it is. The robe is **blue, not purple**,
because purple is already the Warding Sigils orbiting the player, and a player
sprite the same colour as an effect circling it is a player you lose in a crowd.
The left-facing sprite is the right-facing one mirrored, so the two cannot drift
apart.

`render` rejects any non-ASCII character in a pixel map. A Cyrillic "е" is
indistinguishable from a Latin "e" in every editor, and the only symptom is a
transparent hole where an outline pixel should be — which reads as an art
mistake rather than an encoding one. That has cost time twice.

Everything is authored as a pixel map in `tools/make_art.py` and readable as a
picture in the source. That scheme is close to its limit: all fifty-two letters
are assigned, so recent colours are punctuation, and the next batch of art
should probably move to two-character keys.

## Sound

```powershell
.\run.ps1 tools\make_sound.py --report
.\run.ps1 tools\make_music.py --report
.\run.ps1 tools\audio_mix_check.py
```

The Greenwood theme is the fairy one — F lydian, whose raised fourth is most of
what people mean by "magical"; a drifting harp whose pattern is twelve steps
long against bars of sixteen, so it never lands twice in the same place; and
almost no percussion, because a kick and snare would turn it into an adventure
march. The Cinderwaste and the Hollow keep their own moods but share the harp,
so the three arenas sound like one game. The title theme is unchanged.

Nothing here is a recording. Thirty-seven effects and five music loops are
synthesised from oscillators and envelopes in `tools/synth.py`, the same bargain
the pixel art makes: the source is editable text, so changing the fireball means
editing numbers in `cast()`. Music is written as tracker patterns — `D4 . F4 ~`
— which you can read and change in the source.

**Continuous weapons are silent.** Poison Aura, Warding Sigils and Radiant Beam
never stop running; a per-tick cue would be a drone you cannot switch off, and
six equipped weapons would stack six of them. They speak through the enemies
they kill. The class hierarchy already draws this line — those three override
`update()` and never call `fire()` — so one hook in `Weapon.update` covers
exactly the weapons that should make noise.

**The rate gate is the load-bearing part.** A late run asks for sound far faster
than any mixer can serve: measured at **68,553 requests across a 280-enemy
run, of which 2,262 played**. Without gating, the mixer runs out of channels and
drops whatever asked last — which is level-up, taking damage, and a Warden
dying, since those arrive during heavy combat. So every cue in `game/audio.py`
declares a minimum gap and a priority, and six of the 32 channels are reserved
where combat chatter cannot reach them.

**The mix is measured, not guessed.** `audio_mix_check.py` replays a real run's
cues through the real gate against *simulated* time, mixes the actual waveforms,
and reports peak, crest factor and channel overlap. It caught the set clipping
at 1.25 with the volume slider at maximum; the fix was to lower the frequent
chatter and add one measured master-headroom constant, which widened rather than
narrowed the gap between background noise and cues that matter.

Volume is on `-`/`=` (sound) and `[`/`]` (music), `M` mutes, and the pause screen
shows all three. Everything else lives in **Settings**, reachable from the title
and from the pause menu: sliders you click and drag, toggles for damage numbers,
enemy health bars and a frame counter, a screen-shake amount, and the renderer
choice.

Settings are declared as data in `game/settings.py`, so the menu builds itself
from that list and a new option is one entry rather than four — an entry, a menu
row, a save key and a default, which are four places that can disagree. They
persist in the save file; volumes written by older builds are migrated across
rather than reset.

## Balancing weapons

```bash
.\run.ps1 tools\dps_bench.py
```

Measures every weapon alone, at levels 1 / 4 / 8, against an identical frozen
field, and reports the spread between strongest and weakest. Keeping that spread
near 2x at every level is what makes all eight viable as an opening pick.

Two traps this tool taught the hard way, both of which produced numbers that
were confidently wrong:

- **Do not arrange the dummies in rings.** An orbiting weapon whose radius
  lands on a ring reads as enormous, and one level later — orbiting between
  rings — reads as exactly zero. The field is scattered at even area density.
- **Do not rebuild the field each frame.** Weapons with a per-enemy hit cooldown
  key it on `id(enemy)`; fresh objects every frame mean the cooldown never
  matches and the weapon re-hits every frame. That reported Frost Orb at roughly
  six times its true output.
- **Measure while walking, not standing still.** Trail weapons produce nothing
  standing still, so they had to move — but it turned out to matter generally.
  Solar Beam H and V are the same weapon on different axes; measured static they
  read 25% apart purely because the scattered field is not symmetric. Walking a
  lap averages that away and they land within 2% of each other.
- **Ignore differences under about 10%.** That is roughly what remains of the
  noise floor once the field is walked rather than stood in.

For fusions the bench reports a different number, because "how does it compare
to a level-1 weapon" is not a question anyone asks: you only ever see a fusion
after maxing two others. It reports the fusion against **the maxed ingredients it
consumes**. A fusion that starts below 1.0x there is a trap the player cannot
un-pick. Both currently start around 1.2x and cap near 2.8x.

## Tuning notes

The numbers that matter most, all in `config.py` unless noted:

- `Director.spawn_rate` in `spawner.py` is the difficulty curve. It is
  deliberately quadratic — a linear ramp that feels right at minute five is
  already drowning a level-1 loadout at minute zero.
- `ENEMY_HEALTH_SCALE_PER_MIN` / `ENEMY_DAMAGE_SCALE_PER_MIN` keep enemies
  relevant as your damage compounds. Without them the run gets *easier* over
  time.
- `MAX_WEAPONS` / `MAX_PASSIVES` are six each. Once a row fills, level-ups stop
  offering new entries for it and only offer levels in what you already carry,
  so a run commits to a build. There are eight weapons and ten passives, so both
  caps bind.
- **Rarity and `XP_FIRST_LEVEL` are joined at the hip.** Tiers hand out about
  1.47 levels per pick instead of 1, which raised bot survival ~18%. Level
  costs went up to claw most of that back. If you retune the tier weights in
  `rarity.py`, check `rarity.expected_levels()` and move the XP curve with it —
  `.\run.ps1 main.py --smoke 900 --seed 1` over a dozen seeds, because the
  run-to-run variance is wide enough to hide a 10% shift.
- **`PASSIVE_WEIGHT_BUDGET` keeps the offer pool honest.** Passives share a
  fixed weight between them instead of each carrying a flat one. Without it,
  every passive added to the roster quietly makes weapon upgrades rarer —
  going from ten passives to thirteen cost about 25% of bot survival time
  before it was normalised.
- **`FUSION_LEVEL` sets the ingredient caps, not just the requirement.** A
  fusion offer replaces the whole pool once earned, so a weapon allowed to level
  past the threshold could never actually do it — every level-up from there on
  shows the fusion instead. Capping the ingredients *at* the threshold means no
  unreachable levels by construction. Tried at 10: across 20 paired seeds that
  took runs reaching a fusion from 1-in-20 to 0-in-20, because a fusion-hunting
  bot needs ~257s to get a weapon to level 10 while runs end around 135s. At 8
  it is ~145s.
- **The chest economy is a two-sided knob.** Chests spend the same gold you
  bank for permanent upgrades, so the price has to sit against income, not
  against nothing. Trash coins were originally 1 gold at 5% — about 10 gold a
  minute, which put the first chest four minutes out and meant no realistic run
  ever opened one. `COIN_DROP_CHANCE` / `COIN_VALUE` and `CHEST_BASE_COST` move
  together; changing one alone breaks it. The base cost is now 16, down from 35:
  the first chest appears twenty seconds in, and at 35 it was usually still
  unaffordable when you reached it, so the first thing the mechanic ever taught
  you was "Locked". Because the price compounds, the later chests barely move —
  16/27/46/78 against 35/59/101/171.
- `LEVEL_UP_HEAL` is a partial top-up on purpose. A full refill on every level
  removes the attrition pressure the genre runs on.
- `MAX_ENEMIES` is bounded by frame cost: simulation runs about 2ms per frame at
  280 enemies, and drawing them costs about the same.

## Roadmap

What is already in, so nothing gets built twice:

| Built | Where |
|---|---|
| Fireball — splash damage, % chance to burn | `weapons.py` |
| Chain lightning — bigger chain, more damage, **max 2 projectiles**, att speed | `ArcCoil` |
| Poison Aura — bigger AOE, more damage, % chance to poison, ticking damage | `weapons.py` |
| Frost Orb — more/bigger orbs, att speed, stronger slow, freeze at max rank | `weapons.py` |
| **Lightning Strike** — single big hit, multiple strikes, damage, att speed | `LightningStrike` |
| **Solar Beam H / V** — beams left+right and up+down; damage, size, att speed | `SolarBeam` |
| **Radiant Beam** — both solar beams fused into a spinning cross | `RadiantBeam` |
| **Tempest** — Lightning Strike fused with chain lightning | `Tempest` |
| **Earth Trail / Fire Trail** — damaging ground laid in your wake | `TrailWeapon` |
| **Walking Eruption** — both trails fused; the ground detonates behind you | `WalkingEruption` |
| **Weapon fusion system** — max two weapons to combine them | `weapons.EVOLUTIONS` |
| **Chests** — spawn on the map, cost gold, random upgrade, price climbs | `world._open_chest` |
| **Fusions** — two weapons at level 8 combine, freeing a slot | `weapons.FUSION_LEVEL` |
| **Health potions** — low-chance drop, better odds from elites and bosses | `entities.Potion` |
| **Magnet** — rare drop that pulls every gem and coin on the map to you | `world._magnetise_all_drops` |
| **Gem sparkle** — staggered glint so a gem field shimmers | `entities.Gem.draw` |
| **Forest art** — grass/dirt ground, tree and rock obstacles, four-facing knight | `tools/make_art.py` |
| Passives: global att speed, defense, crit chance, crit damage, move speed | `upgrades.py` |
| **Volley** — +1 projectile from every weapon that fires them | `Weapon.shot_count` |
| **Chaos** — tougher, more numerous enemies in exchange for far more XP | `Enemy.__init__` |
| **Fortune** — rarer upgrades, better drops, sometimes a fourth card | `upgrades.offer_count` |
| **Rarity tiers** — Common through Legendary on every upgrade offered | `game/rarity.py` |
| **Three arenas** — Greenwood, Cinderwaste, The Hollow | `game/maps.py` |
| **Victory** — felling the Hollow King ends the run as a win | `world._win` |
| **Portals** — killing the Warden you summoned opens the way onward | `world._open_portal` |
| Choose your starting weapon from a list | `ui.draw_weapon_select` |
| End-of-run screen: time, kills, kills per enemy type, gold, damage per weapon | `ui.draw_summary` |
| Bigger map, enemies drop gold, homing-bolt pierce, rapier | across the package |
| **Sound** — 37 synthesised effects, 5 looping tracks, rate-gated playback | `game/audio.py`, `tools/` |

### Still to build

**Packaging**

Build to `.exe` with PyInstaller so friends can play it without Python.

**More arenas**

The map chain takes any number of links — `game/maps.py` validates the whole
chain — but three is where it stands.

### Deliberately not doing

- **Faster burn ticks with level.** Burn damage scales, but the tick interval
  stays at 0.5s in `Fireball.burn_spec` by decision, not oversight.
