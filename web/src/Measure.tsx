import type { ReactNode } from "react";
import type { Hand, Pt } from "./api";
import { Dim } from "./draw";

const CHECKS: Record<string, string> = {
  sheet_found: "Sheet found, four corners in frame",
  tilt_ok: "Camera within 35° of straight above",
  resolution_ok: "At least 3 pixels per millimetre",
  edges_consistent: "Finger edges agree within 1.2 mm",
};

const BLUE = "#1d46c4";

/** Inverse of the server's view transform (cv2.getRotationMatrix2D about the ring position, then centred). */
function viewToCrop(v: Hand["view"], p: Pt): Pt {
  const a = (v.angle * Math.PI) / 180;
  const al = Math.cos(a), be = Math.sin(a);
  const tx = (1 - al) * v.cx - be * v.cy + v.w / 2 - v.cx;
  const ty = be * v.cx + (1 - al) * v.cy + v.h / 2 - v.cy;
  const x = p[0] - tx, y = p[1] - ty;
  return [al * x - be * y, be * x + al * y];
}

/** The photo with the sheet it was measured on, its two known sides, and the window the loupe shows. */
export function SheetFigure({ hand }: { hand: Hand }) {
  const [w, h] = hand.image_size;
  const c = hand.measure.sheet_corners_px;
  const [ox, oy] = hand.crop_box;
  const len = (a: Pt, b: Pt) => Math.hypot(b[0] - a[0], b[1] - a[1]);
  const topLong = len(c[0], c[1]) > len(c[0], c[3]);
  const s = w / 17;
  const v = hand.view;
  const win = ([[0, 0], [v.w, 0], [v.w, v.h], [0, v.h]] as Pt[]).map((p) => {
    const q = viewToCrop(v, p);
    return `${q[0] + ox},${q[1] + oy}`;
  });
  return (
    <figure className="fig">
      <div className="figure" style={{ aspectRatio: `${w} / ${h}` }}>
        <img src={hand.photo} alt="The hand photo on its sheet" width={w} height={h} />
        <svg viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
          <polygon points={c.map((p) => p.join(",")).join(" ")} fill="none" stroke={BLUE} strokeWidth={1.4}
            strokeDasharray="6 5" vectorEffect="non-scaling-stroke" />
          <Dim a={c[0]} b={c[1]} label={topLong ? "297 mm" : "210 mm"} size={s} tick={s * 0.4} above={false} />
          <Dim a={c[3]} b={c[0]} label={topLong ? "210 mm" : "297 mm"} size={s} tick={s * 0.4} above={false} />
          <polygon points={win.join(" ")} fill="none" stroke={BLUE} strokeWidth={2} vectorEffect="non-scaling-stroke" />
        </svg>
      </div>
      <figcaption className="small muted">The sheet's known sides set the scale and the camera's position.</figcaption>
    </figure>
  );
}

/** The ring position, finger upright, with the two measured widths. */
export function LoupeFigure({ hand, src, children }: { hand: Hand; src?: string; children?: ReactNode }) {
  const [vw, vh] = hand.overlay.size;
  const s = vw / 17;
  return (
    <div className="figure" style={{ aspectRatio: `${vw} / ${vh}` }}>
      <img src={src ?? hand.view_image} alt="" width={vw} height={vh} />
      <svg viewBox={`0 0 ${vw} ${vh}`} aria-hidden="true">
        {children ?? (
          <>
            <Dim a={hand.overlay.line[0]} b={hand.overlay.line[1]} label={`${hand.finger.width_mm.toFixed(2)} mm`} size={s} tick={s * 0.45} above={false} />
            {hand.overlay.knuckle_line.length === 2 && (
              <Dim a={hand.overlay.knuckle_line[0]} b={hand.overlay.knuckle_line[1]} color="#474c57"
                label={`knuckle ${hand.finger.knuckle_mm.toFixed(2)} mm`} size={s * 0.85} tick={s * 0.4} />
            )}
          </>
        )}
      </svg>
    </div>
  );
}

export function MeasureFacts({ hand }: { hand: Hand }) {
  const f = hand.fit;
  const m = hand.measure;
  return (
    <div>
      <p className="label">Ring finger, where the ring sits</p>
      <p className="big" aria-label={`Finger width ${hand.finger.width_mm.toFixed(2)} millimetres`}>
        {hand.finger.width_mm.toFixed(2)} <span className="unit">mm</span>
      </p>
      <table className="facts">
        <tbody>
          <tr><th scope="row">Ring size</th><td>US {f.us} · EU {f.eu}{f.uk ? ` · UK ${f.uk}` : ""}</td></tr>
          <tr><th scope="row">Size range</th><td>US {f.us_low} to {f.us_high}</td></tr>
          <tr><th scope="row">Inner diameter</th><td>{f.inner_diameter_mm.toFixed(2)} mm</td></tr>
          <tr><th scope="row">Knuckle</th><td>{hand.finger.knuckle_mm.toFixed(2)} mm{f.knuckle_rule ? " · sized for the knuckle" : ""}</td></tr>
          <tr><th scope="row">Camera</th><td>{Math.round(m.camera_distance_mm)} mm above the sheet, tilted {m.tilt_deg.toFixed(1)}°</td></tr>
          <tr><th scope="row">Before parallax correction</th><td>{hand.finger.raw_width_mm.toFixed(2)} mm</td></tr>
          <tr><th scope="row">Readings along the ring section</th><td>{hand.finger.samples}, spread {hand.finger.spread_mm.toFixed(2)} mm</td></tr>
        </tbody>
      </table>
      <ul className="checks" aria-label="Capture checks">
        {Object.entries(m.checks).map(([k, ok]) => (
          <li key={k} className={ok ? undefined : "no"}>{CHECKS[k] ?? k}</li>
        ))}
      </ul>
    </div>
  );
}
