import type { ReactNode } from "react";
import type { EvidenceData } from "./App";
import type { Status } from "./api";

function Tile({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="tile">
      <span className="big">{value}</span>
      <span className="small muted">{label}</span>
    </div>
  );
}

function Ev({ no, title, children, cmd }: { no: string; title: string; children: ReactNode; cmd: string }) {
  return (
    <section className="ev" aria-labelledby={`ev-${no}`}>
      <span className="step-no">{no}</span>
      <div>
        <h3 id={`ev-${no}`}>{title}</h3>
        {children}
        <code>$ {cmd}</code>
      </div>
    </section>
  );
}

const mm = (v: number) => `${v.toFixed(2)} mm`;

export default function Evidence({ evidence, status }: { evidence: EvidenceData | null; status: Status | null }) {
  if (!evidence) return <p className="muted" style={{ paddingTop: 48 }}>Loading the results…</p>;
  const e1 = evidence.e1_summary_exif_heldout;
  const e1d = evidence.e1_summary_default_heldout;
  const e1b = evidence.e1before_summary_exif;
  const e2 = evidence.e2_summary;
  const e3 = evidence.e3_summary;
  const e4 = evidence.e4_summary_heldout_rules;
  const e4m = evidence.e4_summary_heldout_model;
  const ftr = evidence.e4_summary_freetext_rules;
  const ftm = evidence.e4_summary_freetext_model;
  const e5 = evidence.e5_summary;
  const maxBaseline = e3 ? Math.max(...Object.values(e3.single_photo_baseline_error_pct as Record<string, number>)) : 0;
  return (
    <>
      <div className="hero hero-slim">
        <div>
          <h1>Evidence</h1>
          <p>
            Every figure on this site comes from a file in <code>eval/results</code>, written by the command under it.
            Test sets were written and committed before the code they score; held-out halves were run once.
          </p>
        </div>
      </div>

      {e1 && (
        <Ev no="E1" title="Finger width from one photo" cmd="python eval/e1_metrology.py --bench <bench dir> --tag heldout">
          <p>
            Rendered scenes of a hand of known size on an A4 sheet, with random camera height, tilt and focal length
            (<code>tools/render_bench.py</code>). Held-out bench, measured once.
          </p>
          <div className="tiles">
            <Tile value={mm(e1.width_corrected.median_abs_error_mm)} label="median error, finger width" />
            <Tile value={mm(e1.width_corrected.p90_abs_error_mm)} label="90th percentile" />
            <Tile value={`${e1.n_measured}/${e1.n_cases}`} label={`measured; ${e1.n_refused} refused (finger edges unclear)`} />
            {e1d && <Tile value={mm(e1d.width_corrected.median_abs_error_mm)} label="median, photo without EXIF" />}
          </div>
          <p className="small">
            Before and after: the first method, on the first bench, had a median error of {mm(e1b.width_corrected.median_abs_error_mm)} and
            a 90th percentile of {mm(e1b.width_corrected.p90_abs_error_mm)}. Without the parallax correction the held-out median
            is {mm(e1.width_raw.median_abs_error_mm)}.
          </p>
        </Ev>
      )}

      {e2 && (
        <Ev no="E2" title="Same hand, different capture" cmd="python eval/e2_robustness.py">
          <p>{e2.description}</p>
          <div className="tiles">
            <Tile value={mm(e2.median_abs_change_mm)} label="median change in finger width" />
            <Tile value={mm(e2.p90_abs_change_mm)} label="90th percentile" />
            <Tile value={`${e2.measured}/${e2.variants}`} label="variants measured" />
            <Tile value={`${e2.size_changed}`} label="ring sizes changed by more than half a size" />
          </div>
          {e2.by_transform && (
            <table className="fields ev-table">
              <tbody>
                {Object.entries(e2.by_transform as Record<string, { n: number; median_abs_change_mm: number; max_abs_change_mm: number; refused: number }>).map(([k, v]) => (
                  <tr key={k}><td>{k}</td><td>median {mm(v.median_abs_change_mm)} · max {mm(v.max_abs_change_mm)} · {v.n} measured{v.refused ? `, ${v.refused} refused` : ""}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </Ev>
      )}

      {e3 && (
        <Ev no="E3" title="Stone size on the hand, YouCam Ring Virtual Try-On" cmd="python eval/e3_render_scale.py --hands hand-1,hand-2 --shapes round,oval">
          <p>
            Calibration rings with a flat green stone go through the live Ring VTO on the sample hands. The green width in
            each render, divided by the finger width, is the size the shopper sees.
          </p>
          <div className="tiles">
            <Tile value={`${e3.per_render.residual_median_pct}%`} label="median error, stone width" />
            <Tile value={`${e3.per_render.residual_p90_pct}%`} label="90th percentile" />
            <Tile value={`${e3.per_render.within_5pct}/${e3.per_render.renders}`} label="renders within 5%" />
            <Tile value={`${e3.calls}`} label={`live calls, ${e3.errors} failed, median ${e3.seconds_median} s`} />
          </div>
          <p className="small">
            One store photo used for every stone size would be off by up to {maxBaseline}%. {e3.per_render.excluded_band_hidden} renders
            are left out of the fit because the stone hides the band. Shapes: {(e3.shapes as string[]).join(", ")}.
          </p>
        </Ev>
      )}

      {e4 && (
        <Ev no="E4" title="Listing reader" cmd="python eval/e4_listing_reader.py --split heldout --model">
          <p>
            60 listings in six formats, English and French (grading reports, retailer pages, marketplace ads), labelled
            before reading. Held-out half, run once.
          </p>
          <div className="tiles">
            <Tile value={`${e4m?.field_accuracy_pct ?? e4.field_accuracy_pct}%`} label={`of ${e4.fields_scored} fields read correctly`} />
            <Tile value={`${e4m?.wrong_number_on_board ?? e4.wrong_number_on_board}`} label="wrong numbers on the board" />
            <Tile value={`${(e4m ?? e4).injection_listings - (e4m ?? e4).injection_obeyed}/${(e4m ?? e4).injection_listings}`} label="injected instructions ignored" />
            <Tile value={`${(e4m ?? e4).ungrounded_fields}`} label="values without a quote in the listing" />
          </div>
          {ftr && ftm && (
            <p className="small">
              Ten listings written the way people write in messages: the rules alone read {ftr.field_accuracy_pct}% of fields and put
              {" "}{ftr.status_correct} of {ftr.listings} stones on the board; with the model reading the gaps, {ftm.field_accuracy_pct}% and {ftm.status_correct} of {ftm.listings},
              with {ftm.wrong_number_on_board} wrong numbers. Every value the model returns is kept only if its quote is in the listing and states it.
            </p>
          )}
        </Ev>
      )}

      {e5 && (
        <Ev no="E5" title="What the comparison is worth on sample shortlists" cmd="python eval/e5_decision_value.py">
          <p>{e5.description}</p>
          <div className="tiles">
            <Tile value={`$${Math.round(e5.median_saving_usd).toLocaleString("en-US")}`} label="median saving at equal or larger face-up area" />
            <Tile value={`${e5.shortlists_with_saving}/${e5.shortlists}`} label="shortlists where a cheaper stone faces up as large" />
            <Tile value={`${e5.median_saving_pct}%`} label="median saving, share of the heaviest stone's price" />
            <Tile value={`+${e5.magic_premium_natural_pct}%`} label="price step at 1.00 ct, natural, matched grades" />
          </div>
          <p className="small">{e5.note}</p>
        </Ev>
      )}

      <Ev no="SA" title="Self-attack" cmd="python -m pytest -q">
        <p>Inputs built to break the product, kept in the test suite.</p>
        <table className="fields ev-table">
          <tbody>
            <tr><td>Instruction injected in a listing</td><td>masked before reading, shown struck; never reaches the model as an instruction</td></tr>
            <tr><td>Moissanite, lab "simulant", cubic zirconia</td><td>refused: waits outside the board</td></tr>
            <tr><td>Two listings of the same stone</td><td>the board says they face up the same; no ranking claim</td></tr>
            <tr><td>Carat that the millimetres contradict</td><td>flagged with the weight the millimetres imply</td></tr>
            <tr><td>"From" price, instalment, setting price</td><td>not read as the stone's price</td></tr>
            <tr><td>Model sentence with a new number</td><td>replaced by the rules' sentence</td></tr>
            <tr><td>Finger touching its neighbour</td><td>refused with a capture instruction</td></tr>
            <tr><td>Render whose size is off by more than 5%</td><td>re-rendered once with a corrected ring, and labelled</td></tr>
          </tbody>
        </table>
      </Ev>

      {status && (
        <section className="ev" aria-labelledby="ev-live">
          <span className="step-no">Now</span>
          <div>
            <h3 id="ev-live">This server</h3>
            <p className="small">
              Mode: {status.mode}. Ring library: {status.library} renders. Calibration: {String(status.calibration.renders)} renders,
              90th percentile {String(status.calibration.residual_p90_pct)}%. Model tokens today: {status.tokens_today.toLocaleString("en-US")} of {status.token_cap.toLocaleString("en-US")}.
              {status.mode === "live" && <> YouCam units spent today: {status.units_today} of {status.day_cap}.</>}
            </p>
          </div>
        </section>
      )}
    </>
  );
}
