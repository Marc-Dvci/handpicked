import math

import pytest

from handpicked import fit, weights


@pytest.mark.parametrize("us", [4.0, 5.5, 7.0, 9.0, 11.5])
def test_us_size_round_trips_through_iso_8653(us):
    assert fit.us_size(fit.us_circumference(us)) == pytest.approx(us)


def test_size_table_agrees_with_the_formula():
    for row in fit._table():
        assert fit.us_circumference(row["us"]) == pytest.approx(row["iso8653_circumference_mm"], abs=0.15)
        assert row["inner_diameter_mm"] == pytest.approx(fit.us_circumference(row["us"]) / math.pi, abs=0.05)


@pytest.mark.parametrize("width,us", [(14.9, 4.0), (16.5, 6.0), (18.1, 8.0)])
def test_perfect_corp_chart_fingers_give_their_sizes(width, us):
    f = fit.ring_size(width)
    assert f.us == us
    assert f.us_low <= f.us <= f.us_high
    assert f.eu == math.floor(fit.us_circumference(f.us) + 0.5)


def test_wider_finger_needs_a_larger_ring():
    assert fit.ring_size(17.0).us > fit.ring_size(15.0).us


def test_a_large_knuckle_moves_the_size_up():
    plain = fit.ring_size(15.5, 15.9)
    knuckly = fit.ring_size(15.5, 17.5)
    assert not plain.knuckle_rule and knuckly.knuckle_rule
    assert knuckly.us > plain.us


def test_uk_letter_is_read_from_the_table():
    row = next(r for r in fit._table() if r["us"] == 6.0)
    assert fit.uk_letter(6.0) == row["uk_au_letter"]
    assert fit.uk_letter(30.0) is None


def test_round_weight_from_mm():
    assert weights.estimate("round", 6.5, 6.5, 3.9) == pytest.approx(1.005, abs=0.002)


def test_oval_uses_length_times_width():
    assert weights.estimate("oval", 8.0, 5.5, 3.4) == pytest.approx(8.0 * 5.5 * 3.4 * 0.0062)


def test_radiant_factor_is_interpolated_between_ratio_points():
    assert weights.factor("radiant", 1.25) == pytest.approx((0.0081 + 0.0084) / 2)
    assert weights.factor("cushion", 1.1) == pytest.approx(0.00815)
