"""YouCam API client: File API upload, Ring Virtual Try-On task, polling, unit ledger and spending caps.

Every live call is recorded in `var/units.jsonl` (feature, units, latency, task id, outcome). A request whose
hand, ring images and parameters were already rendered is answered from the result cache and costs nothing:
first from the recordings shipped in `assets/tryon`, then from `var/tryon`.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE = "https://yce-api-01.makeupar.com"
UNITS = {"2d-vto/ring": 1, "2d-vto/ring:stacked": 2}
JPEG_MAGIC = bytes([0xFF, 0xD8])


class YouCamError(RuntimeError):
    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code, self.status = code, status


class CapReached(YouCamError):
    pass


@dataclass
class TaskResult:
    task_id: str
    image: bytes
    seconds: float
    units: int
    cached: bool


class Ledger:
    def __init__(self, path: Path, day_cap: int, session_cap: int):
        self.path, self.day_cap, self.session_cap = path, day_cap, session_cap
        path.parent.mkdir(parents=True, exist_ok=True)

    def _rows(self):
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def spent(self, session: str | None = None, since: float | None = None) -> int:
        since = time.time() - 86400 if since is None else since
        return sum(r["units"] for r in self._rows() if r["ok"] and r["t"] >= since and (session is None or r["session"] == session))

    def check(self, session: str, units: int):
        if self.spent() + units > self.day_cap:
            raise CapReached("day_cap", "Today's live try-on budget is used up; the recorded sessions still play.")
        if self.spent(session) + units > self.session_cap:
            raise CapReached("session_cap", "This session has used its live try-ons; the recorded sessions still play.")

    def record(self, **row):
        row.setdefault("t", time.time())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


class YouCam:
    def __init__(self, api_key: str | None, cache_dir: Path, ledger: Ledger, base: str = BASE,
                 transport: httpx.AsyncBaseTransport | None = None, poll_every: float = 1.2, timeout: float = 90.0,
                 recordings: Path | None = None, credit_floor: int = 0):
        self.key, self.base, self.ledger = api_key, base, ledger
        self.credit_floor = credit_floor
        self._credit: tuple[float, float | None] = (0.0, None)
        self.cache_dir, self.recordings = cache_dir, recordings
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.poll_every, self.timeout = poll_every, timeout
        self._transport = transport
        self._uploads: dict[str, tuple[str, float]] = {}

    def _client(self):
        return httpx.AsyncClient(base_url=self.base, timeout=60.0, transport=self._transport,
                                 headers={"Authorization": f"Bearer {self.key}"})

    async def _call(self, client, method, path, **kw):
        for attempt in range(4):
            try:
                r = await client.request(method, path, **kw)
            except httpx.TransportError as e:
                if attempt == 3:
                    raise YouCamError("network", f"YouCam API unreachable: {e}") from e
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code >= 400:
                try:
                    body = r.json()
                except ValueError:
                    body = {"error": r.text[:300]}
                raise YouCamError(str(body.get("error_code") or r.status_code), str(body.get("error") or body), r.status_code)
            return r.json()
        raise YouCamError("retries", "YouCam API kept failing")

    async def upload(self, client, data: bytes, name: str, feature: str = "2d-vto/ring") -> str:
        digest = hashlib.sha256(data).hexdigest()
        hit = self._uploads.get(digest)
        if hit and time.time() - hit[1] < 6 * 3600:
            return hit[0]
        ctype = "image/png" if name.lower().endswith(".png") else "image/jpg"
        r = await self._call(client, "POST", f"/s2s/v2.0/file/{feature}",
                             json={"files": [{"content_type": ctype, "file_name": name, "file_size": len(data)}]})
        f = r["data"]["files"][0]
        req = f["requests"][0]
        async with httpx.AsyncClient(timeout=120.0, transport=self._transport) as raw:
            put = await raw.request(req.get("method", "PUT"), req["url"], content=data, headers=req.get("headers", {}))
            if put.status_code >= 400:
                raise YouCamError("upload", f"File upload failed with HTTP {put.status_code}")
        self._uploads[digest] = (f["file_id"], time.time())
        return f["file_id"]

    @staticmethod
    def cache_key(parts: dict) -> str:
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:32]

    def cached(self, key: str) -> TaskResult | None:
        for d in (self.recordings, self.cache_dir):
            if d is None:
                continue
            img, meta = d / f"{key}.jpg", d / f"{key}.json"
            if img.exists() and meta.exists():
                m = json.loads(meta.read_text(encoding="utf-8"))
                return TaskResult(m["task_id"], img.read_bytes(), m["seconds"], 0, True)
        return None

    @property
    def live(self) -> bool:
        return bool(self.key)

    async def ring_tryon(self, hand: bytes, refs: list[tuple[bytes, str]], params: list[dict], session: str,
                         key: str) -> TaskResult:
        """refs: [(image bytes, file name)], one per ring (two for a stacked try-on); params per ring. `key`
        names the request (see `cache_key`)."""
        hit = self.cached(key)
        if hit:
            return hit
        if not self.live:
            raise YouCamError("replay_only", "This server plays recorded try-ons only; this combination was not "
                                             "recorded.")
        feature = "2d-vto/ring"
        units = UNITS["2d-vto/ring:stacked" if len(refs) > 1 else "2d-vto/ring"]
        self.ledger.check(session, units)
        if self.credit_floor:
            left = await self.credit_cached()
            if left is not None and left - units < self.credit_floor:
                raise CapReached("credit_floor", "The live try-on budget for this demo is used up; the recorded sessions "
                                                 "still play.")
        t0 = time.time()
        async with self._client() as client:
            hid = await self.upload(client, hand, "hand.jpg")
            rids = [await self.upload(client, data, name) for data, name in refs]
            payload = {"src_file_id": hid, "ref_file_ids": rids, "source_info": {"name": hid},
                       "object_infos": [{"name": rid, "parameter": p} for rid, p in zip(rids, params)]}
            try:
                r = await self._call(client, "POST", f"/s2s/v2.0/task/{feature}", json=payload)
            except YouCamError as e:
                self.ledger.record(session=session, feature=feature, units=0, ok=False, error=e.code, seconds=time.time() - t0)
                raise
            tid = r["data"]["task_id"]
            while True:
                await asyncio.sleep(self.poll_every)
                s = await self._call(client, "GET", f"/s2s/v2.0/task/{feature}/{tid}")
                st = s["data"].get("task_status")
                if st == "success":
                    url = s["data"]["results"]["url"]
                    break
                if st == "error":
                    code = str(s["data"].get("error") or "task_error")
                    self.ledger.record(session=session, feature=feature, units=0, ok=False, error=code, task_id=tid,
                                       seconds=time.time() - t0)
                    raise YouCamError(code, _task_message(code))
                if time.time() - t0 > self.timeout:
                    raise YouCamError("timeout", "The try-on took too long; please retry.")
            async with httpx.AsyncClient(timeout=120.0, transport=self._transport) as raw:
                img = (await raw.get(url)).content
        secs = round(time.time() - t0, 2)
        self.ledger.record(session=session, feature=feature, units=units, ok=True, task_id=tid, seconds=secs, key=key)
        (self.cache_dir / f"{key}.jpg").write_bytes(to_jpeg(img))
        (self.cache_dir / f"{key}.json").write_text(json.dumps({"task_id": tid, "seconds": secs, "params": params}),
                                                   encoding="utf-8")
        return TaskResult(tid, img, secs, units, False)

    async def credit_cached(self, max_age: float = 300.0) -> float | None:
        """Units left on the account, read at most every `max_age` seconds; None when it cannot be read."""
        t, value = self._credit
        if time.time() - t > max_age:
            try:
                value = await self.credit()
            except YouCamError:
                value = None
            self._credit = (time.time(), value)
        return value

    async def credit(self) -> float:
        async with self._client() as client:
            r = await self._call(client, "GET", "/s2s/v1.0/client/credit")
        return float(sum(x.get("amount_dec", x.get("amount", 0)) for x in r.get("results", [])))


def to_jpeg(data: bytes, quality: int = 93) -> bytes:
    if data[:2] == JPEG_MAGIC:
        return data
    from PIL import Image
    buf = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


TASK_MESSAGES = {
    "PHOTO_DETECTION_FAIL": "The try-on could not find the hand. Use a photo of the back of the hand with all five fingers visible.",
    "PHOTO_CHECK_INVALID": "The hand's pose or size does not suit the try-on. Keep the fingers straight and apart.",
    "OBJECT_DETECTION_FAIL": "The ring image could not be read.",
    "INPUT_ERROR": "The photo format is not supported.",
}


def _task_message(code: str) -> str:
    return TASK_MESSAGES.get(code, f"The try-on failed ({code}).")
