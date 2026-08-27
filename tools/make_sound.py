"""Generate the game's sound effects.

    python tools/make_sound.py             write every effect into assets/sfx/
    python tools/make_sound.py --report    print a table of what was written

Every sound is a recipe built from ``tools/synth.py`` primitives, the same way
every sprite is a grid of characters in ``tools/make_art.py``. To make the
fireball punchier, edit the numbers in ``cast()``. Nothing here is a recording.

Two decisions shape the whole set:

**Continuous weapons stay silent.** Poison Aura ticks twice a second, the sigils
orbit forever, the trails burn under your feet the entire run. Giving those a
per-tick sound is how a survivors-like turns into a dentist's drill. They speak
only through the enemies they kill, which is already one sound per event and
already rate-limited. Only discrete, player-legible actions get a cue.

**Frequent sounds come in variants.** The identical waveform fired forty times a
second reads as a machine gun rather than forty hits; ears latch onto the exact
repetition. Hits, kills and gems are generated as small families that the runtime
cycles through, which costs a few kilobytes and buys a lot.
"""

import argparse
import os
import shutil

from synth import (Clip, adsr, arpeggio, chord, layer, metallic, noise,
                   note, perc, saw, sine, square, swell, triangle, vibrato)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX_DIR = os.path.join(ROOT, "assets", "sfx")
BACKUP = os.path.join(SFX_DIR, "old")


# --- weapon fire ------------------------------------------------------------

def slash():
    """Sword and rapier. A body-less whoosh: air, not metal."""
    air = Clip.tone(0.16, (2400, 600), noise(11), perc(0.02, 6.0)).lowpass(3800)
    body = Clip.tone(0.16, (520, 160), triangle, perc(0.01, 7.0), gain=0.45)
    return layer(air, body).highpass(220)


def shot():
    """Homing Bolts. Short, dry, and pitched so it cuts through a crowd."""
    return Clip.tone(0.11, (900, 260), square(0.35), perc(0.005, 9.0)).crush(7).lowpass(5200)


def cast():
    """Fireball leaving the hand — a rising rush, not an impact."""
    rush = Clip.tone(0.22, (180, 760), noise(23), perc(0.35, 2.5)).lowpass(2600)
    core = Clip.tone(0.22, (220, 560), saw, perc(0.3, 3.0), gain=0.5).drive(1.8)
    return layer(rush, core).highpass(180)


def zap():
    """Arc Coil. Bit-crushed square is the cheapest convincing electricity."""
    spark = Clip.tone(0.13, (1500, 380), square(0.18), perc(0.004, 8.0)).crush(4)
    fizz = Clip.tone(0.13, 4000, noise(31), perc(0.01, 12.0), gain=0.35)
    return layer(spark, fizz).highpass(300)


def thunder():
    """Lightning Strike. The only weapon cue allowed to be genuinely loud."""
    crack = Clip.tone(0.08, (5000, 900), noise(41), perc(0.002, 10.0), gain=0.9)
    rumble = Clip.tone(0.55, (140, 45), saw, perc(0.02, 4.0)).lowpass(320).drive(2.2)
    return layer(crack, rumble).echo(0.09, 0.3, 3).highpass(35)


def beam():
    """Solar and Radiant. A held tone; the swell keeps it from stabbing."""
    return layer(
        Clip.tone(0.5, vibrato(330, 0.012, 5.0), sine, swell(0.25, 0.35)),
        Clip.tone(0.5, vibrato(495, 0.012, 5.0), sine, swell(0.3, 0.4), gain=0.5),
        Clip.tone(0.5, 165, triangle, swell(0.2, 0.4), gain=0.35),
    )


def frost():
    """Frost Orb spawning. Inharmonic ratio and a long tail: glass, not a note."""
    return Clip.tone(0.4, (1800, 1500), metallic(2.71), perc(0.01, 4.5)) \
        .echo(0.06, 0.4, 4)


