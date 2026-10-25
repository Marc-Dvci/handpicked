import math

import pytest

from handpicked import gems, outlines


def test_round_area_factor_is_a_circle():
    assert gems.area_factor("round", 1.0) == pytest.approx(math.pi / 4, abs=1e-4)


def test_oval_area_factor_is_an_ellipse_at_any_ratio():
    for lw in (1.2, 1.4, 1.6):
        assert gems.area_factor("oval", lw) == pytest.approx(math.pi / 4, abs=1e-4)


@pytest.mark.parametrize("shape,lo,hi", [("cushion", 0.84, 0.90), ("princess", 0.95, 0.99), ("radiant", 0.90, 0.96),
                                         ("emerald", 0.96, 0.995), ("marquise", 0.60, 0.70), ("pear", 0.62, 0.75)])
def test_fancy_area_factors_are_plausible(shape, lo, hi):
    f = gems.area_factor(shape, outlines.TYPICAL_LW[shape])
    assert lo < f < hi


def test_outline_reaches_the_listed_extents():
    for shape, b in outlines.TYPICAL_LW.items():
        assert outlines.radius(shape, 0.0, b) == pytest.approx(1.0, abs=2e-3)
        tip = outlines.radius(shape, math.pi / 2, b)
        expected = 2 * b - 1 if shape == "pear" else b
        assert tip == pytest.approx(expected, rel=2e-3)


def test_a_typical_one_carat_round_has_zero_spread():
    g = gems.geometry("round", 1.0, 6.4, 6.4, 3.9)
    assert g.spread_pct == pytest.approx(0.0, abs=1e-6)


def test_a_deep_stone_spreads_less_than_its_weight_suggests():
    shallow = gems.geometry("round", 1.01, 6.48, 6.45, 3.98)
    deep = gems.geometry("round", 1.01, 6.21, 6.18, 4.12)
    assert shallow.spread_pct > 0 > deep.spread_pct
    assert deep.depth_pct > shallow.depth_pct


def test_typical_area_grows_as_carat_to_two_thirds_beyond_the_chart():
    a5 = gems.typical_area("round", 5.0)
    a6 = gems.typical_area("round", 6.0)
    assert a6 / a5 == pytest.approx((6 / 5) ** (2 / 3), rel=1e-9)


def test_an_oval_faces_up_larger_than_a_round_of_the_same_weight():
    assert gems.typical_area("oval", 1.0) > gems.typical_area("round", 1.0)


def test_coverage_uses_the_width_across_the_finger():
    g = gems.geometry("oval", 0.92, 8.01, 5.62, 3.47)
    assert g.coverage(16.8) == pytest.approx(5.62 / 16.8)
    assert g.coverage(16.8, east_west=True) == pytest.approx(8.01 / 16.8)


def test_unsupported_shape_is_refused():
    with pytest.raises(ValueError):
        gems.geometry("heart", 1.0, 6.5, 6.9, 4.1)
