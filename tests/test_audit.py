import numpy as np
import pytest

from handpicked import audit


def _finger_scene(band_half_px=50, stone_half_px=18):
    before = np.full((400, 300, 3), 200, np.uint8)
    after = before.copy()
    after[195:205, 150 - band_half_px:150 + band_half_px] = 90          # band across the finger
    after[170:195, 150 - stone_half_px:150 + stone_half_px] = (0, 220, 60)  # green calibration stone
    return before, after


def test_footprint_reads_the_band_extent_across_the_finger():
    before, after = _finger_scene()
    fp = audit.footprint(before, after, mcp=(150, 300), pip=(150, 100), finger_px=90)
    assert fp.band_px == pytest.approx(100, abs=2)


def test_marker_width_reads_the_green_stone():
    _, after = _finger_scene(stone_half_px=18)
    assert audit.marker_width(after, (150, 300), (150, 100)) == pytest.approx(36, abs=1.5)


def test_audit_reads_the_stone_through_the_band():
    before, after = _finger_scene(band_half_px=50)
    fp = audit.footprint(before, after, (150, 300), (150, 100), finger_px=90)
    band_fit = fp.band_px / 90
    a = audit.audit(fp, 90, target_ratio=0.38, product_ratio=0.38 / (1.06 * band_fit), c_shape=1.06)
    assert a.passed and abs(a.error) < 1e-9


def test_audit_fails_a_render_drawn_too_large():
    before, after = _finger_scene(band_half_px=50)
    fp = audit.footprint(before, after, (150, 300), (150, 100), finger_px=90)
    a = audit.audit(fp, 90, target_ratio=0.30, product_ratio=0.38, c_shape=1.06)
    assert not a.passed and a.error > 0.05


def test_audit_without_a_readable_band_does_not_pass():
    a = audit.audit(None, 90, 0.38, 0.33, 1.06)
    assert not a.passed and a.expected_ratio is None
