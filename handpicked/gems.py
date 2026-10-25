"""Face-up geometry of a stone from its listed measurements.

Face-up area uses the same girdle outlines as the ring renders (`outlines.py`), so the number on the board
and the stone on the hand come from one model. "Spread" compares a stone with a typical well-cut stone of
the same shape and weight, from Perfect Corp's diamond size chart (13 Oct 2026), so a deep stone that
hides weight in its pavilion shows up as negative spread.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from . import outlines

SHAPES = tuple(outlines.TYPICAL_LW)

# Perfect Corp, "Diamond Size Chart: How Big Does 0.5 to 3 Carats Really Look?" (13 Oct 2026):
# typical face-up dimensions in mm (length, width) for well-cut stones.
SIZE_CHART_URL = "https://www.perfectcorp.com/business/blog/general/diamond-size-chart"
ROUND_CHART = {0.25: 4.1, 0.50: 5.1, 0.75: 5.8, 1.00: 6.4, 1.25: 6.9, 1.50: 7.4, 1.75: 7.8, 2.00: 8.1,
               2.50: 8.7, 3.00: 9.3, 4.00: 10.2, 5.00: 11.0}
FANCY_CHART = {
    "oval": {1.0: (8.0, 5.5), 1.5: (9.0, 6.5), 2.0: (10.0, 7.0), 3.0: (11.5, 8.0)},
    "pear": {1.0: (8.5, 5.5), 1.5: (10.0, 6.5), 2.0: (11.0, 7.0), 3.0: (13.0, 8.0)},
    "marquise": {1.0: (10.5, 5.0), 1.5: (11.7, 6.0), 2.0: (13.0, 6.5), 3.0: (15.0, 7.5)},
    "emerald": {1.0: (7.0, 5.0), 1.5: (8.0, 5.5), 2.0: (8.5, 6.0), 3.0: (9.7, 7.0)},
    "radiant": {1.0: (6.5, 5.0), 1.5: (7.5, 5.5), 2.0: (8.0, 6.0), 3.0: (9.0, 6.5)},
    "cushion": {1.0: (5.7, 5.7), 1.5: (6.5, 6.5), 2.0: (7.3, 7.3), 3.0: (8.3, 8.3)},
    "princess": {1.0: (5.5, 5.5), 1.5: (6.3, 6.3), 2.0: (7.0, 7.0), 3.0: (8.0, 8.0)},
}


@lru_cache(maxsize=4096)
def area_factor(shape: str, lw: float) -> float:
    lw = round(max(1.0, lw), 3)
    if shape == "pear":
        lw = max(lw, 1.05)
    return outlines.area_factor(shape, lw, steps=1440)


def face_up_area(shape: str, length: float, width: float) -> float:
    """mm^2 of the stone seen from above."""
    if length < width:
        length, width = width, length
    return area_factor(shape, length / width) * length * width


def typical_area(shape: str, carat: float) -> float:
    """Face-up area of a typical well-cut stone of this shape and weight (log-log interpolation of the chart,
    which scales as carat ** (2/3) between and beyond the chart points)."""
    if shape == "round":
        pts = sorted((c, face_up_area("round", d, d)) for c, d in ROUND_CHART.items())
    else:
        pts = sorted((c, face_up_area(shape, lw[0], lw[1])) for c, lw in FANCY_CHART[shape].items())
    lc = math.log(carat)
    if carat <= pts[0][0]:
        c0, a0 = pts[0]
        return a0 * (carat / c0) ** (2 / 3)
    if carat >= pts[-1][0]:
        c0, a0 = pts[-1]
        return a0 * (carat / c0) ** (2 / 3)
    for (c0, a0), (c1, a1) in zip(pts, pts[1:]):
        if c0 <= carat <= c1:
            t = (lc - math.log(c0)) / (math.log(c1) - math.log(c0))
            return math.exp(math.log(a0) + t * (math.log(a1) - math.log(a0)))
    raise AssertionError


@dataclass(frozen=True)
class Geometry:
    shape: str
    carat: float
    length: float
    width: float
    depth: float
    area_mm2: float
    spread_pct: float      # face-up area against a typical stone of the same weight, in %
    depth_pct: float       # depth as % of width (fancies) or of mean diameter (rounds)

    def coverage(self, finger_width: float, east_west: bool = False) -> float:
        across = self.length if east_west else self.width
        return across / finger_width


def geometry(shape: str, carat: float, length: float, width: float, depth: float) -> Geometry:
    if shape not in SHAPES:
        raise ValueError(f"unsupported shape: {shape}")
    if length < width:
        length, width = width, length
    area = face_up_area(shape, length, width)
    spread = 100.0 * (area / typical_area(shape, carat) - 1.0)
    base = (length + width) / 2 if shape == "round" else width
    return Geometry(shape, carat, length, width, depth, area, spread, 100.0 * depth / base)
