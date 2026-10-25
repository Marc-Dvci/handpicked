"""Girdle outlines of the supported shapes, shared by the face-up area model and the Blender ring renderer.

Coordinates: x runs across the finger, y along it (north-south setting). The outline is normalised to a
half-width of 1 and a half-length of `b`, so a stone of width W and length L has b = L / W.
"""
import math

# Length-to-width ratio the ring library is rendered at, per shape.
TYPICAL_LW = {
    "round": 1.00, "oval": 1.40, "cushion": 1.10, "emerald": 1.40,
    "pear": 1.60, "princess": 1.00, "radiant": 1.25, "marquise": 2.00,
}

SUPERELLIPSE_N = {"cushion": 2.7, "princess": 9.0, "radiant": 5.0}
EMERALD_CORNER = 0.16


def radius(shape: str, theta: float, b: float) -> float:
    """Polar radius of the outline at angle theta (0 = across the finger, +x)."""
    c, s = math.cos(theta), math.sin(theta)
    if shape in ("round", "oval"):
        return 1.0 / math.sqrt(c * c + (s / b) ** 2)
    if shape in SUPERELLIPSE_N:
        n = SUPERELLIPSE_N[shape]
        return (abs(c) ** n + abs(s / b) ** n) ** (-1.0 / n)
    if shape == "emerald":
        cut = EMERALD_CORNER * min(1.0, b)
        lim = [1.0 / abs(c) if abs(c) > 1e-9 else 1e9, b / abs(s) if abs(s) > 1e-9 else 1e9,
               (1.0 + b - cut) / (abs(c) + abs(s))]
        return min(lim)
    if shape == "pear":
        if s <= 0:
            return 1.0
        return _bisect(lambda r: _inside_pear(r * c, r * s, 2.0 * b - 1.0), 2.0 * b + 1.0)
    if shape == "marquise":
        rc = (b * b + 1.0) / 2.0
        return _bisect(lambda r: (r * c + rc - 1.0) ** 2 + (r * s) ** 2 <= rc * rc
                       and (r * c - rc + 1.0) ** 2 + (r * s) ** 2 <= rc * rc, b + 1.0)
    raise ValueError(f"unsupported shape: {shape}")


def _bisect(inside, hi: float) -> float:
    lo = 0.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if inside(mid):
            lo = mid
        else:
            hi = mid
    return lo


def _inside_pear(x: float, y: float, tip: float) -> bool:
    """Convex hull of the unit circle and the tip point (0, tip)."""
    if x * x + y * y <= 1.0:
        return True
    if y <= 0 or tip <= 1.0:
        return False
    phi = math.asin(1.0 / tip)
    tx, ty = math.cos(phi), math.sin(phi)
    if y < ty or y > tip:
        return False
    return tx * (y - tip) - (ty - tip) * abs(x) <= 0


def area_factor(shape: str, b: float | None = None, steps: int = 3600) -> float:
    """Face-up area as a fraction of the bounding rectangle L x W."""
    b = TYPICAL_LW[shape] if b is None else b
    area = 0.0
    for k in range(steps):
        th = 2 * math.pi * (k + 0.5) / steps
        r = radius(shape, th, b)
        area += 0.5 * r * r * (2 * math.pi / steps)
    if shape == "pear":
        length = 1.0 + (2.0 * b - 1.0)   # from the round end (-1) to the tip
        return area / (2.0 * length)
    return area / (2.0 * 2.0 * b)
