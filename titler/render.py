"""Frame rendering with Pillow."""
from __future__ import annotations

import bisect
import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageOps

from .config import OVERLAY_ALIASES, ConfigError
from .fonts import load_font
from .units import UnitError, parse_length

_ANCHORS = {
    "top-left": (0.0, 0.0), "top-center": (0.5, 0.0), "top-right": (1.0, 0.0),
    "center-left": (0.0, 0.5), "center": (0.5, 0.5), "center-right": (1.0, 0.5),
    "bottom-left": (0.0, 1.0), "bottom-center": (0.5, 1.0), "bottom-right": (1.0, 1.0),
}


def _rgb(color, where):
    try:
        return ImageColor.getrgb(str(color))[:3]
    except ValueError as e:
        raise ConfigError(f"{where}: invalid color {color!r}") from e


class _TextElement:
    """A text block laid out at its final position, typed in progressively."""

    def __init__(self, spec: dict, slide: "SlideRenderer", index: int, start: float, rng: random.Random):
        where = f"slide {slide.name!r} text[{index}]"
        w, h, dpi = slide.width, slide.height, slide.dpi
        try:
            self.size_px = max(1, round(parse_length(spec["size"], h, dpi)))
            x = parse_length(spec["x"], w, dpi)
            y = parse_length(spec["y"], h, dpi)
        except UnitError as e:
            raise ConfigError(f"{where}: {e}") from e

        self.text = spec["text"]
        self.font = load_font(tuple(spec["font"]), self.size_px, slide.base_dir)
        self.color = _rgb(spec["color"], where)
        self.glow = spec["glow"]
        if self.glow:
            self.glow_color = _rgb(self.glow["color"] or spec["color"], where)
        self.cursor = spec["cursor"]
        if self.cursor:
            self.cursor_color = _rgb(self.cursor["color"] or spec["color"], where)

        anchor = str(spec["anchor"]).lower()
        if anchor not in _ANCHORS:
            raise ConfigError(f"{where}: invalid anchor {anchor!r}; use one of {list(_ANCHORS)}")
        align = str(spec["align"]).lower()
        if align not in ("left", "center", "right"):
            raise ConfigError(f"{where}: align must be left, center or right")

        # Layout uses the full text so letters never shift while being typed.
        ascent, descent = self.font.getmetrics()
        self.ascent, self.descent = ascent, descent
        line_h = (ascent + descent) * float(spec["line_spacing"])
        self.lines = self.text.split("\n")
        widths = [self.font.getlength(line) for line in self.lines]
        block_w = max(widths) if widths else 0
        block_h = ascent + descent + line_h * (len(self.lines) - 1)
        ax, ay = _ANCHORS[anchor]
        left, top = x - ax * block_w, y - ay * block_h
        factor = {"left": 0.0, "center": 0.5, "right": 1.0}[align]
        self.line_pos = [(left + factor * (block_w - lw), top + ascent + i * line_h)
                         for i, lw in enumerate(widths)]
        self.cursor_w = self.font.getlength("M") if self.cursor else 0

        pad = int(math.ceil(self.glow["radius"] * 3 if self.glow else 2)) + 2
        x0 = int(math.floor(min(px for px, _ in self.line_pos))) - pad
        y0 = int(math.floor(top)) - pad
        x1 = int(math.ceil(left + block_w + self.cursor_w)) + pad
        y1 = int(math.ceil(top + block_h)) + pad
        self.box = (max(0, x0), max(0, y0), min(w, x1), min(h, y1))

        # Per-keystroke timestamps (newlines count as keystrokes).
        speed = float(spec["speed"])
        jitter = float(spec["jitter"])
        line_pause = float(spec["line_pause"])
        self.start = start
        self.times = []
        t = start
        for ch in self.text:
            if speed > 0:
                t += (1.0 / speed) * (1.0 + jitter * (rng.random() * 2 - 1))
            self.times.append(t)
            if ch == "\n":
                t += line_pause
        self.end = self.times[-1] if self.times else start
        self._cache_key = None
        self._cache = None

    def chars_at(self, t: float) -> int:
        return bisect.bisect_right(self.times, t)

    def _caret(self, n: int) -> tuple[float, float]:
        typed = self.text[:n]
        line = typed.count("\n")
        lx, base = self.line_pos[line]
        return lx + self.font.getlength(typed.rsplit("\n", 1)[-1]), base

    def _draw_cursor(self, draw: ImageDraw.ImageDraw, n: int, ox: int, oy: int) -> None:
        cx, base = self._caret(n)
        cx, base = cx - ox, base - oy
        style = self.cursor["style"]
        if style == "underscore":
            th = max(2, round(self.size_px * 0.08))
            draw.rectangle([cx, base + 1, cx + self.cursor_w, base + 1 + th], fill=255)
        elif style == "bar":
            th = max(2, round(self.size_px * 0.07))
            draw.rectangle([cx, base - self.ascent, cx + th, base + self.descent], fill=255)
        else:
            draw.rectangle([cx, base - self.ascent * 0.85, cx + self.cursor_w * 0.9, base + self.descent * 0.6],
                           fill=255)

    def layers(self, n: int, cursor_on: bool):
        """Return (glow_rgb, text_mask, cursor_mask) cropped to ``self.box``; cached per state."""
        key = (n, cursor_on)
        if key == self._cache_key:
            return self._cache
        x0, y0, x1, y1 = self.box
        size = (max(1, x1 - x0), max(1, y1 - y0))
        text_mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(text_mask)
        typed = self.text[:n]
        for i, part in enumerate(typed.split("\n")):
            if part:
                lx, base = self.line_pos[i]
                draw.text((lx - x0, base - y0), part, font=self.font, fill=255, anchor="ls")
        cursor_mask = None
        if cursor_on:
            cursor_mask = Image.new("L", size, 0)
            self._draw_cursor(ImageDraw.Draw(cursor_mask), n, x0, y0)

        glow_rgb = None
        if self.glow:
            src = ImageChops.lighter(text_mask, cursor_mask) if cursor_mask else text_mask
            blurred = src.filter(ImageFilter.GaussianBlur(float(self.glow["radius"])))
            strength = float(self.glow["strength"])
            blurred = blurred.point(lambda v: min(255, int(v * strength)))
            glow_rgb = Image.merge("RGB", [blurred.point(lambda v, c=c: v * c // 255) for c in self.glow_color])

        self._cache_key, self._cache = key, (glow_rgb, text_mask, cursor_mask)
        return self._cache

    def composite(self, frame: Image.Image, n: int, cursor_on: bool) -> None:
        if n == 0 and not cursor_on:
            return
        glow_rgb, text_mask, cursor_mask = self.layers(n, cursor_on)
        x0, y0, x1, y1 = self.box
        if x1 <= x0 or y1 <= y0:
            return
        region = frame.crop(self.box)
        if glow_rgb is not None:
            region = ImageChops.screen(region, glow_rgb)
        region.paste(self.color, (0, 0), text_mask)
        if cursor_mask is not None:
            region.paste(self.cursor_color, (0, 0), cursor_mask)
        frame.paste(region, (x0, y0))


class SlideRenderer:
    def __init__(self, slide: dict, video: dict, base_dir: str):
        self.name = slide["name"]
        self.width, self.height = int(video["width"]), int(video["height"])
        self.fps = float(video["fps"])
        self.dpi = float(video["dpi"])
        self.base_dir = base_dir
        self.fade_in, self.fade_out = slide["fade_in"], slide["fade_out"]
        self.effects = slide["effects"]
        self.seed = slide["seed"]

        rng = random.Random(f"{self.name}:{self.seed}")
        self.elements: list[_TextElement] = []
        prev_end = 0.0
        for i, spec in enumerate(slide["texts"]):
            start = spec["start"]
            if start == "auto":
                start = (prev_end + float(spec["pause"])) if self.elements else float(spec["pause"])
            el = _TextElement(spec, self, i, float(start), rng)
            self.elements.append(el)
            prev_end = max(prev_end, el.end)

        typing_end = max((el.end for el in self.elements), default=0.0)
        if slide["duration"] == "auto":
            self.duration = typing_end + slide["hold"] + self.fade_out
        else:
            self.duration = float(slide["duration"])
            if typing_end > self.duration:
                import warnings
                warnings.warn(f"slide {self.name!r}: typing ends at {typing_end:.2f}s, "
                              f"after the slide duration {self.duration:.2f}s")
        self.frame_count = max(1, round(self.duration * self.fps))

        self.background = self._build_background(slide["background"])
        self.post = self._build_post()

    # --- static layers -------------------------------------------------------------
    def _len(self, value, ref, where):
        try:
            return parse_length(value, ref, self.dpi)
        except UnitError as e:
            raise ConfigError(f"slide {self.name!r} {where}: {e}") from e

    def _build_background(self, bg: dict) -> Image.Image:
        size = (self.width, self.height)
        frame = Image.new("RGB", size, _rgb(bg["color"], f"slide {self.name!r} background"))
        if bg.get("image"):
            path = Path(bg["image"])
            if not path.is_file():
                raise ConfigError(f"slide {self.name!r}: background image not found: {path}")
            img = Image.open(path).convert("RGB")
            fit = str(bg.get("fit", "cover")).lower()
            if fit == "cover":
                img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)
            elif fit == "contain":
                img = ImageOps.contain(img, size, Image.Resampling.LANCZOS)
            elif fit == "stretch":
                img = img.resize(size, Image.Resampling.LANCZOS)
            elif fit != "center":
                raise ConfigError(f"slide {self.name!r}: fit must be cover, contain, stretch or center")
            if float(bg.get("image_blur") or 0) > 0:
                img = img.filter(ImageFilter.GaussianBlur(float(bg["image_blur"])))
            layer = frame.copy()
            layer.paste(img, ((self.width - img.width) // 2, (self.height - img.height) // 2))
            frame = Image.blend(frame, layer, max(0.0, min(1.0, float(bg.get("image_opacity", 1.0)))))

        frame = frame.convert("RGBA")
        for i, ov in enumerate(bg.get("overlays") or []):
            frame = Image.alpha_composite(frame, self._overlay_layer(ov, f"overlays[{i}]"))
        return frame.convert("RGB")

    def _overlay_layer(self, ov: dict, where: str) -> Image.Image:
        w, h = self.width, self.height
        kind = OVERLAY_ALIASES[str(ov["type"]).lower()]
        opacity = max(0.0, min(1.0, float(ov.get("opacity", 1.0))))
        fill = ov.get("color")
        fill = (*_rgb(fill, where), 255) if fill else None
        outline = ov.get("outline")
        outline = (*_rgb(outline, where), 255) if outline else None
        outline_w = round(self._len(ov.get("outline_width", 2), w, where)) if outline else 0

        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        if kind == "rect":
            x = self._len(ov.get("x", 0), w, where)
            y = self._len(ov.get("y", 0), h, where)
            rw = self._len(ov.get("width", "100%"), w, where)
            rh = self._len(ov.get("height", "100%"), h, where)
            radius = self._len(ov.get("radius", 0), min(w, h), where)
            draw.rounded_rectangle([x, y, x + rw, y + rh], radius=radius, fill=fill,
                                   outline=outline, width=outline_w)
        else:
            cx = self._len(ov.get("x", "50%"), w, where)
            cy = self._len(ov.get("y", "50%"), h, where)
            r = self._len(ov.get("radius", "10%"), min(w, h), where)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=outline, width=outline_w)

        if float(ov.get("blur") or 0) > 0:
            layer = layer.filter(ImageFilter.GaussianBlur(float(ov["blur"])))
        if opacity < 1.0:
            layer.putalpha(layer.getchannel("A").point(lambda a: round(a * opacity)))
        return layer

    def _build_post(self) -> Image.Image | None:
        """Multiplicative layer applied on top of everything (scanlines + vignette)."""
        w, h = self.width, self.height
        mask = None
        sl = self.effects.get("scanlines")
        if sl:
            mask = Image.new("L", (w, h), 255)
            draw = ImageDraw.Draw(mask)
            dark = round(255 * (1 - float(sl["opacity"])))
            spacing, thick = max(2, int(sl["spacing"])), max(1, int(sl["thickness"]))
            for yy in range(0, h, spacing):
                draw.rectangle([0, yy, w, yy + thick - 1], fill=dark)
        vignette = float(self.effects.get("vignette") or 0)
        if vignette > 0:
            small = Image.new("L", (256, 256))
            px = small.load()
            for yy in range(256):
                for xx in range(256):
                    d = math.hypot((xx - 127.5) / 127.5, (yy - 127.5) / 127.5) / math.sqrt(2)
                    px[xx, yy] = round(255 * (1 - vignette * d ** 2))
            vig = small.resize((w, h), Image.Resampling.BILINEAR)
            mask = vig if mask is None else ImageChops.multiply(mask, vig)
        return Image.merge("RGB", [mask] * 3) if mask is not None else None

    # --- per frame -------------------------------------------------------------------
    def _cursor_owner(self, t: float):
        started = [el for el in self.elements if el.start <= t]
        return started[-1] if started else (self.elements[0] if self.elements else None)

    def render(self, frame_index: int) -> Image.Image:
        t = frame_index / self.fps
        frame = self.background.copy()

        owner = self._cursor_owner(t)
        for el in self.elements:
            n = el.chars_at(t)
            cursor_on = False
            if el is owner and el.cursor:
                typing = el.start <= t < el.end
                if typing and el.cursor["solid_while_typing"]:
                    cursor_on = True
                else:
                    interval = max(0.05, float(el.cursor["blink_interval"]))
                    cursor_on = int(t / interval) % 2 == 0
            el.composite(frame, n, cursor_on)

        if self.post is not None:
            frame = ImageChops.multiply(frame, self.post)

        level = 1.0
        flicker = float(self.effects.get("flicker") or 0)
        if flicker > 0:
            level *= 1.0 - flicker * random.Random(f"{self.seed}:{frame_index}").random()
        if self.fade_in > 0 and t < self.fade_in:
            level *= t / self.fade_in
        remaining = self.duration - t - 1.0 / self.fps
        if self.fade_out > 0 and remaining < self.fade_out:
            level *= max(0.0, remaining / self.fade_out)
        if level < 0.999:
            frame = frame.point(lambda v: int(v * level))
        return frame
