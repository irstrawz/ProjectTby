"""A small software synthesizer: the audio equivalent of the pixel maps.

``make_art.py`` authors sprites as characters in a grid so they can be edited by
hand. Sound gets the same treatment — every effect and every note in this game
is a recipe built from the primitives here, so changing the fireball's whoosh
means editing numbers in ``make_sound.py`` rather than hunting for a new file.

There is no numpy in this environment, so everything is a plain Python list of
floats in roughly [-1, 1]. That is slow per-sample, but these run once at build
time and write .wav files the game just loads, so the cost never reaches a
frame.

Two rules keep the output usable:

* **Determinism.** Noise draws from a seeded ``random.Random``, never the global
  one. Regenerating the assets twice must produce byte-identical files, or the
  "did my edit change anything?" question becomes unanswerable.
* **Headroom.** Everything is written through ``Clip.normalise``, which leaves
  peaks below full scale. Eight mixer channels summing at once clip hard and
  ugly otherwise, and clipping is the one artefact that sounds broken rather
  than merely retro.
"""

import math
import random
import struct
import wave

SAMPLE_RATE = 44100

# Sounds are written mono. The mixer opens in stereo and upmixes for us, and a
# top-down arena has nothing meaningful to pan — halving the file size and the
# synthesis time is the better trade.
CHANNELS = 1


# --- waveforms --------------------------------------------------------------
# Each takes a phase in [0, 1) and returns a sample in [-1, 1]. Anything with
# this shape can be passed as ``wave=`` below, including a lambda.

def sine(phase):
    return math.sin(2.0 * math.pi * phase)


def saw(phase):
    return 2.0 * phase - 1.0


def triangle(phase):
    return 4.0 * abs(phase - 0.5) - 1.0


def square(duty=0.5):
    """A pulse wave. Duty below 0.5 thins it toward a reedy, nasal tone."""
    def wave(phase):
        return 1.0 if phase < duty else -1.0
    return wave


def noise(seed=0):
    """White noise. Ignores phase, so it is unpitched by construction."""
    rng = random.Random(seed)

    def wave(_phase):
        return rng.uniform(-1.0, 1.0)
    return wave


def metallic(ratio=2.37):
    """Two sines an inharmonic interval apart — bell and impact timbres.

    An integer ratio would give a musical overtone and sound like a chord. The
    fractional ratio is what makes a hit read as a struck object instead.
    """
    def wave(phase):
        return 0.6 * math.sin(2.0 * math.pi * phase) + 0.4 * math.sin(2.0 * math.pi * phase * ratio)
    return wave


# --- envelopes --------------------------------------------------------------
# Each takes normalised time in [0, 1] and returns a gain in [0, 1].

def perc(attack=0.01, curve=4.0):
    """Instant-ish onset then exponential decay. The default for anything hit."""
    def env(t):
        if t < attack:
            return t / attack if attack else 1.0
        fall = (t - attack) / (1.0 - attack) if attack < 1.0 else 1.0
        return math.exp(-curve * fall)
    return env


def swell(attack=0.3, release=0.3):
    """Fade in, hold, fade out — for pads, hums and anything sustained."""
    def env(t):
        if t < attack:
            return t / attack if attack else 1.0
        if t > 1.0 - release:
            return (1.0 - t) / release if release else 1.0
        return 1.0
    return env


def adsr(attack=0.02, decay=0.1, sustain=0.6, release=0.3):
    hold = max(0.0, 1.0 - attack - decay - release)

    def env(t):
        if t < attack:
            return t / attack if attack else 1.0
        if t < attack + decay:
            return 1.0 - (1.0 - sustain) * (t - attack) / decay if decay else sustain
        if t < attack + decay + hold:
            return sustain
        remaining = 1.0 - t
        return sustain * (remaining / release) if release else 0.0
    return env


def flat(t):
    return 1.0


# --- pitch ------------------------------------------------------------------

