"""Compare the stones a shopper is considering, on the shopper's measured finger.

Every number here comes from the listings and the measurement. A stone without measurements waits outside
the ranking with a question for the seller.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import gems, listing, weights

# Natural stones carry a price step at round weights (PriceScope natural rounds, Oct 2026, colour- and
# clarity-matched cells: +23.9% per carat from 0.90-0.99 to 1.00-1.19). Lab-grown stones showed none
# (+4.0% matched, -1.2% band median), so the flag is only raised for natural stones.
ROUND_WEIGHTS = (0.50, 0.70, 1.00, 1.50, 2.00, 3.00)


@dataclass
class Stone:
    id: str
    label: str
    shape: str
    carat: float
    length: float
    width: float
    depth: float
    price: float | None
    currency: str | None
    origin: str | None
    geometry: gems.Geometry
    weight_estimate: float | None
    flags: list[str] = field(default_factory=list)
    listing: listing.Listing | None = None


@dataclass
class Pending:
    id: str
    label: str
    missing: list[str]
    question: str | None
    notes: list[str]
    listing: listing.Listing


def label_for(shape, carat):
    return f"{carat:.2f} ct {shape}"


def stone_from_listing(sid: str, L: listing.Listing) -> Stone | Pending:
    if "not_diamond" in L.fields:
        return Pending(sid, f"{L.get('not_diamond')} stone", ["material"],
                       f"This listing describes {L.get('not_diamond')}. Handpicked compares diamonds; the sizes and "
                       "weights of other stones follow other rules.", L.notes, L)
    if "shape_unsupported" in L.fields:
        return Pending(sid, f"{L.get('shape_unsupported')} stone", ["shape"],
                       "Handpicked compares round, oval, cushion, emerald, pear, princess, radiant and marquise stones.",
                       L.notes, L)
    gaps = listing.missing(L)
    blocking = [g for g in gaps if g != "price"]
    if blocking:
        lab = label_for(L.get("shape"), L.get("carat")) if L.get("shape") and L.get("carat") else f"Stone {sid}"
        return Pending(sid, lab, gaps, listing.seller_question(L), L.notes, L)
    m = L.get("measurements")
    shape, carat = L.get("shape"), float(L.get("carat"))
    geo = gems.geometry(shape, carat, m["length"], m["width"], m["depth"])
    price = L.get("price")
    est = weights.estimate(shape, m["length"], m["width"], m["depth"])
    s = Stone(sid, label_for(shape, carat), shape, carat, geo.length, geo.width, geo.depth,
              price["amount"] if price else None, price["currency"] if price else None, L.get("origin"), geo, est,
              listing=L)
    if est and abs(carat / est - 1) > weights.TOLERANCE:
        s.flags.append("weight_mismatch")
    if s.origin == "natural" and any(w <= carat < w + 0.05 for w in ROUND_WEIGHTS):
        s.flags.append("round_weight")
    if price is None:
        s.flags.append("no_price")
    if any("approximate" in n for n in L.notes):
        s.flags.append("approximate_mm")
    return s


@dataclass
class Row:
    stone: Stone
    area_mm2: float
    coverage: float
    price_per_mm2: float | None
    rank_value: int | None = None


@dataclass
class Board:
    finger_mm: float
    rows: list[Row]
    pending: list[Pending]
    currency: str | None
    facts: dict
    notes: list[str]


def board(items: list[Stone | Pending], finger_mm: float, east_west: bool = False) -> Board:
    stones = [s for s in items if isinstance(s, Stone)]
    pending = [s for s in items if isinstance(s, Pending)]
    notes = []
    currencies = {s.currency for s in stones if s.currency}
    currency = currencies.pop() if len(currencies) == 1 else None
    if len({s.currency for s in stones if s.currency}) > 1:
        notes.append("The listings use different currencies, so prices are not compared.")
    rows = []
    for s in stones:
        ppm = s.price / s.geometry.area_mm2 if (s.price and currency) else None
        rows.append(Row(s, s.geometry.area_mm2, s.geometry.coverage(finger_mm, east_west), ppm))
    priced = sorted([r for r in rows if r.price_per_mm2 is not None], key=lambda r: r.price_per_mm2)
    for i, r in enumerate(priced):
        r.rank_value = i + 1
    rows.sort(key=lambda r: (r.rank_value is None, r.rank_value or 0, -r.area_mm2))
    return Board(finger_mm, rows, pending, currency, verdict_facts(rows, currency), notes)


def verdict_facts(rows: list[Row], currency: str | None) -> dict:
    """The comparison the verdict is written from. Numbers are rounded the way the page shows them."""
    if len(rows) < 2:
        return {}
    heaviest = max(rows, key=lambda r: (r.stone.carat, r.area_mm2))
    largest = max(rows, key=lambda r: r.area_mm2)
    facts = {"heaviest": _desc(heaviest), "largest": _desc(largest),
             "identical": len({(r.stone.shape, r.stone.length, r.stone.width, r.stone.price) for r in rows}) == 1}
    priced = [r for r in rows if r.price_per_mm2 is not None]
    if not (priced and currency):
        return facts
    best = min(priced, key=lambda r: r.price_per_mm2)
    facts["best_value"] = _desc(best)
    if best is not heaviest and heaviest.stone.price:
        facts["best_vs_heaviest"] = {
            "area_pct": round(100 * (best.area_mm2 / heaviest.area_mm2 - 1)),
            "price_diff": round(heaviest.stone.price - best.stone.price),
            "currency": currency,
        }
    twin = look_alike(priced)
    if twin:
        facts["look_alike"] = twin | {"currency": currency}
    return facts


LOOK_ALIKE_MM, LOOK_ALIKE_AREA, LOOK_ALIKE_PRICE = 0.2, 0.06, 0.10


def look_alike(rows: list[Row]) -> dict | None:
    """Two stones of one shape within 0.2 mm across the finger and 6% of face-up area, whose prices differ by more
    than 10%: on the hand they look the same. The pair with the largest price gap is returned."""
    best = None
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a.stone.shape != b.stone.shape:
                continue
            if abs(a.stone.width - b.stone.width) > LOOK_ALIKE_MM or abs(a.area_mm2 / b.area_mm2 - 1) > LOOK_ALIKE_AREA:
                continue
            dear, cheap = (a, b) if a.stone.price >= b.stone.price else (b, a)
            gap = dear.stone.price - cheap.stone.price
            if gap / cheap.stone.price <= LOOK_ALIKE_PRICE or (best and gap <= best["price_diff"]):
                continue
            best = {"dearer": _desc(dear), "cheaper": _desc(cheap),
                    "across_mm": round(abs(dear.stone.width - cheap.stone.width), 2),
                    "coverage_points": abs(round(100 * dear.coverage) - round(100 * cheap.coverage)),
                    "price_diff": round(gap), "price_pct": round(100 * gap / cheap.stone.price)}
    return best


def _desc(r: Row) -> dict:
    return {"id": r.stone.id, "label": r.stone.label, "coverage_pct": round(100 * r.coverage),
            "area_mm2": round(r.area_mm2, 1), "width_mm": round(r.stone.width, 2), "price": r.stone.price,
            "price_per_mm2": round(r.price_per_mm2, 1) if r.price_per_mm2 else None}


SYMBOL = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF "}


def money(v, cur):
    s = SYMBOL.get(cur, "")
    return f"{s}{v:,.0f}" if s != "CHF " else f"CHF {v:,.0f}"


def template_sentence(facts: dict) -> str:
    """Deterministic verdict, used when no model is configured and whenever the model's sentence fails the check."""
    if not facts:
        return "Add a second stone to compare."
    if facts.get("identical"):
        return "These listings describe the same stone: they face up the same on your hand."
    out = []
    v = facts.get("best_vs_heaviest")
    if v:
        b, h, cur = facts["best_value"]["label"], facts["heaviest"]["label"], v["currency"]
        if v["area_pct"] > 0:
            out.append(f"The {b} shows {v['area_pct']}% more face-up area than the {h}, for {money(v['price_diff'], cur)} less.")
        elif v["area_pct"] == 0:
            out.append(f"The {b} shows as much face-up area as the {h}, for {money(v['price_diff'], cur)} less.")
        else:
            out.append(f"The {b} costs {money(v['price_diff'], cur)} less than the {h} and shows "
                       f"{-v['area_pct']}% less face-up area.")
    t = facts.get("look_alike")
    if t:
        out.append(f"The {t['dearer']['label']} and the {t['cheaper']['label']} differ by {t['across_mm']} mm across "
                   f"your finger; the {t['dearer']['label']} costs {money(t['price_diff'], t['currency'])} more.")
    if out:
        return " ".join(out)
    h, lg = facts["heaviest"], facts["largest"]
    if lg["id"] != h["id"]:
        return (f"The {lg['label']} faces up larger than the heavier {h['label']}: {lg['area_mm2']} mm² against "
                f"{h['area_mm2']} mm².")
    return f"The {h['label']} faces up largest, covering {h['coverage_pct']}% of your finger's width."
