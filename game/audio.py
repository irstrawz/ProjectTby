"""Sound playback, rate limiting, and music.

The assets come from ``tools/make_sound.py`` and ``tools/make_music.py``. This
module's job is not playing them — that is two lines of pygame — but deciding
*which* requests to honour.

A survivors-like generates absurd numbers of sound events. Late in a run there
are 200 enemies on the field, six weapons ticking, and a carpet of gems on the
floor; a naive ``Sound.play()`` per event asks for several hundred sounds a
second through a mixer with a few dozen channels. Two things go wrong, and
neither looks like an audio bug from the outside:

* **The mixer runs out of channels**, so ``play()`` starts returning None — and
  what gets dropped is whatever asked last. Level-up, taking damage, and a
  Warden dying are exactly the sounds that arrive during heavy combat, so the
  important cues are the ones that go missing.
* **Identical samples stack.** Forty copies of one waveform starting inside the
  same few milliseconds sum to forty times the amplitude, which clips hard, and
  because they are phase-aligned it reads as one loud honk rather than forty
  hits.

So every cue declares a minimum gap and a priority, high-priority cues get
reserved channels the noise cannot touch, and frequent cues cycle through
variants. The result is that a screen-clearing explosion sounds like a
screen-clearing explosion instead of a click.
"""

import os
import time

import pygame

from . import paths

SFX_DIR = paths.resource_path("assets", "sfx")
MUSIC_DIR = paths.resource_path("assets", "music")

# More than the pygame default of 8. Each channel is a mixing slot, not a
# thread, so the cost of spare ones is trivial; running out is what hurts.
CHANNELS = 32

# Channels set aside for cues that must never be dropped. pygame keeps reserved
# channels out of the pool ``Sound.play()`` allocates from, so no amount of
# combat chatter can take them.
RESERVED = 6

MUSIC_FADE_MS = 700

# Master headroom applied on top of the player's SFX setting.
#
# Individual sounds are authored well below full scale, but they sum: with a
# dozen cues overlapping, tools/audio_mix_check.py measured the busiest ten
# seconds of a real run peaking at 1.12 with the slider at maximum, clipping a
# few dozen samples. There is nowhere to put a limiter — pygame does the
# summing inside the mixer — so the ceiling has to be set before the sounds get
# there. 0.85 covers the measured worst case with margin to spare.
#
# This is deliberately not folded into the authored levels: those encode the
# *relative* balance between cues, which is a design decision, while this is one
# global number answering "how loud can everything be at once", which is a
# measurement. Keeping them separate means re-measuring never disturbs the mix.
MASTER_SFX = 0.85


class Cue:
    """Playback policy for one sound.

    ``gap`` is the minimum seconds between two plays of this cue. It is the
    single most important number here: it converts an unbounded event rate into
    a bounded one, and it is tuned per cue because a hit and a boss roar have
    nothing in common. ``limit`` caps how many copies may overlap, which catches
    the case where a long sound is triggered repeatedly inside its own tail.
    """

    def __init__(self, gap=0.0, priority=False, limit=4, ladder=False):
        self.gap = gap
        self.priority = priority
        self.limit = limit
        # A ladder cue walks up its variants on consecutive plays and resets
        # after a pause — hoovering up a line of gems becomes a rising run
        # instead of the same blip twelve times.
        self.ladder = ladder


# Gaps are set from how often the event can physically occur. Hits and gems are
# the two that arrive in floods; everything rare is left effectively ungated so
# it always speaks.
CUES = {
    # combat chatter — tightly gated
    # Widened from 0.055 after play testing: that allowed 18 hits a second,
    # which is past the point where individual impacts stop registering as
    # separate events and become a texture you want to switch off.
    "hit": Cue(gap=0.095, limit=4),
    "kill": Cue(gap=0.050, limit=6),
    "crit": Cue(gap=0.070, limit=4),
    "boss_hurt": Cue(gap=0.090, limit=3),

    # weapon fire — already rate-limited by cooldowns, gated against stacking
    "slash": Cue(gap=0.070, limit=3),
    "shot": Cue(gap=0.070, limit=4),
    "cast": Cue(gap=0.110, limit=3),
    "zap": Cue(gap=0.090, limit=3),
    "frost": Cue(gap=0.250, limit=2),
    "erupt": Cue(gap=0.220, limit=2),
    "thunder": Cue(gap=0.300, limit=2),
    "beam": Cue(gap=0.450, limit=2),
    "gust": Cue(gap=0.400, limit=2),
    "boom": Cue(gap=0.120, limit=3),

    # pickups
    "gem": Cue(gap=0.045, limit=5, ladder=True),
    "coin": Cue(gap=0.060, limit=4),
    "potion": Cue(gap=0.100, priority=True, limit=2),
    "magnet": Cue(gap=0.200, priority=True, limit=2),

    # the player, and run structure — these must never be starved
    "hurt": Cue(gap=0.220, priority=True, limit=2),
    "death": Cue(gap=1.000, priority=True, limit=1),
    "levelup": Cue(gap=0.150, priority=True, limit=2),
    "victory": Cue(gap=1.000, priority=True, limit=1),
    "chest": Cue(gap=0.150, priority=True, limit=2),
    "altar": Cue(gap=0.400, priority=True, limit=1),
    "boss_roar": Cue(gap=0.500, priority=True, limit=2),
    "portal_open": Cue(gap=0.500, priority=True, limit=1),
    "portal_enter": Cue(gap=0.500, priority=True, limit=1),

    # interface
    "ui_move": Cue(gap=0.040, limit=2),
    "ui_select": Cue(gap=0.070, priority=True, limit=2),
}

