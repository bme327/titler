"""Loading, validation and theme resolution of title configs."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

BUILTIN_THEMES_FILE = Path(__file__).parent / "themes" / "builtin.yaml"


class ConfigError(ValueError):
    pass


VIDEO_DEFAULTS = {
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "dpi": 96,        # used to convert "pt" to pixels (1pt = dpi/72 px)
    "crf": 18,        # x264 quality, lower = better
    "preset": "medium",
}

GLOW_DEFAULTS = {"color": None, "radius": 10, "strength": 1.5}
CURSOR_DEFAULTS = {"style": "block", "color": None, "blink_interval": 0.5, "solid_while_typing": True}
SCANLINES_DEFAULTS = {"spacing": 4, "thickness": 1, "opacity": 0.2}

STYLE_DEFAULTS = {
    "duration": "auto",   # seconds, or "auto" = when typing ends + hold
    "hold": 2.0,
    "fade_in": 0.0,
    "fade_out": 0.0,
    "background": {
        "color": "#000000",
        "image": None,
        "fit": "cover",
        "image_opacity": 1.0,
        "image_blur": 0,
        "overlays": [],
    },
    "text": {
        "x": "10%",
        "y": "10%",
        "anchor": "top-left",
        "align": "left",
        "font": ["DejaVuSans.ttf", "arial.ttf", "Arial", "Helvetica"],
        "size": "48pt",
        "color": "#ffffff",
        "line_spacing": 1.2,
        "speed": 20,          # characters per second; 0 = appear instantly
        "start": "auto",      # seconds from slide start, or "auto" = after previous text + pause
        "pause": 0.4,
        "line_pause": 0.0,
        "jitter": 0.0,        # 0..1 random variation of keystroke timing
        "glow": False,
        "cursor": False,
    },
    "effects": {
        "scanlines": False,
        "vignette": 0.0,
        "flicker": 0.0,
    },
}

TOP_KEYS = {"output_dir", "video", "themes", "theme", "defaults", "slides"}
STYLE_KEYS = set(STYLE_DEFAULTS)
THEME_KEYS = STYLE_KEYS | {"extends", "description"}
SLIDE_KEYS = STYLE_KEYS | {"name", "theme", "texts", "seed"}
BACKGROUND_KEYS = set(STYLE_DEFAULTS["background"])
TEXT_STYLE_KEYS = set(STYLE_DEFAULTS["text"])
TEXT_KEYS = TEXT_STYLE_KEYS | {"text"}
EFFECTS_KEYS = set(STYLE_DEFAULTS["effects"])
OVERLAY_KEYS = {
    "rect": {"type", "x", "y", "width", "height", "radius", "color", "opacity",
             "outline", "outline_width", "blur"},
    "circle": {"type", "x", "y", "radius", "color", "opacity", "outline", "outline_width", "blur"},
}
OVERLAY_ALIASES = {"rect": "rect", "rectangle": "rect", "rounded_rect": "rect",
                   "rounded_rectangle": "rect", "circle": "circle"}
SUB_DEFAULTS = {"glow": GLOW_DEFAULTS, "cursor": CURSOR_DEFAULTS, "scanlines": SCANLINES_DEFAULTS}


def deep_merge(base, override):
    """Recursively merge dicts; non-dict values (including lists) in ``override`` replace ``base``."""
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = deep_merge(base.get(k), v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(override)


def _check_keys(data, allowed, where):
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: expected a mapping, got {type(data).__name__}")
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}")


def _check_style(style, allowed, where):
    _check_keys(style, allowed, where)
    if "background" in style:
        bg = style["background"]
        _check_keys(bg, BACKGROUND_KEYS, f"{where}.background")
        for i, ov in enumerate(bg.get("overlays") or []):
            _check_overlay(ov, f"{where}.background.overlays[{i}]")
    if "text" in style:
        _check_keys(style["text"], TEXT_STYLE_KEYS, f"{where}.text")
    if "effects" in style:
        _check_keys(style["effects"], EFFECTS_KEYS, f"{where}.effects")


def _check_overlay(ov, where):
    if not isinstance(ov, dict) or "type" not in ov:
        raise ConfigError(f"{where}: overlay needs a 'type' (rect, rounded_rect or circle)")
    kind = OVERLAY_ALIASES.get(str(ov["type"]).lower())
    if kind is None:
        raise ConfigError(f"{where}: unknown overlay type {ov['type']!r}")
    _check_keys(ov, OVERLAY_KEYS[kind], where)


def _absolutize(style: dict, base_dir: Path) -> None:
    """Make relative image/font paths absolute w.r.t. the file they were defined in."""
    bg = style.get("background")
    if isinstance(bg, dict) and isinstance(bg.get("image"), str):
        p = Path(bg["image"]).expanduser()
        if not p.is_absolute():
            bg["image"] = str((base_dir / p).resolve())
    for holder in (style.get("text"), style):
        if isinstance(holder, dict) and "font" in holder:
            fonts = holder["font"] if isinstance(holder["font"], list) else [holder["font"]]
            resolved = []
            for f in fonts:
                p = base_dir / str(f)
                resolved.append(str(p.resolve()) if p.is_file() else str(f))
            holder["font"] = resolved


def load_file(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def load_themes(paths: list[Path]) -> dict:
    themes: dict = {}
    for path in paths:
        if not path.is_file():
            raise ConfigError(f"theme file not found: {path}")
        data = load_file(path) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"{path}: theme file must map theme names to definitions")
        for name, theme in data.items():
            where = f"{path.name}:{name}"
            theme = theme or {}
            _check_style(theme, THEME_KEYS, where)
            _absolutize(theme, path.parent)
            themes[name] = theme
    return themes


def resolve_theme(themes: dict, name: str, _chain=()) -> dict:
    if name not in themes:
        raise ConfigError(f"unknown theme {name!r}; available: {sorted(themes)}")
    if name in _chain:
        raise ConfigError(f"theme inheritance cycle: {' -> '.join(_chain + (name,))}")
    theme = dict(themes[name])
    parent = theme.pop("extends", None)
    theme.pop("description", None)
    if parent:
        return deep_merge(resolve_theme(themes, parent, _chain + (name,)), theme)
    return theme


def _normalize_sub(value, defaults):
    if value is None or value is False:
        return None
    if value is True:
        return dict(defaults)
    if isinstance(value, dict):
        return {**defaults, **value}
    raise ConfigError(f"expected true/false or a mapping, got {value!r}")


def load_config(path) -> dict:
    """Load a config file and return a fully resolved project description.

    Precedence (lowest to highest): built-in defaults < ``defaults`` < theme < slide < text element.
    """
    path = Path(path).resolve()
    base_dir = path.parent
    raw = load_file(path)
    _check_keys(raw, TOP_KEYS, path.name)
    if "output_dir" not in raw:
        raise ConfigError("'output_dir' is required")
    slides_raw = raw.get("slides")
    if not isinstance(slides_raw, list) or not slides_raw:
        raise ConfigError("'slides' must be a non-empty list")

    video = deep_merge(VIDEO_DEFAULTS, raw.get("video") or {})
    _check_keys(video, set(VIDEO_DEFAULTS), "video")
    if int(video["width"]) % 2 or int(video["height"]) % 2:
        raise ConfigError("video width and height must be even numbers (H.264 requirement)")

    theme_files = raw.get("themes") or []
    if isinstance(theme_files, str):
        theme_files = [theme_files]
    themes = load_themes([BUILTIN_THEMES_FILE] + [base_dir / p for p in theme_files])

    defaults = copy.deepcopy(raw.get("defaults") or {})
    _check_style(defaults, STYLE_KEYS, "defaults")
    _absolutize(defaults, base_dir)
    base_style = deep_merge(STYLE_DEFAULTS, defaults)

    slides = []
    used_names = set()
    for i, slide_raw in enumerate(slides_raw):
        where = f"slides[{i}]"
        slide_raw = copy.deepcopy(slide_raw)
        _check_style(slide_raw, SLIDE_KEYS, where)
        _absolutize(slide_raw, base_dir)

        style = base_style
        theme_name = slide_raw.get("theme", raw.get("theme"))
        if theme_name:
            style = deep_merge(style, resolve_theme(themes, theme_name))
        style = deep_merge(style, {k: v for k, v in slide_raw.items() if k in STYLE_KEYS})

        texts = []
        for j, el in enumerate(slide_raw.get("texts") or []):
            if isinstance(el, str):
                el = {"text": el}
            _check_keys(el, TEXT_KEYS, f"{where}.texts[{j}]")
            if "text" not in el:
                raise ConfigError(f"{where}.texts[{j}]: missing 'text'")
            _absolutize(el, base_dir)
            merged = deep_merge(style["text"], el)
            merged["text"] = str(merged["text"]).rstrip("\n")
            if not isinstance(merged["font"], list):
                merged["font"] = [merged["font"]]
            for key in ("glow", "cursor"):
                merged[key] = _normalize_sub(merged[key], SUB_DEFAULTS[key])
            texts.append(merged)

        effects = dict(style["effects"])
        effects["scanlines"] = _normalize_sub(effects["scanlines"], SCANLINES_DEFAULTS)

        name = str(slide_raw.get("name") or f"slide{i + 1}")
        if name in used_names:
            raise ConfigError(f"{where}: duplicate slide name {name!r}")
        used_names.add(name)
        slides.append({
            "index": i,
            "name": name,
            "theme": theme_name,
            "seed": slide_raw.get("seed", i),
            "duration": style["duration"],
            "hold": float(style["hold"]),
            "fade_in": float(style["fade_in"]),
            "fade_out": float(style["fade_out"]),
            "background": style["background"],
            "effects": effects,
            "texts": texts,
        })

    return {
        "config_path": str(path),
        "base_dir": str(base_dir),
        "output_dir": str((base_dir / raw["output_dir"]).resolve()),
        "video": video,
        "slides": slides,
    }
