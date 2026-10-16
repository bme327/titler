"""Font lookup by file path, file name or family name."""
from __future__ import annotations

import os
import sys
import warnings
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

_FONT_EXTS = {".ttf", ".otf", ".ttc"}


def _system_font_dirs() -> list[Path]:
    home = Path.home()
    if sys.platform.startswith("win"):
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        dirs = [windir / "Fonts"]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs = [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library" / "Fonts"]
    else:
        dirs = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                home / ".fonts", home / ".local" / "share" / "fonts"]
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=1)
def _font_files() -> tuple[Path, ...]:
    files = []
    for d in _system_font_dirs():
        for root, _, names in os.walk(d):
            files.extend(Path(root) / n for n in names if Path(n).suffix.lower() in _FONT_EXTS)
    return tuple(files)


@lru_cache(maxsize=1)
def _family_index() -> dict[str, Path]:
    """Map lower-cased family names (e.g. 'courier new') to a font file, preferring Regular."""
    index: dict[str, tuple[int, Path]] = {}
    for path in _font_files():
        try:
            family, style = ImageFont.truetype(str(path), 10).getname()
        except Exception:
            continue
        if not family:
            continue
        rank = 0 if (style or "").lower() in ("regular", "normal", "book", "roman") else 1
        key = family.lower()
        if key not in index or rank < index[key][0]:
            index[key] = (rank, path)
    return {k: v[1] for k, v in index.items()}


def _find(name: str, base_dir: Path | None) -> Path | None:
    candidate = Path(name).expanduser()
    if not candidate.is_absolute() and base_dir is not None:
        candidate = base_dir / candidate
    if candidate.is_file():
        return candidate

    lname = name.lower()
    stems = {lname, Path(lname).stem}
    for f in _font_files():
        if f.name.lower() == lname or f.stem.lower() in stems:
            return f
    return _family_index().get(lname)


@lru_cache(maxsize=None)
def resolve_font_path(candidates: tuple[str, ...], base_dir: str | None) -> str | None:
    base = Path(base_dir) if base_dir else None
    for name in candidates:
        found = _find(name, base)
        if found is not None:
            return str(found)
    return None


@lru_cache(maxsize=None)
def load_font(candidates: tuple[str, ...], size_px: int, base_dir: str | None = None):
    """Load the first available font from ``candidates`` at ``size_px`` pixels."""
    path = resolve_font_path(candidates, base_dir)
    if path is None:
        warnings.warn(f"none of the fonts {list(candidates)} were found; using Pillow's default font")
        return ImageFont.load_default(size_px)
    return ImageFont.truetype(path, size_px)
