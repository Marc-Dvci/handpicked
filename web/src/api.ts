export type Pt = [number, number];

export interface Fit {
  width_mm: number;
  knuckle_mm: number;
  us: number;
  us_low: number;
  us_high: number;
  eu: number;
  uk: string | null;
  inner_diameter_mm: number;
  knuckle_rule: boolean;
}

export interface Hand {
  id: string;
  sample: boolean;
  focal_35mm: number;
  focal_source: string;
  image_size: Pt;
  crop_box: number[];
  measure: {
    camera_distance_mm: number;
    tilt_deg: number;
    px_per_mm: number;
    sheet_corners_px: Pt[];
    checks: Record<string, boolean>;
  };
  finger: {
    width_mm: number;
    knuckle_mm: number;
    raw_width_mm: number;
    samples: number;
    spread_mm: number;
    wearing_location: number;
    width_px: number;
    line_px: Pt[];
    knuckle_line_px: Pt[];
    axis_px: Pt[];
  };
  fit: Fit;
  overlay: { line: Pt[]; knuckle_line: Pt[]; axis: Pt[]; finger_px: number; size: Pt };
  photo: string;
  view_image: string;
  view: { cx: number; cy: number; angle: number; w: number; h: number };
  recorded?: boolean;
}

export interface Samples {
  hands: Hand[];
  shortlist: string[];
  source: string;
  recorded: { hand: string; shape: string; width_mm: number; metal: string; band: boolean; key: string; error_pct: number }[];
}

export interface FieldRead {
  value: unknown;
  start: number;
  end: number;
  quote: string;
  method: "rule" | "model";
}

export interface Reading {
  id: string;
  text: string;
  fields: Record<string, FieldRead>;
  notes: string[];
  masked: [number, number][];
  model_asked: boolean;
  model_rejected: string[];
  status: "ready" | "waiting";
  label: string;
  missing?: string[];
  question?: string | null;
  flags?: string[];
  weight_estimate?: number | null;
}

export interface Row {
  id: string;
  label: string;
  shape: string;
  carat: number;
  length_mm: number;
  width_mm: number;
  depth_mm: number;
  area_mm2: number;
  coverage_pct: number;
  price: number | null;
  currency: string | null;
  price_per_mm2: number | null;
  rank: number | null;
  spread_pct: number;
  depth_pct: number;
  typical_area_mm2: number;
  weight_estimate: number | null;
  origin: string | null;
  flags: string[];
  outline: Pt[];
  stone_px: number;
}

export interface Verdict {
  text: string;
  source: "model" | "template";
  model?: string;
  template?: string;
  model_refused?: boolean;
}

export interface Board {
  hand_id: string;
  finger_mm: number;
  currency: string | null;
  rows: Row[];
  pending: Reading[];
  readings: Reading[];
  facts: Record<string, unknown>;
  verdict: Verdict;
  notes: string[];
}

export interface TryOn {
  key: string;
  image: string;
  view: string;
  task_id: string;
  seconds: number;
  units: number;
  cached: boolean;
  render: { name: string; product_ratio: number; anchor_scale: number };
  attempts: { render: string; anchor_scale: number; units: number; error_pct: number | null; band_fit: number | null }[];
  band_fit_source: string;
  target_ratio: number;
  audit: {
    target_ratio: number;
    expected_ratio: number | null;
    error_pct: number | null;
    band_fit: number | null;
    passed: boolean;
    tolerance_pct?: number;
    calibration_p90_pct?: number;
    calibration_renders?: number;
  };
  band: boolean;
  metal: string;
}

export interface Status {
  mode: "live" | "replay";
  model: string | null;
  units_left: number | null;
  units_today: number;
  day_cap: number;
  session_cap: number;
  session_units: number;
  calls: number;
  median_seconds: number | null;
  tokens_today: number;
  token_cap: number;
  calibration: Record<string, number | string>;
  library: number;
}

export interface Offer {
  sku: string;
  label: string;
  shape: string;
  carat: number;
  width_mm: number;
  length_mm: number;
  area_mm2: number;
  coverage_pct: number;
  price: number;
  currency: string;
  price_per_mm2: number;
  spread_pct: number;
  weight_check: boolean;
  depth_mm: number;
  colour: string | null;
  clarity: string | null;
  origin: string | null;
}

export interface MerchantResult {
  finger_mm: number;
  budget: number;
  in_budget: number;
  total: number;
  offers: Offer[];
  largest_vs_heaviest: null | { largest: Offer; heaviest: Offer; area_pct: number; price_diff: number };
  source?: string;
}

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin", ...init });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(body.code ?? "error", body.message ?? `Request failed (${r.status})`, r.status);
  return body as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  samples: () => call<Samples>("/api/samples"),
  hand: (id: string) => call<Hand>(`/api/hands/${id}`),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return call<Hand>("/api/hands", { method: "POST", body: fd });
  },
  compare: (hand_id: string, texts: string[]) => call<Board>("/api/compare", json({ hand_id, texts })),
  tryon: (hand_id: string, shape: string, width_mm: number, metal: string, band: boolean) =>
    call<TryOn>("/api/tryon", json({ hand_id, shape, width_mm, metal, band })),
  status: () => call<Status>("/api/status"),
  merchant: (hand_id: string, budget: number, shapes?: string[]) =>
    call<MerchantResult>("/api/merchant/rank", json({ hand_id, budget, shapes })),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  evidence: () => call<Record<string, any>>("/api/evidence"),
};

export function money(v: number | null | undefined, cur: string | null | undefined): string {
  if (v == null) return "—";
  const sym: Record<string, string> = { USD: "$", EUR: "€", GBP: "£" };
  const n = Math.round(v).toLocaleString("en-US");
  if (cur === "CHF") return `CHF ${n}`;
  return `${sym[cur ?? ""] ?? ""}${n}`;
}

export const SHAPE_NAMES: Record<string, string> = {
  round: "Round", oval: "Oval", cushion: "Cushion", emerald: "Emerald", pear: "Pear",
  princess: "Princess", radiant: "Radiant", marquise: "Marquise",
};