def _pitch_fn(freq):
    """Normalise the many ways a caller can describe pitch into f(t) -> hz.

    Accepts a constant, a ``(start, end)`` tuple for an exponential glide, or a
    callable for anything stranger. Glides are exponential because pitch is
    perceived in ratios: a linear sweep from 800 to 100 spends most of its time
    sounding high, then plummets.
    """
    if callable(freq):
        return freq
    if isinstance(freq, tuple):
        start, end = freq
        start = max(1e-6, start)
        end = max(1e-6, end)
        return lambda t: start * (end / start) ** t
    return lambda _t: freq


def vibrato(base, depth=0.03, rate=6.0):
    """Wrap a pitch spec with periodic wobble. ``depth`` is a fraction."""
    inner = _pitch_fn(base)

    def freq(t):
        return inner(t) * (1.0 + depth * math.sin(2.0 * math.pi * rate * t))
    return freq


# --- the clip ---------------------------------------------------------------

class Clip:
    """A mono buffer of floats, with the operations needed to shape one."""

    def __init__(self, samples=None):
        self.samples = samples if samples is not None else []

    # -- construction --

    @classmethod
    def silence(cls, duration):
        return cls([0.0] * int(duration * SAMPLE_RATE))

    @classmethod
    def tone(cls, duration, freq, wave=sine, env=None, gain=1.0):
        """Render one voice.

        Phase is accumulated rather than computed as ``sin(2*pi*f*t)``. With a
        changing frequency the direct form jumps phase every sample and the
        result buzzes instead of glides — the bug sounds like a broken sound
        card, and it is invisible in any plot of the frequency curve.
        """
        count = int(duration * SAMPLE_RATE)
        if count <= 0:
            return cls([])
        pitch = _pitch_fn(freq)
        envelope = env if env is not None else flat
        samples = [0.0] * count
        phase = 0.0
        step = 1.0 / SAMPLE_RATE
        for index in range(count):
            t = index / count
            phase += pitch(t) * step
            phase -= int(phase)
            samples[index] = wave(phase) * envelope(t) * gain
        return cls(samples)

    # -- combination --

    def mix(self, other, at=0.0, gain=1.0):
        """Add ``other`` in at ``at`` seconds, extending self if it overruns."""
        offset = int(at * SAMPLE_RATE)
        needed = offset + len(other.samples)
        if needed > len(self.samples):
            self.samples.extend([0.0] * (needed - len(self.samples)))
        for index, value in enumerate(other.samples):
            self.samples[offset + index] += value * gain
        return self

    def then(self, other):
        self.samples.extend(other.samples)
        return self

    def pad(self, duration):
        """Extend with silence so a tail has room to ring out."""
        self.samples.extend([0.0] * int(duration * SAMPLE_RATE))
        return self

    # -- shaping --

    def gain(self, amount):
        self.samples = [value * amount for value in self.samples]
        return self

    def peak(self):
        return max((abs(value) for value in self.samples), default=0.0)

    def rms(self):
        if not self.samples:
            return 0.0
        return math.sqrt(sum(value * value for value in self.samples) / len(self.samples))

    def normalise(self, target=0.85):
        peak = self.peak()
        if peak > 0:
            self.gain(target / peak)
        return self

    def fade(self, fade_in=0.0, fade_out=0.01):
        """Taper the ends. A buffer that starts or stops mid-swing clicks."""
        count = len(self.samples)
        rise = int(fade_in * SAMPLE_RATE)
        fall = int(fade_out * SAMPLE_RATE)
        for index in range(min(rise, count)):
            self.samples[index] *= index / rise
        for index in range(min(fall, count)):
            self.samples[count - 1 - index] *= index / fall
        return self

    def lowpass(self, cutoff):
        """One-pole filter — takes the edge off harsh square and noise tones."""
        if cutoff <= 0:
            return self
        dt = 1.0 / SAMPLE_RATE
        rc = 1.0 / (2.0 * math.pi * cutoff)
        alpha = dt / (rc + dt)
        previous = 0.0
        for index, value in enumerate(self.samples):
            previous += alpha * (value - previous)
            self.samples[index] = previous
        return self

    def highpass(self, cutoff):
        """Strips rumble and any DC offset, which otherwise eats headroom."""
        if cutoff <= 0:
            return self
        dt = 1.0 / SAMPLE_RATE
        rc = 1.0 / (2.0 * math.pi * cutoff)
        alpha = rc / (rc + dt)
        result = [0.0] * len(self.samples)
        previous_in = previous_out = 0.0
        for index, value in enumerate(self.samples):
            previous_out = alpha * (previous_out + value - previous_in)
            previous_in = value
            result[index] = previous_out
        self.samples = result
        return self

    def drive(self, amount=2.0):
        """Soft saturation. Thickens a thin tone without the crackle of clipping."""
        if amount <= 0:
            return self
        scale = math.tanh(amount)
        self.samples = [math.tanh(value * amount) / scale for value in self.samples]
        return self

    def crush(self, bits=8):
        """Quantise to fewer bits, for deliberate 8-bit grit."""
        levels = 2 ** bits
        self.samples = [round(value * levels) / levels for value in self.samples]
        return self

    def echo(self, delay=0.08, feedback=0.35, taps=4):
        """Cheap reverb: a few decaying repeats. Adds space to a dry blip."""
        source = list(self.samples)
        gain = feedback
        for tap in range(1, taps + 1):
            self.mix(Clip(source), at=delay * tap, gain=gain)
            gain *= feedback
        return self

    def reverse(self):
        self.samples.reverse()
        return self

    # -- output --

    def to_bytes(self):
        """Pack to 16-bit PCM, clamping rather than wrapping.

        Overflow in a signed 16-bit int wraps a loud positive peak to a loud
        negative one, which is the loudest possible click. Clamping just
        flattens the peak.
        """
        frames = bytearray()
        for value in self.samples:
            clamped = max(-1.0, min(1.0, value))
            frames += struct.pack("<h", int(clamped * 32767))
        return bytes(frames)

    def save(self, path):
        with wave.open(path, "wb") as handle:
            handle.setnchannels(CHANNELS)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(self.to_bytes())
        return path

    @property
    def duration(self):
        return len(self.samples) / SAMPLE_RATE


