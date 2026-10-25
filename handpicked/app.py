"""HTTP API and static web app.

    uvicorn handpicked.app:app --port 8000
"""
from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import Cookie, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import library, metrology, youcam
from .service import Handpicked, evidence, hand_public

MAX_UPLOAD = 15 * 1024 * 1024
WEB = Path(__file__).resolve().parent.parent / "web" / "dist"

_svc: Handpicked | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    if _svc is not None:
        _svc.close()


app = FastAPI(title="Handpicked", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
_tryon_lock = asyncio.Semaphore(4)


def svc() -> Handpicked:
    global _svc
    if _svc is None:
        _svc = Handpicked()
    return _svc


@app.middleware("http")
async def session_cookie(request: Request, call_next):
    sid = request.cookies.get("hp_session")
    if not sid:
        sid = secrets.token_hex(12)
        request.state.new_session = sid
    request.state.session = sid
    response: Response = await call_next(request)
    if getattr(request.state, "new_session", None):
        response.set_cookie("hp_session", sid, max_age=7 * 86400, httponly=True, samesite="lax")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


def _err(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


# ---------------------------------------------------------------------------------------------------- hands
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/samples")
def samples():
    s = svc().samples()
    s["hands"] = [hand_public(svc().hands.get(h["id"])) | {"recorded": h["recorded"]} for h in s["hands"]]
    return s


@app.post("/api/hands")
async def upload_hand(file: UploadFile = File(...)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        _err(413, "too_large", "The photo is larger than 15 MB.")
    try:
        hand = await asyncio.to_thread(svc().hands.add, data)
    except metrology.MeasureError as e:
        _err(422, e.code, str(e))
    return hand_public(hand)


@app.get("/api/hands/{hand_id}")
def get_hand(hand_id: str):
    try:
        return hand_public(svc().hands.get(hand_id))
    except KeyError:
        _err(404, "not_found", "This hand is not on the server any more; upload the photo again.")


@app.get("/api/hands/{hand_id}/photo.jpg")
def hand_photo(hand_id: str):
    try:
        return Response(svc().hands.photo(hand_id), media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})
    except (KeyError, FileNotFoundError):
        _err(404, "not_found", "No such hand.")


@app.get("/api/hands/{hand_id}/view.jpg")
def hand_view(hand_id: str):
    try:
        return Response(_view(hand_id, None), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
    except (KeyError, FileNotFoundError):
        _err(404, "not_found", "No such hand.")


@lru_cache(maxsize=256)
def _view(hand_id: str, key: str | None) -> bytes:
    image = svc().tryon_image(key) if key else None
    return svc().hands.view_image(hand_id, image)


# ---------------------------------------------------------------------------------------------------- listings
class Texts(BaseModel):
    texts: list[str] = Field(..., max_length=6)


class CompareIn(Texts):
    hand_id: str


@app.post("/api/listings/read")
async def read_listings(body: Texts):
    return {"readings": await svc().read(body.texts)}


@app.post("/api/compare")
async def compare(body: CompareIn):
    try:
        return await svc().compare(body.hand_id, body.texts)
    except KeyError:
        _err(404, "not_found", "This hand is not on the server any more; upload the photo again.")


# ---------------------------------------------------------------------------------------------------- try-on
class TryOnIn(BaseModel):
    hand_id: str
    shape: str
    width_mm: float = Field(..., gt=2, lt=20)
    metal: str = "platinum"
    band: bool = False


@app.post("/api/tryon")
async def tryon(body: TryOnIn, request: Request):
    async with _tryon_lock:
        try:
            return await svc().tryon(body.hand_id, body.shape, body.width_mm, body.metal, body.band,
                                     request.state.session)
        except KeyError:
            _err(404, "not_found", "This hand is not on the server any more; upload the photo again.")
        except youcam.CapReached as e:
            _err(429, e.code, str(e))
        except youcam.YouCamError as e:
            _err(502 if e.code != "replay_only" else 409, e.code, str(e))
        except ValueError as e:
            _err(422, "out_of_range", str(e))


@app.get("/api/tryon/{key}.jpg")
def tryon_image(key: str):
    try:
        return Response(svc().tryon_image(key), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
    except KeyError:
        _err(404, "not_found", "No such try-on.")


@app.get("/api/tryon/{key}/view.jpg")
def tryon_view(key: str, hand: str):
    try:
        return Response(_view(hand, key), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
    except (KeyError, FileNotFoundError):
        _err(404, "not_found", "No such try-on.")


# ---------------------------------------------------------------------------------------------------- merchant, status
class MerchantIn(BaseModel):
    hand_id: str
    budget: float = Field(..., gt=0)
    shapes: list[str] | None = None


@app.post("/api/merchant/rank")
def merchant_rank(body: MerchantIn):
    try:
        return svc().merchant(body.hand_id, body.budget, body.shapes)
    except KeyError:
        _err(404, "not_found", "No such hand.")


@app.get("/api/merchant/inventory")
def merchant_inventory():
    return svc().inventory


@app.get("/api/status")
async def status(hp_session: str | None = Cookie(default=None)):
    s = await svc().status()
    s["session_units"] = svc().ledger.spent(hp_session) if hp_session else 0
    return s


@app.get("/api/evidence")
def get_evidence():
    return evidence(svc().s.root)


@app.get("/api/library")
def ring_library():
    lib: library.RingLibrary = svc().library
    return {"shapes": sorted({s for s, _ in lib.items}), "metals": sorted({m for _, m in lib.items}),
            "ratios": [round(m["product_ratio"], 3) for m in lib.items.get(("round", "platinum"), [])],
            "calibration": svc().s.calibration}


EMBED_JS = """(function () {
  var s = document.currentScript, base = s.src.replace(/\\/embed\\.js.*$/, "");
  var b = document.createElement("a");
  b.href = base + "/?add=" + encodeURIComponent(s.getAttribute("data-stone") || "");
  b.target = "_blank"; b.rel = "noopener";
  b.textContent = s.getAttribute("data-label") || "Compare on your hand";
  b.style.cssText = "display:inline-block;padding:10px 16px;border:1px solid #111;color:#111;background:#fff;" +
    "font:500 14px/1.2 system-ui,sans-serif;text-decoration:none;letter-spacing:.02em";
  s.parentNode.insertBefore(b, s);
})();
"""


@app.get("/embed.js")
def embed_js():
    return PlainTextResponse(EMBED_JS, media_type="application/javascript",
                             headers={"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*"})


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=detail)


if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="web-assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = WEB / path
        if path and f.is_file() and WEB in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
