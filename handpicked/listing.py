"""Read a diamond listing pasted by a shopper.

Every field keeps the exact span of listing text it came from, so the page can show the source and a
reviewer can check it. The rules cover GIA and IGI report wording, retailer product pages and free-text
marketplace listings, in English and French. A model is only asked for what the rules could not read, and
its answers go through the same span check (see `ground_model_fields`).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

SHAPE_WORDS = {
    "round": ["round brilliant", "round", "brilliant", "rond", "brillant"],
    "oval": ["oval", "ovale"],
    "cushion": ["cushion", "coussin"],
    "emerald": ["emerald", "émeraude", "emeraude"],
    "pear": ["pear", "poire"],
    "princess": ["princess", "princesse"],
    "radiant": ["radiant"],
    "marquise": ["marquise", "navette"],
}
UNSUPPORTED_SHAPES = ["heart", "coeur", "cœur", "asscher", "trillion", "baguette", "kite", "half moon"]
CURRENCY = {"€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR", "$": "USD", "usd": "USD", "us$": "USD",
            "dollar": "USD", "dollars": "USD",
            "£": "GBP", "gbp": "GBP", "chf": "CHF"}
LABS = ["GIA", "IGI", "HRD", "GCAL", "AGS", "GSI", "EGL"]
CLARITY = ["FL", "IF", "VVS1", "VVS2", "VS1", "VS2", "SI1", "SI2", "I1", "I2", "I3"]

NUM = r"\d{1,3}(?:[.,]\d{1,3})?"
X = r"\s*[x×X\*]\s*"


@dataclass
class Field:
    value: object
    start: int
    end: int
    quote: str
    method: str = "rule"


@dataclass
class Listing:
    text: str
    fields: dict[str, Field] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    masked: list[tuple[int, int]] = field(default_factory=list)   # instruction-like sentences, not read
    readable: str = ""                                            # text with those sentences blanked out

    def get(self, name, default=None):
        f = self.fields.get(name)
        return default if f is None else f.value

    def as_dict(self):
        return {"fields": {k: asdict(v) for k, v in self.fields.items()}, "notes": list(self.notes),
                "masked": [list(m) for m in self.masked]}


def to_float(s: str) -> float:
    """'1,01' -> 1.01 ; '3.050,00' -> 3050.0 ; '3 050' -> 3050.0 ; '4,200' -> 4200.0 ; '6.45' -> 6.45."""
    s = s.strip().replace(" ", " ").replace("\xa0", " ")
    s = re.sub(r"(?<=\d) (?=\d{3}\b)", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, tail = s.rsplit(",", 1)
        s = s.replace(",", "") if len(tail) == 3 and head.isdigit() and len(head) <= 3 else s.replace(",", ".")
    return float(s)


def to_money(s: str) -> float:
    """Like to_float, but a dot followed by exactly three digits is a thousands separator: '2.400' -> 2400."""
    t = s.strip().replace("\xa0", " ")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        return float(t.replace(".", ""))
    return to_float(t)


def _first(pattern, text, flags=re.I):
    return next(re.finditer(pattern, text, flags), None)


def _set(listing, name, value, m, group=0):
    listing.fields[name] = Field(value, m.start(group), m.end(group), m.group(group))


# Sentences written to steer a reader rather than describe the stone. They are blanked out (same length, so every
# span still points into the original text) before any field is read, and the listing is marked.
INSTRUCTION = [
    r"\b(?:ignore|disregard|forget)\b[^.!?\n]{0,60}\b(?:instructions?|previous|above|rules|prompt)\b",
    r"\b(?:ignore[zr]?|oublie[zr]?)\b[^.!?\n]{0,60}\b(?:instructions?|consignes?|règles|regles)\b",
    r"\b(?:note|message|instructions?)\s+(?:to|for|pour)\s+(?:the\s+|l[ea]s?\s+|l')?(?:ai|a\.i\.|ia|assistants?|bots?|"
    r"chatbots?|models?|modèles?|llms?|parsers?)\b",
    r"^\s*(?:system|assistant|ai|ia)\s*:",
    r"\b(?:ai|ia|assistants?|chatbots?|llms?|models?|modèles?)\b[^.!?\n]{0,40}\b(?:must|should|doit|doivent|devez)\b",
    r"\b(?:report|classify|rank|list|present|describe|treat|indique[zr]?|présente[zr]?|presente[zr]?|classe[zr]?)\b"
    r"[^.!?\n]{0,40}\b(?:this|the|ce|cette|le|la)\s+(?:stone|diamond|listing|pierre|diamant|annonce)\b[^.!?\n]{0,20}"
    r"\b(?:as|comme|en tant que)\b",
]
NOT_DIAMOND = {"moissanite": "moissanite", "sapphire": "sapphire", "saphir": "sapphire", "cubic zirconia": "cubic zirconia",
               "zircon": "zircon", "zircone": "cubic zirconia", "zirconium": "cubic zirconia", "zirconia": "cubic zirconia", "topaz": "topaz",
               "topaze": "topaz", "simulant": "simulant", "white spinel": "spinel", "spinelle": "spinel",
               "crystal glass": "glass", "verre": "glass"}


def mask_instructions(text: str) -> tuple[str, list[tuple[int, int]]]:
    spans = []
    for m in re.finditer(r"[^.!?\n]+[.!?]?", text):
        sentence = m.group(0)
        if any(re.search(p, sentence, re.I | re.M) for p in INSTRUCTION):
            spans.append((m.start(), m.end()))
    out = list(text)
    for a, b in spans:
        for i in range(a, b):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out), spans


def _not_diamond(text: str):
    for word, material in NOT_DIAMOND.items():
        for m in re.finditer(rf"\b{re.escape(word)}s?\b", text, re.I):
            before = text[max(0, m.start() - 12):m.start()].lower()
            if re.search(r"\b(?:not|no|non|pas de|pas un|sans)\s+(?:a\s+|une?\s+)?$", before):
                continue
            return material, m
    return None


def parse(text: str) -> Listing:
    original = text
    text, masked = mask_instructions(original)
    L = Listing(text=original, masked=masked, readable=text)
    if masked:
        L.notes.append("instruction-like text was ignored")
    low = text.lower()
    nd = _not_diamond(text)
    if nd:
        L.fields["not_diamond"] = Field(nd[0], nd[1].start(), nd[1].end(), original[nd[1].start():nd[1].end()])

    # --- carat weight (not gold karat, not total carat weight of a ring)
    for m in re.finditer(rf"(?<![\w.,])({NUM})\s*(?:carats?|cts?\.?|carat)(?!\s*(?:gold|or\b|white|yellow|rose))(\s*(?:tw|t\.w\.|ctw|tcw|total))?",
                         text, re.I):
        before = text[max(0, m.start() - 24):m.start()]
        line_before = before.rsplit("\n", 1)[-1]
        if m.group(2) or re.match(r"\s*(?:ctw|cttw|tcw|ct\.?\s*t\.?w|carats?\s*(?:total|t\.?w))", text[m.start(1) + len(m.group(1)):], re.I) \
                or re.search(r"\b(?:total|totale|t\.?w\.?)\b", line_before, re.I):
            L.notes.append("total carat weight found; the centre stone weight is needed")
            continue
        v = to_float(m.group(1))
        if re.fullmatch(r"(?:9|10|14|18|22|24)", m.group(1)):
            continue   # "18 carats" in running text is gold, not stone weight
        if 0.1 <= v <= 15:
            _set(L, "carat", v, m, 1)
            break
    if "carat" not in L.fields:
        m = _first(rf"(?:carat\s*weight|weight|poids|carat)(?!\s*total)\s*[:=.…]*\s*({NUM})(?!\s*(?:k\b|kt\b|gold|or\b))", text)
        if m and 0.1 <= to_float(m.group(1)) <= 15:
            _set(L, "carat", to_float(m.group(1)), m, 1)
    if re.search(r"\b\d{1,2}\s*(?:k|kt|karat|carats?)\s*(?:gold|or)\b", low):
        L.notes.append("gold karat mentioned; not read as stone weight")

    # --- measurements
    m = _first(rf"({NUM})\s*(?:-|–|to|à)\s*({NUM}){X}({NUM})\s*mm", text)
    if m:
        d1, d2, depth = (to_float(g) for g in m.groups())
        L.fields["measurements"] = Field({"length": max(d1, d2), "width": min(d1, d2), "depth": depth, "round_form": True},
                                         m.start(), m.end(), m.group(0))
    else:
        m = _first(rf"({NUM}){X}({NUM}){X}({NUM})\s*mm", text) or _first(rf"({NUM})\s*mm{X}({NUM})\s*mm{X}({NUM})\s*mm", text)
        if m:
            a, b, c = (to_float(g) for g in m.groups())
            L.fields["measurements"] = Field({"length": max(a, b), "width": min(a, b), "depth": c, "round_form": False},
                                             m.start(), m.end(), m.group(0))
    if "measurements" in L.fields and re.search(r"\b(?:approx|approximately|environ|~)\b", low):
        L.notes.append("measurements marked as approximate")

    # --- shape: the earliest shape word wins; unsupported shapes are reported
    best = None
    for shape, words in SHAPE_WORDS.items():
        for w in words:
            for mm in re.finditer(rf"\b{re.escape(w)}\b", text, re.I):
                if best is None or mm.start() < best[1].start():
                    best = (shape, mm)
    for w in UNSUPPORTED_SHAPES:
        mm = re.search(rf"\b{re.escape(w)}\b", text, re.I)
        if mm and (best is None or mm.start() < best[1].start()):
            L.fields["shape_unsupported"] = Field(w, mm.start(), mm.end(), mm.group(0))
            best = None
            break
    if best:
        _set(L, "shape", best[0], best[1])

    # --- price (the first amount with a currency; "from" prices are flagged)
    cur = r"(€|eur(?:os?)?\b|\$|us\$|usd|dollars?\b|£|gbp|chf)"
    amount = r"(\d{1,3}(?:[ ., \xa0]\d{3})+(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)"
    m = None
    for pat in (rf"{cur}\s*{amount}", rf"{amount}\s*{cur}"):
        for cand in re.finditer(pat, text, re.I):
            why = price_context(text, cand.start(), cand.end())
            if why == "from":
                if "price is a 'from' price" not in L.notes:
                    L.notes.append("price is a 'from' price")
                continue
            if why:
                continue
            m = cand
            break
        if m:
            break
    if m:
        g = m.groups()
        sym, num = (g[0], g[1]) if not g[0][0].isdigit() else (g[1], g[0])
        try:
            v = to_money(num)
        except ValueError:
            v = None
        if v and v >= 10:
            L.fields["price"] = Field({"amount": v, "currency": CURRENCY[sym.lower()]}, m.start(), m.end(), m.group(0))

    # --- grading facts
    m = _first(r"\b(" + "|".join(LABS) + r")\b", text, 0)
    if m:
        _set(L, "lab", m.group(1), m, 1)
    m = _first(r"(?:report|certificate|certificat|rapport)\s*(?:no\.?|number|n°|#)?\s*[:#]?\s*(\d{7,12})", text)
    if m:
        _set(L, "report_number", m.group(1), m, 1)
    m = _first(r"\b(lab[- ]?grown|laboratory[- ]grown|lab[- ]created|created diamond|man-made|cvd|hpht|synth[eé]tiques?|de synth[eè]se|de laboratoire|cultiv[ée]e?s?)\b", text)
    if m:
        _set(L, "origin", "lab", m, 1)
    else:
        m = _first(r"\b(natural|mined|earth[- ]mined|naturel(?:le)?s?)\b", text)
        if m:
            _set(L, "origin", "natural", m, 1)
    m = _first(r"(?:colou?r|couleur)\s*(?:grade)?[\s.:=…]*([D-M])\b", text) or _first(r"\b([D-K])\s*(?:colou?r)\b", text)
    if m:
        _set(L, "colour", m.group(1).upper(), m, 1)
    m = _first(r"\b(FL|IF|VVS ?[12]|VS ?[12]|SI ?[12]|I[123])\b", text, 0)
    if m:
        L.fields["clarity"] = Field(m.group(1).replace(" ", ""), m.start(1), m.end(1), m.group(1))
    m = _first(r"(?:depth|profondeur)\s*(?:%|percentage)?\s*[:=]?\s*(\d{2}(?:[.,]\d)?)\s*%", text)
    if m:
        _set(L, "depth_pct", to_float(m.group(1)), m, 1)
    m = _first(r"(?:table)\s*(?:%)?\s*[:=]?\s*(\d{2}(?:[.,]\d)?)\s*%", text)
    if m:
        _set(L, "table_pct", to_float(m.group(1)), m, 1)
    m = _first(r"(?:l/w|ratio|length[- ]to[- ]width)\s*(?:ratio)?\s*[:=]?\s*(\d[.,]\d{1,2})\b", text)
    if m:
        _set(L, "lw_ratio", to_float(m.group(1)), m, 1)
    m = _first(r"\b(platinum|platine|white gold|yellow gold|rose gold|or blanc|or jaune|or rose)\b", text)
    if m:
        metal = {"platine": "platinum", "or blanc": "white gold", "or jaune": "yellow gold", "or rose": "rose gold"}
        _set(L, "metal", metal.get(m.group(1).lower(), m.group(1).lower()), m, 1)
    return L


def price_context(text: str, start: int, end: int) -> str | None:
    """Why the amount at text[start:end] is not the price of this stone: "instalment", "setting" or "from"; None
    when it is."""
    after = text[end:end + 14].lower()
    before = re.sub(r"(?:us\$|\$|€|£|eur|usd|gbp|chf)\s*$", "", text[max(0, start - 28):start].lower())
    if re.match(r"\s*(?:/\s*mo|per month|/\s*mois|par mois|a month|x\s*\d|/\s*month)", after) \
            or re.search(r"\b(?:\d\s*x|ou \d+\s*x|or \d+ payments of|payments? of|mensualités?)\s*$", before):
        return "instalment"
    if re.search(r"\b(?:setting|monture|mount)\b[^\n]{0,20}$", before):
        return "setting"
    if re.search(r"\b(?:from|starting at|à partir de|a partir de|dès|des)\s*$", before):
        return "from"
    return None


REQUIRED = ("carat", "shape", "measurements", "price")


def missing(listing: Listing) -> list[str]:
    return [k for k in REQUIRED if k not in listing.fields]


SELLER_QUESTIONS = {
    "measurements": "Could you send the stone's measurements in millimetres (length x width x depth), as printed on the grading report?",
    "carat": "What is the centre stone's carat weight on its own, without any side stones?",
    "shape": "What is the shape of the centre stone?",
    "price": "What is the price of this stone, and is the setting included?",
}


def seller_question(listing: Listing) -> str | None:
    gaps = missing(listing)
    if not gaps:
        return None
    return " ".join(SELLER_QUESTIONS[g] for g in gaps)


# ------------------------------------------------------------------ model answers are grounded like rules
def ground_model_fields(listing: Listing, proposed: dict) -> list[str]:
    """Accept a model's proposed field only if its quote occurs in the readable listing text (instruction-like
    sentences excluded) and the quote itself states the value: every number of the value is written in the
    quote, next to a unit or currency of the right kind. Returns the names that were rejected."""
    rejected = []
    text = listing.readable or listing.text
    for name, item in proposed.items():
        if name in listing.fields or name not in GROUNDABLE or not isinstance(item, dict):
            continue
        quote = str(item.get("quote", "")).strip()
        start = text.find(quote) if quote else -1
        value = _normalise(name, item.get("value"))
        if start < 0 or value is None or not _quote_states(name, quote, value):
            rejected.append(name)
            continue
        if name == "price" and _price_refused(text, start, start + len(quote)):
            rejected.append(name)
            continue
        listing.fields[name] = Field(value, start, start + len(quote), listing.text[start:start + len(quote)],
                                     method="model")
    return rejected


GROUNDABLE = ("carat", "shape", "measurements", "price", "lab", "origin")


def _price_refused(text: str, start: int, end: int) -> bool:
    """A price the model quotes is held to the rules' context checks, on the amount inside the quote."""
    for m in _NUMS.finditer(text[start:end]):
        if price_context(text, start + m.start(), start + m.end()):
            return True
    return price_context(text, start, end) is not None
