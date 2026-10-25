"""Hand photos: normalise an upload, measure it once, and derive the two images the rest of the app uses.

* The try-on input: the hand cropped from the photo with a margin, so the Ring VTO sees the back of the hand
  large in frame. Landmarks and measurement lines are kept in this crop's pixel coordinates.
* The view: a rotated window centred on the ring position with the finger pointing up, used to show the bare
  finger and every try-on side by side at the same scale.

Uploads are re-encoded without their EXIF block (location, device), after the focal length has been read.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import fit, metrology

MAX_SIDE = 4032          # the Ring VTO accepts up to 4096 px on the long side
CROP_MARGIN = 0.28       # around the landmarks' bounding box, as a fraction of its larger side
VIEW_W, VIEW_H = 3.4, 4.2  # view size in finger widths


@dataclass
class View:
    cx: float
    cy: float
    angle: float          # degrees; rotating the crop by this puts the finger axis upright
    w: int
    h: int

    def matrix(self) -> np.ndarray:
        M = cv2.getRotationMatrix2D((self.cx, self.cy), self.angle, 1.0)
        M[0, 2] += self.w / 2 - self.cx
        M[1, 2] += self.h / 2 - self.cy
        return M

    def apply(self, pts) -> list:
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        M = self.matrix()
        return (p @ M[:, :2].T + M[:, 2]).round(1).tolist()

    def render(self, rgb: np.ndarray) -> np.ndarray:
        return cv2.warpAffine(rgb, self.matrix(), (self.w, self.h), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)


@dataclass
class Hand:
    id: str
    sample: bool
    focal_35mm: float
    focal_source: str
    image_size: list
    crop_box: list                 # [x0, y0, x1, y1] in the photo
    landmarks: list                # 21 points in crop pixels
    measure: dict                  # metrology.HandMeasure.as_dict(), coordinates in photo pixels
    finger: dict                   # ring finger, coordinates in crop pixels
    fit: dict
    view: dict
    created: float

    def as_public(self) -> dict:
        d = asdict(self)
        d.pop("landmarks")
        return d


def normalise(data: bytes) -> tuple[bytes, float, str]:
    """Upright RGB JPEG without EXIF, at most MAX_SIDE px; returns (jpeg, focal_35mm, focal source)."""
    focal, source = metrology.focal_from_exif(data)
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:  # noqa: BLE001 - any decoder error means the upload is not a photo we can read
        raise metrology.MeasureError("not_an_image", "The file could not be read as a photo.") from e
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue(), focal, source


def crop_box(landmarks: np.ndarray, size: tuple) -> list:
    w, h = size
    x0, y0 = landmarks.min(0)
    x1, y1 = landmarks.max(0)
    pad = CROP_MARGIN * max(x1 - x0, y1 - y0)
    return [int(max(0, x0 - pad)), int(max(0, y0 - pad)), int(min(w, x1 + pad)), int(min(h, y1 + pad))]


def make_view(finger: dict) -> View:
    """Window centred on the ring position, finger pointing up, sized in finger widths."""
    (mx, my), (px, py) = finger["axis_px"]
    t = finger["wearing_location"]
    cx, cy = mx + t * (px - mx), my + t * (py - my)
    angle = math.degrees(math.atan2(px - mx, -(py - my)))   # rotate the MCP->PIP direction onto "up"
    (lx0, ly0), (lx1, ly1) = finger["line_px"]
    fpx = math.hypot(lx1 - lx0, ly1 - ly0)
    return View(round(cx, 1), round(cy, 1), round(angle, 2), int(VIEW_W * fpx), int(VIEW_H * fpx))


def _shift(points, dx, dy):
    return [[round(x - dx, 1), round(y - dy, 1)] for x, y in points]


def build(hand_id: str, photo: bytes, focal: float, source: str, detector, sample: bool = False) -> tuple[Hand, bytes]:
    """Measure a normalised photo; returns the hand record and the try-on input (JPEG crop)."""
    rgb = np.asarray(Image.open(io.BytesIO(photo)).convert("RGB"))
    lms = detector(rgb)
    if lms is None:
        raise metrology.MeasureError("no_hand", "No hand found. Lay the back of the hand flat on the sheet, "
                                                "fingers apart.")
    m = metrology.measure(rgb, lms, focal, source)
    h, w = rgb.shape[:2]
    box = crop_box(lms, (w, h))
    x0, y0, x1, y1 = box
    crop = rgb[y0:y1, x0:x1]
    buf = io.BytesIO()
    Image.fromarray(crop).save(buf, "JPEG", quality=92)
    f = m.as_dict()["fingers"]["ring"]
    fc = dict(f)
    for k in ("line_px", "knuckle_line_px", "axis_px"):
        fc[k] = _shift(f[k], x0, y0) if f[k] else []
    fc["width_px"] = round(math.dist(*fc["line_px"]), 2)
    view = make_view(fc)
    size = fit.ring_size(f["width_mm"], f["knuckle_mm"])
    hand = Hand(hand_id, sample, focal, source, [w, h], box, _shift(lms.tolist(), x0, y0), m.as_dict(), fc,
                size.as_dict(), asdict(view), time.time())
    return hand, buf.getvalue()


def _plain(o):
    """numpy scalars from the measurement, as JSON values."""
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(type(o).__name__)


def photo_id(photo: bytes) -> str:
    return hashlib.sha256(photo).hexdigest()[:16]


class HandStore:
    """Sample hands ship in assets/hands; uploads live under var/hands/<id> and expire after `ttl` seconds."""

    def __init__(self, samples_dir: Path, var_dir: Path, detector_factory, ttl: float = 24 * 3600):
        self.samples_dir, self.var_dir, self.ttl = Path(samples_dir), Path(var_dir), ttl
        self.var_dir.mkdir(parents=True, exist_ok=True)
        self._detector_factory = detector_factory
        self._detector = None
        self._cache: dict[str, Hand] = {}

    @property
    def detector(self):
        if self._detector is None:
            self._detector = self._detector_factory()
        return self._detector

    def _dir(self, hand_id: str) -> Path:
        return self.var_dir / hand_id

    def samples(self) -> list[dict]:
        idx = json.loads((self.samples_dir / "index.json").read_text(encoding="utf-8"))
        return [self.get(r["id"]).as_public() | {"photo": f"/api/hands/{r['id']}/photo.jpg"} for r in idx]

    def _sample_paths(self, hand_id: str):
        photo = self.samples_dir / f"{hand_id}.jpg"
        return (photo, self._dir(hand_id)) if photo.exists() else (None, None)

    def get(self, hand_id: str) -> Hand:
        if hand_id in self._cache:
            return self._cache[hand_id]
        if not hand_id.replace("-", "").isalnum():
            raise KeyError(hand_id)
        sample_photo, _ = self._sample_paths(hand_id)
        d = self._dir(hand_id)
        meta = d / "hand.json"
        if not meta.exists():
            if sample_photo is None:
                raise KeyError(hand_id)
            photo = sample_photo.read_bytes()
            hand, crop = build(hand_id, photo, metrology.DEFAULT_FOCAL_35MM, "default", self.detector, sample=True)
            d.mkdir(parents=True, exist_ok=True)
            (d / "crop.jpg").write_bytes(crop)
            meta.write_text(json.dumps(asdict(hand), default=_plain), encoding="utf-8")
        hand = Hand(**json.loads(meta.read_text(encoding="utf-8")))
        self._cache[hand_id] = hand
        return hand

    def add(self, upload: bytes) -> Hand:
        photo, focal, source = normalise(upload)
        hand_id = "u" + photo_id(photo)
        d = self._dir(hand_id)
        if (d / "hand.json").exists():
            return self.get(hand_id)
        hand, crop = build(hand_id, photo, focal, source, self.detector)
        d.mkdir(parents=True, exist_ok=True)
        (d / "photo.jpg").write_bytes(photo)
        (d / "crop.jpg").write_bytes(crop)
        (d / "hand.json").write_text(json.dumps(asdict(hand), default=_plain), encoding="utf-8")
        self._cache[hand_id] = hand
        return hand

    def photo(self, hand_id: str) -> bytes:
        sample_photo, _ = self._sample_paths(hand_id)
        if sample_photo is not None:
            return sample_photo.read_bytes()
        return (self._dir(hand_id) / "photo.jpg").read_bytes()

    def crop(self, hand_id: str) -> bytes:
        self.get(hand_id)
        return (self._dir(hand_id) / "crop.jpg").read_bytes()

    def view_image(self, hand_id: str, image: bytes | None = None) -> bytes:
        """The view window over the bare crop, or over a try-on result of the same crop."""
        hand = self.get(hand_id)
        src = image if image is not None else self.crop(hand_id)
        rgb = np.asarray(Image.open(io.BytesIO(src)).convert("RGB"))
        x0, y0, x1, y1 = hand.crop_box
        if rgb.shape[1] != x1 - x0 or rgb.shape[0] != y1 - y0:
            rgb = cv2.resize(rgb, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
        out = View(**hand.view).render(rgb)
        buf = io.BytesIO()
        Image.fromarray(out).save(buf, "JPEG", quality=90)
        return buf.getvalue()

    def expire(self) -> int:
        n = 0
        now = time.time()
        for d in self.var_dir.glob("u*"):
            meta = d / "hand.json"
            if meta.exists() and now - meta.stat().st_mtime > self.ttl:
                for f in d.iterdir():
                    f.unlink()
                d.rmdir()
                self._cache.pop(d.name, None)
                n += 1
        return n
