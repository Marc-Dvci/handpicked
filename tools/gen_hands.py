"""Generate the sample hand photos with Qwen-Image 2.1 on a local ComfyUI engine.

Each photo is a top-down phone shot of the back of one hand lying on a white A4 sheet: the capture the shopper is
asked for. The generator samples at 1104 x 1472, about 4.5 px per mm on the sheet, above the 3 px/mm the
measurement requires.

    python tools/gen_hands.py --out <dir> [--only h01,h02] [--seeds 2] [--url http://127.0.0.1:8288]

No real person is photographed: every hand in the demo comes from this script.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
import zlib
from pathlib import Path

UNET = "qwen2.1-realism_Base_fp8.safetensors"
CLIP = "qwen3vl_8b_int8_convrot.safetensors"
VAE = "QwenImage21\\qwen_image_2.1_vae_bf16.safetensors"
TURBO_LORA = "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors"
SIZE = (1104, 1472)

SCENE = ("Top-down smartphone photo, camera held straight above. {who} {side} hand, back of the hand facing up, lies "
         "flat on a plain white A4 sheet of printer paper in portrait orientation. The sheet lies on {table}. The "
         "whole sheet is in the frame with all four corners visible and a margin of table around it. The fingers "
         "point to the top of the sheet, straight and spread wide apart like a fan. Every finger is separated from the "
         "next by a clear V-shaped gap of white paper all the way down to the knuckles, including between the "
         "middle finger and the ring finger. The thumb is relaxed, angled out to the side "
         "and lower than the four fingers, as on a normal hand. All five fingers are fully visible and flat on the "
         "paper. The hand is small compared with the sheet, as a real hand is on A4 paper: the palm covers only the "
         "middle third of the sheet's width with wide white margins on both sides, and the fingertips stop well "
         "below the top edge of the sheet. The wrist crosses the bottom edge of the sheet. {nails} No rings, no jewellery, no "
         "watch. {light} Realistic photo, sharp focus, natural skin texture, true colours.")

HANDS = [
    ("h01", "A young woman's slender", "left", "a light oak wooden table", "Short natural nails, no polish.",
     "Soft even daylight from a window."),
    ("h02", "A woman's", "left", "a walnut wooden desk", "Short nails with clear varnish.",
     "Even indoor daylight, faint soft shadow beside the fingers."),
    ("h03", "A man's broad", "left", "a pale grey laminate table", "Short clean nails.",
     "Soft overcast daylight."),
    ("h04", "A Black woman's", "left", "a light oak wooden table", "Short natural nails, no polish.",
     "Soft even daylight from a window."),
    ("h05", "An East Asian woman's small", "left", "a white-washed pine table", "Short natural nails.",
     "Even indoor daylight."),
    ("h06", "A South Asian man's", "left", "a dark wooden kitchen table", "Short clean nails.",
     "Warm late afternoon daylight, soft shadow."),
    ("h07", "An older woman's", "left", "a light oak wooden table", "Short nails, no polish.",
     "Soft even daylight from a window."),
    ("h08", "A young man's", "right", "a concrete-grey desk", "Short clean nails.",
     "Even indoor daylight."),
    ("h09", "A Latina woman's", "left", "a medium brown wooden table", "Short nails with nude polish.",
     "Soft daylight, faint shadow to the right."),
    ("h10", "A Black man's", "left", "a pale grey laminate table", "Short clean nails.",
     "Soft overcast daylight."),
    ("h11", "A freckled red-haired woman's", "left", "a light oak wooden table", "Short natural nails.",
     "Soft even daylight from a window."),
    ("h12", "A Middle Eastern woman's", "left", "a walnut wooden desk", "Short nails, no polish.",
     "Even indoor daylight."),
]


def prompt_for(row) -> str:
    _, who, side, table, nails, light = row
    return SCENE.format(who=who, side=side, table=table, nails=nails, light=light)


def graph(prompt: str, seed: int, prefix: str) -> dict:
    w, h = SIZE
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "30": {"class_type": "ViggleTurboLora", "inputs": {"model": ["1", 0], "lora_name": TURBO_LORA, "strength": 1.0}},
        "2": {"class_type": "QwenImage21Cache", "inputs": {"model": ["30", 0], "device": "auto", "dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "5": {"class_type": "TextEncodeQwenImage21",
              "inputs": {"clip": ["3", 0], "prompt": prompt, "negative_prompt": "", "resolution": 1024}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "31": {"class_type": "BasicGuider", "inputs": {"model": ["2", 0], "conditioning": ["5", 0]}},
        "32": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "33": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "34": {"class_type": "ViggleTurboSigmas",
               "inputs": {"latent": ["6", 0], "nodes": "1.0, 0.9375, 0.875, 0.75, 0.5, 0.25"}},
        "7": {"class_type": "SamplerCustomAdvanced",
              "inputs": {"noise": ["32", 0], "guider": ["31", 0], "sampler": ["33", 0], "sigmas": ["34", 0],
                         "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["7", 0], "vae": ["4", 0], "tile_size": 512,
                                                         "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }


class Comfy:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.client_id = "hp-" + uuid.uuid4().hex[:8]

    def _json(self, method, path, payload=None, timeout=60):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def run(self, g: dict, timeout: float = 1800) -> bytes:
        r = self._json("POST", "/prompt", {"prompt": g, "client_id": self.client_id})
        if r.get("node_errors"):
            raise RuntimeError(json.dumps(r["node_errors"])[:1500])
        pid, start = r["prompt_id"], time.time()
        while time.time() - start < timeout:
            h = self._json("GET", f"/history/{pid}")
            if h and pid in h:
                entry = h[pid]
                if entry.get("status", {}).get("status_str") == "error":
                    raise RuntimeError(json.dumps(entry["status"])[:1500])
                for out in entry.get("outputs", {}).values():
                    for im in out.get("images", []):
                        q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                                    "type": im.get("type", "output")})
                        with urllib.request.urlopen(f"{self.url}/view?{q}", timeout=120) as resp:
                            return resp.read()
                raise RuntimeError("no image in outputs")
            time.sleep(1.0)
        raise TimeoutError(pid)


# command that starts a headless ComfyUI with the models above, e.g. "<python> <ComfyUI>/main.py --port 8288"
ENGINE_CMD = os.environ.get("HANDPICKED_COMFY_CMD", "")


def engine_up(url: str) -> bool:
    try:
        urllib.request.urlopen(url + "/system_stats", timeout=2).read()
        return True
    except OSError:
        return False


def start_engine(url: str, log: Path):
    if not ENGINE_CMD:
        raise RuntimeError("the engine is not running; set HANDPICKED_COMFY_CMD to let the script start it")
    args = shlex.split(ENGINE_CMD, posix=False)
    proc = subprocess.Popen([a.strip('"') for a in args], stdout=log.open("a"), stderr=subprocess.STDOUT,
                            cwd=str(Path(args[-1].strip('"')).parent))
    for _ in range(200):
        if engine_up(url):
            return proc
        if proc.poll() is not None:
            raise RuntimeError("engine exited during start")
        time.sleep(2)
    raise TimeoutError("engine did not start")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8288")
    ap.add_argument("--only", default="")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--seed-offset", type=int, default=0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = {s for s in args.only.split(",") if s}
    comfy = Comfy(args.url)
    index = []
    for row in HANDS:
        hid = row[0]
        if only and hid not in only:
            continue
        prompt = prompt_for(row)
        for k in range(args.seed_offset, args.seed_offset + args.seeds):
            name = f"{hid}_s{k}"
            seed = zlib.crc32(name.encode()) % (2 ** 31)
            path = out / f"{name}.png"
            for _ in range(3):
                if path.exists():
                    break
                if not engine_up(args.url):
                    start_engine(args.url, out / "engine.log")
                t0 = time.time()
                try:
                    path.write_bytes(comfy.run(graph(prompt, seed, f"handpicked/{name}")))
                    print(f"{name} {time.time() - t0:5.1f}s", flush=True)
                except (OSError, RuntimeError) as e:
                    print(f"{name} failed ({e}); restarting the engine", flush=True)
                    time.sleep(5)
            index.append({"id": name, "hand": hid, "seed": seed, "side": row[2], "prompt": prompt,
                          "model": UNET, "lora": TURBO_LORA})
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
