"""Generate the game's music as seamless looping tracks.

    python tools/make_music.py            write every track into assets/music/
    python tools/make_music.py --report   print length, peak and RMS
    python tools/make_music.py --only hollow

Songs are written as tracker patterns: a voice is a string of note names, "."
for a rest and "~" to hold the previous note. That keeps a track editable as
text, the same bargain the pixel maps make — you can read the bassline in the
source and change a note without a DAW.

**Voices are deliberately different lengths.** A 4-bar bass under an 8-bar lead
under a 3-bar counter-line does not repeat until those lengths line up again, so
a 24-second file stops sounding like a 24-second file. This matters more here
than in most games: a survivors-like run is fifteen minutes of staring at the
same arena, and audible looping is what turns background music into an irritant.

**Loops wrap, they do not fade.** A reverb tail that runs past the end of the
buffer is mixed back into the *start* instead of being cut off, so the last
sample flows into the first. Fading out and in would be seamless too, but it
would also announce the loop point twice a minute.
"""

import argparse
import os
import shutil

from synth import (SAMPLE_RATE, Clip, adsr, layer, metallic, noise, note, perc,
                   saw, sine, square, swell, triangle, vibrato)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_DIR = os.path.join(ROOT, "assets", "music")
BACKUP = os.path.join(MUSIC_DIR, "old")

STEPS_PER_BAR = 16   # sixteenth notes


# --- instruments ------------------------------------------------------------
# Each returns a Clip for one note. Signature is (duration, freq, gain).

def inst_bass(duration, freq, gain):
    body = Clip.tone(duration, freq, triangle, adsr(0.01, 0.15, 0.7, 0.25), gain)
    grit = Clip.tone(duration, freq, square(0.5), adsr(0.01, 0.2, 0.4, 0.25), gain * 0.3)
    return layer(body, grit).lowpass(900)


def inst_lead(duration, freq, gain):
    return Clip.tone(duration, vibrato(freq, 0.006, 5.5), square(0.4),
                     adsr(0.02, 0.12, 0.65, 0.3), gain).lowpass(4200)


def inst_pluck(duration, freq, gain):
    return Clip.tone(duration, freq, triangle, perc(0.006, 3.2), gain).lowpass(5000)


def inst_pad(duration, freq, gain):
    """Two slightly detuned saws. The beating between them is the warmth."""
    return layer(
        Clip.tone(duration, freq, saw, swell(0.25, 0.35), gain * 0.5),
        Clip.tone(duration, freq * 1.006, saw, swell(0.3, 0.4), gain * 0.5),
    ).lowpass(1500)


def inst_bell(duration, freq, gain):
    return Clip.tone(duration, freq, metallic(2.76), perc(0.005, 3.0), gain)


def inst_choir(duration, freq, gain):
    """Sine stack with a fifth on top — the cheapest 'something is watching'."""
    return layer(
        Clip.tone(duration, vibrato(freq, 0.008, 4.0), sine, swell(0.35, 0.4), gain * 0.6),
        Clip.tone(duration, vibrato(freq * 1.5, 0.008, 4.3), sine, swell(0.4, 0.45), gain * 0.25),
    )


def inst_harp(duration, freq, gain):
    """Plucked string: bright attack, long ring, no sustain.

    The octave above is mixed in quietly rather than relying on the triangle's
    own harmonics — a plucked string's second partial is what makes it read as
    plucked rather than as a soft synth blip.
    """
    body = Clip.tone(duration, freq, triangle, perc(0.004, 2.6), gain)
    shimmer = Clip.tone(duration, freq * 2.0, sine, perc(0.004, 4.5), gain * 0.28)
    return layer(body, shimmer).lowpass(6500)


def inst_glock(duration, freq, gain):
    """Struck bell. Inharmonic partial and a long clean decay: the twinkle."""
    return Clip.tone(duration, freq, metallic(2.83), perc(0.002, 2.0), gain).highpass(500)


def inst_flute(duration, freq, gain):
    """Soft breathy lead.

    The noise layer is barely audible on its own and is the entire difference
    between "flute" and "sine wave" — wind instruments are pitched air, and
    without some air in the mix a pure tone sounds synthetic.
    """
    tone = Clip.tone(duration, vibrato(freq, 0.010, 5.0), sine,
                     adsr(0.10, 0.15, 0.80, 0.30), gain)
    breath = Clip.tone(duration, 3200, noise(4001), adsr(0.12, 0.20, 0.5, 0.35),
                       gain * 0.05).highpass(1800)
    return layer(tone, breath)


