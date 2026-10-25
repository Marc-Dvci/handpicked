"""Choose the ring render that puts a stone on the hand at its listed size.

The library holds one render per shape, metal and stone-to-band ratio (0.16 to 0.68 in steps of 0.02).
The try-on draws the stone at `scale` times the product image's ratio, where scale = c_shape x the hand's band
fit (eval/e3_render_scale.py); the render closest to target / scale is chosen and the small rest is taken up by
scaling the anchor points, which scales the whole ring by at most a few per cent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MAX_ANCHOR_SCALE = 0.06


@dataclass
class Choice:
    name: str
    image_path: Path
    shape: str
    metal: str
    product_ratio: float        # stone width / band outer diameter in the product image
    anchor_scale: float         # >1 draws the ring larger on the finger
    anchor_points: list
    expected_ratio: float       # scale * product_ratio * anchor_scale
    meta: dict


class RingLibrary:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.items: dict[tuple[str, str], list[dict]] = {}
        self.bands: dict[str, dict] = {}
        for p in sorted(self.root.glob("*.json")):
            m = json.loads(p.read_text(encoding="utf-8"))
            if m.get("shape") == "band":
                self.bands[m["metal"]] = m
            elif not m.get("marker"):
                m["product_ratio"] = m["stone_width_mm"] / m["outer_diameter_mm"]
                self.items.setdefault((m["shape"], m["metal"]), []).append(m)
        for v in self.items.values():
            v.sort(key=lambda m: m["product_ratio"])

    def metals(self, shape: str) -> list[str]:
        return sorted(m for s, m in self.items if s == shape)

    def choose(self, shape: str, metal: str, target_ratio: float, scale: float = 1.0) -> Choice:
        opts = self.items.get((shape, metal))
        if not opts:
            raise KeyError(f"no renders for {shape} in {metal}")
        want = target_ratio / scale
        best = min(opts, key=lambda m: abs(m["product_ratio"] - want))
        a = want / best["product_ratio"]
        if abs(a - 1) > MAX_ANCHOR_SCALE:
            raise ValueError(f"a stone {target_ratio:.0%} of the finger width is outside the library's range")
        return Choice(best["name"], self.root / best["image"], shape, metal, best["product_ratio"], a,
                      scaled_anchors(best["anchor_points"], a), scale * best["product_ratio"] * a, best)

    def band(self, metal: str) -> tuple[Path, dict]:
        m = self.bands[metal]
        return self.root / m["image"], m


def scaled_anchors(points, scale: float) -> list:
    """Anchor points closer together make the engine draw the ring larger: divide the span by `scale`."""
    (x0, y0), (x1, y1) = points
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = (x1 - x0) / 2 / scale, (y1 - y0) / 2 / scale
    return [[int(round(cx - hx)), int(round(cy - hy))], [int(round(cx + hx)), int(round(cy + hy))]]
