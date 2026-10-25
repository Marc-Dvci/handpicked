"""The try-on loop: a render whose size check fails is re-rendered once with the band fit that render showed."""
import asyncio

import pytest

from handpicked import config, youcam
from handpicked.service import Handpicked


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    s = config.load()
    s.var = tmp_path_factory.mktemp("var")
    s.youcam_key = s.dashscope_key = None
    h = Handpicked(s)
    yield h
    h.close()


def audit(error_pct, band_fit=1.25):
    passed = abs(error_pct) <= 5
    return {"band_fit": band_fit, "expected_ratio": 0.34 * (1 + error_pct / 100), "error_pct": error_pct, "passed": passed}


def fake_render(calls, fail_on=None):
    async def render(hand, choice, metal, band, session):
        calls.append(choice)
        if fail_on == len(calls):
            raise youcam.YouCamError("replay_only", "not recorded")
        return youcam.TaskResult(f"t{len(calls)}", b"", 4.0, 1, False), f"k{len(calls)}"
    return render


def test_render_within_tolerance_is_kept(svc, monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "_render", fake_render(calls))
    monkeypatch.setattr(svc, "_audit", lambda *a: audit(1.2))
    r = asyncio.run(svc.tryon("hand-1", "oval", 5.62, "platinum", False, "s"))
    assert len(calls) == 1 and r["key"] == "k1" and r["units"] == 1


def test_off_render_is_re_rendered_once_with_a_smaller_ring(svc, monkeypatch):
    calls = []
    results = iter([audit(8.0), audit(0.4)])
    monkeypatch.setattr(svc, "_render", fake_render(calls))
    monkeypatch.setattr(svc, "_audit", lambda *a: next(results))
    r = asyncio.run(svc.tryon("hand-1", "oval", 5.62, "platinum", False, "s"))
    assert len(r["attempts"]) == 2 and r["key"] == "k2" and r["units"] == 2
    first, second = (c.product_ratio * c.anchor_scale for c in calls)
    assert second < first          # the render showed a wider band than calibrated: ask for a smaller stone ratio
    assert r["audit"]["passed"]


def test_correction_that_cannot_be_rendered_keeps_the_first_render(svc, monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "_render", fake_render(calls, fail_on=2))
    monkeypatch.setattr(svc, "_audit", lambda *a: audit(8.0))
    r = asyncio.run(svc.tryon("hand-1", "oval", 5.62, "platinum", False, "s"))
    assert r["key"] == "k1" and len(r["attempts"]) == 1 and not r["audit"]["passed"]


def test_render_without_a_readable_band_is_not_retried(svc, monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "_render", fake_render(calls))
    monkeypatch.setattr(svc, "_audit", lambda *a: {"band_fit": None, "expected_ratio": None, "error_pct": None, "passed": False})
    asyncio.run(svc.tryon("hand-1", "oval", 5.62, "platinum", False, "s"))
    assert len(calls) == 1


def test_uploads_and_their_renders_expire_after_a_day(svc):
    import os
    import time
    old = time.time() - 25 * 3600
    up = svc.s.var / "hands" / "u0000000000000000"
    up.mkdir(parents=True)
    (up / "hand.json").write_text("{}", encoding="utf-8")
    (up / "photo.jpg").write_bytes(b"jpeg")
    render = svc.s.var / "tryon" / "abc.jpg"
    render.write_bytes(b"jpeg")
    fresh = svc.s.var / "tryon" / "new.jpg"
    fresh.write_bytes(b"jpeg")
    for f in (up / "hand.json", render):
        os.utime(f, (old, old))
    assert svc.expire() == 2
    assert not up.exists() and not render.exists() and fresh.exists()
