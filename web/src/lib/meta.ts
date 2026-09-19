import type { Pillar, ScoreRow, State } from "./types";

export type Tone = "good" | "warn" | "serious" | "bad" | "info" | "neutral";

export interface StateMeta {
  label: string;
  tone: Tone;
  order: number;
}

// List order: the groups that need attention first, the quiet ones last.
export const STATE_META: Record<State, StateMeta> = {
  falling: { label: "Falling", tone: "bad", order: 0 },
  bending: { label: "Bending", tone: "warn", order: 1 },
  weak: { label: "Weak", tone: "serious", order: 2 },
  bump: { label: "Bump", tone: "info", order: 3 },
  improving: { label: "Improving", tone: "good", order: 4 },
  healthy: { label: "Healthy", tone: "good", order: 5 },
  stable: { label: "Stable", tone: "neutral", order: 6 },
  not_enough_data: { label: "Not enough data", tone: "neutral", order: 7 },
};

export const STATE_ORDER = (Object.keys(STATE_META) as State[]).sort(
  (a, b) => STATE_META[a].order - STATE_META[b].order,
);

// Comparison series by slot. Validated for color-blind separation against each other; none is a state color.
export const SERIES_COLORS = ["var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];

export const alertKey = (a: { group_id: string; month: string }) => `${a.group_id}-${a.month}`;

export const toneColor = (tone: Tone) => `var(--${tone})`;

export interface PillarMeta {
  key: Pillar;
  label: string;
  weight: number;
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
    evidence: (s) => (s.buffer_days == null ? null : `${s.buffer_days.toFixed(0)} days of cash`),
  },
  {
    key: "cash_generation",
    label: "Cash generation",
    weight: 20,
    evidence: (s) =>
      s.operating_margin == null ? null : `${(s.operating_margin * 100).toFixed(0)}% margin`,
  },
  {
    key: "payment_discipline",
    label: "Payment discipline",
    weight: 20,
    evidence: (s) => terms(s.ap_days_beyond_terms, "paying"),
  },
  {
    key: "collections",
    label: "Collections",
    weight: 10,
    evidence: (s) => terms(s.ar_days_beyond_terms, "collecting"),
  },
  {
    key: "debt_burden",
    label: "Debt burden",
    weight: 10,
    evidence: (s) => (s.dscr == null ? null : `${s.dscr.toFixed(2)}x debt cover`),
  },
];

export const PILLAR_LABEL = Object.fromEntries(PILLARS.map((p) => [p.key, p.label])) as Record<
  Pillar,
  string
>;
