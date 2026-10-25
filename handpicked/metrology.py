"""Measure a finger from one photo of the hand lying on an A4 sheet.

1. Find the sheet: the brightest low-chroma region, its convex hull, and a line fit to each side, so the
   corners stay exact where the wrist covers part of an edge.
2. Map the image onto the sheet plane in millimetres (homography).
3. Take the finger's axis from hand landmarks, cast profiles across it, and find both skin-to-paper edges on
   chroma, which shadows on the paper do not change.
4. Correct for parallax: the finger's silhouette edges sit above the paper, so their rays land wider on the sheet.
   The camera's position comes from the homography and the focal length; the finger's cross-section is taken as an
   ellipse (depth = FINGER_DEPTH_RATIO x width) and its width is solved so that its two silhouette rays land on the
   measured edges. Straight above the finger this is the familiar Z / (Z - h) factor; from the side it also
   accounts for the finger's flank the camera sees.

All lengths are millimetres on the sheet plane unless a name ends in `_px`.
"""
from __future__ import annotations

import io
import math
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np
from PIL import Image

A4 = (210.0, 297.0)
PX_PER_MM = 10.0            # rectified sampling resolution
FINGER_DEPTH_RATIO = 0.95   # finger depth / width at the proximal ring-finger joint (AIST hand data, see docs/METHOD.md)
DEFAULT_FOCAL_35MM = 26.0   # typical phone main camera when the photo carries no EXIF focal length

GAP_MM = 0.8                # paper must follow an edge for this long
SEARCH_PAST_MM = 1.0        # the steepest-drop search runs this far past the midpoint crossing
DROP_PER_MM = 4.0           # an edge falls at least this fast in chroma per mm
MIN_WIDTH_MM, MAX_WIDTH_MM = 9.0, 26.0
WINDOW = 7                  # profiles in the ring-position window, 2% of the MCP-PIP span apart

# MediaPipe hand landmark indices: (MCP, PIP) per finger
FINGERS = {"index": (5, 6), "middle": (9, 10), "ring": (13, 14), "little": (17, 18)}
VTO_FINGER = {"thumb": 0, "index": 1, "middle": 2, "ring": 3, "little": 4}