def erupt():
    """Walking Eruption. Earth opening — low, gritty, brief."""
    crunch = Clip.tone(0.3, (400, 90), noise(53), perc(0.01, 5.0)).lowpass(900)
    thud = Clip.tone(0.3, (150, 50), sine, perc(0.005, 6.0), gain=0.8)
    return layer(crunch, thud).drive(1.6)


def gust():
    """Tempest. Filtered noise with no pitch centre reads as wind."""
    return Clip.tone(0.45, (700, 300), noise(59), swell(0.3, 0.45)) \
        .lowpass(1600).highpass(400)


# --- impacts ----------------------------------------------------------------

def hit(index=0):
    """Landing a blow. Fires more than anything else, so: short and quiet.

    Retuned after play testing said the hits nagged. Measuring first ruled out
    the obvious suspect: these carry only 1.8-3.5% of their energy in the
    2-5kHz band where listening fatigue lives, *less* than the kill or the coin,
    so brightness was not the problem. What was: a 560-820Hz centroid with an
    inharmonic partial — a metallic tick, right in the register a dripping tap
    occupies — arriving up to eighteen times a second.

    So the fix is duller rather than darker. The inharmonic ratio is gone (that
    partial was the "clank"), the fundamental drops about 40%, and a low-pass
    takes off the top so what is left reads as a soft thud. Four variants
    rather than three, because the ear latches onto exact repetition and a
    quieter sound has to survive being heard more often than any other.
    """
    base = 250 + index * 48
    body = Clip.tone(0.045, (base, base * 0.5), sine, perc(0.002, 14.0))
    tap = Clip.tone(0.03, (base * 2.2, base * 1.1), triangle, perc(0.002, 16.0), gain=0.18)
    return layer(body, tap).lowpass(1500).highpass(120)


def crit():
    """A crit has to be audible over the hit it replaces — brighter, not louder."""
    ring = Clip.tone(0.16, (1400, 700), metallic(2.4), perc(0.002, 7.0))
    chirp = Clip.tone(0.09, (900, 1900), square(0.4), perc(0.01, 6.0), gain=0.4)
    return layer(ring, chirp).highpass(400)


def kill(index=0):
    """An enemy popping. Downward pitch is the universal cue for 'gone'."""
    base = 300 - index * 45
    pop = Clip.tone(0.13, (base, base * 0.35), noise(67 + index), perc(0.004, 7.0)).lowpass(2200)
    body = Clip.tone(0.13, (base * 1.2, base * 0.4), triangle, perc(0.004, 8.0), gain=0.6)
    return layer(pop, body).highpass(150)


def boom():
    """Fireball detonating."""
    blast = Clip.tone(0.45, (900, 120), noise(71), perc(0.006, 5.0)).lowpass(1400)
    low = Clip.tone(0.45, (180, 40), sine, perc(0.01, 4.0), gain=0.9)
    return layer(blast, low).drive(1.9).highpass(40)


def boss_hurt():
    """A Warden taking damage — deeper than a normal hit so bosses feel massive."""
    return Clip.tone(0.2, (240, 110), metallic(1.47), perc(0.004, 6.0)) \
        .lowpass(1800)


# --- the player -------------------------------------------------------------

def hurt():
    """Taking damage. Harsh on purpose; this one should interrupt you."""
    stab = Clip.tone(0.28, (420, 130), square(0.28), perc(0.004, 5.0)).drive(2.4)
    grit = Clip.tone(0.18, (800, 200), noise(83), perc(0.01, 6.0), gain=0.5).lowpass(2000)
    return layer(stab, grit).highpass(120)


def death():
    """A long fall. Minor third down, everything slowing."""
    fall = Clip.tone(1.5, (330, 60), saw, perc(0.02, 2.2)).lowpass(1200).drive(1.4)
    toll = chord(1.5, [note("A2"), note("C3"), note("E3")], triangle, perc(0.05, 2.0), 0.6)
    return layer(fall, toll).echo(0.22, 0.32, 3)


