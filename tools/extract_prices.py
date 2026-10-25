"""Extract the PriceScope colour x clarity cells (natural and lab-grown) into the compact CSV the repo ships.

    python tools/extract_prices.py --prices <prices.csv> --out eval/prices/pricescope_cells_2026-10.csv

The source CSV holds every figure read from the price pages fetched on 24 Oct 2026; only the per-cell average price
per carat rows are kept.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

FIELDS = ["source", "url", "fetched", "shape", "origin", "carat_min", "carat_max", "colour", "clarity", "price_per_carat"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rows = []
    for r in csv.DictReader(Path(args.prices).open(encoding="utf-8")):
        m = re.match(r"CELL colour (\w) clarity (\w+);", r["filter_note"])
        if r["source"] in ("PS_NAT", "PS_LAB") and m:
            rows.append({"source": r["source"], "url": r["url"], "fetched": r["fetched"], "shape": r["shape"],
                         "origin": r["origin"], "carat_min": r["carat_min"], "carat_max": r["carat_max"],
                         "colour": m.group(1), "clarity": m.group(2), "price_per_carat": r["value"]})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(len(rows), "cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
