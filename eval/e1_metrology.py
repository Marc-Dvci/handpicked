"""E1: how accurately does metrology.py measure the ring finger's width, against the renders of known geometry?

`tools/render_bench.py` writes bench_XXX.png with bench_XXX.json (ground truth). This runs `metrology.measure` on each
photo with the two ring-finger landmarks (13 = MCP, 14 = PIP) and compares the result with the rendered width.

    python eval/e1_metrology.py --bench <dir> [--focal exif|default]

`--focal exif` (default) passes the focal length the render was made with, as an EXIF 35 mm-equivalent would.
`--focal default` passes metrology.DEFAULT_FOCAL_35MM, as for a photo without EXIF.

Writes eval/results/e1_metrology_{focal}[_{tag}].jsonl (one row per case) and eval/results/e1_summary_{focal}[_{tag}].json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handpicked import metrology  # noqa: E402

RESULTS = ROOT / "eval" / "results"


def pct(a: np.ndarray, q: float) -> float:
    return float(np.percentile(a, q))


def abs_stats(err: list[float]) -> dict:
    if not err:
        return {"n": 0}
    e = np.asarray(err, dtype=np.float64)
    a = np.abs(e)
    return {
        "n": int(e.size),
        "mean_error_mm": round(float(e.mean()), 3),
        "median_abs_error_mm": round(float(np.median(a)), 3),
        "p90_abs_error_mm": round(pct(a, 90), 3),
        "p95_abs_error_mm": round(pct(a, 95), 3),
        "max_abs_error_mm": round(float(a.max()), 3),
    }


def measure_case(meta: dict, rgb: np.ndarray, focal_mode: str) -> dict:
    lm = np.zeros((21, 2), dtype=np.float64)
    lm[13] = meta["landmarks_px"]["13"]
    lm[14] = meta["landmarks_px"]["14"]
    if focal_mode == "exif":
        focal, source = float(meta["focal_35mm"]), "exif"
    else:
        focal, source = metrology.DEFAULT_FOCAL_35MM, "default"
    row = {
        "case": meta["case"],
        "ring_width_mm": meta["ring_width_mm"],
        "knuckle_width_mm": meta["knuckle_width_mm"],
        "camera_height_mm": meta["camera_height_mm"],
        "tilt_true_deg": meta["tilt_deg"],
        "focal_35mm_used": focal,
        "focal_source": source,
    }
    try:
        out = metrology.measure(rgb, lm, focal, source)
    except metrology.MeasureError as e:
        row.update(measured=False, refused_code=e.code, refused_message=str(e))
        return row
    f = out.fingers["ring"]
    row.update(
        measured=True,
        refused_code=None,
        width_mm=f.width_mm,
        raw_width_mm=f.raw_width_mm,
        knuckle_mm=f.knuckle_mm,
        spread_mm=f.spread_mm,
        samples=f.samples,
        camera_distance_mm=out.camera_distance_mm,
        tilt_deg=out.tilt_deg,
        sheet_corners_px=out.sheet_corners_px,
        err_width_mm=round(f.width_mm - meta["ring_width_mm"], 3),
        err_raw_mm=round(f.raw_width_mm - meta["ring_width_mm"], 3),
        err_knuckle_mm=round(f.knuckle_mm - meta["knuckle_width_mm"], 3),
        err_camera_distance_mm=round(out.camera_distance_mm - meta["camera_height_mm"], 3),
    )
    return row


def summarise(rows: list[dict], focal_mode: str) -> dict:
    measured = [r for r in rows if r["measured"]]
    refused: dict[str, int] = {}
    for r in rows:
        if not r["measured"]:
            refused[r["refused_code"]] = refused.get(r["refused_code"], 0) + 1
    return {
        "focal": focal_mode,
        "n_cases": len(rows),
        "n_measured": len(measured),
        "n_refused": len(rows) - len(measured),
        "refused_by_code": refused,
        "width_corrected": abs_stats([r["err_width_mm"] for r in measured]),
        "width_raw": abs_stats([r["err_raw_mm"] for r in measured]),
        "knuckle": abs_stats([r["err_knuckle_mm"] for r in measured]),
        "camera_distance": abs_stats([r["err_camera_distance_mm"] for r in measured]),
    }


def print_summary(s: dict) -> None:
    print(f"focal={s['focal']}  cases={s['n_cases']}  measured={s['n_measured']}  refused={s['n_refused']}"
          f"  refused_by_code={s['refused_by_code']}")
    for key, label in (("width_corrected", "width (height-corrected)"), ("width_raw", "width (raw)"),
                       ("knuckle", "knuckle"), ("camera_distance", "camera distance")):
        st = s[key]
        if st.get("n", 0) == 0:
            print(f"  {label}: no measured cases")
            continue
        print(f"  {label}: mean {st['mean_error_mm']:+.3f}  median|e| {st['median_abs_error_mm']:.3f}  "
              f"p90|e| {st['p90_abs_error_mm']:.3f}  p95|e| {st['p95_abs_error_mm']:.3f}  "
              f"max|e| {st['max_abs_error_mm']:.3f} mm")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True, help="directory with bench_XXX.png and bench_XXX.json")
    ap.add_argument("--focal", choices=("exif", "default"), default="exif")
    ap.add_argument("--tag", default="", help="suffix for the result files, e.g. heldout")
    args = ap.parse_args()

    bench = Path(args.bench).resolve()
    jsons = sorted(bench.glob("bench_*.json"))
    if not jsons:
        raise SystemExit(f"no bench_*.json in {bench}")
    rows = []
    for jp in jsons:
        meta = json.loads(jp.read_text(encoding="utf-8"))
        png = jp.with_suffix(".png")
        rgb = np.asarray(Image.open(png).convert("RGB"))
        row = measure_case(meta, rgb, args.focal)
        row["file"] = png.name
        rows.append(row)
        status = (f"width {row['width_mm']:.2f} (true {row['ring_width_mm']:.2f}, err {row['err_width_mm']:+.2f})"
                  if row["measured"] else f"refused: {row['refused_code']}")
        print(f"{png.name}: {status}", flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    with open(RESULTS / f"e1_metrology_{args.focal}{args.tag and '_' + args.tag}.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    summary = summarise(rows, args.focal)
    with open(RESULTS / f"e1_summary_{args.focal}{args.tag and '_' + args.tag}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print_summary(summary)


if __name__ == "__main__":
    main()