def inst_strings(duration, freq, gain):
    """Warm swelling pad: three saws detuned a few cents apart.

    Wider and slower than ``inst_pad`` — this one is meant to sit under a whole
    phrase rather than pulse with it.
    """
    return layer(
        Clip.tone(duration, freq, saw, swell(0.35, 0.40), gain * 0.40),
        Clip.tone(duration, freq * 1.004, saw, swell(0.40, 0.45), gain * 0.34),
        Clip.tone(duration, freq * 0.997, saw, swell(0.30, 0.40), gain * 0.26),
    ).lowpass(1900)


def inst_growl(duration, freq, gain):
    return Clip.tone(duration, freq, saw, adsr(0.03, 0.2, 0.7, 0.3), gain) \
        .lowpass(700).drive(2.0)


# --- percussion -------------------------------------------------------------

def drum_kick(gain=1.0):
    return Clip.tone(0.18, (150, 45), sine, perc(0.002, 6.0), gain).drive(1.5)


def drum_snare(gain=1.0):
    crack = Clip.tone(0.16, 800, noise(1009), perc(0.002, 7.0), gain).highpass(600)
    body = Clip.tone(0.16, (330, 180), triangle, perc(0.002, 8.0), gain * 0.4)
    return layer(crack, body)


def drum_hat(gain=1.0):
    return Clip.tone(0.05, 9000, noise(1013), perc(0.001, 14.0), gain).highpass(5500)


def drum_tom(gain=1.0):
    return Clip.tone(0.22, (220, 90), sine, perc(0.003, 5.0), gain).drive(1.3)


DRUMS = {"k": drum_kick, "s": drum_snare, "h": drum_hat, "t": drum_tom}


# --- the sequencer ----------------------------------------------------------

class Voice:
    """One instrument playing one repeating pattern.

    ``pattern`` is whitespace-separated: a note name ("D3"), "." for a rest, or
    "~" to sustain the previous note through this step.
    """

    def __init__(self, instrument, pattern, gain=0.5, octave=0, length=1.0):
        self.instrument = instrument
        self.tokens = pattern.split()
        self.gain = gain
        self.octave = octave
        self.length = length   # note duration as a multiple of one step

    def notes(self):
        """Walk the pattern, merging "~" into the note it extends.

        Yields ``(step, steps_held, frequency)``.
        """
        pending = None
        for index, token in enumerate(self.tokens):
            if token == "~":
                # A rest ends the note, so there is nothing left to hold. This
                # is a real mistake worth catching loudly: writing "A4 . ~"
                # when you meant "A4 ~ ~" otherwise surfaces as a note-parsing
                # error about a tilde, which tells you nothing.
                if pending is None:
                    raise ValueError(
                        f"step {index}: '~' follows a rest, so there is no note to hold "
                        f"(write 'A4 ~ ~' rather than 'A4 . ~')")
                pending[1] += 1
                continue
            if pending:
                yield pending
                pending = None
            if token != ".":
                pending = [index, 1, note(token) * (2.0 ** self.octave)]
        if pending:
            yield pending


class Drum:
    def __init__(self, pattern, gain=0.5):
        self.tokens = pattern.split()
        self.gain = gain


