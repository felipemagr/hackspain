import type { Pillar, ScoreRow, State } from "./types";

export type Tone = "good" | "warn" | "serious" | "bad" | "info" | "neutral";

export type Bucket = "attention" | "improving" | "steady";

export interface StateMeta {
  label: string;
  tone: Tone;
  bucket: Bucket;
}

// Three hues and a grey: red is trouble, amber is a warning, green is good news.
export const STATE_META: Record<State, StateMeta> = {
  falling: { label: "Falling", tone: "bad", bucket: "attention" },
  bending: { label: "Bending", tone: "warn", bucket: "attention" },
  weak: { label: "Weak", tone: "bad", bucket: "attention" },
  bump: { label: "Bump", tone: "neutral", bucket: "steady" },
  improving: { label: "Improving", tone: "good", bucket: "improving" },
  healthy: { label: "Healthy", tone: "good", bucket: "steady" },
  stable: { label: "Stable", tone: "neutral", bucket: "steady" },
  not_enough_data: { label: "Not enough data", tone: "neutral", bucket: "steady" },
};

// Rail sections in reading order. Each one says how it is sorted, so the order explains itself.
export const BUCKETS: { key: Bucket; label: string; hint: string }[] = [
  { key: "attention", label: "Needs attention", hint: "steepest fall first" },
  { key: "improving", label: "Improving", hint: "fastest rise first" },
  { key: "steady", label: "Steady", hint: "highest score first" },
];

/** Covered months the engine wants before it trusts a trend (`trend.MIN_HISTORY_MONTHS`). */
export const MIN_HISTORY_MONTHS = 6;

/** A level that rests on fewer months than the engine needs: shown, but flagged. */
export const thinHistory = (months: number | null | undefined): months is number =>
  months != null && months < MIN_HISTORY_MONTHS;

export const LOCAL_STATE_META: Record<State, StateMeta> = {
  ...STATE_META,
  healthy: { ...STATE_META.healthy, label: "Score 70+" },
  stable: { ...STATE_META.stable, label: "Score 40–69" },
  weak: { ...STATE_META.weak, label: "Score below 40" },
  not_enough_data: { ...STATE_META.not_enough_data, label: "Score unavailable" },
};

// Comparison series by slot. Validated for color-blind separation against each other; none is a state color.
export const SERIES_COLORS = ["var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];

export const alertKey = (a: { group_id: string; month: string }) => `${a.group_id}-${a.month}`;

export const toneColor = (tone: Tone) => `var(--${tone})`;

export interface PillarMeta {
  key: Pillar;
  label: string;
  weight: number;
  /** The name of the headline indicator behind the pillar. */
  indicator: string;
  /** That indicator as a bare figure with its unit. */
  metric: (s: ScoreRow) => string | null;
  /** The headline indicator behind the pillar, already formatted. */
  evidence: (s: ScoreRow) => string | null;
}

const terms = (v: number | null, verb: string) => {
  if (v == null) return null;
  const n = Math.abs(Math.round(v));
  if (n === 0) return `${verb} on terms`;
  return `${verb} ${n} ${n === 1 ? "day" : "days"} ${v > 0 ? "late" : "early"}`;
};

export const PILLARS: PillarMeta[] = [
  {
    key: "liquidity",
    label: "Liquidity",
    weight: 40,
    indicator: "Days of cash buffer",
    metric: (s) => (s.buffer_days == null ? null : `${s.buffer_days.toFixed(0)} d`),
    evidence: (s) => (s.buffer_days == null ? null : `${s.buffer_days.toFixed(0)} days of cash`),
  },
  {
    key: "cash_generation",
    label: "Cash generation",
    weight: 20,
    indicator: "Operating margin",
    metric: (s) =>
      s.operating_margin == null ? null : `${(s.operating_margin * 100).toFixed(1)}%`,
    evidence: (s) =>
      s.operating_margin == null ? null : `${(s.operating_margin * 100).toFixed(0)}% margin`,
  },
  {
    key: "payment_discipline",
    label: "Payment discipline",
    weight: 20,
    indicator: "Days past your own terms",
    metric: (s) =>
      s.ap_days_beyond_terms == null ? null : `${s.ap_days_beyond_terms.toFixed(0)} d`,
    evidence: (s) => terms(s.ap_days_beyond_terms, "paying"),
  },
  {
    key: "collections",
    label: "Collections",
    weight: 10,
    indicator: "Days customers run past terms",
    metric: (s) =>
      s.ar_days_beyond_terms == null ? null : `${s.ar_days_beyond_terms.toFixed(0)} d`,
    evidence: (s) => terms(s.ar_days_beyond_terms, "collecting"),
  },
  {
    key: "debt_burden",
    label: "Debt burden",
    weight: 10,
    indicator: "Debt service cover (DSCR)",
    metric: (s) => (s.dscr == null ? null : `${s.dscr.toFixed(2)}×`),
    evidence: (s) => (s.dscr == null ? null : `${s.dscr.toFixed(2)}x debt cover`),
  },
];

export const PILLAR_LABEL = Object.fromEntries(PILLARS.map((p) => [p.key, p.label])) as Record<
  Pillar,
  string
>;
