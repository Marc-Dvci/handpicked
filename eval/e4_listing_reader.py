"""E4: how accurately does Handpicked read a pasted listing, and does any wrong number reach the board?

Corpus: eval/listings/corpus.jsonl, 60 listings in six formats (GIA and IGI report text, retailer pages in English
and French, marketplace ads in English and French), labelled with what each listing states. Half is held out.

Two readers are scored on the same listings:
* rules: `listing.parse`, deterministic;
* rules + model: the model reads only the fields the rules left empty, and each value it returns is kept only if
  its quote occurs in the listing and states that value (`listing.ground_model_fields`).

For every field the result is correct when it equals the label, including "not stated" left empty. A wrong number
on the board is a stone the board ranks with a carat, measurement or price that differs from its label.

    python eval/e4_listing_reader.py --split dev|heldout|all|freetext [--model]

`--split freetext` scores eval/listings/freetext.jsonl: ten listings phrased the way people write in messages
("7.9 by 5.6 by 3.4 mm", "a touch under a carat (0.96 ct)"), where the rules alone leave gaps.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handpicked import compare, config, listing  # noqa: E402
from handpicked.service import Handpicked  # noqa: E402

CORPUS = ROOT / "eval" / "listings" / "corpus.jsonl"
RESULTS = ROOT / "eval" / "results"
FIELDS = ["carat", "shape", "measurements", "price", "lab", "origin", "colour", "clarity", "not_diamond",
          "shape_unsupported"]


def same(name, got, want) -> bool:
    if name == "not_diamond":
        return bool(got) == bool(want)
    if want is None or got is None:
        return want is None and got is None
    if name == "measurements":
        return all(abs(float(got[k]) - float(want[k])) < 0.011 for k in ("length", "width", "depth"))
    if name == "price":
        return abs(float(got["amount"]) - float(want["amount"])) < 0.51 and got["currency"] == want["currency"]
    if name == "carat":
        return abs(float(got) - float(want)) < 0.0051
    return str(got).lower() == str(want).lower()


def grounded(L: listing.Listing) -> list[str]:
    """Fields whose quote is not the text at their span: must be empty."""
    return [k for k, f in L.fields.items() if L.text[f.start:f.end] != f.quote]


async def read(svc: Handpicked | None, text: str) -> listing.Listing:
    L = listing.parse(text)
    if svc and svc.model:
        gaps = [g for g in listing.missing(L) if g in listing.GROUNDABLE]
        if gaps and "not_diamond" not in L.fields and "shape_unsupported" not in L.fields:
            proposed = await svc._cached("extract", L.readable, lambda: svc.model.extract(L.readable)) or {}
            listing.ground_model_fields(L, {k: v for k, v in proposed.items() if k in gaps})
    return L


def value(L: listing.Listing, name):
    if name == "not_diamond":
        return "not_diamond" in L.fields
    v = L.get(name)
    if name == "measurements" and v:
        return {k: v[k] for k in ("length", "width", "depth")}
    return v


async def run(split: str, use_model: bool, corpus: Path = CORPUS) -> dict:
    rows = [json.loads(x) for x in corpus.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        r.setdefault("split", "freetext")
        r.setdefault("format", "freetext")
        r.setdefault("traps", [])
        for f in FIELDS:
            r["label"].setdefault(f, False if f == "not_diamond" else None)
    rows = [r for r in rows if split in ("all", "freetext") or r["split"] == split]
    svc = Handpicked(config.load()) if use_model else None
    per_field = {f: {"correct": 0, "wrong": 0, "missed": 0} for f in FIELDS}
    out, wrong_on_board, ungrounded, injected_obeyed, model_fields = [], 0, 0, 0, 0
    status_ok = 0
    for r in rows:
        L = await read(svc, r["text"])
        lab = r["label"]
        res = {"id": r["id"], "format": r["format"], "split": r["split"], "fields": {}}
        for f in FIELDS:
            got, want = value(L, f), lab.get(f)
            ok = same(f, got, want)
            kind = "correct" if ok else ("missed" if got in (None, False) else "wrong")
            per_field[f][kind] += 1
            if not ok:
                res["fields"][f] = {"got": got, "want": want}
        ungrounded += len(grounded(L))
        model_fields += sum(1 for x in L.fields.values() if x.method == "model")
        item = compare.stone_from_listing(r["id"], L)
        want_ready = all(lab.get(k) is not None for k in ("carat", "shape", "measurements")) and not lab.get(
            "not_diamond") and not lab.get("shape_unsupported")
        status_ok += isinstance(item, compare.Stone) == want_ready
        if isinstance(item, compare.Stone):
            bad = [f for f in ("carat", "measurements", "price", "shape")
                   if value(L, f) is not None and not same(f, value(L, f), lab.get(f))]
            if bad:
                wrong_on_board += 1
                res["on_board_wrong"] = bad
        if "injection" in r.get("traps", []):
            injected_obeyed += not same("carat", value(L, "carat"), lab.get("carat"))
        res["status"] = "ready" if isinstance(item, compare.Stone) else "waiting"
        out.append(res)
    total = len(rows) * len(FIELDS)
    correct = sum(v["correct"] for v in per_field.values())
    summary = {
        "split": split, "reader": "rules + model" if use_model else "rules", "listings": len(rows),
        "field_accuracy_pct": round(100 * correct / total, 1), "fields_scored": total,
        "per_field": per_field, "wrong_number_on_board": wrong_on_board,
        "status_correct": status_ok, "ungrounded_fields": ungrounded, "model_fields_accepted": model_fields,
        "injection_listings": sum("injection" in r.get("traps", []) for r in rows),
        "injection_obeyed": injected_obeyed,
        "model": svc.s.model if svc and svc.model else None,
    }
    tag = f"{split}_{'model' if use_model else 'rules'}"
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"e4_reader_{tag}.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out),
                                                     encoding="utf-8")
    (RESULTS / f"e4_summary_{tag}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("dev", "heldout", "all", "freetext"), default="dev")
    ap.add_argument("--model", action="store_true", help="rules + model (needs DASHSCOPE_API_KEY)")
    args = ap.parse_args()
    corpus = ROOT / "eval" / "listings" / ("freetext.jsonl" if args.split == "freetext" else "corpus.jsonl")
    print(json.dumps(asyncio.run(run(args.split, args.model, corpus)), indent=1))


if __name__ == "__main__":
    main()
