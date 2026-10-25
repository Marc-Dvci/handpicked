"""Handpicked service: the one object the web app talks to.

    hand photo ──► hands.HandStore ──► metrology + fit          (code)
    listing text ─► listing.parse ──► model reads the gaps ──► quotes grounded by the rules   (model proposes)
    stones + finger ─► compare.board ──► facts ──► model phrases ──► numbers checked, else template
    stone + hand ──► library.choose ──► YouCam Ring VTO ──► audit (band fit, calibrated scale)

Numbers, rankings, sizes and the audit come from code. The model only reads listing text and phrases the verdict;
photos never reach it.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import time
from functools import partial

import numpy as np
from PIL import Image

from . import audit, compare, config, hands, library, listing, llm, merchant, metrology, outlines, youcam

SAMPLE_SHORTLIST = [
    "Natural round brilliant diamond, 1.01 ct, GIA graded\nMeasurements: 6.36 - 6.40 x 3.96 mm\n"
    "Colour G, clarity VS2, cut Excellent\nPrice: $4,413",
    "Natural round brilliant diamond, 0.93 ct, GIA graded\nMeasurements: 6.24 - 6.27 x 3.86 mm\n"
    "Colour G, clarity VS2, cut Excellent\nPrice: $2,841",
    "Natural oval diamond, 0.92 ct, GIA graded\nMeasurements: 8.10 x 5.62 x 3.45 mm\n"
    "Colour G, clarity VS2\nPrice: $2,506",
]
SAMPLE_SOURCE = ("Sample prices: PriceScope natural diamond price chart, October 2026, colour G clarity VS2 average "
                 "price per carat times weight.")
LABELS = "ABCDEF"
METALS = ("platinum", "yellow")


class Handpicked:
    def __init__(self, settings: config.Settings | None = None):
        self.s = s = settings or config.load()
        s.var.mkdir(parents=True, exist_ok=True)
        self.hands = hands.HandStore(s.assets / "hands", s.var / "hands",
                                     lambda: metrology.MediaPipeHands(str(s.assets / "models" / "hand_landmarker.task")))
        self.library = library.RingLibrary(s.assets / "rings")
        self.ledger = youcam.Ledger(s.var / "units.jsonl", s.day_units, s.session_units)
        self.youcam = youcam.YouCam(s.youcam_key, s.var / "tryon", self.ledger, recordings=s.assets / "tryon",
                                    credit_floor=s.unit_floor)
        self.budget = llm.TokenBudget(s.var / "tokens.jsonl", s.day_tokens)
        self.model = llm.DashScope(s.dashscope_key, self.budget, s.model) if s.dashscope_key else None
        self.llm_cache = s.var / "llm"
        self.llm_cache.mkdir(parents=True, exist_ok=True)
        inv = s.assets / "inventory.json"
        self.inventory = json.loads(inv.read_text(encoding="utf-8")) if inv.exists() else {"stones": []}

    def close(self):
        self.hands.close()

    def expire(self) -> int:
        """Delete uploads, and live renders (which show the uploaded hand), older than the store's 24 h."""
        n = self.hands.expire()
        now = time.time()
        for f in (self.s.var / "tryon").glob("*"):
            if f.is_file() and now - f.stat().st_mtime > self.hands.ttl:
                f.unlink()
                n += 1
        return n

    # ------------------------------------------------------------------ model calls, cached on disk
    async def _cached(self, kind: str, payload: str, call):
        key = hashlib.sha256(f"{kind}|{self.s.model}|{payload}".encode()).hexdigest()[:24]
        path = self.llm_cache / f"{kind}-{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["out"]
        out = await call()
        if out is not None:
            path.write_text(json.dumps({"out": out}), encoding="utf-8")
        return out

    # ------------------------------------------------------------------ listings
    async def read(self, texts: list[str]) -> list[dict]:
        return [r for r, _ in await self._read(texts)]

    async def _read(self, texts: list[str]) -> list[tuple[dict, compare.Stone | compare.Pending]]:
        out = []
        for i, text in enumerate(texts[:len(LABELS)]):
            text = text.strip()[:4000]
            if not text:
                continue
            sid = LABELS[i]
            L = listing.parse(text)
            rejected, asked = [], False
            gaps = [g for g in listing.missing(L) if g in listing.GROUNDABLE]
            if gaps and self.model and "not_diamond" not in L.fields and "shape_unsupported" not in L.fields:
                asked = True
                proposed = await self._cached("extract", L.readable, partial(self.model.extract, L.readable)) or {}
                rejected = listing.ground_model_fields(L, {k: v for k, v in proposed.items() if k in gaps})
            item = compare.stone_from_listing(sid, L)
            out.append((self._reading(sid, text, L, item, asked, rejected), item))
        return out

    @staticmethod
    def _reading(sid, text, L, item, asked, rejected) -> dict:
        fields = {k: {"value": f.value, "start": f.start, "end": f.end, "quote": f.quote, "method": f.method}
                  for k, f in L.fields.items()}
        d = {"id": sid, "text": text, "fields": fields, "notes": L.notes, "masked": [list(m) for m in L.masked],
             "model_asked": asked, "model_rejected": rejected}
        if isinstance(item, compare.Pending):
            d |= {"status": "waiting", "label": item.label, "missing": item.missing, "question": item.question}
        else:
            d |= {"status": "ready", "label": item.label, "flags": item.flags,
                  "weight_estimate": round(item.weight_estimate, 2) if item.weight_estimate else None}
        return d

    # ------------------------------------------------------------------ board
    async def compare(self, hand_id: str, texts: list[str]) -> dict:
        hand = self.hands.get(hand_id)
        finger = hand.finger["width_mm"]
        pairs = await self._read(texts)
        readings, items = [r for r, _ in pairs], [i for _, i in pairs]
        b = compare.board(items, finger)
        rows = [self._row(r, hand) for r in b.rows]
        verdict = await self.verdict(b.facts)
        return {"hand_id": hand_id, "finger_mm": finger, "currency": b.currency, "rows": rows,
                "pending": [r for r in readings if r["status"] == "waiting"], "readings": readings,
                "facts": b.facts, "verdict": verdict, "notes": b.notes}

    def _row(self, r: compare.Row, hand: hands.Hand) -> dict:
        st = r.stone
        g = st.geometry
        return {"id": st.id, "label": st.label, "shape": st.shape, "carat": st.carat, "length_mm": st.length,
                "width_mm": st.width, "depth_mm": st.depth, "area_mm2": round(r.area_mm2, 1),
                "coverage_pct": round(100 * r.coverage, 1), "price": st.price, "currency": st.currency,
                "price_per_mm2": round(r.price_per_mm2, 1) if r.price_per_mm2 else None, "rank": r.rank_value,
                "spread_pct": round(g.spread_pct, 1), "depth_pct": round(g.depth_pct, 1),
                "typical_area_mm2": round(g.area_mm2 / (1 + g.spread_pct / 100), 1),
                "weight_estimate": round(st.weight_estimate, 2) if st.weight_estimate else None,
                "origin": st.origin, "flags": st.flags, "outline": outline_mm(st.shape, st.length, st.width),
                "stone_px": round(g.width / hand.finger["width_mm"] * hand.finger["width_px"], 1)}

    async def verdict(self, facts: dict) -> dict:
        """The template states the verdict from the facts; the model may reword it. The reworded text is shown only
        if it keeps every number of the template and adds none that is not in the facts."""
        template = compare.template_sentence(facts)
        if not self.model or not facts or facts.get("identical"):
            return {"text": template, "source": "template"}
        payload = json.dumps({"draft": template, "facts": facts}, sort_keys=True)
        text = await self._cached("verdict", payload, partial(self.model.verdict, template, facts))
        ok = (bool(text) and llm.keeps_numbers(text, template)
              and llm.numbers_grounded(text, facts | {"draft": template})
              and "!" not in text and len(text.split()) <= 60)
        if ok:
            return {"text": text, "source": "model", "model": self.s.model, "template": template}
        return {"text": template, "source": "template", "model_refused": bool(text)}

    # ------------------------------------------------------------------ try-on
    def c_shape(self, shape: str) -> float:
        c = self.s.calibration.get("c_by_shape", {})
        return c.get(shape) or float(np.median(list(c.values()) or [1.07]))

    def band_fit(self, hand_id: str) -> tuple[float, str]:
        """The hand's band fit: measured in calibration for sample hands, learned from its first live try-on for an
        upload, else the median over the calibration hands."""
        cal = self.s.calibration
        if hand_id in cal.get("band_fit_by_hand", {}):
            return cal["band_fit_by_hand"][hand_id], "calibrated"
        p = self.s.var / "hands" / hand_id / "band_fit.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))["band_fit"], "measured on this hand"
        return cal.get("band_fit_prior", 1.11), "median of the calibration hands"

    async def tryon(self, hand_id: str, shape: str, width_mm: float, metal: str, band: bool, session: str) -> dict:
        if metal not in METALS:
            raise ValueError("metal must be platinum or yellow")
        hand = self.hands.get(hand_id)
        f = hand.finger
        target = width_mm / f["width_mm"]
        c = self.c_shape(shape)
        bf, bf_source = self.band_fit(hand_id)
        attempts = []
        for _attempt in range(2):
            choice = self.library.choose(shape, metal, target, c * bf)
            try:
                res, key = await self._render(hand, choice, metal, band, session)
            except youcam.YouCamError:
                if not attempts:
                    raise
                break                       # the correction could not be rendered: keep the first render, labelled
            a = self._audit(hand, res.image, target, choice, c)
            attempts.append({"render": choice.name, "anchor_scale": round(choice.anchor_scale, 4), "units": res.units,
                             "error_pct": a["error_pct"], "band_fit": a["band_fit"], "key": key})
            kept = (res, key, a, choice)
            measured = a["band_fit"] is not None and a["expected_ratio"] is not None
            if not measured:
                break
            render_fit = a["band_fit"] / choice.anchor_scale
            if bf_source != "calibrated":
                bf, bf_source = render_fit, "measured on this hand"
                self._remember_band_fit(hand_id, bf)
            if a["passed"]:
                break
            bf = render_fit                 # re-render once with the band fit this render showed
        res, key, a, choice = kept
        return {"key": key, "image": f"/api/tryon/{key}.jpg", "view": f"/api/tryon/{key}/view.jpg?hand={hand_id}",
                "task_id": res.task_id, "seconds": res.seconds, "units": sum(x["units"] for x in attempts),
                "cached": res.cached, "attempts": attempts,
                "render": {"name": choice.name, "product_ratio": round(choice.product_ratio, 4),
                           "anchor_scale": round(choice.anchor_scale, 4)},
                "band_fit_source": bf_source, "target_ratio": round(target, 4), "audit": a, "band": band,
                "metal": metal}

    async def _render(self, hand: hands.Hand, choice: library.Choice, metal: str, band: bool, session: str):
        loc = hand.finger["wearing_location"]
        refs = [(choice.image_path.read_bytes(), choice.image_path.name)]
        params = [{"ring_wearing_finger": 3, "ring_wearing_location": loc, "ring_anchor_point": choice.anchor_points}]
        if band:
            bpath, bmeta = self.library.band(metal)
            refs.append((bpath.read_bytes(), bpath.name))
            params.append({"ring_wearing_finger": 3, "ring_wearing_location": round(max(0.0, loc - 0.12), 2),
                           "ring_anchor_point": bmeta["anchor_points"]})
        key = youcam.YouCam.cache_key({"hand": hand.id, "rings": [r[1] for r in refs], "params": params})
        res = await self.youcam.ring_tryon(self.hands.crop(hand.id), refs, params, session, key)
        return res, key

    def _remember_band_fit(self, hand_id: str, bf: float):
        d = self.s.var / "hands" / hand_id
        if d.exists():
            (d / "band_fit.json").write_text(json.dumps({"band_fit": round(bf, 4), "t": time.time()}), encoding="utf-8")

    def _audit(self, hand: hands.Hand, image: bytes, target: float, choice: library.Choice, c: float) -> dict:
        before = np.asarray(Image.open(io.BytesIO(self.hands.crop(hand.id))).convert("RGB"))
        after = np.asarray(Image.open(io.BytesIO(image)).convert("RGB"))
        f = hand.finger
        fp = audit.footprint(before, after, f["axis_px"][0], f["axis_px"][1], f["width_px"])
        a = audit.audit(fp, f["width_px"], target, choice.product_ratio, c)
        return a.as_dict() | {"tolerance_pct": round(100 * audit.TOLERANCE),
                              "calibration_p90_pct": self.s.calibration.get("residual_p90_pct"),
                              "calibration_renders": self.s.calibration.get("renders")}

    def tryon_image(self, key: str) -> bytes:
        hit = self.youcam.cached(key)
        if hit is None:
            raise KeyError(key)
        return hit.image

    # ------------------------------------------------------------------ merchant, status
    def merchant(self, hand_id: str, budget: float, shapes: list[str] | None = None) -> dict:
        hand = self.hands.get(hand_id)
        return merchant.rank(self.inventory["stones"], hand.finger["width_mm"], budget, shapes) | {
            "source": self.inventory.get("source")}

    async def status(self) -> dict:
        credit = await self.youcam.credit_cached() if self.youcam.live else None
        rows = self.ledger._rows()
        ok = [r for r in rows if r["ok"]]
        return {"mode": "live" if self.youcam.live else "replay", "model": self.s.model if self.model else None,
                "units_left": credit, "units_today": self.ledger.spent(),
                "day_cap": self.s.day_units, "session_cap": self.s.session_units, "unit_floor": self.s.unit_floor,
                "calls": len(ok), "median_seconds": float(np.median([r["seconds"] for r in ok])) if ok else None,
                "tokens_today": self.budget.used(), "token_cap": self.s.day_tokens,
                "calibration": self.s.calibration, "library": sum(len(v) for v in self.library.items.values())}

    def recorded(self) -> list[dict]:
        """Try-ons shipped in assets/tryon (tools/record_samples.py): what replay mode can show."""
        p = self.s.assets / "tryon" / "index.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    def samples(self) -> dict:
        rec = self.recorded()
        hands_ = [h | {"recorded": any(r["hand"] == h["id"] for r in rec)} for h in self.hands.samples()]
        return {"hands": hands_, "shortlist": SAMPLE_SHORTLIST, "source": SAMPLE_SOURCE,
                "recorded": [{k: r[k] for k in ("hand", "shape", "width_mm", "metal", "band", "key", "error_pct")}
                             for r in rec]}


def outline_mm(shape: str, length: float, width: float, n: int = 96) -> list:
    """Girdle outline in mm, centred, x across the finger and y along it (north-south setting)."""
    b = length / width
    pts = []
    for k in range(n):
        th = 2 * math.pi * k / n
        r = outlines.radius(shape, th, b)
        pts.append((r * math.cos(th) * width / 2, r * math.sin(th) * width / 2))
    ys = [p[1] for p in pts]
    mid = (max(ys) + min(ys)) / 2
    return [[round(x, 3), round(y - mid, 3)] for x, y in pts]


def evidence(root) -> dict:
    out = {}
    for p in sorted((root / "eval" / "results").glob("*summary*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def hand_public(h: hands.Hand) -> dict:
    d = h.as_public()
    v = hands.View(**h.view)
    f = h.finger
    d["overlay"] = {"line": v.apply(f["line_px"]), "knuckle_line": v.apply(f["knuckle_line_px"]) if f["knuckle_line_px"] else [],
                    "axis": v.apply(f["axis_px"]), "finger_px": f["width_px"], "size": [v.w, v.h]}
    d["photo"] = f"/api/hands/{h.id}/photo.jpg"
    d["view_image"] = f"/api/hands/{h.id}/view.jpg"
    return d

