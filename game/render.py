"""Drawing through a backend, so the world layer can run on the GPU.

Everything that draws the world talks to a ``Painter`` instead of calling
``surface.blit`` and ``pygame.draw.*`` directly. Two backends implement it:
``SoftwarePainter`` forwards straight to pygame and is the behaviour the game
has always had, while ``GpuPainter`` submits to SDL2's ``Renderer``.

**Read the measurements before trusting the idea.** Blitting is CPU memory
traffic, so moving it to the GPU sounds like a clear win, and an idealised
benchmark agrees enthusiastically — ``tools/gpu_spike.py`` reports 12-22x for one
texture drawn repeatedly with no state changes. That number does not survive
contact with a real frame:

* A mixed workload (several sprites, per-sprite tint for hit flashes, health
  bars, occasional circles) measures **2.25x**, because changing tint or blend
  between draws breaks batching.
* The UI cannot follow. SDL2's renderer has no rounded rectangle and no text, so
  the HUD keeps drawing with pygame onto an offscreen surface that has to be
  uploaded every frame — **about 1ms**, charged whether the HUD changed or not.
* The abstraction itself costs. Every sprite that used to be one ``blit`` call
  became a dict lookup, three property setters, a ``get_alpha``, a ``get_size``
  and a ``Rect`` construction. The first working version of this backend was
  *slower than software*, and only became competitive after the fast path in
  ``blit`` cut that per-sprite Python work back down.

**The crossover, measured.** Drawing the same scene both ways at increasing
enemy counts:

===========  ==========  ======  =========
enemies      software    GPU     winner
===========  ==========  ======  =========
100          1.41ms      3.18ms  software
250          1.79ms      3.18ms  software
500          2.42ms      3.46ms  software
1000         3.64ms      3.91ms  software
2000         6.04ms      5.06ms  GPU
===========  ==========  ======  =========

The GPU path does not pay for itself until roughly 1,200-1,500 sprites, and
``MAX_ENEMIES`` is 280 — where software is about 1.8x faster. It has a fixed
overhead of about 3ms (the UI upload plus per-draw state) that barely grows with
the scene, while software grows linearly; that is exactly the shape you would
expect, and it is why the GPU eventually wins and why it loses today.

So **software is the default** and ``--gpu`` opts in. The backend is kept, not
deleted: it is correct, pixel-diffed against software, and it is the answer the
day ``MAX_ENEMIES`` goes up by a factor of five.

**Why the software path stays.** It is the reference implementation: the GPU
output is pixel-diffed against it, which is how the hit-flash alpha bug in
``blit`` was found. It is the fallback when SDL2's renderer misbehaves on
someone else's machine, which matters once this ships as an .exe. And headless
tooling needs no GPU context at all.
"""

import pygame

from . import assets

# Circle art is generated at this size and scaled to whatever radius is asked
# for. Big enough that shrinking stays smooth, small enough to upload once.
CIRCLE_SOURCE = 128


class Painter:
    """The drawing surface, as the game sees it.

    Deliberately mirrors the pygame calls it replaces — ``circle(color, center,
    radius)`` rather than a scene graph — so converting a draw method is a
    mechanical edit and the diffs stay readable.
    """

    def blit(self, image, dest, area=None, flags=0, dynamic=False):
        raise NotImplementedError

    def circle(self, color, center, radius, width=0):
        raise NotImplementedError

    def rect(self, color, rect, width=0):
        raise NotImplementedError

    def line(self, color, start, end, width=1):
        raise NotImplementedError

    def lines(self, color, closed, points, width=1):
        for index in range(len(points) - 1):
            self.line(color, points[index], points[index + 1], width)
        if closed and len(points) > 2:
            self.line(color, points[-1], points[0], width)

    def polygon(self, color, points, width=0):
        raise NotImplementedError

    def fill(self, color):
        raise NotImplementedError

    def ui_target(self):
        """A surface for the HUD and menus to draw on with plain pygame.

        Called exactly once per frame: the GPU implementation clears it, so a
        second call mid-frame would wipe what was just drawn.
        """
        raise NotImplementedError

    def flush_ui(self):
        """Composite whatever was drawn on ``ui_target`` over the frame."""

    def present(self):
        raise NotImplementedError

    def to_surface(self):
        """The frame as a Surface, for screenshots and pixel diffing."""
        raise NotImplementedError


