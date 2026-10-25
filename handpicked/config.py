"""Settings from the environment.

| Variable | Default | Meaning |
|---|---|---|
| `YOUCAM_API_KEY` | unset | Live Ring VTO calls. Unset: recorded try-ons only (replay mode) |
| `DASHSCOPE_API_KEY` | unset | Listing reader and verdict on Alibaba Cloud Model Studio. Unset: rules and template only |
| `HANDPICKED_MODEL` | `deepseek-v4.1-flash-1017` | Model Studio model id |
| `HANDPICKED_VAR` | `<repo>/var` | Uploads, ledgers, live try-on cache |
| `HANDPICKED_DAY_UNITS` | 120 | YouCam units the server may spend in 24 h |
| `HANDPICKED_SESSION_UNITS` | 8 | YouCam units one browser session may spend |
| `HANDPICKED_DAY_TOKENS` | 60000 | Model tokens the server may spend in 24 h |
| `HANDPICKED_ENV_FILE` | unset | Optional `KEY=value` files (separated by `;`) read before the variables above |
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env_files(spec: str | None) -> None:
    for name in filter(None, (spec or "").split(";")):
        p = Path(name)
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


@dataclass
class Settings:
    root: Path
    assets: Path
    var: Path
    youcam_key: str | None
    dashscope_key: str | None
    model: str
    day_units: int
    session_units: int
    day_tokens: int
    calibration: dict


def load() -> Settings:
    load_env_files(os.environ.get("HANDPICKED_ENV_FILE"))
    assets = ROOT / "assets"
    cal_path = assets / "calibration.json"
    cal = json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.exists() else {}
    return Settings(
        root=ROOT,
        assets=assets,
        var=Path(os.environ.get("HANDPICKED_VAR", ROOT / "var")),
        youcam_key=os.environ.get("YOUCAM_API_KEY") or None,
        dashscope_key=os.environ.get("DASHSCOPE_API_KEY") or None,
        model=os.environ.get("HANDPICKED_MODEL", "deepseek-v4.1-flash-1017"),
        day_units=int(os.environ.get("HANDPICKED_DAY_UNITS", 120)),
        session_units=int(os.environ.get("HANDPICKED_SESSION_UNITS", 8)),
        day_tokens=int(os.environ.get("HANDPICKED_DAY_TOKENS", 60000)),
        calibration=cal,
    )