# --- helpers used by the recipes -------------------------------------------

def layer(*clips):
    """Sum clips that all start together, keeping the longest tail."""
    result = Clip()
    for clip in clips:
        result.mix(clip)
    return result


def chord(duration, freqs, wave=sine, env=None, gain=1.0):
    return layer(*(Clip.tone(duration, freq, wave, env, gain / len(freqs))
                   for freq in freqs))


def arpeggio(freqs, note_length=0.06, wave=square(0.5), env=None, gain=1.0, overlap=0.5):
    """Notes in sequence, each overlapping the last so it reads as one gesture.

    The length parameter is ``note_length`` rather than ``note`` so it does not
    shadow the ``note()`` name lookup below — callers pass both together.
    """
    envelope = env if env is not None else perc(0.02, 5.0)
    result = Clip()
    for index, freq in enumerate(freqs):
        result.mix(Clip.tone(note_length * (1.0 + overlap), freq, wave, envelope, gain),
                   at=note_length * index)
    return result


# Equal temperament from A4 = 440. Names are parsed as e.g. "C4", "F#3", "Bb5".
_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note(name):
    """Frequency of a note name. ``note("A4") == 440``."""
    letter = name[0].upper()
    if letter not in _SEMITONES:
        raise ValueError(f"unknown note {name!r}")
    semitone = _SEMITONES[letter]
    index = 1
    while index < len(name) and name[index] in "#b":
        semitone += 1 if name[index] == "#" else -1
        index += 1
    octave = int(name[index:])
    return 440.0 * 2.0 ** ((semitone - 9) / 12.0 + (octave - 4))
