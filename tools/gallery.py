"""Build the Devpost gallery: 2400 x 1600 white frames from the product captures, in the gallery's fixed order.

    node web/scripts/capture.mjs <captures>          # real product at 2x, plus the two figures
    python tools/gallery.py --captures <captures> [--out docs/gallery]

Each frame holds real screenshots only (cut from the running app) or a figure drawn from the repository's data.
Captions live in docs/gallery/CAPTIONS.md, one per image; the build refuses a caption over 140 characters (Devpost's
limit) or an image without a caption. Image 01 is the cover, made separately.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
W, H, MARGIN = 2400, 1600, 90
RULE = (217, 220, 226)

# file name -> list of captures, stacked top to bottom
FRAMES = {
    "02-problem": ["problem"],
    "03-main-screen": ["hero"],
    "04-measure": ["measure"],
    "05-listings-read": ["readings"],
    "06-board": ["board"],
    "07-on-the-hand": ["tryon"],
    "08-results": ["ev-E1", "ev-E3", "ev-E4"],
    "09-architecture": ["architecture"],
    "10-youcam-api": ["sponsor-docs"],
    "11-safety": ["waiting"],
    "12-jewellers": ["jewellers-top"],
}
FULL_BLEED = {"problem", "architecture"}


def stack(images: list[Image.Image], gap: int = 0) -> Image.Image:
    w = max(i.width for i in images)
    out = Image.new("RGB", (w, sum(i.height for i in images) + gap * (len(images) - 1)), "white")
    y = 0
    for i in images:
        out.paste(i, (0, y))
        y += i.height + gap
    return out


def frame(img: Image.Image, border: bool = True) -> Image.Image:
    canvas = Image.new("RGB", (W, H), "white")
    k = min((W - 2 * MARGIN) / img.width, (H - 2 * MARGIN) / img.height, 1.5)   # captures are 2x: 1.5 stays sharp
    im = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    x, y = (W - im.width) // 2, (H - im.height) // 2
    canvas.paste(im, (x, y))
    if border:
        ImageDraw.Draw(canvas).rectangle([x - 1, y - 1, x + im.width, y + im.height], outline=RULE, width=2)
    return canvas


def captions(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(\d\d-[\w-]+)\.png\s*\|\s*(.+?)\s*\|$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--captures", required=True)
    ap.add_argument("--out", default=str(ROOT / "docs" / "gallery"))
    args = ap.parse_args()
    cap, out = Path(args.captures), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    caps = captions(out / "CAPTIONS.md")
    bad = [f"{k}: {len(v)} characters" for k, v in caps.items() if len(v) > 140]
    missing = [k for k in FRAMES if k not in caps]
    if bad or missing:
        print("captions over 140 characters:", bad, "\nimages without a caption:", missing)
        return 1
    jew = cap / "jewellers.png"
    if jew.exists():   # the top of the jeweller page: form, callout and the first rows
        j = Image.open(jew).convert("RGB")
        j.crop((0, 0, j.width, min(j.height, round(j.width * 0.92)))).save(cap / "jewellers-top.png")
    for name, parts in FRAMES.items():
        imgs = [Image.open(cap / f"{p}.png").convert("RGB") for p in parts]
        img = stack(imgs, gap=0)
        full = parts[0] in FULL_BLEED
        result = img.resize((W, H), Image.LANCZOS) if full and img.size != (W, H) else (img if full else frame(img))
        result.save(out / f"{name}.png", optimize=True)
        print(f"{name}.png  {caps[name]}  ({len(caps[name])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
