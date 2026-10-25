"""Jeweller view: rank an inventory feed for one customer's finger and budget.

The feed is a list of stones with shape, carat, measurements and price (`assets/inventory.json` is a sample).
For a measured finger and a budget, the stones within budget are ranked by face-up area, so the first row is the
stone that will look largest on this customer's hand for the money available.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from . import gems, weights


@dataclass
class Offer:
    sku: str
    label: str
    shape: str
    carat: float
    width_mm: float
    length_mm: float
    area_mm2: float
    coverage_pct: int
    price: float
    currency: str
    price_per_mm2: float
    spread_pct: float
    weight_check: bool
    depth_mm: float
    colour: str | None
    clarity: str | None
    origin: str | None

    def as_dict(self):
        return asdict(self)


def offers(stones: list[dict], finger_mm: float) -> list[Offer]:
    out = []
    for s in stones:
        g = gems.geometry(s["shape"], s["carat"], s["length_mm"], s["width_mm"], s["depth_mm"])
        est = weights.estimate(s["shape"], g.length, g.width, g.depth)
        out.append(Offer(s["sku"], f"{s['carat']:.2f} ct {s['shape']}", s["shape"], s["carat"], g.width, g.length,
                         round(g.area_mm2, 1), round(100 * g.coverage(finger_mm)), s["price"], s["currency"],
                         round(s["price"] / g.area_mm2, 1), round(g.spread_pct, 1),
                         bool(est and abs(s["carat"] / est - 1) <= weights.TOLERANCE), g.depth, s.get("colour"),
                         s.get("clarity"), s.get("origin")))
    return out


def rank(stones: list[dict], finger_mm: float, budget: float, shapes: list[str] | None = None, top: int = 8) -> dict:
    all_offers = [o for o in offers(stones, finger_mm) if not shapes or o.shape in shapes]
    within = sorted((o for o in all_offers if o.price <= budget), key=lambda o: (-o.area_mm2, o.price))
    heaviest = max(within, key=lambda o: (o.carat, o.area_mm2), default=None)
    best = within[0] if within else None
    note = None
    if best and heaviest and best is not heaviest:
        note = {"largest": best.as_dict(), "heaviest": heaviest.as_dict(),
                "area_pct": round(100 * (best.area_mm2 / heaviest.area_mm2 - 1)),
                "price_diff": round(heaviest.price - best.price)}
    return {"finger_mm": finger_mm, "budget": budget, "in_budget": len(within), "total": len(all_offers),
            "offers": [o.as_dict() for o in within[:top]], "largest_vs_heaviest": note}
