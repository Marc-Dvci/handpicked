"""E5: what does the board find on shortlists a shopper might bring, priced from public price data?

Each shortlist holds three natural stones a shopper might weigh against a round at a round weight (0.70, 1.00, 1.50,
2.00 ct): that round, a round just under the weight, and an oval, pear, radiant or princess just under it, in nine
colour and clarity grades. Every stone has the typical dimensions of its shape and weight (Perfect Corp's diamond size
chart, `gems.typical_area`) and the PriceScope average price per carat of its cell (October 2026,
eval/prices/pricescope_cells_2026-10.csv). Each shortlist is written as listing text and goes through the same reader
and board as the web app.

The saving is the heaviest stone's price minus the cheapest stone on the same board that faces up at least as large.
This is what the board finds on these shortlists, not a market-wide saving: the prices are cell averages for average
cut quality, and real stones of one weight vary in spread.

    python eval/e5_decision_value.py

Writes eval/results/e5_shortlists.jsonl and eval/results/e5_summary.json.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handpicked import compare, gems, listing, outlines, weights  # noqa: E402

PRICES = ROOT / "eval" / "prices" / "pricescope_cells_2026-10.csv"
RESULTS = ROOT / "eval" / "results"
FINGER_MM = 16.7          # sample hand 1; the finger changes coverage, not area or price
THRESHOLDS = {0.70: (0.65, 0.64), 1.00: (0.93, 0.92), 1.50: (1.40, 1.38), 2.00: (1.86, 1.84)}
FANCY = ("oval", "pear", "radiant", "princess")
GRADES = [(c, q) for c in ("F", "G", "H") for q in ("VS1", "VS2", "SI1")]
DEPTH_PCT = {"round": 61.5, "oval": 61.0, "pear": 61.0, "princess": 70.0, "radiant": 64.0}


def cells(origin: str) -> dict:
    out = {}
    for r in csv.DictReader(PRICES.open(encoding="utf-8")):
        if r["origin"] == origin:
            out[(r["shape"], float(r["carat_min"]), float(r["carat_max"]), r["colour"], r["clarity"])] = float(r["price_per_carat"])
    return out


def ppc(table, shape, carat, colour, clarity):
    for (s, lo, hi, c, q), v in table.items():
        if s == shape and c == colour and q == clarity and lo <= carat <= hi + 0.0049:
            return v
    return None


def typical_stone(shape: str, carat: float) -> tuple[float, float, float]:
    lw = 1.0 if shape == "round" else outlines.TYPICAL_LW[shape]
    area = gems.typical_area(shape, carat)
    width = math.sqrt(area / (gems.area_factor(shape, lw) * lw))
    length = width * lw
    depth = width * DEPTH_PCT[shape] / 100
    depth *= carat / weights.estimate(shape, length, width, depth)     # depth that gives the listed weight
    return length, width, depth


def listing_text(shape, carat, colour, clarity, price) -> str:
    length, width, depth = typical_stone(shape, carat)
    return (f"Natural {shape} diamond, {carat:.2f} ct\nMeasurements: {length:.2f} x {width:.2f} x {depth:.2f} mm\n"
            f"Colour {colour}, clarity {clarity}\nPrice: ${price:,.0f}")


def matched_step(table, lo_band, hi_band) -> tuple[float, int]:
    """Median ratio of price per carat between two weight bands over the round cells populated in both."""
    ratios = []
    for (s, lo, hi, c, q), v in table.items():
        if s == "round" and (lo, hi) == lo_band:
            w = table.get(("round", *hi_band, c, q))
            if w:
                ratios.append(w / v)
    return round(100 * (statistics.median(ratios) - 1), 1), len(ratios)


def main():
    nat = cells("natural")
    rows = []
    for t, (below_round, below_fancy) in THRESHOLDS.items():
        for colour, clarity in GRADES:
            for fancy in FANCY:
                stones = [("round", t), ("round", below_round), (fancy, below_fancy)]
                prices = [ppc(nat, s, c, colour, clarity) for s, c in stones]
                if None in prices:
                    continue
                texts = [listing_text(s, c, colour, clarity, round(p * c, -1)) for (s, c), p in zip(stones, prices)]
                items = [compare.stone_from_listing("ABC"[i], listing.parse(x)) for i, x in enumerate(texts)]
                if any(isinstance(i, compare.Pending) for i in items):
                    raise SystemExit(f"a sample listing was not read: {texts}")
                b = compare.board(items, FINGER_MM)
                heavy = max(b.rows, key=lambda r: (r.stone.carat, r.area_mm2))
                cands = [r for r in b.rows if r is not heavy and r.area_mm2 >= heavy.area_mm2 and r.stone.price < heavy.stone.price]
                best = min(cands, key=lambda r: r.stone.price) if cands else None
                twin = b.facts.get("look_alike")
                rows.append({
                    "threshold": t, "colour": colour, "clarity": clarity, "fancy": fancy,
                    "stones": [{"label": r.stone.label, "area_mm2": round(r.area_mm2, 1), "width_mm": r.stone.width,
                                "price": r.stone.price} for r in b.rows],
                    "heaviest": heavy.stone.label, "heaviest_price": heavy.stone.price,
                    "saving_usd": round(heavy.stone.price - best.stone.price) if best else 0,
                    "saving_pct": round(100 * (1 - best.stone.price / heavy.stone.price), 1) if best else 0.0,
                    "saving_with": best.stone.label if best else None,
                    "area_gain_pct": round(100 * (best.area_mm2 / heavy.area_mm2 - 1), 1) if best else None,
                    "look_alike": {"across_mm": twin["across_mm"], "price_diff": twin["price_diff"],
                                   "price_pct": twin["price_pct"]} if twin else None,
                    "verdict": compare.template_sentence(b.facts),
                })
    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / "e5_shortlists.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    saved = [r for r in rows if r["saving_usd"] > 0]
    twins = [r for r in rows if r["look_alike"]]
    nat_step, nat_n = matched_step(nat, (0.90, 0.99), (1.00, 1.19))
    lab_step, lab_n = matched_step(cells("lab"), (0.90, 0.99), (1.00, 1.19))
    summary = {
        "description": f"{len(rows)} shortlists of three natural stones weighed against a round at 0.70, 1.00, 1.50 or "
                       "2.00 ct: the round, a round just under the weight, and an oval, pear, radiant or princess just "
                       "under it, in nine colour and clarity grades. Typical dimensions from Perfect Corp's diamond size "
                       "chart; prices are PriceScope cell averages, October 2026.",
        "shortlists": len(rows), "shortlists_with_saving": len(saved),
        "median_saving_usd": round(statistics.median([r["saving_usd"] for r in saved])) if saved else 0,
        "median_saving_pct": round(statistics.median([r["saving_pct"] for r in saved]), 1) if saved else 0,
        "max_saving_usd": max((r["saving_usd"] for r in saved), default=0),
        "by_fancy": {f: sum(1 for r in saved if r["saving_with"] and f in r["saving_with"]) for f in FANCY},
        "saving_with_round": sum(1 for r in saved if r["saving_with"] and "round" in r["saving_with"]),
        "by_threshold": {f"{t:.2f}": {"shortlists": sum(r["threshold"] == t for r in rows),
                                      "with_saving": sum(r["threshold"] == t for r in saved),
                                      "median_saving_usd": round(statistics.median([r["saving_usd"] for r in saved if r["threshold"] == t]))
                                      if any(r["threshold"] == t for r in saved) else 0} for t in THRESHOLDS},
        "look_alike_pairs": len(twins),
        "look_alike_median_across_mm": round(statistics.median([r["look_alike"]["across_mm"] for r in twins]), 2) if twins else None,
        "look_alike_median_price_diff_usd": round(statistics.median([r["look_alike"]["price_diff"] for r in twins])) if twins else None,
        "look_alike_median_price_pct": round(statistics.median([r["look_alike"]["price_pct"] for r in twins]), 1) if twins else None,
        "magic_premium_natural_pct": nat_step, "magic_premium_natural_cells": nat_n,
        "magic_premium_lab_pct": lab_step, "magic_premium_lab_cells": lab_n,
        "note": "What the board finds on these shortlists, not a market-wide saving: prices are cell averages for "
                "average cut quality, and real stones of one weight vary in spread. The 1.00 ct step is the median "
                "change in price per carat from the 0.90-0.99 to the 1.00-1.19 band over the colour and clarity cells "
                "populated in both.",
    }
    (RESULTS / "e5_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