class SoftwarePainter(Painter):
    """Straight passthrough to pygame. The reference behaviour."""

    def __init__(self, surface):
        self.surface = surface

    @property
    def size(self):
        return self.surface.get_size()

    def blit(self, image, dest, area=None, flags=0, dynamic=False):
        self.surface.blit(image, dest, area, flags)

    def circle(self, color, center, radius, width=0):
        pygame.draw.circle(self.surface, color, (int(center[0]), int(center[1])),
                           int(radius), int(width))

    def rect(self, color, rect, width=0):
        pygame.draw.rect(self.surface, color, rect, int(width))

    def line(self, color, start, end, width=1):
        pygame.draw.line(self.surface, color, start, end, int(width))

    def lines(self, color, closed, points, width=1):
        if len(points) > 1:
            pygame.draw.lines(self.surface, color, closed, points, int(width))

    def polygon(self, color, points, width=0):
        pygame.draw.polygon(self.surface, color, points, int(width))

    def fill(self, color):
        self.surface.fill(color)

    def ui_target(self):
        # The screen itself — the UI already draws exactly where it lands.
        return self.surface

    def present(self):
        pygame.display.flip()

    def to_surface(self):
        return self.surface.copy()


class GpuPainter(Painter):
    """Draws through SDL2's Renderer."""

    def __init__(self, renderer, size):
        from pygame._sdl2 import video

        self._video = video
        self.renderer = renderer
        self._size = size
        self._cache = {}
        self._rings = {}
        self._ui_surface = None
        self._ui_texture = None

        # One white pixel, stretched and tinted, serves every filled rectangle.
        pixel = pygame.Surface((2, 2))
        pixel.fill((255, 255, 255))
        self._pixel = video.Texture.from_surface(renderer, pixel)

        disc = pygame.Surface((CIRCLE_SOURCE, CIRCLE_SOURCE), pygame.SRCALPHA)
        pygame.draw.circle(disc, (255, 255, 255, 255),
                           (CIRCLE_SOURCE // 2, CIRCLE_SOURCE // 2), CIRCLE_SOURCE // 2)
        self._disc = video.Texture.from_surface(renderer, disc)

        # Textures are tied to this renderer; ``load_images`` empties the cache
        # when the context is rebuilt.
        assets.register_cache(self._cache)

    @property
    def size(self):
        return self._size

    # -- texture cache -------------------------------------------------------

    def _entry(self, surface):
        """``[surface, texture, width, height, colour, alpha, blend]``.

        Uploading costs real time, so anything drawn repeatedly is uploaded once
        and kept — that is the entire source of any speedup, and a miss per
        sprite per frame would make this slower than software.

        The record holds the surface itself, not just its id. Keyed on ``id``
        alone, a collected surface could have its address reused by a new one
        and the cache would hand back a texture of the wrong picture — sprites
        wearing each other's art, and only under memory pressure.

        The last three fields mirror the GPU state currently set on the texture.
        SDL keeps colour, alpha and blend per texture, so tracking them here lets
        ``blit`` skip the setter when nothing changed, which is the common case:
        most sprites draw untinted and opaque.
        """
        key = id(surface)
        entry = self._cache.get(key)
        if entry is None or entry[0] is not surface:
            width, height = surface.get_size()
            entry = [surface,
                     self._video.Texture.from_surface(self.renderer, surface),
                     width, height, (255, 255, 255), 255, pygame.BLENDMODE_BLEND]
            self._cache[key] = entry
        return entry

    def _ring(self, radius, width):
        """An outline circle cannot be a scaled disc — scaling would thicken the
        line with it, so a thin ring at a large radius would come out fat. Each
        (radius, width) pair gets its own texture; the game uses few enough
        distinct pairs for that to stay small."""
        key = (int(radius), int(width))
        texture = self._rings.get(key)
        if texture is None:
            size = max(2, int(radius) * 2 + int(width) * 2 + 2)
            surface = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(surface, (255, 255, 255, 255),
                               (size // 2, size // 2), int(radius), int(width))
            texture = self._video.Texture.from_surface(self.renderer, surface)
            self._rings[key] = texture
        return texture

    # -- drawing -------------------------------------------------------------

    def blit(self, image, dest, area=None, flags=0, dynamic=False):
        blend = (pygame.BLENDMODE_ADD if flags & pygame.BLEND_RGB_ADD
                 else pygame.BLENDMODE_BLEND)

        if dynamic:
            # Rebuilt every frame (the scratch buffers weapons use for additive
            # shapes), so caching would grow without limit.
            texture = self._video.Texture.from_surface(self.renderer, image)
            texture.blend_mode = blend
            width, height = image.get_size()
            texture.draw(dstrect=pygame.Rect(int(dest[0]), int(dest[1]), width, height))
            return

        entry = self._entry(image)
        texture = entry[1]

        # Surface-level alpha is read every call rather than baked into the
        # cached texture, because callers set it per frame on a *shared*
        # surface: ``flash.set_alpha(...)`` on the cached hit-flash silhouette is
        # the clearest case, and a texture built once would freeze whatever
        # alpha happened to be set first.
        #
        # Ignoring it is worse, and was the bug this replaced — hit flashes drew
        # fully opaque, turning every struck enemy into a solid white block.
        # Nothing crashed and no test failed; it was caught by pixel-diffing
        # this backend against the software one.
        alpha = image.get_alpha()
        alpha = 255 if alpha is None else alpha
        if entry[5] != alpha:
            texture.alpha = alpha
            entry[5] = alpha
        if entry[6] != blend:
            texture.blend_mode = blend
            entry[6] = blend
        if entry[4] != (255, 255, 255):
            texture.color = (255, 255, 255)
            entry[4] = (255, 255, 255)

        if area is not None:
            source = pygame.Rect(area)
            texture.draw(srcrect=source,
                         dstrect=pygame.Rect(int(dest[0]), int(dest[1]),
                                             source.width, source.height))
        elif type(dest) is pygame.Rect:
            # Callers almost always pass ``image.get_rect(center=...)``, which is
            # already the right size — reusing it avoids building another Rect
            # for every sprite on screen.
            texture.draw(dstrect=dest)
        else:
            texture.draw(dstrect=pygame.Rect(int(dest[0]), int(dest[1]),
                                             entry[2], entry[3]))

    def circle(self, color, center, radius, width=0):
        radius = int(radius)
        if radius <= 0:
            return
        if width <= 0:
            texture = self._disc
            box = pygame.Rect(0, 0, radius * 2, radius * 2)
        else:
            texture = self._ring(radius, width)
            box = texture.get_rect()
        box.center = (int(center[0]), int(center[1]))
        texture.color = tuple(color[:3])
        texture.alpha = color[3] if len(color) > 3 else 255
        texture.blend_mode = pygame.BLENDMODE_BLEND
        texture.draw(dstrect=box)

    def rect(self, color, rect, width=0):
        box = pygame.Rect(rect)
        pixel = self._pixel
        pixel.color = tuple(color[:3])
        pixel.alpha = color[3] if len(color) > 3 else 255
        pixel.blend_mode = pygame.BLENDMODE_BLEND
        if width <= 0:
            pixel.draw(dstrect=box)
            return
        width = int(width)
        pixel.draw(dstrect=pygame.Rect(box.left, box.top, box.width, width))
        pixel.draw(dstrect=pygame.Rect(box.left, box.bottom - width, box.width, width))
        pixel.draw(dstrect=pygame.Rect(box.left, box.top, width, box.height))
        pixel.draw(dstrect=pygame.Rect(box.right - width, box.top, width, box.height))

    def line(self, color, start, end, width=1):
        self.renderer.draw_color = (*color[:3], color[3] if len(color) > 3 else 255)
        if width <= 1:
            self.renderer.draw_line((int(start[0]), int(start[1])),
                                    (int(end[0]), int(end[1])))
            return
        # No thick-line primitive; offset copies perpendicular to the run. Only
        # a handful of call sites ask for width > 1.
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = max(1e-6, (dx * dx + dy * dy) ** 0.5)
        nx, ny = -dy / length, dx / length
        for step in range(-int(width) // 2, int(width) // 2 + 1):
            self.renderer.draw_line(
                (int(start[0] + nx * step), int(start[1] + ny * step)),
                (int(end[0] + nx * step), int(end[1] + ny * step)))

    def polygon(self, color, points, width=0):
        """Rasterised on the CPU and uploaded.

        SDL2's renderer has no polygon primitive, and the game asks for one in
        exactly two places — the small off-screen direction markers. A
        triangulator would be far more machinery than two call sites justify.
        """
        xs = [int(p[0]) for p in points]
        ys = [int(p[1]) for p in points]
        left, top = min(xs), min(ys)
        scratch = pygame.Surface((max(2, max(xs) - left + 2),
                                  max(2, max(ys) - top + 2)), pygame.SRCALPHA)
        pygame.draw.polygon(scratch, color,
                            [(x - left, y - top) for x, y in zip(xs, ys)], int(width))
        self.blit(scratch, (left, top), dynamic=True)

    def fill(self, color):
        self.renderer.draw_color = (*color[:3], 255)
        self.renderer.clear()

    # -- the UI overlay ------------------------------------------------------

    def ui_target(self):
        if self._ui_surface is None:
            self._ui_surface = pygame.Surface(self._size, pygame.SRCALPHA)
        self._ui_surface.fill((0, 0, 0, 0))
        return self._ui_surface

    def flush_ui(self):
        """Upload the overlay and draw it over the world.

        A *streaming* texture updated in place, not a fresh one built from the
        surface each frame: measured at 0.54ms against 1.06ms. Handing back half
        a millisecond for one extra object is worth it on a 16.67ms budget.
        """
        if self._ui_surface is None:
            return
        if self._ui_texture is None:
            self._ui_texture = self._video.Texture(self.renderer, self._size,
                                                   streaming=True)
            self._ui_texture.blend_mode = pygame.BLENDMODE_BLEND
        self._ui_texture.update(self._ui_surface)
        self._ui_texture.draw(dstrect=pygame.Rect(0, 0, *self._size))

    def present(self):
        self.renderer.present()

    def to_surface(self):
        return self.renderer.to_surface()


def create(size, use_gpu=True, hidden=False):
    """Open a window and return ``(painter, display_surface_or_None)``.

    Falls back to software silently when the GPU path cannot start: a machine
    without a working accelerated renderer should get a running game, not a
    stack trace.
    """
    if use_gpu:
        try:
            from pygame._sdl2 import video

            window = video.Window("Project Tby", size=size, hidden=hidden)
            renderer = video.Renderer(window, accelerated=1)
            # No display mode exists on this path, so nothing can be converted
            # to match one — and nothing needs to be, since uploading to a
            # texture does its own conversion.
            assets.convert_enabled = False
            return GpuPainter(renderer, size), None
        except Exception:                    # noqa: BLE001 - any failure means software
            pass
    flags = pygame.HIDDEN if hidden else 0
    surface = pygame.display.set_mode(size, flags)
    assets.convert_enabled = True
    return SoftwarePainter(surface), surface
