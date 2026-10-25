"""Record the sample try-ons that replay mode plays without a YouCam key.

Runs the service live (YOUCAM_API_KEY set) on the sample hands with the sample shortlist, through the same
`Handpicked.tryon` the web app calls, and copies every render it made (a corrective re-render included) to
`assets/tryon` with an index. A server without a key answers these requests from the copies.

    python tools/record_samples.py [--hands hand-1,hand-2,hand-5] [--dry-run]

Re-record after any change to the ring library or to assets/calibration.json: both change which render a request
picks, and so the cache key.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("HANDPICKED_DAY_UNITS", "1000")
os.environ.setdefault("HANDPICKED_SESSION_UNITS", "1000")

from handpicked import listing  # noqa: E402
from handpicked.service import SAMPLE_SHORTLIST, Handpicked  # noqa: E402

PLAN = {  # hand: [(metal, band)]
    "hand-1": [("platinum", False), ("yellow", False)],
    "hand-2": [("platinum", False), ("yellow", False)],
    "hand-5": [("platinum", False), ("yellow", False)],
}


def stones() -> list[tuple[str, float]]:
    out = []
    for text in SAMPLE_SHORTLIST:
        L = listing.parse(text)
        out.append((L.get("shape"), L.get("measurements")["width"]))
    return out


async def main(args):
    svc = Handpicked()
    if not svc.youcam.live and not args.dry_run:
        sys.exit("YOUCAM_API_KEY is not set")
    out = ROOT / "assets" / "tryon"
    out.mkdir(parents=True, exist_ok=True)
    index_path = out / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    hands = args.hands.split(",") if args.hands else list(PLAN)
    for hid in hands:
        for metal, band in PLAN.get(hid, [("platinum", False)]):
            for shape, width in stones():
                if any(r["hand"] == hid and r["shape"] == shape and r["width_mm"] == width and r["metal"] == metal
                       and r["band"] == band for r in index):
                    continue
                if args.dry_run:
                    print("would record", hid, shape, width, metal, band)
                    continue
                r = await svc.tryon(hid, shape, width, metal, band, "record")
                for a in r["attempts"]:
                    for ext in ("jpg", "json"):
                        src = svc.s.var / "tryon" / f"{a['key']}.{ext}"
                        if src.exists():
                            shutil.copyfile(src, out / src.name)
                row = {"hand": hid, "shape": shape, "width_mm": width, "metal": metal, "band": band, "key": r["key"],
                       "task_id": r["task_id"], "seconds": r["seconds"], "units": r["units"],
                       "attempts": len(r["attempts"]), "error_pct": r["audit"]["error_pct"],
                       "passed": r["audit"]["passed"]}
                index.append(row)
                index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
                print(json.dumps(row), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", default="")
    ap.add_argument("--dry-run", action="store_true")
    asyncio.run(main(ap.parse_args()))
