"""Synthetic photos for the metrology tests: an A4 sheet seen in perspective, with a flat skin-coloured
'finger' of known width lying on it and a soft grey shadow beside it."""
import cv2
import numpy as np

from handpicked import metrology


def scene(finger_mm=16.8, knuckle_mm=18.4, angle_deg=0.0, tilt=0.12, size=(3000, 4000), shadow=True,
          skin=(214, 160, 128), seed=0, neighbour=False, table=(122, 92, 64)):
    rng = np.random.default_rng(seed)
    W, H = size
    # sheet plane in mm -> image, through a mild perspective
    dst = np.array([[620, 520], [2380, 470 + 260 * tilt], [2470, 3510], [540, 3570 - 240 * tilt]], dtype=np.float32)
    src = np.array([[0, 0], [210, 0], [210, 297], [0, 297]], dtype=np.float32)
    P = cv2.getPerspectiveTransform(src, dst)
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = table                                      # wooden table by default
    img = (img + rng.normal(0, 6, img.shape)).clip(0, 255).astype(np.uint8)
    S = 24.0                                            # draw the sheet plane at 24 px/mm, then warp
    plane = np.full((int(297 * S), int(210 * S), 3), 246, np.uint8)
    c = np.array([105.0, 150.0])
    a = np.radians(angle_deg)
    u = np.array([np.sin(a), -np.cos(a)])               # finger axis, pointing up the sheet
    n = np.array([-u[1], u[0]])
    mcp, pip = c - 22 * u, c + 22 * u
    if shadow:
        poly = [mcp + 3 * n - 30 * u + (finger_mm / 2 + 3.5) * n, pip + 3 * n + 30 * u + (finger_mm / 2 + 3.5) * n,
                pip + 30 * u - (finger_mm / 2 - 1) * n, mcp - 30 * u - (finger_mm / 2 - 1) * n]
        cv2.fillPoly(plane, [np.int32(np.array(poly) * S * 16)], (168, 168, 166), cv2.LINE_AA, 4)
        plane = cv2.GaussianBlur(plane, (0, 0), 6)
    pts = []
    for t in np.linspace(-1.4, 1.4, 60):
        wdt = finger_mm if t < 0.85 else knuckle_mm
        pts.append(c + t * 22 * u + wdt / 2 * n)
    for t in np.linspace(1.4, -1.4, 60):
        wdt = finger_mm if t < 0.85 else knuckle_mm
        pts.append(c + t * 22 * u - wdt / 2 * n)
    cv2.fillPoly(plane, [np.int32(np.array(pts) * S * 16)], skin, cv2.LINE_AA, 4)
    if neighbour:   # a second finger lying against this one: no paper between them
        side = [c - 1.4 * 22 * u + finger_mm / 2 * n, c + 1.4 * 22 * u + finger_mm / 2 * n,
                c + 1.4 * 22 * u + (finger_mm / 2 + 17) * n, c - 1.4 * 22 * u + (finger_mm / 2 + 17) * n]
        cv2.fillPoly(plane, [np.int32(np.array(side) * S * 16)], skin, cv2.LINE_AA, 4)
    M = P @ np.array([[1 / S, 0, 0], [0, 1 / S, 0], [0, 0, 1]])
    warped = cv2.warpPerspective(plane, M, (W, H), flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.full(plane.shape[:2], 255, np.uint8), M, (W, H))
    img[mask > 0] = warped[mask > 0]
    lm = np.zeros((21, 2))
    for m_idx, p_idx in metrology.FINGERS.values():
        lm[m_idx] = cv2.perspectiveTransform(np.array([[mcp]], dtype=np.float64), P)[0, 0]
        lm[p_idx] = cv2.perspectiveTransform(np.array([[pip]], dtype=np.float64), P)[0, 0]
    return img, lm
