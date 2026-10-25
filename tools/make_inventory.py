"""Build the sample jeweller inventory used by the merchant view.

Each stone is a natural diamond with measurements drawn around Perfect Corp's size chart for its shape and weight
(face-up area from 8% below to 8% above the typical stone, so some stones spread and some hide weight in depth),
priced at PriceScope's October 2026 page-table average price per carat for its colour, clarity and weight band.

    python tools/make_inventory.py --prices eval/prices/pricescope_cells_2026-10.csv --out assets/inventory.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handpicked import gems, outlines, weights  # noqa: E402

SHAPES = ["round", "oval", "pear", "princess", "radiant"]
COLOURS = ["F", "G", "H"]
CLARITIES = ["VS1", "VS2", "SI1"]
CARATS = [0.70, 0.75, 0.80, 0.90, 0.92, 0.95, 1.00, 1.01, 1.05, 1.10, 1.20, 1.25, 1.40, 1.50, 1.60, 2.00]
DEPTH_PCT = {"round": 61.5, "oval": 61.0, "pear": 61.0, "princess": 70.0, "radiant": 64.0}


def cell_prices(path: Path) -> dict:
    out = {}
    for r in csv.DictReader(path.open(encoding="utf-8")):
        if r["source"] != "PS_NAT":
            continue
        if "colour" in r:          # the extract shipped in eval/prices (tools/extract_prices.py)
            out[(r["shape"], float(r["carat_min"]), float(r["carat_max"]), r["colour"], r["clarity"])] = float(r["price_per_carat"])
            continue
        m = re.match(r"CELL colour (\w) clarity (\w+);", r["filter_note"])
        if m:
            out[(r["shape"], float(r["carat_min"]), float(r["carat_max"]), m.group(1), m.group(2))] = float(r["value"])
    return out


def price_per_carat(cells, shape, carat, colour, clarity):
    for (s, lo, hi, c, q), v in cells.items():
        if s == shape and c == colour and q == clarity and lo <= carat <= hi + 0.0049:
            return v
    return None


def stone(rng, cells, sku):
    while True:
        shape = rng.choice(SHAPES)
        carat = rng.choice(CARATS)
        colour, clarity = rng.choice(COLOURS), rng.choice(CLARITIES)
        ppc = price_per_carat(cells, shape, carat, colour, clarity)
        if ppc:
            break
    lw = outlines.TYPICAL_LW[shape] * rng.uniform(0.95, 1.05) if shape != "round" else 1.0
    area = gems.typical_area(shape, carat) * rng.uniform(0.92, 1.08)
    width = math.sqrt(area / (gems.area_factor(shape, lw) * lw))
    length = width * lw
    depth = width * DEPTH_PCT[shape] / 100 * rng.uniform(0.97, 1.04)
    # keep the weight consistent with the measurements: scale depth to the weight formula
    est = weights.estimate(shape, length, width, depth)
    depth *= carat / est * rng.uniform(0.97, 1.03)
    return {"sku": f"HP-{sku:04d}", "shape": shape, "carat": carat, "colour": colour, "clarity": clarity,
            "origin": "natural", "length_mm": round(length, 2), "width_mm": round(width, 2),
            "depth_mm": round(depth, 2), "price": round(ppc * carat, -1), "currency": "USD"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    cells = cell_prices(Path(args.prices))
    stones = [stone(rng, cells, i + 1) for i in range(args.n)]
    Path(args.out).write_text(json.dumps({"source": "PriceScope natural diamond price charts, October 2026 "
                                          "(page-table average price per carat by colour, clarity and weight band); "
                                          "measurements around Perfect Corp's diamond size chart (13 Oct 2026)",
                                          "stones": stones}, indent=1), encoding="utf-8")
    print(len(stones), "stones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
