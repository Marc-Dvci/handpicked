"""E3: how large does the Ring VTO draw a stone, given the ring image it is sent?

Calibration rings carry a flat green stone (`tools/render_rings.py --marker`). Each one goes through the live Ring
VTO on the sample hands; the green region is segmented in the result and its width across the finger is divided
by the finger's width in the same image. The ratio in the product image (stone width / band outer diameter) is
known exactly from the render, so every call gives one point of the engine's response. The band's footprint in
the same render (`audit.footprint`) is measured too: the engine scales the whole ring to each hand a little
differently, and the band shows by how much.

The run writes every call to `eval/results/e3_calls.jsonl` and the fit to `eval/results/e3_summary.json` and
`assets/calibration.json` (per-shape constants and band fits, which the service uses to pick the render for a
target size and to audit every try-on).

    python eval/e3_render_scale.py --rings <marker library> [--hands hand-1,hand-2] [--limit 3] [--fit-only]
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handpicked import audit, config, hands, metrology, youcam  # noqa: E402

RESULTS = ROOT / "eval" / "results"
BAND_FIT_VALID = (0.95, 1.35)   # below this the stone hides the band and the footprint cannot be read


def params_for(finger: dict, anchors, scale: float = 1.0) -> dict:
    from handpicked.library import scaled_anchors
    return {"ring_wearing_finger": 3, "ring_wearing_location": finger["wearing_location"],
            "ring_anchor_point": scaled_anchors(anchors, scale)}


def measure_call(hand: hands.Hand, before: bytes, after: bytes) -> dict:
    a = np.asarray(Image.open(io.BytesIO(after)).convert("RGB"))
    b = np.asarray(Image.open(io.BytesIO(before)).convert("RGB"))
    out = {"result_size": [a.shape[1], a.shape[0]], "input_size": [b.shape[1], b.shape[0]]}
    if a.shape != b.shape:
        a = np.asarray(Image.fromarray(a).resize((b.shape[1], b.shape[0]), Image.LANCZOS))
    f = hand.finger
    mcp, pip = f["axis_px"]
    green = audit.marker_width(a, mcp, pip)
    fp = audit.footprint(b, a, mcp, pip, f["width_px"])
    out.update({"finger_px": f["width_px"], "marker_px": green,
                "observed_ratio": round(green / f["width_px"], 4) if green else None,
                "band_fit": round(fp.band_px / f["width_px"], 3) if fp else None})
    return out


async def run(args):
    s = config.load()
    ledger = youcam.Ledger(s.var / "units.jsonl", day_cap=10_000, session_cap=10_000)
    yc = youcam.YouCam(s.youcam_key, s.var / "tryon", ledger)
    store = hands.HandStore(s.assets / "hands", s.var / "hands",
                            lambda: metrology.MediaPipeHands(str(s.assets / "models" / "hand_landmarker.task")))
    rings = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(args.rings).glob("*.json"))]
    rings = [r for r in rings if r.get("marker")]
    if args.shapes:
        rings = [r for r in rings if r["shape"] in args.shapes.split(",")]
    hand_ids = args.hands.split(",") if args.hands else [r["id"] for r in json.loads(
        (s.assets / "hands" / "index.json").read_text(encoding="utf-8"))]
    RESULTS.mkdir(parents=True, exist_ok=True)
    raw_dir = Path(args.raw)
    raw_dir.mkdir(parents=True, exist_ok=True)
    log = RESULTS / "e3_calls.jsonl"
    done = {(r["hand"], r["ring"]) for r in map(json.loads, log.read_text(encoding="utf-8").splitlines())} \
        if log.exists() else set()
    n = 0
    for hid in hand_ids:
        hand = store.get(hid)
        crop = store.crop(hid)
        for r in rings:
            if (hid, r["name"]) in done:
                continue
            if args.limit and n >= args.limit:
                return
            img = (Path(args.rings) / r["image"]).read_bytes()
            p = params_for(hand.finger, r["anchor_points"])
            key = youcam.YouCam.cache_key({"hand": hid, "ring": r["name"], "params": p})
            t0 = time.time()
            try:
                res = await yc.ring_tryon(crop, [(img, r["image"])], [p], "e3", key)
            except youcam.YouCamError as e:
                row = {"hand": hid, "ring": r["name"], "error": e.code, "message": str(e)}
                print(json.dumps(row), flush=True)
                with log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
                n += 1
                continue
            raw = raw_dir / f"{hid}_{r['name']}.png"
            if not res.cached:
                raw.write_bytes(res.image)
            after = raw.read_bytes() if raw.exists() else res.image
            m = measure_call(hand, crop, after)
            row = {"hand": hid, "ring": r["name"], "shape": r["shape"], "product_ratio": round(
                r["stone_width_mm"] / r["outer_diameter_mm"], 4), "location": p["ring_wearing_location"],
                "task_id": res.task_id, "seconds": res.seconds, "units": res.units, "wall": round(time.time() - t0, 2),
                **m}
            print(json.dumps(row), flush=True)
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            n += 1


def remeasure(args):
    """Re-read the saved renders (no API call) after a change to the hand measurement."""
    s = config.load()
    store = hands.HandStore(s.assets / "hands", s.var / "hands",
                            lambda: metrology.MediaPipeHands(str(s.assets / "models" / "hand_landmarker.task")))
    log = RESULTS / "e3_calls.jsonl"
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    out = []
    for r in rows:
        raw = Path(args.raw) / f"{r['hand']}_{r['ring']}.png"
        if "error" in r or not raw.exists():
            out.append(r)
            continue
        hand = store.get(r["hand"])
        out.append(r | measure_call(hand, store.crop(r["hand"]), raw.read_bytes()))
    with log.open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")


def fit(args):
    """Two models of the rendered stone width (stone / finger, across the finger):

    open loop   observed = k_shape x product_ratio
    per render  observed = c_shape x product_ratio x band_fit, with band_fit measured in the same render

    The service uses the per-render model: band_fit is read from every try-on it returns."""
    rows = [json.loads(x) for x in (RESULTS / "e3_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    ok = [r for r in rows if r.get("observed_ratio")]
    shapes = sorted({r["shape"] for r in ok})
    k = {s: statistics.median([r["observed_ratio"] / r["product_ratio"] for r in ok if r["shape"] == s]) for s in shapes}
    open_res = [abs(r["observed_ratio"] / (k[r["shape"]] * r["product_ratio"]) - 1) for r in ok]
    banded = [r for r in ok if r.get("band_fit") and r["band_fit"] >= BAND_FIT_VALID[0]]
    c = {s: statistics.median([r["observed_ratio"] / (r["product_ratio"] * r["band_fit"]) for r in banded
                                if r["shape"] == s]) for s in shapes}
    res = [abs(r["observed_ratio"] / (c[r["shape"]] * r["product_ratio"] * r["band_fit"]) - 1) for r in banded]
    by_hand = {h: round(statistics.median([r["band_fit"] for r in banded if r["hand"] == h]), 4)
               for h in sorted({r["hand"] for r in banded})}
    within = [abs(r["band_fit"] / by_hand[r["hand"]] - 1) for r in banded]
    targets = sorted({r["product_ratio"] for r in ok})
    mid = statistics.median(targets)

    def pct(xs, q):
        return round(100 * float(np.percentile(xs, q)), 2)

    summary = {
        "calls": len(rows), "measured": len(ok), "errors": len(rows) - len(ok),
        "hands": len({r["hand"] for r in ok}), "rings": len({r["ring"] for r in ok}), "shapes": shapes,
        "seconds_median": round(statistics.median([r["seconds"] for r in ok if r.get("units")] or [0]), 2),
        "open_loop": {"k_by_shape": {s: round(v, 4) for s, v in k.items()},
                      "residual_median_pct": pct(open_res, 50), "residual_p90_pct": pct(open_res, 90),
                      "residual_max_pct": round(100 * max(open_res), 2)},
        "per_render": {"c_by_shape": {s: round(v, 4) for s, v in c.items()}, "renders": len(banded),
                       "excluded_band_hidden": len(ok) - len(banded),
                       "residual_median_pct": pct(res, 50), "residual_p90_pct": pct(res, 90),
                       "residual_max_pct": round(100 * max(res), 2),
                       "within_3pct": sum(x <= 0.03 for x in res), "within_5pct": sum(x <= 0.05 for x in res)},
        "band_fit": {"median": round(statistics.median([r["band_fit"] for r in banded]), 4), "by_hand": by_hand,
                     "within_hand_p90_pct": pct(within, 90)},
        "single_photo_baseline_error_pct": {f"{t:.2f}": round(100 * abs(mid / t - 1), 1) for t in targets},
    }
    (RESULTS / "e3_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if not args.no_write_calibration:
        cal_path = ROOT / "assets" / "calibration.json"
        cal = json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.exists() else {}
        cal.update({"c_by_shape": cal.get("c_by_shape", {}) | summary["per_render"]["c_by_shape"],
                    "band_fit_prior": summary["band_fit"]["median"],
                    "band_fit_by_hand": cal.get("band_fit_by_hand", {}) | by_hand,
                    "residual_p90_pct": summary["per_render"]["residual_p90_pct"],
                    "renders": summary["per_render"]["renders"], "source": "eval/e3_render_scale.py"})
        cal_path.write_text(json.dumps(cal, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rings", default=str(ROOT / "assets" / "rings_marker"))
    ap.add_argument("--hands", default="")
    ap.add_argument("--shapes", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--raw", default=str(ROOT / "var" / "e3_raw"))
    ap.add_argument("--fit-only", action="store_true")
    ap.add_argument("--remeasure", action="store_true", help="re-read every saved render with the current metrology")
    ap.add_argument("--no-write-calibration", action="store_true")
    args = ap.parse_args()
    if args.remeasure:
        remeasure(args)
    elif not args.fit_only:
        asyncio.run(run(args))
    fit(args)


if __name__ == "__main__":
    main()
