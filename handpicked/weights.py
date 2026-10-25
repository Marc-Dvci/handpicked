"""Carat weight estimated from a stone's measurements, used to check a listing against itself.

weight (ct) = L x W x D x factor (rounds: mean diameter squared x depth x factor). The factors are Omni
Calculator's diamond weight constants (S3 in docs/METHOD.md), cross-checked against the International Gem Society
formulas. Fancy-shape factors depend on the length-to-width ratio and are interpolated between S3's ratio points.
"""
from __future__ import annotations

TOLERANCE = 0.12   # a listed weight more than 12% from the estimate is flagged

FACTORS = {
    "round": [(1.00, 0.0061)],
    "oval": [(1.00, 0.0062)],
    "cushion": [(1.00, 0.00815)],
    "princess": [(1.00, 0.0083)],
    "radiant": [(1.00, 0.0081), (1.50, 0.0084)],
    "emerald": [(1.00, 0.0080), (1.50, 0.0092), (2.00, 0.0100), (2.50, 0.0106)],
    "pear": [(1.25, 0.00615), (1.50, 0.00600), (1.66, 0.00590), (2.00, 0.00575)],
    "marquise": [(1.50, 0.00565), (2.00, 0.00580), (2.50, 0.00585), (3.00, 0.00595)],
}


def factor(shape: str, lw: float) -> float:
    pts = FACTORS[shape]
    if lw <= pts[0][0]:
        return pts[0][1]
    for (r0, f0), (r1, f1) in zip(pts, pts[1:]):
        if r0 <= lw <= r1:
            return f0 + (f1 - f0) * (lw - r0) / (r1 - r0)
    return pts[-1][1]


def estimate(shape: str, length: float, width: float, depth: float) -> float | None:
    if shape not in FACTORS or min(length, width, depth) <= 0:
        return None
    if length < width:
        length, width = width, length
    if shape == "round":
        d = (length + width) / 2
        return d * d * depth * factor(shape, 1.0)
    return length * width * depth * factor(shape, length / width)