def levelup():
    """Rising major arpeggio over a low hit — the game's most-heard reward.

    The arpeggio alone was thin. What was missing was not volume but *weight*:
    the whole sound lived above 500Hz, so it pinged rather than landed. Two low
    layers fix that without making it louder — a sub sine sliding from 110 down
    to 55Hz, which is felt more than heard, and a short 82Hz thud on the
    downbeat to give the arpeggio something to push off.

    The sub is a glide rather than a held note because a static low sine reads
    as a hum; moving pitch reads as an impact.
    """
    figure = arpeggio([note("C5"), note("E5"), note("G5"), note("C6")],
                      note_length=0.07, wave=square(0.45), gain=0.7)
    shimmer = Clip.tone(0.5, note("C6"), sine, perc(0.15, 3.0), gain=0.3)
    sub_bass = Clip.tone(0.55, (note("A2"), note("A1")), sine, perc(0.01, 3.4), gain=0.55)
    thud = Clip.tone(0.22, (note("E2"), note("E1")), triangle, perc(0.004, 6.0), gain=0.38)
    body = Clip.tone(0.34, note("C3"), triangle, perc(0.02, 4.0), gain=0.30)
    return layer(figure, shimmer, sub_bass, thud, body).echo(0.1, 0.25, 2)


def victory():
    """Fanfare. Earned once per run at most; it can afford to be big."""
    figure = arpeggio([note("C5"), note("E5"), note("G5"), note("C6"), note("G5"), note("C6")],
                      note_length=0.13, wave=square(0.5), gain=0.6)
    pad = chord(1.6, [note("C4"), note("E4"), note("G4")], triangle, swell(0.1, 0.5), 0.5)
    return layer(figure, pad).echo(0.16, 0.3, 3)


# --- pickups ----------------------------------------------------------------

def gem(index=0):
    """XP. A pentatonic ladder the runtime climbs as you hoover up a cluster."""
    scale = [note(n) for n in ("C6", "D6", "F6", "G6", "A6")]
    freq = scale[index % len(scale)]
    return Clip.tone(0.09, freq, triangle, perc(0.004, 8.0))


def coin():
    """Gold. Two fast notes up, the way coins have sounded since 1985."""
    first = Clip.tone(0.05, note("B5"), square(0.5), perc(0.004, 7.0))
    second = Clip.tone(0.14, note("E6"), square(0.5), perc(0.004, 5.0))
    return first.then(second)


def potion():
    """Healing. Warm, rising, no edge to it."""
    return layer(
        Clip.tone(0.4, (note("G4"), note("G5")), sine, perc(0.12, 3.0)),
        Clip.tone(0.4, (note("D5"), note("D6")), sine, perc(0.18, 3.5), gain=0.4),
    )


def magnet():
    """Everything on the floor rushing in — a sweep that keeps climbing."""
    sweep = Clip.tone(0.55, (300, 2400), noise(97), perc(0.5, 1.6)).lowpass(3000)
    tone = Clip.tone(0.55, (400, 2000), triangle, perc(0.45, 2.0), gain=0.5)
    return layer(sweep, tone).highpass(250)


# --- interactables and run structure ----------------------------------------

def chest():
    """Lid, then contents. The creak sells the wood; the chime sells the loot."""
    creak = Clip.tone(0.22, (110, 190), saw, perc(0.15, 3.0)).lowpass(700).drive(1.5)
    chime = arpeggio([note("G5"), note("B5"), note("D6")], note_length=0.075,
                     wave=triangle, gain=0.55)
    return creak.mix(chime, at=0.16).echo(0.11, 0.28, 2)


def altar():
    """Summoning a Warden. Dread, rising — this is a decision with consequences."""
    drone = Clip.tone(1.2, (55, 110), saw, swell(0.5, 0.2)).lowpass(600).drive(2.0)
    voice = Clip.tone(1.2, (220, 330), metallic(1.59), swell(0.6, 0.25), gain=0.4)
    return layer(drone, voice).echo(0.2, 0.35, 3)


def boss_roar():
    """A Warden arriving."""
    growl = Clip.tone(1.0, vibrato((90, 62), 0.05, 7.0), saw, adsr(0.06, 0.2, 0.7, 0.4))
    return growl.lowpass(800).drive(2.6).echo(0.17, 0.3, 3)


