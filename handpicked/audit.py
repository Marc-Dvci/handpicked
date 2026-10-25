"""Check a rendered try-on against the size it was asked for.

Two readings, both across the finger's axis:

* the footprint: the try-on changes only the pixels where the ring is drawn, so the difference between the
  photo and the render is the ring. Its extent across the finger is the band, which the engine fits to the
  finger's silhouette; `band_fit` compares it with the finger width the metrology measured in the photo.
* the marker: calibration rings carry a pure green stone (`tools/render_rings.py --marker`). Its width in the
  render divided by the finger width is the stone-to-finger ratio the shopper sees. The calibration run
  (`eval/e3_render_scale.py`) measures how that ratio follows the ratio in the product image and the band fit.

A production render has no marker, so its stone width is read through its band: c_shape x product ratio x band
fit, with c_shape from the calibration.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

TOLERANCE = 0.05


def _frame(mcp, pip):
    mcp, pip = np.asarray(mcp, float), np.asarray(pip, float)
    axis = pip - mcp
    seg = float(np.hypot(*axis))
    u = axis / seg
    return mcp, u, np.array([-u[1], u[0]]), seg


def _extent(values: np.ndarray, lo=1.0, hi=99.0) -> float:
    if len(values) < 8:
        return 0.0
    a, b = np.percentile(values, [lo, hi])
    return float(b - a + 1.0)


@dataclass
class Footprint:
    band_px: float
    along_px: float
    pixels: int


def footprint(before: np.ndarray, after: np.ndarray, mcp, pip, finger_px: float, threshold: int = 42) -> Footprint | None:
    if after.shape != before.shape:
        after = cv2.resize(after, (before.shape[1], before.shape[0]), interpolation=cv2.INTER_AREA)
    diff = np.abs(after.astype(np.int16) - before.astype(np.int16)).sum(2)
    mask = cv2.morphologyEx((diff > threshold).astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    o, u, n, seg = _frame(mcp, pip)
    ys, xs = np.nonzero(mask)
    if len(xs) < 30:
        return None
    rel = np.stack([xs - o[0], ys - o[1]], 1)
    along, across = rel @ u, rel @ n
    keep = (np.abs(across) < 0.85 * finger_px) & (along > -0.2 * seg) & (along < 1.2 * seg)
    if keep.sum() < 30:
        return None
    return Footprint(band_px=_extent(across[keep]), along_px=_extent(along[keep]), pixels=int(keep.sum()))


def marker_width(after: np.ndarray, mcp, pip) -> float | None:
    """Width across the finger of the green calibration stone in a render."""
    hsv = cv2.cvtColor(after, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    green = ((h > 45) & (h < 85) & (s > 90) & (v > 60)).astype(np.uint8)
    green = cv2.morphologyEx(green, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n_lab, lab, stats, _ = cv2.connectedComponentsWithStats(green, 8)
    if n_lab < 2:
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    ys, xs = np.nonzero(lab == k)
    if len(xs) < 12:
        return None
    o, u, n, _ = _frame(mcp, pip)
    across = np.stack([xs - o[0], ys - o[1]], 1) @ n
    return _extent(across, 0.5, 99.5)


BAND_FIT_VALID = (0.95, 1.35)


@dataclass
class Audit:
    target_ratio: float       # stone width / finger width the shopper should see
    expected_ratio: float | None  # what this render shows: c_shape x product ratio x band fit measured in it
    band_fit: float | None    # band extent in the render / finger width in the photo
    passed: bool

    @property
    def error(self) -> float | None:
        return None if self.expected_ratio is None else self.expected_ratio / self.target_ratio - 1

    def as_dict(self):
        return {"target_ratio": round(self.target_ratio, 4),
                "expected_ratio": None if self.expected_ratio is None else round(self.expected_ratio, 4),
                "error_pct": None if self.error is None else round(100 * self.error, 1),
                "band_fit": None if self.band_fit is None else round(self.band_fit, 3), "passed": self.passed}


def audit(fp: Footprint | None, finger_px: float, target_ratio: float, product_ratio: float, c_shape: float) -> Audit:
    """The engine scales each ring to the hand a little differently; the band's footprint in the render shows by
    how much, and the stone follows it (eval/e3_render_scale.py: 133 renders, 90% within 2.3%)."""
    band_fit = fp.band_px / finger_px if fp else None
    if band_fit is None or not BAND_FIT_VALID[0] <= band_fit <= BAND_FIT_VALID[1]:
        return Audit(target_ratio, None, band_fit, False)
    expected = c_shape * product_ratio * band_fit
    return Audit(target_ratio, expected, band_fit, abs(expected / target_ratio - 1) <= TOLERANCE)
