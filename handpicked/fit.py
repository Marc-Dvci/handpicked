"""Ring size from the measured finger.

A finger's cross-section at the ring position is close to round (AIST Hand Dimension Database, n = 530: depth is
0.95 of the breadth at the proximal ring-finger joint), so the ring's inner diameter is taken as the finger's
measured width. Perfect Corp's diamond size chart uses the same convention when it treats US sizes 4, 6 and 8 as
fingers 14.9, 16.5 and 18.1 mm wide.

Sizes follow ISO 8653: inner circumference C = 2.55 s + 36.5 mm for US/Canada size s, and the EU size is C rounded
to the nearest millimetre. When the knuckle is more than one size larger than the base, the estimate moves halfway
to the knuckle size, because the ring has to pass over the knuckle.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

US_SLOPE, US_OFFSET = 2.55, 36.5
DATA = Path(__file__).resolve().parent / "data" / "ring_sizes.json"


def us_size(circ_mm: float) -> float:
    return (circ_mm - US_OFFSET) / US_SLOPE


def us_circumference(size: float) -> float:
    return US_SLOPE * size + US_OFFSET


def half(x: float) -> float:
    return math.floor(x * 2 + 0.5) / 2


@lru_cache(maxsize=1)
def _table() -> list[dict]:
    return json.loads(DATA.read_text(encoding="utf-8"))["rows"]


def uk_letter(us: float) -> str | None:
    best = min(_table(), key=lambda r: abs(r["us"] - us))
    return best["uk_au_letter"] if abs(best["us"] - us) <= 0.25 else None


@dataclass
class Fit:
    width_mm: float
    knuckle_mm: float
    us: float                 # nearest half size
    us_low: float             # range carried from the width tolerance
    us_high: float
    eu: int
    uk: str | None
    inner_diameter_mm: float  # of the recommended size
    knuckle_rule: bool        # the estimate moved toward the knuckle

    def as_dict(self):
        return asdict(self)


def ring_size(width_mm: float, knuckle_mm: float | None = None, tolerance_mm: float = 0.35) -> Fit:
    """`tolerance_mm` is the width error carried into the size range (E1 metrology bench)."""
    knuckle_mm = max(knuckle_mm or width_mm, width_mm)
    s_base, s_knuckle = us_size(math.pi * width_mm), us_size(math.pi * knuckle_mm)
    moved = bool(s_knuckle - s_base > 1.0)
    s = (s_base + s_knuckle) / 2 if moved else s_base
    ds = math.pi * tolerance_mm / US_SLOPE
    us = half(s)
    c = us_circumference(us)
    return Fit(round(width_mm, 2), round(knuckle_mm, 2), us, half(s - ds), half(s + ds), int(math.floor(c + 0.5)),
               uk_letter(us), round(c / math.pi, 2), moved)
