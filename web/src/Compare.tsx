import { useEffect, useRef, useState } from "react";
import type { EvidenceData } from "./App";
import { api, ApiError, money, SHAPE_NAMES, type Board, type Hand, type Reading, type Row, type Samples, type Status, type TryOn } from "./api";
import { Dim, FIELD_NAMES, fieldValue, ScaleDrawing, SourceText } from "./draw";
import { LoupeFigure, MeasureFacts, SheetFigure } from "./Measure";

const SLOTS = 4;
const LETTERS = "ABCD";
const READ_ORDER = ["shape", "carat", "measurements", "price", "origin", "lab", "colour", "clarity", "not_diamond", "shape_unsupported"];

type TryState = { state: "loading" } | { state: "done"; r: TryOn } | { state: "error"; message: string };

interface Props {
  samples: Samples | null;
  hand: Hand | null;
  setHand: (h: Hand) => void;
  status: Status | null;
  evidence: EvidenceData | null;
  onSpend: () => void;
}

const scrollTo = (id: string) =>
  requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }));

export default function Compare({ samples, hand, setHand, status, evidence, onSpend }: Props) {
  const [texts, setTexts] = useState<string[]>(() => {
    const add = new URLSearchParams(location.search).get("add");
    return Array.from({ length: SLOTS }, (_, i) => (i === 0 && add ? add : ""));
  });
  const [usedSample, setUsedSample] = useState(false);
  const [board, setBoard] = useState<Board | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ where: string; message: string } | null>(null);
  const [tries, setTries] = useState<Record<string, TryState>>({});
  const [metal, setMetal] = useState<"platinum" | "yellow">("platinum");
  const band = false;
  const [chosen, setChosen] = useState<string | null>(null);
  const lastCompared = useRef<string>("");

  useEffect(() => {
    if (new URLSearchParams(location.search).get("add")) {
      history.replaceState(null, "", location.pathname + location.hash);
      scrollTo("step-2");
    }
  }, []);

  const filled = texts.filter((t) => t.trim()).length;
  const live = status?.mode === "live";

  async function runCompare(h: Hand, t: string[]) {
    setBusy("compare");
    setError(null);
    try {
      const b = await api.compare(h.id, t.filter((x) => x.trim()));
      setBoard(b);
      setTries({});
      setChosen(null);
      lastCompared.current = h.id + "|" + t.join("\u0000");
      return b;
    } catch (e) {
      setError({ where: "compare", message: (e as Error).message });
      return null;
    } finally {
      setBusy(null);
    }
  }

  // A new hand changes every coverage figure and every try-on: compare again with the same listings.
  useEffect(() => {
    if (hand && board && board.hand_id !== hand.id && filled) void runCompare(hand, texts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hand?.id]);

  async function quickDemo() {
    if (!samples) return;
    const h = samples.hands[0];
    const t = Array.from({ length: SLOTS }, (_, i) => samples.shortlist[i] ?? "");
    setHand(h);
    setTexts(t);
    setUsedSample(true);
    const b = await runCompare(h, t);
    if (b) scrollTo("step-3");
  }

  async function upload(file: File) {
    setBusy("upload");
    setError(null);
    try {
      const h = await api.upload(file);
      setHand(h);
      scrollTo("measure");
    } catch (e) {
      setError({ where: "upload", message: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  function isRecorded(row: Row) {
    if (!samples || !hand) return false;
    return samples.recorded.some((r) => r.hand === hand.id && r.shape === row.shape && Math.abs(r.width_mm - row.width_mm) < 0.005
      && r.metal === metal && r.band === band);
  }

  async function tryOn(row: Row) {
    if (!hand) return;
    setTries((s) => ({ ...s, [tryKey(row.id, metal, band)]: { state: "loading" } }));
    try {
      const r = await api.tryon(hand.id, row.shape, row.width_mm, metal, band);
      setTries((s) => ({ ...s, [tryKey(row.id, metal, band)]: { state: "done", r } }));
    } catch (e) {
      const err = e as ApiError;
      const message = err.code === "replay_only"
        ? "This server plays recorded try-ons only, and this stone was not recorded on this hand. The sample hands 1, 2 and 5 with the sample shortlist were."
        : err.message;
      setTries((s) => ({ ...s, [tryKey(row.id, metal, band)]: { state: "error", message } }));
    } finally {
      onSpend();
    }
  }

  async function tryAll() {
    if (!board) return;
    await Promise.all(board.rows.map((r) => {
      const t = tries[tryKey(r.id, metal, band)];
      return t?.state === "done" || t?.state === "loading" ? undefined : tryOn(r);
    }));
  }

  const stale = !!(board && hand && lastCompared.current !== hand.id + "|" + texts.join("\u0000"));
  const ranked = board?.rows ?? [];
  const decided = ranked.find((r) => r.id === chosen) ?? ranked.find((r) => r.rank === 1) ?? ranked[0];

  return (
    <>
      <Hero onDemo={quickDemo} ready={!!samples} busy={busy === "compare"} evidence={evidence} samples={samples} />

      {/* ------------------------------------------------------------------ 01 hand */}
      <section className="step" id="step-1" aria-labelledby="h-1">
        <StepHead no="01" id="h-1" title="Your hand"
          text="Choose a sample hand, or photograph the back of your own hand lying flat on a sheet of A4 or US Letter paper." />
        <div className="hands" role="group" aria-label="Sample hands">
          {samples?.hands.map((h, i) => (
            <button key={h.id} type="button" className="hand-pick" aria-pressed={hand?.id === h.id} onClick={() => setHand(h)}>
              <img src={h.photo} alt="" loading="lazy" width={h.image_size[0]} height={h.image_size[1]} />
              <span>Hand {i + 1}<br />{h.finger.width_mm.toFixed(1)} mm · US {h.fit.us}
                {!live && h.recorded && <><br /><em>try-ons recorded</em></>}</span>
            </button>
          ))}
          {!samples && Array.from({ length: 7 }, (_, i) => <div key={i} className="hand-pick ghost" aria-hidden="true" />)}
        </div>
        <Upload busy={busy === "upload"} onFile={upload} />
        {error?.where === "upload" && <p className="error" role="alert">{error.message}</p>}

        {hand && (
          <div className="measure" id="measure" aria-live="polite">
            <div className="measure-figs">
              <SheetFigure hand={hand} />
              <figure className="fig">
                <LoupeFigure hand={hand} />
                <figcaption className="small muted">Where the ring sits, finger upright. Edges are read where the colour changes fastest.</figcaption>
              </figure>
            </div>
            <MeasureFacts hand={hand} />
          </div>
        )}
      </section>

      {/* ------------------------------------------------------------------ 02 listings */}
      <section className="step" id="step-2" aria-labelledby="h-2">
        <StepHead no="02" id="h-2" title="The stones you are comparing"
          text="Paste two to four listings as the seller wrote them. Each value is shown with the words it was read from; a stone missing its millimetres waits for the seller's answer." />
        <div className="listings">
          {texts.map((t, i) => (
            <div className="listing" key={i}>
              <label className="label" htmlFor={`listing-${i}`}>Stone {LETTERS[i]}</label>
              <textarea id={`listing-${i}`} value={t} spellCheck={false}
                placeholder={i === 0 ? "Oval diamond, 0.92 ct\n8.10 x 5.62 x 3.45 mm\n$2,506" : "Paste a listing"}
                onChange={(e) => {
                  const v = e.target.value;
                  setTexts((s) => s.map((x, j) => (j === i ? v : x)));
                  setUsedSample(false);
                }} />
            </div>
          ))}
        </div>
        <div className="row-gap actions">
          <button type="button" className="btn" disabled={!hand || filled < 1 || busy === "compare"}
            onClick={() => hand && runCompare(hand, texts).then((b) => b && scrollTo("step-3"))}>
            {busy === "compare" ? "Reading…" : "Read and compare"}
          </button>
          <button type="button" className="btn ghost" disabled={!samples} onClick={() => {
            if (!samples) return;
            setTexts(Array.from({ length: SLOTS }, (_, i) => samples.shortlist[i] ?? ""));
            setUsedSample(true);
          }}>Load the sample shortlist</button>
          {!hand && <span className="small muted">Choose a hand first.</span>}
          {stale && <span className="small flag">The listings or the hand changed: compare again.</span>}
        </div>
        {usedSample && samples && <p className="small muted">{samples.source}</p>}
        {error?.where === "compare" && <p className="error" role="alert">{error.message}</p>}

        {board && (
          <>
            <p className="legend small">
              <mark>highlighted</mark> read by the rules · <mark className="model">ruled above and below</mark> read by
              the model and found word for word in the listing · <s>struck</s> instruction-like text, ignored
            </p>
            <div className="readings">
              {board.readings.map((r) => <ReadingView key={r.id} r={r} />)}
            </div>
          </>
        )}
      </section>

      {/* ------------------------------------------------------------------ 03 board */}
      <section className="step" id="step-3" aria-labelledby="h-3" aria-disabled={!board}>
        <StepHead no="03" id="h-3" title="On paper"
          text="What each stone shows from above, on your finger, and what each face-up square millimetre costs. Ranked by price per mm²." />
        {!board && <p className="muted">The board appears once a hand is chosen and the listings are read.</p>}
        {board && <BoardView board={board} />}
      </section>

      {/* ------------------------------------------------------------------ 04 try-on */}
      <section className="step" id="step-4" aria-labelledby="h-4" aria-disabled={!board?.rows.length}>
        <StepHead no="04" id="h-4" title="On your hand"
          text="Each stone drawn on your photo by the YouCam Ring Virtual Try-On, at its listed width. Every render is measured after it comes back." />
        {board && board.rows.length > 0 && hand && (
          <>
            <div className="controls">
              <div className="seg" role="group" aria-label="Metal">
                {(["platinum", "yellow"] as const).map((m) => (
                  <button key={m} type="button" aria-pressed={metal === m} onClick={() => setMetal(m)}>
                    {m === "platinum" ? "Platinum" : "Yellow gold"}
                  </button>
                ))}
              </div>
              <button type="button" className="btn" onClick={tryAll}
                disabled={ranked.every((r) => ["loading", "done"].includes(tries[tryKey(r.id, metal, band)]?.state ?? ""))}>
                Put every stone on my hand
              </button>
              <span className="small muted">
                {live ? `About 5 s and 1 unit per stone; this session may spend ${status?.session_cap}.`
                  : "Replay: recorded renders for the sample hands 1, 2 and 5 with the sample shortlist."}
              </span>
            </div>
            <div className="tryons">
              <figure className="tryon">
                <div className="frame" style={{ ["--ar" as string]: `${hand.overlay.size[0]} / ${hand.overlay.size[1]}` }}>
                  <img src={hand.view_image} alt="The bare finger" />
                  <svg viewBox={`0 0 ${hand.overlay.size[0]} ${hand.overlay.size[1]}`} aria-hidden="true">
                    <FingerDim hand={hand} />
                  </svg>
                </div>
                <figcaption>
                  <h3>Bare finger</h3>
                  <p className="audit">{hand.finger.width_mm.toFixed(2)} mm · US {hand.fit.us}</p>
                </figcaption>
              </figure>
              {ranked.map((row) => (
                <TryOnCard key={row.id} row={row} hand={hand} t={tries[tryKey(row.id, metal, band)]} recorded={isRecorded(row)}
                  live={live} chosen={decided?.id === row.id} onTry={() => tryOn(row)} onChoose={() => { setChosen(row.id); scrollTo("step-5"); }} />
              ))}
            </div>
            <p className="small muted note">
              The size check reads the band's width in each render, because the engine fits the band to the finger; the
              stone follows it. Calibrated on {evidence?.e3_summary?.per_render?.renders ?? "…"} live renders.
            </p>
          </>
        )}
        {!board?.rows.length && <p className="muted">Try-ons appear once at least one stone is on the board.</p>}
      </section>

      {/* ------------------------------------------------------------------ 05 decision */}
      <section className="step print" id="step-5" aria-labelledby="h-5" aria-disabled={!decided}>
        <StepHead no="05" id="h-5" title="Your decision"
          text="One stone, the size to order, and the reason in one line. Print it or copy it into a message to the seller." />
        {decided && hand && board ? (
          <Decision row={decided} hand={hand} board={board} t={tries[tryKey(decided.id, metal, band)]} />
        ) : (
          <p className="muted">The decision card appears with the board.</p>
        )}
      </section>
    </>
  );
}

const tryKey = (id: string, metal: string, band: boolean) => `${id}|${metal}|${band ? 1 : 0}`;

function StepHead({ no, id, title, text }: { no: string; id: string; title: string; text: string }) {
  return (
    <div className="step-head">
      <span className="step-no">{no}</span>
      <h2 id={id}>{title}</h2>
      <p>{text}</p>
    </div>
  );
}

function Hero({ onDemo, ready, busy, evidence, samples }: {
  onDemo: () => void; ready: boolean; busy: boolean; evidence: EvidenceData | null; samples: Samples | null;
}) {
  const e1 = evidence?.e1_summary_exif_heldout?.width_corrected;
  const e3 = evidence?.e3_summary?.leave_one_hand_out;
  const e4 = evidence?.e4_summary_heldout_model;
  const h1 = samples?.hands[0];
  const shots = (samples?.shortlist ?? []).map((_, i) => {
    const want = HERO_STONES[i];
    const r = samples?.recorded.find((x) => x.hand === "hand-1" && x.metal === "platinum" && !x.band && x.shape === want.shape
      && Math.abs(x.width_mm - want.width) < 0.005);
    return r ? { ...want, key: r.key, error: r.error_pct } : null;
  }).filter((x): x is NonNullable<typeof x> => !!x);
  return (
    <div className="hero">
      <div>
        <h1>Which diamond looks biggest on your hand?</h1>
        <p>
          Carat is weight. What you see is the stone's face-up area against your finger. Handpicked measures your finger
          from one photo, reads the listings you are comparing, and shows each stone on your own hand at its listed size
          with the YouCam Ring Virtual Try-On, next to the price of each face-up square millimetre.
        </p>
        <div className="row-gap hero-actions">
          <button type="button" className="btn" disabled={!ready || busy} onClick={onDemo}>
            {busy ? "Comparing…" : "Run the sample: hand 1, three stones"}
          </button>
          <a className="btn ghost" href="#step-1" onClick={(e) => { e.preventDefault(); scrollTo("step-1"); }}>Use my own hand</a>
        </div>
        <dl aria-label="Measured">
          <dt>Finger</dt>
          <dd>{e1 ? <>median error <b className="num">{e1.median_abs_error_mm.toFixed(2)} mm</b> on {e1.n} held-out scenes of known size</> : "…"}</dd>
          <dt>Try-on</dt>
          <dd>{e3 ? <>stone width within <b className="num">{e3.residual_median_pct}%</b> (median) on hands the calibration did not see; {e3.within_5pct} of {e3.renders} live renders within 5%</> : "…"}</dd>
          <dt>Listings</dt>
          <dd>{e4 ? <><b className="num">{e4.field_accuracy_pct}%</b> of fields read, <b className="num">{e4.wrong_number_on_board}</b> wrong numbers on the board, {e4.injection_listings - e4.injection_obeyed} of {e4.injection_listings} injections ignored</> : "…"}</dd>
        </dl>
      </div>
      {h1 && shots.length === 3 && (
        <figure className="hero-fig">
          <div className="hero-tiles">
            {shots.map((s) => (
              <div key={s.key} className="hero-tile">
                <div className="crop">
                  <img src={`/api/tryon/${s.key}/view.jpg?hand=hand-1`} alt={`${s.label} on hand 1`} width={h1.overlay.size[0]} height={h1.overlay.size[1]} />
                </div>
                <p><b>{s.label}</b><span className="num">{s.price}</span></p>
              </div>
            ))}
          </div>
          <figcaption className="small muted">
            Hand 1, finger {h1.finger.width_mm.toFixed(2)} mm. Each stone at its listed width, rendered by the YouCam Ring VTO and
            checked after rendering (all within {Math.max(...shots.map((s) => Math.abs(s.error))).toFixed(1)}%).
          </figcaption>
        </figure>
      )}
    </div>
  );
}

const HERO_STONES = [
  { shape: "round", width: 6.36, label: "1.01 ct round", price: "$4,413" },
  { shape: "round", width: 6.24, label: "0.93 ct round", price: "$2,841" },
  { shape: "oval", width: 5.62, label: "0.92 ct oval", price: "$2,506" },
];

function Upload({ busy, onFile }: { busy: boolean; onFile: (f: File) => void }) {
  const [consent, setConsent] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="upload">
      <ol className="capture">
        <li>Lay the back of your hand flat on the sheet, fingers apart.</li>
        <li>Photograph from straight above, the whole sheet in frame.</li>
      </ol>
      <label className="check">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        This is my hand, or its owner agreed
      </label>
      <input ref={input} id="upload" type="file" accept="image/jpeg,image/png,image/webp" className="visually-hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
      <button type="button" className="btn ghost" disabled={!consent || busy} onClick={() => input.current?.click()}>
        {busy ? "Measuring…" : "Upload a photo"}
      </button>
      <p className="small muted privacy">
        The photo is measured on this server, sent to the YouCam API for the try-on, and deleted after 24 hours. It is
        never sent to a language model.
      </p>
    </div>
  );
}

function ReadingView({ r }: { r: Reading }) {
  const [copied, setCopied] = useState(false);
  const keys = READ_ORDER.filter((k) => r.fields[k]);
  return (
    <article className="reading">
      <h3><span className="num">{r.id}</span>{r.label}
        <span className={`tag ${r.status === "ready" ? "ok" : "flag"}`}>{r.status === "ready" ? "on the board" : "waiting for the seller"}</span>
      </h3>
      <SourceText text={r.text} fields={r.fields} masked={r.masked} />
      <table className="fields">
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <td>{FIELD_NAMES[k] ?? k}</td>
              <td>{fieldValue(k, r.fields[k])}{r.fields[k].method === "model" && <span className="muted"> · model, checked</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {r.notes.length > 0 && <ul className="notes small">{r.notes.map((n) => <li key={n}>{cap(n)}.</li>)}</ul>}
      {r.model_rejected.length > 0 && (
        <p className="small muted">The model proposed {r.model_rejected.join(", ")}; not found in the listing's words, so not used.</p>
      )}
      {r.status === "waiting" && r.question && (
        <div className="question">
          <p className="label">Question for the seller</p>
          <p>{r.question}</p>
          <button type="button" className="btn link" onClick={() => navigator.clipboard?.writeText(r.question!).then(() => setCopied(true))}>
            {copied ? "Copied" : "Copy the question"}
          </button>
        </div>
      )}
    </article>
  );
}

const FLAG_TEXT: Record<string, (r: Row) => string> = {
  round_weight: () => "Priced at a round weight: natural stones cost about 24% more per carat from 1.00 ct.",
  weight_mismatch: (r) => `The listed millimetres imply ${r.weight_estimate} ct, not ${r.carat} ct. Ask for the report.`,
  approximate_mm: () => "Measurements marked approximate.",
  no_price: () => "No price given: not ranked.",
};

function BoardView({ board }: { board: Board }) {
  const v = board.verdict;
  return (
    <div aria-live="polite">
      <div className="board-wrap">
        <table className="board">
          <caption className="visually-hidden">Stones ranked by price per face-up square millimetre on a finger {board.finger_mm.toFixed(2)} mm wide</caption>
          <thead>
            <tr>
              <th scope="col">Stone</th>
              <th scope="col">Face-up<br />area</th>
              <th scope="col">Across<br />your finger</th>
              <th scope="col">Price</th>
              <th scope="col">Per<br />mm²</th>
              <th scope="col">Spread vs<br />typical cut</th>
              <th scope="col">Weight<br />from mm</th>
            </tr>
          </thead>
          <tbody>
            {board.rows.map((r) => (
              <tr key={r.id} className={r.rank === 1 ? "best" : undefined}>
                <td className="stone">
                  <span className="num letter">{r.id}</span> <b>{r.label}</b>
                  <span className="sub">{r.origin ? cap(r.origin) + " · " : ""}{r.width_mm.toFixed(2)} × {r.length_mm.toFixed(2)} × {r.depth_mm.toFixed(2)} mm</span>
                  {r.flags.filter((f) => FLAG_TEXT[f]).map((f) => <span key={f} className="sub flag">{FLAG_TEXT[f](r)}</span>)}
                </td>
                <td>{r.area_mm2.toFixed(1)} mm²</td>
                <td>{r.coverage_pct.toFixed(0)}%<span className="sub">{r.width_mm.toFixed(2)} mm</span></td>
                <td>{money(r.price, r.currency)}</td>
                <td>{r.price_per_mm2 != null ? money(r.price_per_mm2, r.currency) : "—"}{r.rank === 1 && <span className="sub ok">lowest</span>}</td>
                <td>{r.spread_pct > 0 ? "+" : ""}{r.spread_pct.toFixed(1)}%<span className="sub">typical {r.typical_area_mm2.toFixed(1)} mm²</span></td>
                <td>{r.weight_estimate != null ? `${r.weight_estimate.toFixed(2)} ct` : "—"}
                  {r.weight_estimate != null && <span className={`sub ${r.flags.includes("weight_mismatch") ? "flag" : "ok"}`}>
                    {r.flags.includes("weight_mismatch") ? "does not match" : "matches"}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {board.notes.map((n) => <p key={n} className="small flag">{n}</p>)}
      {board.pending.length > 0 && (
        <p className="small muted">Waiting outside the ranking: {board.pending.map((p) => `${p.id} (${p.label})`).join(", ")}.</p>
      )}
      <div className="verdict">
        <span className="step-no">Verdict</span>
        <blockquote>{v.text}</blockquote>
        <p className="src">
          {v.source === "model"
            ? "Worded by the model on Alibaba Cloud Model Studio from the computed facts; every number in it was checked against them."
            : v.model_refused
              ? "The model's wording failed the number check, so the sentence written by the rules is shown."
              : "Written by the rules from the computed facts."}
        </p>
      </div>
      {board.rows.length > 0 && (
        <figure className="scale">
          <ScaleDrawing rows={board.rows} finger={board.finger_mm} />
          <figcaption className="small muted">Drawn to scale on your finger, {board.finger_mm.toFixed(2)} mm wide, as each stone would be set.</figcaption>
        </figure>
      )}
    </div>
  );
}

function FingerDim({ hand }: { hand: Hand }) {
  const [p, q] = hand.overlay.line;
  const cy = (p[1] + q[1]) / 2, cx = (p[0] + q[0]) / 2;
  const f = hand.overlay.finger_px;
  const s = hand.overlay.size[0] / 17;
  return <Dim a={[cx - f / 2, cy + 0.85 * f]} b={[cx + f / 2, cy + 0.85 * f]} label={`${hand.finger.width_mm.toFixed(2)} mm`}
    above={false} color="#474c57" size={s} tick={s * 0.4} />;
}

function TryOnCard({ row, hand, t, recorded, live, chosen, onTry, onChoose }: {
  row: Row; hand: Hand; t?: TryState; recorded: boolean; live: boolean; chosen: boolean; onTry: () => void; onChoose: () => void;
}) {
  const [vw, vh] = hand.overlay.size;
  const [p, q] = hand.overlay.line;
  const cx = (p[0] + q[0]) / 2, cy = (p[1] + q[1]) / 2;
  const f = hand.overlay.finger_px;
  const s = vw / 17;
  const done = t?.state === "done" ? t.r : null;
  const a = done?.audit;
  return (
    <figure className={`tryon${chosen ? " chosen" : ""}`}>
      <div className="frame" style={{ ["--ar" as string]: `${vw} / ${vh}` }}>
        <img src={done ? done.view : hand.view_image} alt={done ? `The ${row.label} on the hand` : ""} />
        {done && (
          <svg viewBox={`0 0 ${vw} ${vh}`} aria-hidden="true">
            <Dim a={[cx - row.stone_px / 2, cy - 0.75 * f]} b={[cx + row.stone_px / 2, cy - 0.75 * f]}
              label={`${row.width_mm.toFixed(2)} mm`} size={s} tick={s * 0.4} />
            <FingerDim hand={hand} />
          </svg>
        )}
        {!done && t?.state !== "loading" && (
          <div className="pending">
            <button type="button" className="btn ghost" onClick={onTry} disabled={!live && !recorded}>Try it on</button>
          </div>
        )}
        {t?.state === "loading" && (
          <div className="pending" role="status"><div><div className="spinner" />Rendering with YouCam…</div></div>
        )}
      </div>
      <figcaption>
        <h3><span className="num letter">{row.id}</span> {row.label}</h3>
        <p className="audit">{row.width_mm.toFixed(2)} mm across · {row.coverage_pct.toFixed(0)}% of your finger · {money(row.price, row.currency)}</p>
        {t?.state === "error" && <p className="audit flag" role="alert">{t.message}</p>}
        {a && (
          <p className={`audit ${a.passed ? "" : "flag"}`}>
            {a.expected_ratio != null && a.error_pct != null ? (
              <>Render check: {(100 * a.expected_ratio).toFixed(1)}% of finger width against {(100 * a.target_ratio).toFixed(1)}% asked,{" "}
                {a.error_pct > 0 ? "+" : ""}{a.error_pct.toFixed(1)}% {a.passed ? <span className="ok">✓ within {a.tolerance_pct ?? 5}%</span> : "outside the tolerance"}</>
            ) : (
              <>Render check: the stone hides the band, so this render's width could not be read.</>
            )}
          </p>
        )}
        {done && (
          <p className="audit muted">
            {done.cached ? "Recorded render" : `YouCam task ${done.seconds.toFixed(1)} s, ${done.units} unit${done.units === 1 ? "" : "s"}`}
            {done.attempts.length > 1 && " · re-rendered once to correct the size"}
          </p>
        )}
        {!live && !recorded && !done && <p className="audit muted">Not recorded on this hand.</p>}
        <button type="button" className="btn link" onClick={onChoose} aria-pressed={chosen}>{chosen ? "Chosen" : "Choose this stone"}</button>
      </figcaption>
    </figure>
  );
}

function Decision({ row, hand, board, t }: { row: Row; hand: Hand; board: Board; t?: TryState }) {
  const [copied, setCopied] = useState(false);
  const best = row.rank === 1;
  const reason = best ? board.verdict.text
    : row.rank ? `Ranked ${row.rank} of ${board.rows.filter((r) => r.rank).length} by price per face-up mm² on your finger.`
      : "Chosen without a price comparison.";
  const done = t?.state === "done" ? t.r : null;
  const f = hand.fit;
  const lines = [
    `Handpicked: ${row.label}`,
    `Finger ${hand.finger.width_mm.toFixed(2)} mm, ring size US ${f.us} (EU ${f.eu}${f.uk ? `, UK ${f.uk}` : ""}).`,
    `Face-up area ${row.area_mm2.toFixed(1)} mm², ${row.width_mm.toFixed(2)} mm across the finger (${row.coverage_pct.toFixed(0)}% of its width).`,
    `Measurements ${row.width_mm.toFixed(2)} x ${row.length_mm.toFixed(2)} x ${row.depth_mm.toFixed(2)} mm.`,
    row.price != null ? `Price ${money(row.price, row.currency)}, ${money(row.price_per_mm2, row.currency)} per face-up mm².` : "No price listed.",
    reason,
  ];
  return (
    <div className="decision">
      <div>
        <p className="label">Handpicked for a finger {hand.finger.width_mm.toFixed(2)} mm wide</p>
        <h3>{row.label}</h3>
        <p className="reason">{reason}</p>
        {done && <img className="decision-img" src={done.view} alt={`The ${row.label} on the hand`} />}
      </div>
      <div>
        <table className="facts">
          <tbody>
            <tr><th scope="row">Shape</th><td>{SHAPE_NAMES[row.shape] ?? row.shape}{row.origin ? `, ${row.origin}` : ""}</td></tr>
            <tr><th scope="row">Measurements</th><td>{row.width_mm.toFixed(2)} × {row.length_mm.toFixed(2)} × {row.depth_mm.toFixed(2)} mm</td></tr>
            <tr><th scope="row">Face-up area</th><td>{row.area_mm2.toFixed(1)} mm²</td></tr>
            <tr><th scope="row">Across the finger</th><td>{row.coverage_pct.toFixed(0)}% of {hand.finger.width_mm.toFixed(2)} mm</td></tr>
            <tr><th scope="row">Price</th><td>{money(row.price, row.currency)}</td></tr>
            <tr><th scope="row">Per face-up mm²</th><td>{money(row.price_per_mm2, row.currency)}</td></tr>
            <tr><th scope="row">Ring size</th><td>US {f.us} · EU {f.eu}{f.uk ? ` · UK ${f.uk}` : ""}</td></tr>
          </tbody>
        </table>
        <div className="row-gap actions no-print">
          <button type="button" className="btn" onClick={() => window.print()}>Print the card</button>
          <button type="button" className="btn ghost" onClick={() => navigator.clipboard?.writeText(lines.join("\n")).then(() => setCopied(true))}>
            {copied ? "Copied" : "Copy as text"}
          </button>
        </div>
      </div>
    </div>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