class MeasureError(ValueError):
    """The photo cannot be measured; `code` names the capture check that failed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class FingerMeasure:
    name: str
    width_mm: float               # dorsal width at the ring position, height-corrected
    knuckle_mm: float             # width across the middle joint, height-corrected
    raw_width_mm: float           # before the height correction
    samples: int
    spread_mm: float              # max - min of the per-profile widths (consistency)
    line_px: list                 # [[x0, y0], [x1, y1]] measurement line in image pixels
    knuckle_line_px: list
    axis_px: list                 # [[x_mcp, y_mcp], [x_pip, y_pip]]
    wearing_location: float       # 0 = base of the finger, 1 = first knuckle (YouCam ring_wearing_location)


@dataclass
class HandMeasure:
    image_size: tuple
    sheet_corners_px: list
    px_per_mm: float              # original-image pixels per mm on the sheet, at the finger
    camera_distance_mm: float
    tilt_deg: float
    focal_35mm: float
    focal_source: str
    fingers: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)

    def as_dict(self):
        d = asdict(self)
        d["fingers"] = {k: asdict(v) if not isinstance(v, dict) else v for k, v in self.fingers.items()}
        return d


# ----------------------------------------------------------------------------------------------- sheet
def find_sheet(rgb: np.ndarray) -> np.ndarray:
    """Return the 4 sheet corners (float32, image px) ordered TL, TR, BR, BL in the sheet's own frame."""
    h, w = rgb.shape[:2]
    scale = 1600.0 / max(h, w) if max(h, w) > 1600 else 1.0
    small = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, a, b = lab[..., 0], lab[..., 1] - 128, lab[..., 2] - 128
    chroma = np.sqrt(a * a + b * b)
    Lc = L[chroma < 14]
    if Lc.size < 1000:
        raise MeasureError("no_sheet", "No white sheet found in the photo.")
    thr, _ = cv2.threshold(Lc.astype(np.uint8).reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    paper = ((L > max(thr, 150)) & (chroma < 14)).astype(np.uint8) * 255
    paper = cv2.morphologyEx(paper, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab_img, stats, _ = cv2.connectedComponentsWithStats(paper, 8)
    if n < 2:
        raise MeasureError("no_sheet", "No white sheet found in the photo.")
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[k, cv2.CC_STAT_AREA] < 0.04 * paper.size:
        raise MeasureError("sheet_too_small", "The sheet covers too little of the photo; move closer.")
    region = (lab_img == k).astype(np.uint8)
    cnts, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cnt = max(cnts, key=cv2.contourArea)
    hull = cv2.convexHull(cnt)
    quad = None
    peri = cv2.arcLength(hull, True)
    for eps in (0.01, 0.015, 0.02, 0.03, 0.04, 0.05):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            quad = approx.reshape(4, 2).astype(np.float32)
            break
    if quad is None:
        raise MeasureError("sheet_corners", "All four corners of the sheet must be visible.")
    quad = _refine_corners(cnt.reshape(-1, 2).astype(np.float32), quad)
    border = 3.0
    if (quad[:, 0] < border).any() or (quad[:, 1] < border).any() or (quad[:, 0] > small.shape[1] - border).any() \
            or (quad[:, 1] > small.shape[0] - border).any():
        raise MeasureError("sheet_cut", "The sheet runs off the edge of the photo.")
    return _order_long_vertical(quad / scale)


def _refine_corners(contour: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Fit a line to the contour points along each side (excluding the parts near corners and where the
    contour leaves the side, e.g. around the wrist), then intersect neighbouring lines."""
    lines = []
    for i in range(4):
        p, q = quad[i], quad[(i + 1) % 4]
        d = q - p
        length = float(np.hypot(*d))
        if length < 1:
            return quad
        u = d / length
        nrm = np.array([-u[1], u[0]])
        rel = contour - p
        along = rel @ u
        off = rel @ nrm
        sel = (along > 0.08 * length) & (along < 0.92 * length) & (np.abs(off) < max(2.5, 0.004 * length))
        pts = contour[sel]
        if len(pts) < 20:
            lines.append((p, u))
            continue
        vx, vy, x0, y0 = cv2.fitLine(pts, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))
    out = []
    for i in range(4):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        A = np.array([d1, -d2]).T
        if abs(np.linalg.det(A)) < 1e-9:
            return quad
        t = np.linalg.solve(A, p2 - p1)
        out.append(p1 + t[0] * d1)
    return np.array(out, dtype=np.float32)


def _order_long_vertical(q: np.ndarray) -> np.ndarray:
    """Order corners clockwise from top-left so that TL->TR is a short (210 mm) side."""
    c = q.mean(0)
    ang = np.arctan2(q[:, 1] - c[1], q[:, 0] - c[0])
    q = q[np.argsort(ang)]                      # clockwise in image coordinates (y down)
    tl = int(np.argmin(q.sum(1)))
    q = np.roll(q, -tl, axis=0)
    side01 = np.hypot(*(q[1] - q[0]))
    side12 = np.hypot(*(q[2] - q[1]))
    if side01 > side12:                         # TL->TR is the long side: rotate the frame by one corner
        q = np.roll(q, -1, axis=0)
    return q.astype(np.float32)


def sheet_homography(corners: np.ndarray) -> np.ndarray:
    dst = np.array([[0, 0], [A4[0], 0], [A4[0], A4[1]], [0, A4[1]]], dtype=np.float32)
    return cv2.getPerspectiveTransform(corners.astype(np.float32), dst)


def camera_pose(H_img_to_mm: np.ndarray, image_size: tuple, focal_35mm: float) -> tuple[np.ndarray, float, float]:
    """Camera centre in sheet coordinates (mm, z above the sheet), its distance to the sheet plane and the plane's
    tilt from the image plane (degrees), from the homography and the focal length."""
    w, h = image_size
    f = focal_35mm / math.hypot(36.0, 24.0) * math.hypot(w, h)
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
    G = np.linalg.inv(K) @ np.linalg.inv(H_img_to_mm)   # = [r1 r2 t] up to scale
    lam = 1.0 / np.linalg.norm(G[:, 0])
    r1, r2, t = G[:, 0] * lam, G[:, 1] * lam, G[:, 2] * lam
    if t[2] < 0:                                        # the sheet lies in front of the camera
        r1, r2, t = -r1, -r2, -t
    r3 = np.cross(r1, r2)
    r3 /= np.linalg.norm(r3)
    R = np.stack([r1 / np.linalg.norm(r1), r2 / np.linalg.norm(r2), r3], axis=1)
    centre = -R.T @ t
    centre[2] = abs(centre[2])
    tilt = math.degrees(math.acos(min(1.0, abs(r3[2]))))
    return centre, float(centre[2]), tilt


def camera_distance(H_img_to_mm: np.ndarray, image_size: tuple, focal_35mm: float) -> tuple[float, float]:
    """Distance from the camera to the sheet plane (mm) and the plane's tilt from the image plane (degrees)."""
    _, dist, tilt = camera_pose(H_img_to_mm, image_size, focal_35mm)
    return dist, tilt


def silhouette_on_sheet(cam_across: float, cam_height: float, centre: float, width: float,
                        depth_ratio: float = None) -> tuple[float, float]:
    """Where the two silhouette rays of a finger lying on the sheet meet the sheet, across the finger.

    The finger's cross-section is an ellipse `width` wide and depth_ratio x width deep, resting on the sheet at
    `centre`; the camera sits `cam_across` mm across and `cam_height` mm above. Each silhouette ray is a tangent from
    the camera to the ellipse, and the homography maps it to where it meets the sheet."""
    r = FINGER_DEPTH_RATIO if depth_ratio is None else depth_ratio
    a, b = width / 2, r * width / 2
    X, Z = (cam_across - centre) / a, (cam_height - b) / b      # camera in the unit-circle frame
    d = math.hypot(X, Z)
    th, al = math.atan2(Z, X), math.acos(min(1.0, 1.0 / d))
    out = []
    for ang in (th - al, th + al):
        tx, tz = math.cos(ang), math.sin(ang)
        lam = (-1 - Z) / (tz - Z)
        out.append(centre + (X + lam * (tx - X)) * a)
    return min(out), max(out)


def solve_width(left: float, right: float, cam_across: float, cam_height: float) -> float:
    """Finger width whose silhouette lands on the measured edges (Newton's method on centre and width)."""
    c, w = (left + right) / 2, (right - left) * (1 - 0.5 * FINGER_DEPTH_RATIO * (right - left) / cam_height)
    for _ in range(12):
        l0, r0 = silhouette_on_sheet(cam_across, cam_height, c, w)
        e = np.array([l0 - left, r0 - right])
        if abs(e).max() < 1e-6:
            break
        J = np.zeros((2, 2))
        for j, (dc, dw) in enumerate(((1e-4, 0.0), (0.0, 1e-4))):
            l1, r1 = silhouette_on_sheet(cam_across, cam_height, c + dc, w + dw)
            J[:, j] = [(l1 - l0) / 1e-4, (r1 - r0) / 1e-4]
        dc, dw = np.linalg.solve(J, -e)
        c, w = c + dc, w + dw
    return float(w)


def focal_from_exif(data: bytes) -> tuple[float, str]:
    try:
        exif = Image.open(io.BytesIO(data)).getexif()
        sub = exif.get_ifd(0x8769)
        f35 = sub.get(41989) or exif.get(41989)
        if f35:
            return float(f35), "exif"
    except Exception:
        pass
    return DEFAULT_FOCAL_35MM, "default"


# ----------------------------------------------------------------------------------------------- landmarks
class MediaPipeHands:
    def __init__(self, model_path: str):
        from mediapipe.tasks.python import BaseOptions, vision
        opts = vision.HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=model_path), num_hands=1,
                                            min_hand_detection_confidence=0.3)
        self._lm = vision.HandLandmarker.create_from_options(opts)

    def __call__(self, rgb: np.ndarray) -> np.ndarray | None:
        import mediapipe as mp
        res = self._lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        if not res.hand_landmarks:
            return None
        h, w = rgb.shape[:2]
        return np.array([[p.x * w, p.y * h] for p in res.hand_landmarks[0]], dtype=np.float64)


# ----------------------------------------------------------------------------------------------- measuring
def _to_mm(H, pts):
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, H).reshape(-1, 2)


