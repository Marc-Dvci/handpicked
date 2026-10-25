import numpy as np
import pytest

from handpicked import metrology
from tests.synthetic import scene


@pytest.mark.parametrize("finger", [14.6, 16.8, 19.5])
def test_flat_finger_width_is_recovered_through_perspective(finger):
    img, lm = scene(finger_mm=finger, knuckle_mm=finger * 1.1)
    m = metrology.measure(img, lm)
    f = m.fingers["ring"]
    assert f.raw_width_mm == pytest.approx(finger, abs=0.15)
    assert f.knuckle_mm > f.width_mm


def test_shadow_on_the_paper_does_not_widen_the_finger():
    a, lma = scene(shadow=False)
    b, lmb = scene(shadow=True)
    wa = metrology.measure(a, lma).fingers["ring"].raw_width_mm
    wb = metrology.measure(b, lmb).fingers["ring"].raw_width_mm
    assert abs(wa - wb) < 0.12


def test_rotated_finger():
    img, lm = scene(angle_deg=18)
    assert metrology.measure(img, lm).fingers["ring"].raw_width_mm == pytest.approx(16.8, abs=0.2)


def test_parallax_correction_shrinks_the_silhouette_width():
    img, lm = scene()
    m = metrology.measure(img, lm)
    f = m.fingers["ring"]
    assert f.width_mm < f.raw_width_mm
    assert 100 < m.camera_distance_mm < 2000


@pytest.mark.parametrize("across", [0.0, 60.0, -150.0])
def test_silhouette_model_round_trips(across):
    left, right = metrology.silhouette_on_sheet(across, 420.0, 1.5, 17.0)
    assert right - left > 17.0
    assert metrology.solve_width(left, right, across, 420.0) == pytest.approx(17.0, abs=1e-4)


def test_straight_above_matches_the_height_factor():
    left, right = metrology.silhouette_on_sheet(0.0, 420.0, 0.0, 17.0)
    h = metrology.FINGER_DEPTH_RATIO * 17.0 / 2
    assert right - left == pytest.approx(17.0 * 420.0 / (420.0 - h), rel=0.01)


def test_a_camera_off_to_the_side_sees_a_wider_silhouette():
    above = metrology.silhouette_on_sheet(0.0, 420.0, 0.0, 17.0)
    side = metrology.silhouette_on_sheet(160.0, 420.0, 0.0, 17.0)
    assert side[1] - side[0] > above[1] - above[0]


def test_corner_order_puts_the_short_side_on_top():
    img, _ = scene()
    q = metrology.find_sheet(img)
    top, right = np.hypot(*(q[1] - q[0])), np.hypot(*(q[2] - q[1]))
    assert top < right


def test_photo_without_a_sheet_is_refused():
    img = np.full((1200, 900, 3), (122, 92, 64), np.uint8)
    with pytest.raises(metrology.MeasureError) as e:
        metrology.find_sheet(img)
    assert e.value.code in ("no_sheet", "sheet_too_small")


def test_sheet_running_off_the_photo_is_refused():
    img, _ = scene()
    with pytest.raises(metrology.MeasureError) as e:
        metrology.find_sheet(img[:, 700:])
    assert e.value.code in ("sheet_cut", "sheet_corners")
