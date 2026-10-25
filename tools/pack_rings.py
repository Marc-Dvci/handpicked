"""Pack the Blender ring renders into the library the service ships with.

Each 1024 px RGBA render is composited on white and saved as a 768 px JPEG (the Ring VTO takes jpg/png up to
4096 px; 768 px keeps the library small). Pixel coordinates in the metadata are scaled to the new size.

    python tools/pack_rings.py --src <render dir> --out assets/rings [--size 768]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

PIXEL_FIELDS = ("anchor_points", "inner_edge_px", "outer_edge_px", "stone_px")


def scale_points(v, k):
    if isinstance(v, (int, float)):
        return round(v * k, 2)
    return [scale_points(x, k) for x in v]


def pack(src: Path, out: Path, size: int) -> int:
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for meta_path in sorted(src.glob("*.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        img = Image.open(src / meta["image"]).convert("RGBA")
        k = size / img.width
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        white.alpha_composite(img)
        rgb = white.convert("RGB").resize((size, round(img.height * k)), Image.LANCZOS)
        name = meta["name"] + ".jpg"
        rgb.save(out / name, "JPEG", quality=90, optimize=True)
        for f in PIXEL_FIELDS:
            if f in meta:
                meta[f] = scale_points(meta[f], k)
        if "anchor_points" in meta:
            meta["anchor_points"] = [[int(round(x)), int(round(y))] for x, y in meta["anchor_points"]]
        if "px_per_mm" in meta:
            meta["px_per_mm"] = round(meta["px_per_mm"] * k, 5)
        meta["image"], meta["resolution"] = name, size
        (out / meta_path.name).write_text(json.dumps(meta, indent=1), encoding="utf-8")
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=768)
    args = ap.parse_args()
    print(pack(Path(args.src), Path(args.out), args.size), "rings packed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
