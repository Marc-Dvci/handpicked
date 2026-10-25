import type { ReactNode } from "react";
import type { FieldRead, Pt, Row } from "./api";

/** A dimension line with end ticks and a label, in the coordinates of the image under it. */
export function Dim({ a, b, label, tick = 7, color = "#1d46c4", above = true, size = 13 }: {
  a: Pt; b: Pt; label: string; tick?: number; color?: string; above?: boolean; size?: number;
}) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len, ny = dx / len;
  const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
  const off = (above ? -1 : 1) * (tick + size * 0.6);
  return (
    <g>
      <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={color} strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
      {[a, b].map((p, i) => (
        <line key={i} x1={p[0] - nx * tick} y1={p[1] - ny * tick} x2={p[0] + nx * tick} y2={p[1] + ny * tick}
          stroke={color} strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
      ))}
      <text x={mx + nx * off} y={my + ny * off} textAnchor="middle" dominantBaseline="middle"
        fontFamily="IBM Plex Mono, monospace" fontSize={size} fill={color} stroke="#fff" strokeWidth={3}
        paintOrder="stroke">{label}</text>
    </g>
  );
}

/** The stones drawn to scale against the measured finger, north-south as they would be set. */
export function ScaleDrawing({ rows, finger }: { rows: Row[]; finger: number }) {
  const margin = 12;
  const cell = finger + 12;
  const h = 30;
  const w = margin + cell * rows.length;
  return (
    <svg viewBox={`0 0 ${w} ${h + 12}`} role="img"
      aria-label={`The stones drawn to scale on a finger ${finger.toFixed(1)} mm wide`}>
      <g>
        <line x1={2} y1={h - 2} x2={7} y2={h - 2} stroke="#15171c" strokeWidth={0.25} />
        <line x1={2} y1={h - 2.8} x2={2} y2={h - 1.2} stroke="#15171c" strokeWidth={0.25} />
        <line x1={7} y1={h - 2.8} x2={7} y2={h - 1.2} stroke="#15171c" strokeWidth={0.25} />
        <text x={4.5} y={h - 3.6} textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize={1.6} fill="#474c57">5 mm</text>
      </g>
      {rows.map((r, i) => {
        const cx = margin + cell * i + cell / 2, cy = h / 2;
        const pts = r.outline.map(([x, y]) => `${(cx + x).toFixed(3)},${(cy - y).toFixed(3)}`).join(" ");
        return (
          <g key={r.id}>
            <rect x={cx - finger / 2} y={0.5} width={finger} height={h - 1} fill="#f3f4f6" />
            <line x1={cx - finger / 2} y1={0.5} x2={cx - finger / 2} y2={h - 0.5} stroke="#15171c" strokeWidth={0.12} />
            <line x1={cx + finger / 2} y1={0.5} x2={cx + finger / 2} y2={h - 0.5} stroke="#15171c" strokeWidth={0.12} />
            <polygon points={pts} fill="#e9eefb" stroke="#1d46c4" strokeWidth={0.16} />
            <text x={cx} y={h + 3.4} textAnchor="middle" fontFamily="Newsreader, serif" fontSize={2.4} fill="#15171c">{r.label}</text>
            <text x={cx} y={h + 6.6} textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize={1.7} fill="#15171c">
              {r.area_mm2.toFixed(1)} mm²
            </text>
            <text x={cx} y={h + 9.4} textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize={1.5} fill="#6b707b">
              {r.width_mm.toFixed(2)} × {r.length_mm.toFixed(2)} mm
            </text>
          </g>
        );
      })}
    </svg>
  );
}

const FIELD_ORDER = ["shape", "carat", "measurements", "price", "lab", "origin", "colour", "clarity", "depth_pct",
  "not_diamond", "shape_unsupported"];

/** The listing text with every field it gave highlighted where it was read, and ignored instructions struck. */
export function SourceText({ text, fields, masked }: { text: string; fields: Record<string, FieldRead>; masked: [number, number][] }) {
  const marks: { s: number; e: number; kind: "rule" | "model" | "masked"; title: string }[] = [];
  for (const [k, f] of Object.entries(fields)) {
    if (FIELD_ORDER.includes(k)) marks.push({ s: f.start, e: f.end, kind: f.method, title: `${k} (${f.method === "model" ? "read by the model, checked" : "read by the rules"})` });
  }
  for (const [s, e] of masked) marks.push({ s, e, kind: "masked", title: "instruction-like text, not read" });
  marks.sort((a, b) => a.s - b.s);
  const out: ReactNode[] = [];
  let at = 0;
  marks.forEach((m, i) => {
    if (m.s < at) return;
    if (m.s > at) out.push(text.slice(at, m.s));
    const chunk = text.slice(m.s, m.e);
    out.push(m.kind === "masked"
      ? <s key={i} title={m.title}>{chunk}</s>
      : <mark key={i} className={m.kind === "model" ? "model" : undefined} title={m.title}>{chunk}</mark>);
    at = m.e;
  });
  out.push(text.slice(at));
  return <p className="source">{out}</p>;
}

export function fieldValue(k: string, f: FieldRead): string {
  const v = f.value as Record<string, number | string> | number | string;
  if (k === "measurements" && typeof v === "object") return `${mm2(v.length)} × ${mm2(v.width)} × ${mm2(v.depth)} mm`;
  if (k === "price" && typeof v === "object") return `${Number(v.amount).toLocaleString("en-US")} ${v.currency}`;
  if (k === "carat") return `${v} ct`;
  if (k === "depth_pct") return `${v}%`;
  return String(v);
}

export const FIELD_NAMES: Record<string, string> = {
  shape: "Shape", carat: "Carat", measurements: "Measurements", price: "Price", lab: "Lab", origin: "Origin",
  colour: "Colour", clarity: "Clarity", depth_pct: "Depth", report_number: "Report", table_pct: "Table",
  lw_ratio: "L/W ratio", metal: "Metal", not_diamond: "Material", shape_unsupported: "Shape",
};

const mm2 = (v: number | string) => Number(v).toFixed(2);
