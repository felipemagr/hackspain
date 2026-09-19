export type State =
  | "healthy"
  | "stable"
  | "weak"
  | "improving"
  | "bending"
  | "falling"
  | "bump"
  | "not_enough_data";

export type Tier = "healthy" | "coping" | "vulnerable";

export type Pillar =
  | "liquidity"
  | "cash_generation"
  | "payment_discipline"
  | "collections"
  | "debt_burden";

export interface GroupRow {
  group_id: string;
  name: string;
  /** The challenge dataset carries no sector; only the mock tables fill it. */
  sector: string | null;
  country: string | null;
  n_companies: number;
  has_erp: boolean;
  annual_revenue_eur: number;
  /** Mock tables only. */
  archetype?: string;
}

export interface ScoreRow {
  group_id: string;
  month: string;
  liquidity: number | null;
  cash_generation: number | null;
  payment_discipline: number | null;
  collections: number | null;
  debt_burden: number | null;
  level_uncapped: number;
  is_capped: boolean;
  level: number;
  coverage: number;
  buffer_days: number | null;
  operating_margin: number | null;
  ap_days_beyond_terms: number | null;
  ar_days_beyond_terms: number | null;
  dscr: number | null;
  trend: number | null;
  state: State;
  months_observed: number;
  compound: number;
  tier: Tier;
  monthly_inflow_eur: number;
}

export interface AlertRow {
  group_id: string;
  month: string;
  state_from: State;
  state_to: State;
  onset_month: string;
  level_at_onset: number;
  level_at_alert: number;
  driver_1: Pillar | null;
  driver_2: Pillar | null;
  tier_change_month: string | null;
  anticipation_months: number | null;
}

export interface OfferRow {
  group_id: string;
  month: string;
  eligible: boolean;
  limit_eur: number;
  apr: number | null;
  limit_change_eur: number;
}

export interface ActionRow {
  group_id: string;
  month: string;
  rank: number;
  pillar: Pillar;
  action: string;
  expected_level_gain: number;
}

export interface CompanyRow {
  company_id: string;
  group_id: string;
  name: string;
  inflow_share: number | null;
  // Null for a company with no activity in the window.
  level: number | null;
  is_weakest: boolean;
}

/** One row per group, month and window: what falls due, and what can be paid early with it. */
export interface PromptPayRow {
  group_id: string;
  month: string;
  window_days: number;
  due_eur: number;
  expected_eur: number;
  /** Euros squared: the page takes the square root to price the 5th percentile. */
  variance: number;
  thin_eur: number;
  n_customers: number;
  n_thin: number;
  payable_n: number;
  payable_eur: number;
  payable_days: number | null;
}

export interface PromptPayCustomerRow {
  group_id: string;
  month: string;
  counterparty_id: string;
  name: string;
  n_paid: number;
  median_late: number | null;
  solid: boolean;
  due_30_eur: number;
  exp_30_eur: number;
  var_30: number;
  due_60_eur: number;
  exp_60_eur: number;
  var_60: number;
  due_90_eur: number;
  exp_90_eur: number;
  var_90: number;
}

export interface DriverRow {
  group_id: string;
  month: string;
  pillar: Pillar;
  score: number;
  contribution: number;
  delta_score: number | null;
  delta_contribution: number | null;
}