def portal_open():
    """The way onward appearing. Bright, ascending, unmistakably good news."""
    rise = Clip.tone(0.9, (200, 1600), metallic(2.14), swell(0.35, 0.4))
    sparkle = arpeggio([note("D5"), note("A5"), note("D6"), note("A6")],
                       note_length=0.1, wave=sine, gain=0.4)
    return layer(rise, sparkle).echo(0.13, 0.4, 4)


def portal_enter():
    """Stepping through. A downward rush that hands off to the next map's music."""
    rush = Clip.tone(0.7, (2000, 180), noise(101), perc(0.06, 3.0)).lowpass(2600)
    drop = Clip.tone(0.7, (880, 110), sine, perc(0.04, 3.5), gain=0.6)
    return layer(rush, drop).echo(0.14, 0.32, 3).highpass(90)


# --- interface --------------------------------------------------------------

def ui_move():
    """Moving between cards. Heard constantly, so it is nearly nothing."""
    return Clip.tone(0.035, 1200, square(0.5), perc(0.002, 9.0))


def ui_select():
    """Committing to a choice. Up a fifth from ui_move, so it reads as 'yes'."""
    first = Clip.tone(0.04, note("E5"), square(0.45), perc(0.003, 8.0))
    second = Clip.tone(0.1, note("B5"), square(0.45), perc(0.003, 6.0))
    return first.then(second)


# --- the mix ----------------------------------------------------------------
# Peak level every sound is normalised to, which is the entire loudness balance
# of the game in one readable table.
#
# It lives here rather than inside each recipe for two reasons. Balance is
# relative — "is the hit too loud?" is a question about hits *against gems and
# kills*, and you cannot answer it while the numbers are scattered across thirty
# functions. And a recipe that simply forgot to normalise has no ceiling at all:
# the first build produced seven sounds peaking above full scale, up to 1.75,
# every one of which would have clipped.
#
# Levels follow how often a sound plays. Hits fire dozens of times a second and
# sit near the bottom; a fanfare plays once per run and sits at the top.
#
# "hit" has been cut twice on play-test feedback, 0.28 -> 0.23 -> 0.16 -> 0.11.
# It is now the quietest thing in the game apart from the menu tick, which is
# right: it fires several times a second for fifteen minutes, and anything you
# hear that often should sit under the music rather than on top of it.
#
# The frequent cues were cut a further 15-20% after tools/audio_mix_check.py
# measured the busiest ten seconds of a real run peaking at 1.25 — clipping
# 0.02% of samples once a player raised the volume slider to full. Lowering the
# chatter rather than the whole mix keeps hurt, level-up and the fanfare exactly
# as loud as they were, so the gap between background and event got wider, not
# narrower.
# Sustained sounds (beam, gust) are pulled down further than their peak suggests
# they need, because loudness is heard as average energy, not peak.
LEVELS = {
    "ui_move": 0.16,
    "hit": 0.11,
    "gem": 0.25,
    "ui_select": 0.32,
    "beam": 0.29,
    "kill": 0.30,
    "gust": 0.36,
    "coin": 0.34,
    "shot": 0.36,
    "zap": 0.36,
    "slash": 0.37,
    "boss_hurt": 0.38,
    "crit": 0.44,
    "cast": 0.50,
    "frost": 0.43,
    "potion": 0.52,
    "erupt": 0.55,
    "magnet": 0.55,
    "chest": 0.60,
    "boom": 0.68,
    "levelup": 0.70,
    "thunder": 0.72,
    "altar": 0.72,
    "portal_open": 0.72,
    "portal_enter": 0.72,
    "hurt": 0.76,
    "boss_roar": 0.80,
    "death": 0.85,
    "victory": 0.90,
}


# --- registry ---------------------------------------------------------------
# Name -> callable. Names ending in a digit are variant families; the runtime
# discovers them by counting files, so adding hit_3 needs no code change.

