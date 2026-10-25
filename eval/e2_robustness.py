"""E2: does the finger width hold when the same hand is captured differently?

Each sample hand photo is re-encoded, rescaled, rotated, re-lit, blurred and given sensor noise, and measured again
through the same path as an upload (`metrology.measure_photo`, MediaPipe landmarks, no EXIF). The change in finger
width against the original photo is the measure; a refusal (a capture check failing) is counted, not hidden.

    python eval/e2_robustness.py [--hands hand-1,hand-2]

Writes eval/results/e2_robustness.jsonl (one row per variant) and eval/results/e2_summary.json.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handpicked import fit, metrology  # noqa: E402

RESULTS = ROOT / "eval" / "results"


def jpeg(im: Image.Image, q: int = 92) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return buf.getvalue()


def noise(im: Image.Image, sigma: float, seed: int) -> Image.Image:
    a = np.asarray(im).astype(np.float32)
    a += np.random.default_rng(seed).normal(0, sigma, a.shape)
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def warm(im: Image.Image, k: float) -> Image.Image:
    a = np.asarray(im).astype(np.float32)
    a[..., 0] *= 1 + k
    a[..., 2] *= 1 - k
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def rotate(im: Image.Image, deg: float) -> Image.Image:
    edge = tuple(int(x) for x in np.asarray(im)[:8].reshape(-1, 3).mean(0))   # table colour fills the corners
    return im.rotate(deg, resample=Image.BICUBIC, expand=True, fillcolor=edge)


def scale(im: Image.Image, k: float) -> Image.Image:
    return im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)


VARIANTS = {   # family: [(name, function)]
    "re-encode": [("JPEG quality 60", lambda im, s: jpeg(im, 60)), ("JPEG quality 35", lambda im, s: jpeg(im, 35))],
    "rescale": [("75% size", lambda im, s: jpeg(scale(im, 0.75))), ("upscaled 150%", lambda im, s: jpeg(scale(im, 1.5)))],
    "rotate": [("rotated 90°", lambda im, s: jpeg(im.transpose(Image.Transpose.ROTATE_90))),
               ("rotated 7°", lambda im, s: jpeg(rotate(im, 7)))],
    "relight": [("30% darker", lambda im, s: jpeg(ImageEnhance.Brightness(im).enhance(0.7))),
                ("15% brighter", lambda im, s: jpeg(ImageEnhance.Brightness(im).enhance(1.15))),
                ("warm white balance", lambda im, s: jpeg(warm(im, 0.08))),
                ("lower contrast", lambda im, s: jpeg(ImageEnhance.Contrast(im).enhance(0.75)))],
    "blur and noise": [("slight defocus", lambda im, s: jpeg(im.filter(ImageFilter.GaussianBlur(1.2)))),
                       ("sensor noise", lambda im, s: jpeg(noise(im, 5.0, s)))],
}


def pct(xs, q):
    return round(float(np.percentile(xs, q)), 3) if xs else None


def main(args):
    detector = metrology.MediaPipeHands(str(ROOT / "assets" / "models" / "hand_landmarker.task"))
    idx = json.loads((ROOT / "assets" / "hands" / "index.json").read_text(encoding="utf-8"))
    hand_ids = args.hands.split(",") if args.hands else [r["id"] for r in idx]
    rows = []
    for k, hid in enumerate(hand_ids):
        data = (ROOT / "assets" / "hands" / f"{hid}.jpg").read_bytes()
        base = metrology.measure_photo(data, detector).fingers["ring"]
        base_size = fit.ring_size(base.width_mm, base.knuckle_mm).us
        im = Image.open(io.BytesIO(data)).convert("RGB")
        for family, variants in VARIANTS.items():
            for name, make in variants:
                row = {"hand": hid, "family": family, "variant": name, "base_mm": round(base.width_mm, 3)}
                try:
                    f = metrology.measure_photo(make(im, k), detector).fingers["ring"]
                    size = fit.ring_size(f.width_mm, f.knuckle_mm).us
                    row |= {"width_mm": round(f.width_mm, 3), "change_mm": round(f.width_mm - base.width_mm, 3),
                            "us": size, "us_change": size - base_size}
                except metrology.MeasureError as e:
                    row |= {"refused": e.code}
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    detector.close()
    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / "e2_robustness.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    ok = [r for r in rows if "change_mm" in r]
    ch = [abs(r["change_mm"]) for r in ok]
    by = {}
    for family in VARIANTS:
        fr = [r for r in rows if r["family"] == family]
        fo = [abs(r["change_mm"]) for r in fr if "change_mm" in r]
        by[family] = {"n": len(fo), "refused": len(fr) - len(fo), "median_abs_change_mm": pct(fo, 50),
                      "max_abs_change_mm": round(max(fo), 3) if fo else None}
    summary = {
        "description": f"{len(hand_ids)} sample hands, each captured {sum(len(v) for v in VARIANTS.values())} more ways "
                       "(re-encoded, rescaled, rotated, re-lit, blurred, noisy) and measured again as an upload.",
        "hands": len(hand_ids), "variants": len(rows), "measured": len(ok), "refused": len(rows) - len(ok),
        "median_abs_change_mm": pct(ch, 50), "p90_abs_change_mm": pct(ch, 90), "max_abs_change_mm": round(max(ch), 3),
        "size_changed": sum(abs(r["us_change"]) > 0.5 for r in ok),
        "size_moved_half": sum(abs(r["us_change"]) == 0.5 for r in ok),
        "by_transform": by,
    }
    before = RESULTS / "before" / "e2_summary_before.json"
    if before.exists():   # the same run before failed capture checks were enforced and the sheet search was widened
        b = json.loads(before.read_text(encoding="utf-8"))
        summary["before"] = {k: b[k] for k in ("measured", "refused", "median_abs_change_mm", "p90_abs_change_mm",
                                                "max_abs_change_mm", "size_changed")}
    (RESULTS / "e2_summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", default="")
    main(ap.parse_args())
