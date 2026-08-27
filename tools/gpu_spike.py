"""Measure what moving sprite drawing onto the GPU would actually buy.

    python tools/gpu_spike.py

Porting the renderer to SDL2's ``Texture``/``Renderer`` is not a small change.
It replaces the display Surface outright, so every ``blit``, every
``pygame.draw.circle`` and every font render in the game has to change with it —
around 2,000 lines across six modules, all of it drawing code with no test
coverage that a screenshot would not catch. That is worth doing if the payoff is
large and worth skipping if it is not, and the only honest way to tell the
difference is to measure the payoff before paying the cost.

So this draws the same number of sprites both ways and reports the crossover:
how many sprites the CPU path handles before the GPU path pulls ahead, and by
how much at the counts this game actually reaches.

It deliberately measures the *best case* for the GPU. Real drawing here also
includes per-frame circles, rectangles, health bars and text, some of which have
no direct texture equivalent and would need rebuilding rather than porting.
Whatever number comes out is therefore an upper bound on the win.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

SCREEN_WIDTH, SCREEN_HEIGHT = 1280, 720
COUNTS = (250, 500, 1000, 2000, 4000)
FRAMES = 200


def positions(count):
    """Deterministic scatter, so both paths draw the same layout."""
    return [((index * 137) % (SCREEN_WIDTH - 40), (index * 89) % (SCREEN_HEIGHT - 40))
            for index in range(count)]


def make_sprite():
    sprite = pygame.Surface((40, 40), pygame.SRCALPHA)
    pygame.draw.circle(sprite, (200, 90, 90, 255), (20, 20), 18)
    pygame.draw.circle(sprite, (250, 200, 200, 255), (14, 14), 6)
    return sprite


def bench_surface(count):
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.HIDDEN)
    sprite = make_sprite().convert_alpha()
    spots = positions(count)
    times = []
    for _ in range(FRAMES):
        start = time.perf_counter()
        screen.fill((10, 10, 22))
        blit = screen.blit
        for spot in spots:
            blit(sprite, spot)
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def bench_gpu(count):
    from pygame._sdl2 import video

    window = video.Window("spike", size=(SCREEN_WIDTH, SCREEN_HEIGHT), hidden=True)
    renderer = video.Renderer(window)
    texture = video.Texture.from_surface(renderer, make_sprite())
    spots = [pygame.Rect(x, y, 40, 40) for x, y in positions(count)]
    times = []
    for _ in range(FRAMES):
        start = time.perf_counter()
        renderer.draw_color = (10, 10, 22, 255)
        renderer.clear()
        for spot in spots:
            texture.draw(dstrect=spot)
        renderer.present()
        times.append((time.perf_counter() - start) * 1000)
    window.destroy()
    return statistics.median(times)


def main():
    pygame.init()
    print(f"  {FRAMES} frames per measurement, {SCREEN_WIDTH}x{SCREEN_HEIGHT}\n")
    print(f"  {'sprites':>8}{'surface':>11}{'gpu':>10}{'speedup':>10}   verdict")
    for count in COUNTS:
        cpu = bench_surface(count)
        pygame.display.quit()
        try:
            gpu = bench_gpu(count)
        except Exception as exc:                     # noqa: BLE001 - spike tool
            print(f"  {count:>8}{cpu:>11.2f}   GPU path unavailable: {exc}")
            continue
        ratio = cpu / gpu if gpu else 0.0
        verdict = "GPU ahead" if ratio > 1.15 else ("even" if ratio > 0.87 else "CPU ahead")
        print(f"  {count:>8}{cpu:>11.2f}{gpu:>10.2f}{ratio:>9.2f}x   {verdict}")
    pygame.quit()


if __name__ == "__main__":
    main()