# How long a ladder cue waits before dropping back to its lowest variant.
LADDER_RESET = 0.55

# Which track plays where. Falls back to the menu theme for anything unlisted,
# so adding a fourth map cannot produce silence.
MAP_TRACKS = {
    "greenwood": "greenwood",
    "cinderwaste": "cinderwaste",
    "hollow": "hollow",
}


class _Mixer:
    """Owns the device. Every method is a no-op when there is no audio.

    Headless runs — the self-test, the DPS bench, the smoke simulation — have no
    audio device, and neither do some players. Rather than sprinkling `if
    audio_enabled` through the game, the whole module degrades to doing nothing
    and callers never check.
    """

    def __init__(self):
        self.ready = False
        self.sounds = {}          # cue name -> list of Sound variants
        self.last_played = {}     # cue name -> time.monotonic()
        self.ladder_index = {}    # cue name -> next variant to use
        self.sfx_volume = 0.7
        self.music_volume = 0.22
        self.current_track = None
        self.suppressed = 0       # plays refused by the gate, for diagnostics
        self.played = 0
        # The gate reads the clock through this rather than calling
        # time.monotonic directly, so headless tooling can drive it with
        # simulated time. A 240-second run that finishes in 10 wall seconds
        # would otherwise be measured against a 10-second budget and suppress
        # almost everything, making the gating look far better than it is.
        self.clock = time.monotonic

    # -- setup --

    def init(self, sfx_volume=0.7, music_volume=0.22):
        """Open the device and load every sound. Safe to call twice."""
        self.sfx_volume = sfx_volume
        self.music_volume = music_volume
        if self.ready:
            self.apply_volumes()
            return True
        try:
            # A small buffer keeps latency low. 512 frames at 44.1kHz is about
            # 12ms — below the point where a hit sounds late against the flash
            # on screen.
            #
            # The device has to be closed first. ``pygame.init()`` already
            # opened the mixer with default settings, and ``pre_init`` only
            # affects the *next* open — so without the quit, these parameters
            # are silently ignored and the buffer stays at whatever the default
            # was.
            if pygame.mixer.get_init():
                pygame.mixer.quit()
            pygame.mixer.pre_init(44100, -16, 2, 512)
            pygame.mixer.init()
        except pygame.error:
            # No device, or one already in use. Silent is a valid outcome.
            return False
        pygame.mixer.set_num_channels(CHANNELS)
        pygame.mixer.set_reserved(RESERVED)
        self.ready = True
        self._load_sounds()
        self.apply_volumes()
        return True

    def _load_sounds(self):
        """Load assets/sfx, grouping ``hit_0``/``hit_1``/... into one cue.

        Variants are discovered from the filenames rather than listed in code,
        so adding a fourth hit sound is a matter of dropping in a file.
        """
        self.sounds.clear()
        if not os.path.isdir(SFX_DIR):
            return
        for filename in sorted(os.listdir(SFX_DIR)):
            if not filename.endswith(".wav"):
                continue
            name = filename[:-4]
            stem = name.rsplit("_", 1)[0]
            cue = stem if (stem in CUES and name[-1].isdigit()) else name
            try:
                sound = pygame.mixer.Sound(os.path.join(SFX_DIR, filename))
            except pygame.error:
                continue
            self.sounds.setdefault(cue, []).append(sound)

    def apply_volumes(self):
        if not self.ready:
            return
        for variants in self.sounds.values():
            for sound in variants:
                sound.set_volume(self.sfx_volume * MASTER_SFX)
        pygame.mixer.music.set_volume(self.music_volume)

    def set_sfx_volume(self, value):
        self.sfx_volume = max(0.0, min(1.0, value))
        self.apply_volumes()

    def set_music_volume(self, value):
        self.music_volume = max(0.0, min(1.0, value))
        if self.ready:
            pygame.mixer.music.set_volume(self.music_volume)

    # -- effects --

    def play(self, name, volume=1.0):
        """Play a cue if its policy allows. Returns True if it actually played.

        Callers fire this on every event without checking anything; deciding
        what survives is this function's whole purpose.
        """
        if not self.ready:
            return False
        variants = self.sounds.get(name)
        if not variants:
            return False
        cue = CUES.get(name)
        if cue is None:
            cue = CUES.setdefault(name, Cue())

        now = self.clock()
        last = self.last_played.get(name, -999.0)
        if now - last < cue.gap:
            self.suppressed += 1
            return False

        sound = self._pick_variant(name, variants, cue, now - last)
        if sound.get_num_channels() >= cue.limit:
            self.suppressed += 1
            return False

        channel = sound.play()
        if channel is None:
            # Every unreserved channel is busy. Priority cues force their way in
            # on the reserved block; anything else accepts the loss, which is
            # the whole point of reserving.
            if not cue.priority:
                self.suppressed += 1
                return False
            channel = self._reserved_channel()
            if channel is None:
                self.suppressed += 1
                return False
            channel.play(sound)

        # Always set it, even at 1.0. Channel volume persists after a sound
        # finishes, so a channel left at 0.4 by a quiet cue would mute whatever
        # the mixer happens to allocate to it next — an intermittent bug that
        # would look like sounds randomly going missing. Note this is the *per
        # play* scale only: pygame multiplies channel volume by the Sound's own
        # volume, which already carries the SFX setting, so folding it in here
        # too would square it.
        channel.set_volume(max(0.0, min(1.0, volume)))
        self.last_played[name] = now
        self.played += 1
        return True

    def _pick_variant(self, name, variants, cue, since):
        if len(variants) == 1:
            return variants[0]
        if cue.ladder:
            index = 0 if since > LADDER_RESET else self.ladder_index.get(name, 0)
            self.ladder_index[name] = (index + 1) % len(variants)
            return variants[index]
        # Cycle rather than choose randomly: random repeats itself audibly
        # (two identical hits in a row happens a third of the time with three
        # variants), and a cycle guarantees maximum spacing for free.
        index = self.ladder_index.get(name, 0)
        self.ladder_index[name] = (index + 1) % len(variants)
        return variants[index]

    def _reserved_channel(self):
        """Find a free reserved channel, else steal the one that will end soonest."""
        for index in range(RESERVED):
            channel = pygame.mixer.Channel(index)
            if not channel.get_busy():
                return channel
        return pygame.mixer.Channel(0)

    def stop_all(self):
        if self.ready:
            pygame.mixer.stop()

    # -- music --

    def play_music(self, track, force=False):
        """Switch to ``track``, fading through silence.

        Requesting the track already playing does nothing — otherwise every
        state change that passes through the menu would restart the theme from
        the top, which is far more noticeable than a missing transition.
        """
        if not self.ready:
            return False
        if track == self.current_track and not force:
            return False
        path = os.path.join(MUSIC_DIR, f"{track}.wav")
        if not os.path.exists(path):
            return False
        try:
            if self.current_track is not None:
                pygame.mixer.music.fadeout(MUSIC_FADE_MS)
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self.music_volume)
            pygame.mixer.music.play(-1, fade_ms=MUSIC_FADE_MS)
        except pygame.error:
            return False
        self.current_track = track
        return True

    def music_for_map(self, map_key):
        return self.play_music(MAP_TRACKS.get(map_key, "menu"))

    def stop_music(self, fade_ms=MUSIC_FADE_MS):
        if self.ready and self.current_track is not None:
            pygame.mixer.music.fadeout(fade_ms)
            self.current_track = None

    def stats(self):
        total = self.played + self.suppressed
        return {
            "played": self.played,
            "suppressed": self.suppressed,
            "share_played": self.played / total if total else 0.0,
        }


_mixer = _Mixer()

# Module-level API. Callers say ``audio.play("hit")`` and never think about
# devices, channels or whether sound is even enabled.
init = _mixer.init
play = _mixer.play
play_music = _mixer.play_music
music_for_map = _mixer.music_for_map
stop_music = _mixer.stop_music
stop_all = _mixer.stop_all
set_sfx_volume = _mixer.set_sfx_volume
set_music_volume = _mixer.set_music_volume
stats = _mixer.stats


def set_clock(fn):
    """Swap the clock the rate gate reads. Pass None to restore the real one."""
    _mixer.clock = fn or time.monotonic
    _mixer.last_played.clear()


def reset_stats():
    _mixer.played = _mixer.suppressed = 0


def is_ready():
    return _mixer.ready


def volumes():
    return _mixer.sfx_volume, _mixer.music_volume