class Song:
    def __init__(self, bpm, bars, voices, drums=(), echo=None, level=0.5):
        self.bpm = bpm
        self.bars = bars
        self.voices = voices
        self.drums = drums
        self.echo = echo          # (delay_seconds, feedback, taps) or None
        self.level = level

    @property
    def step_seconds(self):
        return 60.0 / self.bpm / (STEPS_PER_BAR / 4)

    def render(self):
        step = self.step_seconds
        total_steps = self.bars * STEPS_PER_BAR
        total_samples = int(total_steps * step * SAMPLE_RATE)
        track = Clip([0.0] * total_samples)

        for voice in self.voices:
            span = len(voice.tokens)
            if not span:
                continue
            # Repeat each pattern across the whole song. Patterns whose length
            # does not divide the song are the point, not a bug — that is where
            # the variation comes from.
            for repeat in range((total_steps + span - 1) // span):
                base = repeat * span
                for start, held, freq in voice.notes():
                    if base + start >= total_steps:
                        break
                    clip = voice.instrument(step * held * voice.length, freq, voice.gain)
                    _mix_wrapped(track, clip, (base + start) * step)

        for drum in self.drums:
            span = len(drum.tokens)
            if not span:
                continue
            for repeat in range((total_steps + span - 1) // span):
                base = repeat * span
                for index, token in enumerate(drum.tokens):
                    if token == "." or base + index >= total_steps:
                        continue
                    clip = DRUMS[token](drum.gain)
                    _mix_wrapped(track, clip, (base + index) * step)

        if self.echo:
            delay, feedback, taps = self.echo
            source = list(track.samples)
            gain = feedback
            for tap in range(1, taps + 1):
                _mix_wrapped(track, Clip(source), delay * tap, gain)
                gain *= feedback

        _highpass_cyclic(track, 26)
        track.normalise(self.level)
        return track


def _highpass_cyclic(track, cutoff):
    """High-pass a looping buffer without breaking the loop.

    A one-pole filter carries state, and it starts from zero. On a normal clip
    that settling transient is inaudible, but on a loop it lands at sample 0 and
    the *end* of the buffer is fully settled — so the two ends no longer meet
    and the seam clicks. The Hollow's deep pads made this measurable: its wrap
    discontinuity was 1.7x an ordinary sample step while the other four tracks
    sat near 0.1x.

    Running the filter over two copies and keeping the second gives it a full
    lap to settle, which is the steady state the loop actually plays in.
    """
    doubled = Clip(track.samples + track.samples)
    doubled.highpass(cutoff)
    track.samples = doubled.samples[len(track.samples):]
    return track


def _mix_wrapped(track, clip, at, gain=1.0):
    """Mix ``clip`` into ``track`` at ``at`` seconds, wrapping past the end.

    This is what makes the loop seamless. A note or a reverb tail that runs off
    the end of the buffer continues at the beginning, which is exactly where it
    would be heard on the next pass. Truncating instead would leave a hole at
    the loop point that reads as a stutter.
    """
    size = len(track.samples)
    if not size:
        return
    offset = int(at * SAMPLE_RATE)
    for index, value in enumerate(clip.samples):
        track.samples[(offset + index) % size] += value * gain


# --- the songs --------------------------------------------------------------
# Voice lengths are chosen to be mutually awkward on purpose; see the module
# docstring. A comment on each says how many bars it spans.

def menu():
    """Title and hub. Unhurried, warm, going nowhere in particular."""
    return Song(
        bpm=84, bars=16, level=0.42, echo=(0.34, 0.26, 3),
        voices=[
            # 4 bars
            Voice(inst_pad, """
                C3 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                A2 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                F2 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                G2 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
            """, gain=0.30),
            # 3 bars, so it drifts against the 4-bar pad
            Voice(inst_pluck, """
                C5 . G4 . E5 . G4 . C5 . . . E5 . . .
                A4 . E5 . C5 . E5 . A4 . . . C5 . . .
                F4 . C5 . A4 . C5 . F4 . . . A4 . . .
            """, gain=0.22),
            # 8 bars
            Voice(inst_bass, """
                C2 . . . . . . . C2 . . . G1 . . .
                A1 . . . . . . . A1 . . . E1 . . .
                F1 . . . . . . . F1 . . . C2 . . .
                G1 . . . . . . . G1 . . . D2 . . .
                C2 . . . . . . . E2 . . . G2 . . .
                A1 . . . . . . . C2 . . . E2 . . .
                F1 . . . . . . . A1 . . . C2 . . .
                G1 . . . . . . . B1 . . . D2 . . .
            """, gain=0.34, length=3.0),
        ],
    )


def greenwood():
    """Open forest — the fairy theme, and the track most of a run is spent in.

    **F lydian.** Lydian is major with a raised fourth, and that one note (B
    natural against an F chord) is most of what people mean by "magical" — it is
    the interval doing the work in almost every fairy-tale score ever written.
    Plain F major here would sound pleasant and ordinary.

    **The harp runs in twelve.** Its pattern is twelve steps long against bars of
    sixteen, so it never lands in the same place twice until they realign three
    bars later. That is a hemiola, and it is why the arpeggios feel like they
    are drifting over the beat rather than marching with it.

    **Almost no drums.** A kick-and-snare pattern would turn this into an
    adventure march. What is left is a soft hat on the offbeat, closer to a
    tambourine shaken somewhere behind the trees.
    """
    return Song(
        bpm=100, bars=24, level=0.44, echo=(0.33, 0.30, 4),
        voices=[
            # 4 bars — root and fifth, left long and soft
            Voice(inst_bass, """
                F2 . . . . . . . C3 . . . . . . .
                G2 . . . . . . . D3 . . . . . . .
                A2 . . . . . . . E3 . . . . . . .
                C3 . . . . . . . G2 . . . . . . .
            """, gain=0.34, length=5.0),
            # 8 bars of pad: F - G - Am - C, two bars each
            Voice(inst_strings, """
                F3 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                F3 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                G3 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                G3 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                A3 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                A3 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                C4 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                C4 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
            """, gain=0.15),
            # 5 bars — an inner voice that drifts against the 8-bar pad
            Voice(inst_strings, """
                A3 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                B3 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                C4 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                E4 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                D4 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
            """, gain=0.10),
            # 12 steps against 16-step bars: the drifting arpeggio
            Voice(inst_harp, "F4 . A4 . C5 . F5 . C5 . A4 .", gain=0.20, length=3.0),
            # 6 bars — the tune, with the lydian B natural in bars 2 and 4
            Voice(inst_flute, """
                . . F4 . A4 ~ ~ ~ C5 . B4 . A4 . . .
                . . G4 . B4 ~ ~ ~ A4 . . . F4 . G4 .
                A4 . C5 . F5 ~ ~ ~ E5 . C5 . A4 . . .
                . . B4 . D5 ~ ~ ~ C5 . A4 . G4 . . .
                F4 . A4 . C5 . E5 . D5 ~ ~ ~ C5 . . .
                . . A4 . G4 . F4 . G4 ~ ~ ~ ~ . . .
            """, gain=0.22),
            # 7 bars of sparse bells, so the sparkle never lands predictably
            Voice(inst_glock, """
                . . . . F6 . . . . . . . . . . .
                . . . . . . . . . . . . C6 . . .
                . . . . . . . . . . . . . . . .
                . . . . A5 . . . . . . . . . . .
                . . . . . . . . . . . . . . . .
                . . . . . . . . E6 . . . . . . .
                . . . . . . . . . . . . . . . .
            """, gain=0.13, length=4.0),
        ],
        drums=[
            Drum(". . . . h . . . . . . . h . . .", gain=0.07),
        ],
    )


def cinderwaste():
    """Burnt ground. E phrygian — the flat second is the whole mood."""
    return Song(
        bpm=138, bars=24, level=0.48, echo=(0.21, 0.24, 3),
        voices=[
            # 2 bars: relentless, this one is supposed to nag
            Voice(inst_bass, """
                E1 . E1 . E1 . E1 . F1 . F1 . E1 . . .
                E1 . E1 . E1 . E1 . D1 . D1 . E1 . . .
            """, gain=0.44, length=1.2),
            # 5 bars against the 2-bar riff
            Voice(inst_lead, """
                E4 . . . F4 . . . G4 . . . F4 . E4 .
                . . B3 . E4 . . . F4 . . . . . . .
                G4 . F4 . E4 . D4 . E4 . . . . . . .
                . . G4 . A4 . . . B4 ~ ~ . A4 . G4 .
                F4 . E4 . . . D4 . E4 ~ ~ ~ ~ . . .
            """, gain=0.28),
            # 3 bars
            Voice(inst_growl, """
                E2 ~ ~ ~ ~ ~ ~ ~ F2 ~ ~ ~ ~ ~ ~ ~
                E2 ~ ~ ~ ~ ~ ~ ~ D2 ~ ~ ~ ~ ~ ~ ~
                C2 ~ ~ ~ ~ ~ ~ ~ B1 ~ ~ ~ ~ ~ ~ ~
            """, gain=0.20),
            # 9 steps against 16-step bars — the same drifting-harp idea as the
            # Greenwood theme, in the minor mode, so the two tracks are audibly
            # the same game.
            Voice(inst_harp, "E4 . G4 . B4 . E5 . B4", gain=0.13, length=2.5),
            # 7 bars — the longest line, so the track keeps unfolding
            Voice(inst_bell, """
                . . . . . . . . . . . . E5 . . .
                . . . . . . . . . . . . . . . .
                . . . . F5 . . . . . . . . . . .
                . . . . . . . . . . . . . . . .
                . . . . . . . . B4 . . . . . . .
                . . . . . . . . . . . . . . . .
                . . . . . . . . . . . . G4 . . .
            """, gain=0.13),
        ],
        drums=[
            Drum("k . . k . . k . . . k . . . . .", gain=0.32),
            Drum(". . . . s . . . . . . . s . . .", gain=0.24),
            Drum("h . h . h . h . h . h . h . h h", gain=0.11),
            Drum(". . . . . . . . . . . . . . t t", gain=0.16),
        ],
    )


def hollow():
    """A broken citadel over the dark. Slow, vast, and mostly empty.

    The final map earns restraint: fewer notes, more space, and no hats. The
    drums that remain are toms, which read as distance rather than groove.
    """
    return Song(
        bpm=76, bars=24, level=0.44, echo=(0.44, 0.34, 4),
        voices=[
            # 4 bars
            Voice(inst_bass, """
                A1 . . . . . . . . . . . . . . .
                A1 . . . . . . . E1 . . . . . . .
                F1 . . . . . . . . . . . . . . .
                G1 . . . . . . . D1 . . . . . . .
            """, gain=0.42, length=6.0),
            # 6 bars
            Voice(inst_choir, """
                A3 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                C4 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                E4 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                D4 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                F4 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                E4 ~ ~ ~ ~ ~ ~ ~ C4 ~ ~ ~ ~ ~ ~ ~
            """, gain=0.22),
            # 11 steps: slower and sparser than the other two harps, because
            # the Hollow is meant to feel empty rather than enchanted.
            Voice(inst_harp, "A3 . . C4 . . E4 . . A4 .", gain=0.11, length=4.0),
            # 5 bars
            Voice(inst_bell, """
                . . . . A5 . . . . . . . . . . .
                . . . . . . . . . . . . E5 . . .
                . . . . . . . . . . . . . . . .
                . . . . C5 . . . . . . . . . . .
                . . . . . . . . . . . . . . . .
            """, gain=0.15),
            # 7 bars
            Voice(inst_pad, """
                A2 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                A2 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                F2 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                F2 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                G2 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                E2 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                D2 ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
            """, gain=0.16),
        ],
        drums=[
            Drum("t . . . . . . . . . . . . . . .", gain=0.20),
            Drum(". . . . . . . . . . . . . . . . "
                 ". . . . . . . . t . . . . . . .", gain=0.14),
        ],
    )


def boss():
    """Warden fights. Fast, tight, and short — urgency, not grandeur."""
    return Song(
        bpm=150, bars=16, level=0.50, echo=(0.19, 0.2, 2),
        voices=[
            # 2 bars
            Voice(inst_bass, """
                D1 . D1 . D1 . D1 . D1 . D1 . D1 . D1 .
                C1 . C1 . C1 . C1 . Bb1 . Bb1 . A1 . A1 .
            """, gain=0.46, length=1.1),
            # 3 bars
            Voice(inst_growl, """
                D3 ~ ~ ~ ~ ~ ~ ~ F3 ~ ~ ~ ~ ~ ~ ~
                E3 ~ ~ ~ ~ ~ ~ ~ D3 ~ ~ ~ ~ ~ ~ ~
                Bb2 ~ ~ ~ ~ ~ ~ ~ A2 ~ ~ ~ ~ ~ ~ ~
            """, gain=0.24),
            # 5 bars
            Voice(inst_lead, """
                D5 . C5 . Bb4 . A4 . D5 . . . F5 . . .
                E5 . D5 . C5 . Bb4 . A4 ~ ~ ~ . . . .
                . . F5 . G5 . A5 ~ ~ . G5 . F5 . E5 .
                D5 . . . A4 . . . D5 . . . E5 . F5 .
                G5 . F5 . E5 . D5 ~ ~ ~ ~ . . . . .
            """, gain=0.30),
        ],
        drums=[
            Drum("k . . . k . . . k . . . k . . .", gain=0.34),
            Drum(". . . . s . . . . . . . s . . s", gain=0.26),
            Drum("h h h h h h h h h h h h h h h h", gain=0.10),
        ],
    )


SONGS = {
    "menu": menu,
    "greenwood": greenwood,
    "cinderwaste": cinderwaste,
    "hollow": hollow,
    "boss": boss,
}


def main():
    parser = argparse.ArgumentParser(description="Generate music tracks.")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--only", help="build just the tracks whose name contains this")
    args = parser.parse_args()

    os.makedirs(MUSIC_DIR, exist_ok=True)
    names = sorted(SONGS)
    if args.only:
        names = [name for name in names if args.only in name]

    rows = []
    for name in names:
        track = SONGS[name]().render()
        path = os.path.join(MUSIC_DIR, f"{name}.wav")
        if os.path.exists(path):
            os.makedirs(BACKUP, exist_ok=True)
            shutil.move(path, os.path.join(BACKUP, f"{name}.wav"))
        track.save(path)
        rows.append((name, track.duration, track.peak(), track.rms(),
                     os.path.getsize(path)))
        print(f"  {name}")

    print(f"wrote {len(rows)} tracks to {os.path.relpath(MUSIC_DIR, ROOT)}")
    if args.report:
        print(f"\n{'track':<14}{'seconds':>9}{'peak':>8}{'rms':>8}{'KB':>9}")
        for name, duration, peak, rms, size in rows:
            print(f"{name:<14}{duration:>9.2f}{peak:>8.3f}{rms:>8.3f}{size / 1024:>9.0f}")


if __name__ == "__main__":
    main()
