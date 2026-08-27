"""Transient visual feedback: floating damage numbers and hit particles.

None of this affects simulation state — it exists purely so that hitting things
feels like hitting things.
"""

import random

import pygame

from . import assets
from .config import COL_CRIT, COL_DAMAGE, COL_GOLD, COL_HEAL


class FloatingText:
    __slots__ = ("pos", "vel", "text", "color", "life", "max_life", "size")

    def __init__(self, pos, text, color, size=24, rise=70.0, life=0.75):
        self.pos = pygame.Vector2(pos)
        self.vel = pygame.Vector2(random.uniform(-22, 22), -rise)
        self.text = text
        self.color = color
        self.life = life
        self.max_life = life
        self.size = size

    def update(self, dt):
        self.pos += self.vel * dt
        self.vel.y += 130 * dt          # gentle arc back down
        self.life -= dt
        return self.life > 0

    def draw(self, painter, camera):
        alpha = max(0.0, min(1.0, self.life / self.max_life))
        font = assets.get_font(self.size, bold=True)
        label = font.render(self.text, True, self.color)
        label.set_alpha(int(255 * alpha))
        painter.blit(label, label.get_rect(center=camera.to_screen(self.pos)))


class Particle:
    __slots__ = ("pos", "vel", "color", "life", "max_life", "radius", "drag")

    def __init__(self, pos, vel, color, life, radius, drag=2.6):
        self.pos = pygame.Vector2(pos)
        self.vel = pygame.Vector2(vel)
        self.color = color
        self.life = life
        self.max_life = life
        self.radius = radius
        self.drag = drag

    def update(self, dt):
        self.pos += self.vel * dt
        self.vel *= max(0.0, 1.0 - self.drag * dt)
        self.life -= dt
        return self.life > 0

    def draw(self, painter, camera):
        fade = max(0.0, self.life / self.max_life)
        radius = max(1, int(self.radius * fade))
        sx, sy = camera.to_screen(self.pos)
        painter.circle(self.color, (int(sx), int(sy)), radius)


class EffectSystem:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.texts = []
        self.particles = []
        self.beams = []          # [start, end, color, life, max_life, width]
        self.rings = []          # [pos, radius, color, life, max_life]

    def clear(self):
        self.texts.clear()
        self.particles.clear()
        self.beams.clear()
        self.rings.clear()

    # -- spawners ------------------------------------------------------------
    def damage_number(self, pos, amount, crit=False):
        # Skip trivial numbers so the screen stays readable when 200 enemies die.
        if amount < 1:
            return
        self.texts.append(
            FloatingText(
                pos,
                str(int(amount)),
                COL_CRIT if crit else COL_DAMAGE,
                size=30 if crit else 22,
                rise=95 if crit else 70,
            )
        )

    def notice(self, pos, text, color=COL_GOLD, size=26):
        self.texts.append(FloatingText(pos, text, color, size=size, life=1.1))

    def heal_number(self, pos, amount):
        self.texts.append(FloatingText(pos, f"+{int(amount)}", COL_HEAL, size=22))

    def burst(self, pos, color, count=8, speed=190.0, life=0.35, radius=4):
        for _ in range(count):
            angle = self.rng.uniform(0, 6.28318)
            magnitude = self.rng.uniform(speed * 0.35, speed)
            vel = pygame.Vector2(magnitude, 0).rotate_rad(angle)
            self.particles.append(
                Particle(pos, vel, color, self.rng.uniform(life * 0.6, life), radius)
            )

    def beam(self, start, end, color=(150, 220, 255), life=0.14, width=3):
        self.beams.append([pygame.Vector2(start), pygame.Vector2(end), color, life, life, width])

    def shockwave(self, pos, radius, color=(255, 160, 70), life=0.26):
        """An expanding ring, so a blast reads at its true radius."""
        self.rings.append([pygame.Vector2(pos), radius, color, life, life])

    # -- lifecycle -----------------------------------------------------------
    def update(self, dt):
        self.texts = [t for t in self.texts if t.update(dt)]
        self.particles = [p for p in self.particles if p.update(dt)]
        for beam in self.beams:
            beam[3] -= dt
        self.beams = [b for b in self.beams if b[3] > 0]
        for ring in self.rings:
            ring[3] -= dt
        self.rings = [r for r in self.rings if r[3] > 0]

    def draw(self, painter, camera):
        for pos, radius, color, life, max_life in self.rings:
            progress = 1.0 - life / max_life
            current = int(radius * (0.35 + 0.65 * progress))
            width = max(1, int(5 * (1.0 - progress)))
            if current > width:
                sx, sy = camera.to_screen(pos)
                faded = tuple(int(c * (1.0 - progress * 0.8)) for c in color)
                painter.circle(faded, (int(sx), int(sy)), current, width)

        for beam in self.beams:
            start, end, color, life, max_life, width = beam
            fade = max(0.0, life / max_life)
            painter.line(
                tuple(int(c * fade + 20 * (1 - fade)) for c in color),
                camera.to_screen(start),
                camera.to_screen(end),
                max(1, int(width * fade)),
            )
        for particle in self.particles:
            particle.draw(painter, camera)
        for text in self.texts:
            text.draw(painter, camera)