RECIPES = {
    "slash": slash,
    "shot": shot,
    "cast": cast,
    "zap": zap,
    "thunder": thunder,
    "beam": beam,
    "frost": frost,
    "erupt": erupt,
    "gust": gust,
    "crit": crit,
    "boom": boom,
    "boss_hurt": boss_hurt,
    "hurt": hurt,
    "death": death,
    "levelup": levelup,
    "victory": victory,
    "coin": coin,
    "potion": potion,
    "magnet": magnet,
    "chest": chest,
    "altar": altar,
    "boss_roar": boss_roar,
    "portal_open": portal_open,
    "portal_enter": portal_enter,
    "ui_move": ui_move,
    "ui_select": ui_select,
}

for _index in range(4):
    RECIPES[f"hit_{_index}"] = (lambda i: lambda: hit(i))(_index)
for _index in range(3):
    RECIPES[f"kill_{_index}"] = (lambda i: lambda: kill(i))(_index)
for _index in range(5):
    RECIPES[f"gem_{_index}"] = (lambda i: lambda: gem(i))(_index)


def family(name):
    """``hit_2`` and ``hit`` both mix at the ``hit`` level."""
    stem = name.rsplit("_", 1)[0]
    return stem if stem in LEVELS else name


def build(name):
    """Render one recipe and apply the finishing every sound needs.

    Order matters. The high-pass runs first and is not cosmetic: asymmetric
    pulse waves carry a DC offset — a mix measured -0.043 during development —
    and DC is inaudible loudness that steals headroom from the part you can
    hear, so normalising before removing it makes everything quieter for
    nothing. Normalising second sets the level with that headroom recovered.
    The fade runs last and guards the other end: a buffer that stops mid-swing
    steps straight to zero, and a step is a click.

    Only the tail is faded. Every envelope here already starts at zero, so a
    fade-in protects against nothing — and it actively hurt: percussive
    envelopes peak within a millisecond, so a 1ms fade-in was landing on the
    attack transient and shaving 8% off exactly the part that makes a hit
    sound like a hit.
    """
    clip = RECIPES[name]()
    clip.highpass(28)
    clip.normalise(LEVELS[family(name)])
    clip.fade(0.0, 0.008)
    return clip


def _validate():
    """Every sound must have a level, and every level must belong to a sound."""
    missing = sorted(name for name in RECIPES if family(name) not in LEVELS)
    assert not missing, f"sounds with no mix level: {missing}"
    stems = {family(name) for name in RECIPES}
    stale = sorted(set(LEVELS) - stems)
    assert not stale, f"mix levels for sounds that do not exist: {stale}"


_validate()


def main():
    parser = argparse.ArgumentParser(description="Generate sound effects.")
    parser.add_argument("--report", action="store_true",
                        help="print duration, peak and RMS for every sound")
    parser.add_argument("--only", help="build just the sounds whose name contains this")
    args = parser.parse_args()

    os.makedirs(SFX_DIR, exist_ok=True)
    names = sorted(RECIPES)
    if args.only:
        names = [name for name in names if args.only in name]

    rows = []
    for name in names:
        clip = build(name)
        path = os.path.join(SFX_DIR, f"{name}.wav")
        # Never overwrite in place, matching make_art.py: a hand-tweaked sound
        # survives a careless regeneration.
        if os.path.exists(path):
            os.makedirs(BACKUP, exist_ok=True)
            shutil.move(path, os.path.join(BACKUP, f"{name}.wav"))
        clip.save(path)
        rows.append((name, clip.duration, clip.peak(), clip.rms()))

    print(f"wrote {len(rows)} sounds to {os.path.relpath(SFX_DIR, ROOT)}")
    if args.report:
        print(f"\n{'sound':<14}{'seconds':>9}{'peak':>8}{'rms':>8}")
        for name, duration, peak, rms in rows:
            print(f"{name:<14}{duration:>9.3f}{peak:>8.3f}{rms:>8.3f}")
        total = sum(duration for _, duration, _, _ in rows)
        print(f"{'':<14}{total:>9.3f}  total")


if __name__ == "__main__":
    main()
