"""Measure what the game actually sounds like during combat.

    python tools/audio_mix_check.py            240 simulated seconds
    python tools/audio_mix_check.py --write    also save the busiest window

Rate limits are guesses until something checks them. A gap of 55ms per hit looks
reasonable in a table, but twenty overlapping copies a second of a sound with a
long tail is a wall of mush, and the table cannot tell you that.

So: run a real simulated run, record every cue the game asks for against
*simulated* time, replay the actual waveforms through the actual gate, and
measure the result. Three numbers matter.

**Clipped fraction** — how much of the mix exceeds full scale. Anything above a
hair here is audible distortion during exactly the busiest moments.

**Crest factor**, peak over RMS. High means transients still poke out of the
mix, which is what makes individual hits legible. As it falls toward 1 the sound
is becoming a constant wall, which is the failure mode gating exists to prevent.

**Concurrency** — how many sounds overlap at the peak. If that approaches the
channel count, cues are being dropped by exhaustion rather than by policy, and
the policy is what decides *which* ones get dropped.

Simulated time is essential: a 240-second run finishes in about ten wall
seconds, so gating against the wall clock would suppress nearly everything and
report a mix far cleaner than a player would ever hear.
"""

import argparse
import os
import sys
import wave
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from synth import SAMPLE_RATE, Clip                     # noqa: E402
from game import audio                                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_wav(path):
    with wave.open(path, "rb") as handle:
        count = handle.getnframes()
        raw = handle.readframes(count)
    return [value / 32767.0 for value in struct.unpack(f"<{count}h", raw)]


def collect(duration, seed, weapon):
    """Run the game and return the cue events the gate would let through."""
    import main

    events = []
    clock = {"t": 0.0}
    audio.set_clock(lambda: clock["t"])

    from game.world import World
    original_update = World.update

    def timed_update(self, dt, move_input, interact=False):
        clock["t"] = self.director.elapsed
        return original_update(self, dt, move_input, interact)

    World.update = timed_update

    # Stand in for the mixer: apply the real gate, record what survives. The
    # device itself is never opened, so this runs anywhere.
    accepted = []
    real_play = audio.play

    def recording_play(name, volume=1.0):
        cue = audio.CUES.get(name)
        if cue is None:
            return False
        now = clock["t"]
        last = _last.get(name, -999.0)
        if now - last < cue.gap:
            return False
        _last[name] = now
        accepted.append((now, name, volume))
        return True

    _last = {}
    audio.play = recording_play
    try:
        main.smoke(duration, seed=seed, verbose=False, immortal=True, weapon=weapon)
    finally:
        audio.play = real_play
        World.update = original_update
        audio.set_clock(None)
    events.extend(accepted)
    return events


def render(events, start, length):
    """Mix the real waveforms for a window of the timeline.

    Rendered at the loudest the game can be: the slider at maximum, scaled
    by the master headroom. Measuring at the default setting instead would
    hide clipping that any player who turns it up would hear.
    """
    cache = {}
    sfx_dir = os.path.join(ROOT, "assets", "sfx")
    variants = {}
    for filename in sorted(os.listdir(sfx_dir)):
        if not filename.endswith(".wav"):
            continue
        name = filename[:-4]
        stem = name.rsplit("_", 1)[0]
        cue = stem if (stem in audio.CUES and name[-1].isdigit()) else name
        variants.setdefault(cue, []).append(os.path.join(sfx_dir, filename))

    track = Clip([0.0] * int(length * SAMPLE_RATE))
    counter = {}
    concurrent = []
    for when, name, volume in events:
        if not (start <= when < start + length):
            continue
        paths = variants.get(name)
        if not paths:
            continue
        index = counter.get(name, 0)
        counter[name] = index + 1
        path = paths[index % len(paths)]
        if path not in cache:
            cache[path] = load_wav(path)
        samples = cache[path]
        offset = int((when - start) * SAMPLE_RATE)
        for i, value in enumerate(samples):
            position = offset + i
            if position >= len(track.samples):
                break
            track.samples[position] += value * volume * audio.MASTER_SFX
        concurrent.append((when, len(samples) / SAMPLE_RATE))
    return track, concurrent


def peak_concurrency(concurrent):
    """Most sounds sounding at once, from start/end events."""
    edges = []
    for start, length in concurrent:
        edges.append((start, 1))
        edges.append((start + length, -1))
    edges.sort()
    current = best = 0
    for _, delta in edges:
        current += delta
        best = max(best, current)
    return best


def busiest_window(events, length, total):
    """Find the densest window — the mix is only in danger at its worst moment."""
    if not events:
        return 0.0
    best_start, best_count = 0.0, -1
    step = 1.0
    start = 0.0
    while start + length <= total:
        count = sum(1 for when, _, _ in events if start <= when < start + length)
        if count > best_count:
            best_start, best_count = start, count
        start += step
    return best_start


def main_cli():
    parser = argparse.ArgumentParser(description="Measure the combat audio mix.")
    parser.add_argument("--duration", type=int, default=240)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--weapon", default=None)
    parser.add_argument("--window", type=float, default=10.0)
    parser.add_argument("--write", action="store_true",
                        help="save the busiest window as a wav for listening")
    args = parser.parse_args()

    events = collect(args.duration, args.seed, args.weapon)
    print(f"{len(events)} cues passed the gate over {args.duration}s "
          f"({len(events) / args.duration:.1f}/s average)")

    start = busiest_window(events, args.window, args.duration)
    track, concurrent = render(events, start, args.window)
    window_events = len(concurrent)

    peak = track.peak()
    rms = track.rms()
    clipped = sum(1 for value in track.samples if abs(value) > 1.0)
    overlap = peak_concurrency(concurrent)

    print(f"\nbusiest {args.window:.0f}s window starts at {start:.0f}s "
          f"({window_events} cues, {window_events / args.window:.1f}/s)")
    print(f"  peak            {peak:.3f}   {'CLIPPING' if peak > 1.0 else 'ok'}")
    print(f"  rms             {rms:.3f}")
    print(f"  crest factor    {peak / rms if rms else 0:.1f}x   "
          f"{'(transients still read)' if rms and peak / rms > 4 else '(mix is flattening)'}")
    print(f"  clipped samples {clipped} ({clipped / max(1, len(track.samples)) * 100:.4f}%)")
    print(f"  peak overlap    {overlap} sounds at once "
          f"(of {audio.CHANNELS} channels)")

    counts = {}
    for _, name, _ in events:
        counts[name] = counts.get(name, 0) + 1
    print(f"\n{'cue':<14}{'played':>9}{'per sec':>10}")
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"{name:<14}{count:>9}{count / args.duration:>10.1f}")

    if args.write:
        # Not into assets/ — that directory is the game's content, and a
        # diagnostic render is not content.
        out = os.path.join(ROOT, "audio_mix_sample.wav")
        Clip(list(track.samples)).save(out)
        print(f"\nwrote {os.path.relpath(out, ROOT)} — the busiest window, as heard")


if __name__ == "__main__":
    main_cli()
