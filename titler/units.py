"""Length parsing: pixels, points and percentages."""
from __future__ import annotations

import re

_LENGTH_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(px|pt|%)?\s*$", re.IGNORECASE)


class UnitError(ValueError):
    pass


def parse_length(value, reference: float, dpi: float) -> float:
    """Convert a length to pixels.

    Accepted forms: ``120`` / ``"120px"`` (pixels), ``"36pt"`` (points, 1pt = dpi/72 px)
    and ``"50%"`` (percentage of ``reference``, e.g. frame width for x, height for y).
    """
    if isinstance(value, bool):
        raise UnitError(f"invalid length: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise UnitError(f"invalid length: {value!r}")
    m = _LENGTH_RE.match(value)
    if not m:
        raise UnitError(f"invalid length {value!r} (use e.g. 120, '120px', '36pt' or '50%')")
    number = float(m.group(1))
    unit = (m.group(2) or "px").lower()
    if unit == "px":
        return number
    if unit == "pt":
        return number * dpi / 72.0
    return number * reference / 100.0
