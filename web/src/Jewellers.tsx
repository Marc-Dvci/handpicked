import { useEffect, useRef, useState } from "react";
import { api, money, SHAPE_NAMES, type Hand, type MerchantResult, type Offer, type Samples } from "./api";

const SHAPES = ["round", "oval", "cushion", "emerald", "pear", "princess", "radiant", "marquise"];

export function listingText(o: Offer): string {
  const origin = o.origin ? o.origin.charAt(0).toUpperCase() + o.origin.slice(1) + " " : "";
  const grade = [o.colour && `Colour ${o.colour}`, o.clarity && `clarity ${o.clarity}`].filter(Boolean).join(", ");
  return [`${origin}${o.shape} diamond, ${o.carat.toFixed(2)} ct`,
    `Measurements: ${o.length_mm.toFixed(2)} x ${o.width_mm.toFixed(2)} x ${o.depth_mm.toFixed(2)} mm`,
    grade, `Price: ${money(o.price, o.currency)}`].filter(Boolean).join("\n");
}

export default function Jewellers({ samples, hand, active }: { samples: Samples | null; hand: Hand | null; active: boolean }) {
  const [handId, setHandId] = useState<string>("");
  const [budget, setBudget] = useState(4000);
  const [shapes, setShapes] = useState<string[]>([]);
  const [result, setResult] = useState<MerchantResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hands = [...(hand && !hand.sample ? [hand] : []), ...(samples?.hands ?? [])];
  const current = hands.find((h) => h.id === handId) ?? hand ?? samples?.hands[0] ?? null;

  async function rank() {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.merchant(current.id, budget, shapes.length ? shapes : undefined));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (active && !result && current) void rank();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, current?.id]);

  const sample = result?.offers[0];
  const snippet = sample
    ? `<script src="${location.origin}/embed.js"\n  data-stone="${listingText(sample).replace(/\n/g, ", ").replace(/"/g, "&quot;")}"\n  data-label="Compare on your hand"></script>`
    : "";

  return (
    <>
      <div className="hero hero-slim">
        <div>
          <h1>For jewellers</h1>
          <p>
            Rank your stock for the customer in front of you: the stones that will look largest on their finger for
            their budget, with the heaviest stone shown for comparison. Each row opens on the customer's hand.
          </p>
        </div>
      </div>

      <section className="step" aria-labelledby="j-1">
        <div className="step-head">
          <span className="step-no">01</span>
          <h2 id="j-1">Customer and budget</h2>
          <p>{result?.source ? `Sample feed of ${result.total} stones: ${result.source}.` : "Sample feed of natural stones."}</p>
        </div>
        <form className="inline-form" onSubmit={(e) => { e.preventDefault(); void rank(); }}>
          <label>
            <span className="label">Hand</span>
            <select value={current?.id ?? ""} onChange={(e) => setHandId(e.target.value)}>
              {hands.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.sample ? `Sample ${h.id.replace("hand-", "hand ")}` : "Uploaded hand"} · {h.finger.width_mm.toFixed(1)} mm
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="label">Budget, USD</span>
            <input type="number" min={500} step={100} value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
          </label>
          <fieldset className="shapes">
            <legend className="label">Shapes (none ticked: all)</legend>
            {SHAPES.map((s) => (
              <label key={s} className="check">
                <input type="checkbox" checked={shapes.includes(s)}
                  onChange={(e) => setShapes((x) => (e.target.checked ? [...x, s] : x.filter((y) => y !== s)))} />
                {SHAPE_NAMES[s]}
              </label>
            ))}
          </fieldset>
          <button className="btn" type="submit" disabled={busy || !current}>{busy ? "Ranking…" : "Rank the stock"}</button>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      <section className="step" aria-labelledby="j-2" aria-live="polite">
        <div className="step-head">
          <span className="step-no">02</span>
          <h2 id="j-2">Largest on this finger, within budget</h2>
          <p>{result ? `${result.in_budget} of ${result.total} stones fit ${money(result.budget, "USD")} on a finger ${result.finger_mm.toFixed(2)} mm wide.` : " "}</p>
        </div>
        {result?.largest_vs_heaviest && (
          <p className="callout">
            The {result.largest_vs_heaviest.largest.label} faces up {result.largest_vs_heaviest.area_pct}% larger than the
            heaviest stone in budget, the {result.largest_vs_heaviest.heaviest.label}
            {result.largest_vs_heaviest.price_diff > 0
              ? `, for ${money(result.largest_vs_heaviest.price_diff, "USD")} less.`
              : result.largest_vs_heaviest.price_diff < 0
                ? `, for ${money(-result.largest_vs_heaviest.price_diff, "USD")} more.`
                : ", at the same price."}
          </p>
        )}
        {result && result.offers.length > 0 && (
          <div className="board-wrap" tabIndex={0} role="region" aria-label="Ranked stock">
            <table className="board">
              <thead>
                <tr>
                  <th scope="col">Stone</th>
                  <th scope="col">Face-up<br />area</th>
                  <th scope="col">Across<br />the finger</th>
                  <th scope="col">Price</th>
                  <th scope="col">Per<br />mm²</th>
                  <th scope="col">Weight<br />vs mm</th>
                  <th scope="col"><span className="visually-hidden">Action</span></th>
                </tr>
              </thead>
              <tbody>
                {result.offers.map((o, i) => (
                  <tr key={o.sku} className={i === 0 ? "best" : undefined}>
                    <td className="stone"><span className="num letter">{i + 1}</span> <b>{o.label}</b>
                      <span className="sub">{o.sku} · {[o.colour, o.clarity].filter(Boolean).join(" ")} · {o.width_mm.toFixed(2)} × {o.length_mm.toFixed(2)} mm</span>
                    </td>
                    <td>{o.area_mm2.toFixed(1)} mm²</td>
                    <td>{o.coverage_pct}%</td>
                    <td>{money(o.price, o.currency)}</td>
                    <td>{money(o.price_per_mm2, o.currency)}</td>
                    <td className={o.weight_check ? "ok" : "flag"}>{o.weight_check ? "matches" : "check"}</td>
                    <td><a href={`/?add=${encodeURIComponent(listingText(o))}#/`}>On the hand</a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {result && result.offers.length === 0 && <p className="muted">No stone in the feed fits this budget and these shapes.</p>}
      </section>

      <section className="step" aria-labelledby="j-3">
        <div className="step-head">
          <span className="step-no">03</span>
          <h2 id="j-3">On your product page</h2>
          <p>One script tag adds a button that opens Handpicked with the stone already in the comparison.</p>
        </div>
        {snippet && (
          <div className="embed">
            <pre className="code" aria-label="Embed snippet"><code>{snippet}</code></pre>
            <div>
              <p className="label">What the shopper sees</p>
              <EmbedPreview stone={listingText(sample!).replace(/\n/g, ", ")} />
            </div>
          </div>
        )}
      </section>
    </>
  );
}

function EmbedPreview({ stone }: { stone: string }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.innerHTML = "";
    const s = document.createElement("script");
    s.src = "/embed.js";
    s.setAttribute("data-stone", stone);
    s.setAttribute("data-label", "Compare on your hand");
    el.appendChild(s);
  }, [stone]);
  return <div ref={box} className="embed-preview" />;
}