def _rectify(rgb: np.ndarray, H: np.ndarray, margin_mm: float = 40.0):
    """Rectified view of the sheet plane at PX_PER_MM, with a margin so a wrist past the edge is kept."""
    S = np.array([[PX_PER_MM, 0, margin_mm * PX_PER_MM], [0, PX_PER_MM, margin_mm * PX_PER_MM], [0, 0, 1]])
    size = (int((A4[0] + 2 * margin_mm) * PX_PER_MM), int((A4[1] + 2 * margin_mm) * PX_PER_MM))
    rect = cv2.warpPerspective(rgb, S @ H, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return rect, S, margin_mm


def _chroma_map(rect_rgb: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(rect_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    a, b = lab[..., 1] - 128, lab[..., 2] - 128
    return np.sqrt(a * a + b * b), lab[..., 0]


def _paper_chroma(chroma: np.ndarray, margin: float) -> float:
    """Chroma of bare paper: a low percentile over the sheet, which the hand covers less than half of."""
    m = int(margin * PX_PER_MM)
    sheet = chroma[m:m + int(A4[1] * PX_PER_MM):4, m:m + int(A4[0] * PX_PER_MM):4]
    return float(np.percentile(sheet, 25))


def _profile_width(chroma, centre_mm, normal, margin, paper, half_len_mm=16.0, step_mm=0.05):
    """Width (mm) of the finger across `normal` at `centre_mm`, or None.

    Each edge is where chroma falls fastest going outward from the finger: the skin-to-paper step is sharp, while
    the tint that skin reflects onto the paper next to it, and the shading across the finger, change slowly. The
    search on each side ends a little past the first point where chroma reaches the midpoint between the finger and
    bare paper, so the next finger is never reached. A run wider than MAX_WIDTH_MM is the finger still joined to its
    neighbour by the web of skin, and is refused."""
    ts = np.arange(-half_len_mm, half_len_mm + step_mm / 2, step_mm)
    xs = (centre_mm[0] + margin + ts * normal[0]) * PX_PER_MM
    ys = (centre_mm[1] + margin + ts * normal[1]) * PX_PER_MM
    raw = cv2.remap(chroma, xs.astype(np.float32).reshape(1, -1), ys.astype(np.float32).reshape(1, -1),
                    cv2.INTER_LINEAR).ravel()
    c = cv2.GaussianBlur(raw.reshape(1, -1).astype(np.float32), (0, 0), sigmaX=2.0).ravel()
    i0 = len(ts) // 2
    skin = float(np.median(c[i0 - 8:i0 + 9]))
    if skin - paper < 6.0:
        return None
    level = (skin + paper) / 2.0
    hold = int(GAP_MM / step_mm)
    pad = int(SEARCH_PAST_MM / step_mm)
    grad = np.gradient(c, step_mm)

    def edge(direction):
        # outer end of the search: first point past the midpoint level that stays below it, plus a margin
        i, stop = i0, None
        while 0 < i < len(ts) - 1:
            j = i + direction
            if c[j] < level <= c[i]:
                after = c[j:j + direction * hold:direction] if direction > 0 else c[max(0, j - hold):j + 1]
                if len(after) >= hold // 2 and float(np.mean(after)) < level:
                    stop = j
                    break
            i = j
        if stop is None:
            return None
        stop = min(max(stop + direction * pad, 1), len(ts) - 2)
        lo, hi = (stop, i0) if direction < 0 else (i0, stop)
        seg = grad[lo:hi + 1] * direction            # outward slope; the edge is its most negative point
        k = int(np.argmin(seg))
        if seg[k] > -DROP_PER_MM:
            return None
        if 0 < k < len(seg) - 1:                    # parabola through the three samples around the minimum
            a, b, cc = seg[k - 1], seg[k], seg[k + 1]
            den = a - 2 * b + cc
            frac = 0.5 * (a - cc) / den if den != 0 else 0.0
        else:
            frac = 0.0
        return float(ts[lo + k] + frac * step_mm)

    left, right = edge(-1), edge(+1)
    if left is None or right is None:
        return None
    w = right - left
    if not MIN_WIDTH_MM <= w <= MAX_WIDTH_MM:
        return None
    return w, (left, right)


def _ring_window(samples: list) -> list | None:
    """The most proximal run of WINDOW consecutive positions (one gap allowed) whose widths agree within
    1.2 mm: the base of the finger just past the web, where a ring sits."""
    for i in range(len(samples)):
        run, gaps = [], 0
        for s in samples[i:]:
            if s[1] is None:
                gaps += 1
                if gaps > 1:
                    break
                continue
            run.append(s)
            if len(run) == WINDOW:
                break
        if len(run) >= WINDOW - 1:
            ws = [s[1] for s in run]
            if max(ws) - min(ws) <= 1.2:
                return run
    return None


def _corrected(p, edges, camera, normal, Z) -> float:
    """Finger width from the edges seen on the sheet at profile centre `p`, for the camera at `camera`."""
    return solve_width(edges[0], edges[1], float((camera[:2] - p) @ normal), Z)


def measure(rgb: np.ndarray, landmarks_px: np.ndarray, focal_35mm: float = DEFAULT_FOCAL_35MM,
            focal_source: str = "default", fingers=("ring",)) -> HandMeasure:
    h, w = rgb.shape[:2]
    corners = find_sheet(rgb)
    H = sheet_homography(corners)
    centre_mm, Z, tilt = camera_pose(H, (w, h), focal_35mm)
    rect, S, margin = _rectify(rgb, H)
    chroma, _ = _chroma_map(rect)
    paper = _paper_chroma(chroma, margin)
    Hinv = np.linalg.inv(H)
    out = HandMeasure(image_size=(w, h), sheet_corners_px=corners.round(2).tolist(), px_per_mm=0.0,
                      camera_distance_mm=round(Z, 1), tilt_deg=round(tilt, 1), focal_35mm=focal_35mm,
                      focal_source=focal_source)
    out.checks = {"sheet_found": True, "tilt_ok": tilt <= 35.0}
    lm_mm = _to_mm(H, landmarks_px)
    for name in fingers:
        mcp, pip = FINGERS[name]
        a, b = lm_mm[mcp], lm_mm[pip]
        axis = b - a
        seg = float(np.hypot(*axis))
        if seg < 8:
            raise MeasureError("finger_not_found", f"The {name} finger was not found.")
        u = axis / seg
        nrm = np.array([-u[1], u[0]])
        samples = []
        for t in np.arange(0.30, 0.921, 0.02):
            p = a + t * axis
            r = _profile_width(chroma, p, nrm, margin, paper)
            samples.append((float(t), r[0] if r else None, p, r[1] if r else None))
        window = _ring_window(samples)
        knuckles = []
        for t in np.linspace(0.93, 1.07, 8):
            p = a + t * axis
            r = _profile_width(chroma, p, nrm, margin, paper)
            if r:
                knuckles.append((r[0], p, r[1]))
        if window is None:
            raise MeasureError("finger_edges", f"The edges of the {name} finger are not clear. Spread the fingers so "
                                                "paper shows between them at the base, and keep them flat.")
        widths = [s[1] for s in window]
        lines = [(s[2], s[3]) for s in window]
        location = float(np.mean([s[0] for s in window]))
        raw = float(np.median(widths))
        width = float(np.median([_corrected(p, lr, centre_mm, nrm, Z) for p, lr in lines]))
        if knuckles:
            _, kp, klr = sorted(knuckles, key=lambda k: k[0])[len(knuckles) // 2]   # median profile
            knuckle = _corrected(kp, klr, centre_mm, nrm, Z)
        else:
            knuckle = width
        mid = lines[len(lines) // 2]
        p, (l, r) = mid
        line_mm = [p + l * nrm, p + r * nrm]
        line_px = _to_mm(Hinv, line_mm)
        kline_px = _to_mm(Hinv, [kp + klr[0] * nrm, kp + klr[1] * nrm]).round(1).tolist() if knuckles else []
        ppm = float(np.hypot(*(line_px[1] - line_px[0]))) / raw
        out.px_per_mm = round(ppm, 3)
        out.fingers[name] = FingerMeasure(
            name=name, width_mm=round(width, 2), knuckle_mm=round(knuckle, 2), raw_width_mm=round(raw, 2),
            samples=len(widths), spread_mm=round(float(np.max(widths) - np.min(widths)), 2),
            line_px=line_px.round(1).tolist(), knuckle_line_px=kline_px,
            axis_px=[landmarks_px[mcp].round(1).tolist(), landmarks_px[pip].round(1).tolist()],
            wearing_location=round(location, 2))
    out.checks["resolution_ok"] = out.px_per_mm >= 3.0
    out.checks["edges_consistent"] = all(f.spread_mm <= 1.2 for f in out.fingers.values())
    out.checks = {k: bool(v) for k, v in out.checks.items()}
    return out


def measure_photo(data: bytes, detector, fingers=("ring",)) -> HandMeasure:
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    rgb = np.asarray(img)
    focal, source = focal_from_exif(data)
    lms = detector(rgb)
    if lms is None:
        raise MeasureError("no_hand", "No hand found. Lay the back of the hand flat on the sheet, fingers apart.")
    return measure(rgb, lms, focal, source, fingers)