_NUMS = re.compile(r"\d{1,3}(?:[ .,\xa0]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?")


def _numbers_in(quote: str, money: bool = False) -> list[float]:
    out = []
    for tok in _NUMS.findall(quote):
        try:
            out.append(to_money(tok) if money else to_float(tok))
        except ValueError:
            pass
    return out


def _has(nums, v, tol):
    return any(abs(n - v) <= tol for n in nums)


def _normalise(name, v):
    try:
        if name == "carat":
            v = float(v)
            return v if 0.1 <= v <= 15 else None
        if name == "measurements":
            d = {k: float(v[k]) for k in ("length", "width", "depth")}
            if d["length"] < d["width"]:
                d["length"], d["width"] = d["width"], d["length"]
            return d | {"round_form": False} if all(1.0 <= x <= 30 for x in d.values()) else None
        if name == "price":
            amount = float(v["amount"] if isinstance(v, dict) else v)
            cur = str(v.get("currency", "")).upper() if isinstance(v, dict) else ""
            return {"amount": amount, "currency": cur} if cur in ("EUR", "USD", "GBP", "CHF") and amount >= 50 else None
        if name == "shape":
            return str(v).lower() if str(v).lower() in SHAPE_WORDS else None
        if name == "lab":
            return str(v).upper() if str(v).upper() in LABS else None
        if name == "origin":
            return str(v).lower() if str(v).lower() in ("lab", "natural") else None
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    return None


def _quote_states(name, quote, value) -> bool:
    q = quote.lower()
    nums = _numbers_in(quote)
    if name == "carat":
        return _has(nums, value, 0.005) and re.search(r"\b(?:ct|cts|carats?|weight|poids|karat)\b", q) is not None \
            and not re.search(r"\b(?:tw|t\.w\.|ctw|cttw|tcw|total)\b", q)
    if name == "measurements":
        return all(_has(nums, value[k], 0.011) for k in ("length", "width", "depth")) and "mm" in q
    if name == "price":
        sym = {"EUR": ("€", "eur"), "USD": ("$", "usd", "dollar"), "GBP": ("£", "gbp"), "CHF": ("chf",)}[value["currency"]]
        return _has(_numbers_in(quote, money=True), value["amount"], 0.51) and any(x in q for x in sym) \
            and not re.search(r"/\s*mo|per month|par mois|/\s*mois|setting|monture", q)
    if name == "shape":
        return any(re.search(rf"\b{re.escape(w)}\b", q) for w in SHAPE_WORDS[value])
    if name == "lab":
        return re.search(rf"\b{value.lower()}\b", q) is not None
    if name == "origin":
        return parse(quote).get("origin") == value
    return False
