"""Spending limits on the YouCam client, against a mock transport: nothing here reaches the network."""
import asyncio

import httpx
import pytest

from handpicked import youcam


def client(tmp_path, credit=1000.0, day=120, session=8, floor=0):
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if request.url.path.endswith("/client/credit"):
            return httpx.Response(200, json={"results": [{"amount": credit}]})
        return httpx.Response(500, json={"error": "a task must not be started in these tests"})

    led = youcam.Ledger(tmp_path / "units.jsonl", day, session)
    yc = youcam.YouCam("key", tmp_path / "cache", led, transport=httpx.MockTransport(handler), credit_floor=floor)
    return yc, led, calls


def run(yc):
    return asyncio.run(yc.ring_tryon(b"hand", [(b"ring", "r.jpg")], [{}], "s1", "k1"))


def test_credit_floor_stops_live_calls_before_any_task(tmp_path):
    yc, _, calls = client(tmp_path, credit=60, floor=60)
    with pytest.raises(youcam.CapReached) as e:
        run(yc)
    assert e.value.code == "credit_floor"
    assert all(p.endswith("/client/credit") for p in calls)


def test_session_cap(tmp_path):
    yc, led, calls = client(tmp_path, session=2)
    led.record(session="s1", units=2, ok=True, seconds=4.0)
    with pytest.raises(youcam.CapReached) as e:
        run(yc)
    assert e.value.code == "session_cap" and calls == []


def test_day_cap_counts_every_session(tmp_path):
    yc, led, _ = client(tmp_path, day=3)
    for s in ("a", "b", "c"):
        led.record(session=s, units=1, ok=True, seconds=4.0)
    with pytest.raises(youcam.CapReached) as e:
        run(yc)
    assert e.value.code == "day_cap"


def test_failed_calls_cost_nothing(tmp_path):
    _, led, _ = client(tmp_path)
    led.record(session="s1", units=0, ok=False, seconds=1.0, error="task_error")
    assert led.spent() == 0


def test_recorded_result_needs_no_key_and_no_budget(tmp_path):
    led = youcam.Ledger(tmp_path / "units.jsonl", 0, 0)
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "k1.jpg").write_bytes(b"\xff\xd8jpeg")
    (rec / "k1.json").write_text('{"task_id": "t", "seconds": 4.2}', encoding="utf-8")
    yc = youcam.YouCam(None, tmp_path / "cache", led, recordings=rec)
    r = run(yc)
    assert r.cached and r.units == 0 and r.image.startswith(b"\xff\xd8")
