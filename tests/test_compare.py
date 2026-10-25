import json

import pytest

from handpicked import compare, library, listing, llm, weights

ROUND = "Lab-grown round brilliant 1.01 ct, IGI, 6.45 - 6.48 x 3.98 mm, F VS1, EUR 3,900"
OVAL = "Lab-grown oval 0.92 ct, IGI, 8.01 x 5.62 x 3.47 mm, E VS1, EUR 3,050"
CUSHION = "Lab-grown cushion 1.20 ct, IGI, 6.52 x 6.10 x 4.41 mm, G VS2, EUR 4,250"


def stones(*texts):
    return [compare.stone_from_listing(str(i + 1), listing.parse(t)) for i, t in enumerate(texts)]


def test_board_ranks_by_price_per_face_up_mm2():
    b = compare.board(stones(ROUND, OVAL, CUSHION), finger_mm=16.8)
    assert b.rows[0].stone.shape == "oval"
    assert all(r.price_per_mm2 > 0 for r in b.rows)
    assert b.rows[0].rank_value == 1


def test_oval_faces_up_larger_than_the_heavier_round():
    b = compare.board(stones(ROUND, OVAL), finger_mm=16.8)
    f = b.facts
    assert f["heaviest"]["label"].startswith("1.01")
    assert f["best_value"]["label"].startswith("0.92")
    assert f["best_vs_heaviest"]["price_diff"] == 850
    assert f["best_vs_heaviest"]["area_pct"] > 0
    s = compare.template_sentence(f)
    assert "0.92 ct oval" in s and "€850 less" in s


NAT_101 = "Natural round brilliant 1.01 ct, GIA, 6.36 - 6.40 x 3.96 mm, G VS2, $4,413"
NAT_093 = "Natural round brilliant 0.93 ct, GIA, 6.24 - 6.27 x 3.86 mm, G VS2, $2,841"


def test_look_alike_rounds_are_named_with_their_price_gap():
    f = compare.board(stones(NAT_101, NAT_093), finger_mm=17.0).facts
    t = f["look_alike"]
    assert t["dearer"]["label"] == "1.01 ct round" and t["cheaper"]["label"] == "0.93 ct round"
    assert t["across_mm"] == 0.12 and t["price_diff"] == 1572
    assert "0.12 mm" in compare.template_sentence(f)


def test_different_sizes_are_not_look_alikes():
    big = "Natural round brilliant 1.50 ct, GIA, 7.38 - 7.41 x 4.55 mm, G VS2, $9,900"
    assert "look_alike" not in compare.board(stones(NAT_101, big), finger_mm=17.0).facts


def test_non_diamond_waits_outside_the_ranking():
    items = stones(ROUND, "Moissanite oval 1.5 ct, 9.0 x 7.0 x 4.5 mm, $390")
    b = compare.board(items, finger_mm=16.8)
    assert len(b.rows) == 1 and b.pending[0].missing == ["material"]


def test_identical_stones_give_identical_verdict_and_no_winner():
    b = compare.board(stones(ROUND, ROUND), finger_mm=16.8)
    assert b.facts["identical"]
    assert "same stone" in compare.template_sentence(b.facts)


def test_coverage_depends_on_the_measured_finger():
    slim = compare.board(stones(ROUND, OVAL), finger_mm=15.0).rows
    wide = compare.board(stones(ROUND, OVAL), finger_mm=19.0).rows
    assert all(a.coverage > b.coverage for a, b in zip(slim, wide))


def test_stone_without_measurements_waits_with_a_question():
    items = stones(ROUND, "Natural oval diamond 1.00 carat, G VS2, EUR 5,900")
    b = compare.board(items, finger_mm=16.8)
    assert len(b.rows) == 1 and len(b.pending) == 1
    assert "millimetres" in b.pending[0].question


def test_weight_contradicting_measurements_is_flagged():
    s = stones("Natural round 1.50 ct, GIA, 6.40 - 6.44 x 3.96 mm, EUR 9,900")[0]
    assert "weight_mismatch" in s.flags


def test_weight_estimate_matches_a_typical_round():
    est = weights.estimate("round", 6.48, 6.45, 3.98)
    assert est == pytest.approx(1.01, rel=0.03)


def test_round_weight_flag_only_for_natural_stones():
    nat = stones("Natural round 1.01 ct, GIA, 6.45 - 6.48 x 3.98 mm, EUR 6,900")[0]
    lab = stones(ROUND)[0]
    assert "round_weight" in nat.flags and "round_weight" not in lab.flags


def test_mixed_currencies_are_not_compared():
    b = compare.board(stones(ROUND, OVAL.replace("EUR", "USD")), finger_mm=16.8)
    assert b.currency is None and all(r.price_per_mm2 is None for r in b.rows)


def test_library_choice_hits_the_target_ratio(tmp_path):
    for r in (0.30, 0.32, 0.34):
        name = f"oval_platinum_r{int(r * 1000):03d}"
        (tmp_path / f"{name}.json").write_text(json.dumps({
            "name": name, "shape": "oval", "metal": "platinum", "image": name + ".jpg", "marker": False,
            "stone_width_mm": r * 20.4, "outer_diameter_mm": 20.4, "anchor_points": [[100, 400], [600, 400]]}))
    lib = library.RingLibrary(tmp_path)
    c = lib.choose("oval", "platinum", 5.62 / 16.8, scale=0.97)
    assert c.expected_ratio == pytest.approx(5.62 / 16.8, rel=1e-9)
    assert abs(c.anchor_scale - 1) < 0.04
    with pytest.raises(ValueError):
        lib.choose("oval", "platinum", 0.60, scale=0.97)


def test_anchor_scale_moves_the_points_closer():
    pts = library.scaled_anchors([[100, 400], [600, 400]], 1.25)
    assert pts == [[150, 400], [550, 400]]


def test_verdict_with_an_invented_number_is_refused():
    b = compare.board(stones(ROUND, OVAL), finger_mm=16.8)
    good = compare.template_sentence(b.facts)
    assert llm.numbers_grounded(good, b.facts | {"labels": [r.stone.label for r in b.rows]})
    assert not llm.numbers_grounded("The oval saves you €1,200 and looks 25% bigger.", b.facts)


def test_model_json_is_parsed_from_fenced_output():
    assert llm.parse_json('```json\n{"carat": {"value": 1.0, "quote": "1.00 ct"}}\n```')["carat"]["value"] == 1.0
    assert llm.parse_json("no json here") is None
