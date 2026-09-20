import { API_HEADERS, API_URL } from "./api";

export type Weights = Record<"level" | "financial" | "evolution", Record<string, number>>;
export interface ScoreNode {
  score: number | null; confidence: number | null; coverage: number;
  raw_value?: number | null; history?: number; perimeter?: number | null;
  quality?: number; reason?: string; score_range?: number[] | null;
}
export interface ScoringConfig {
  version: string; status: string; weights: Weights; warnings: { dpo_days: number };
  curves: Record<string, number[][]>;
}
export interface Entity {
  id: string; kind: "company" | "group"; name: string; group_id?: string;
  currency: string; member_count?: number; level?: number | null; confidence?: number | null;
  fx_estimated?: boolean; fx_partial?: boolean; original_currency?: string[];
  debt_snapshot?: { date: string; owed: number | null; guarantees: number | null; product_count: number; known_balance_count: number };
}
export interface MonthRecord {
  month: string; [key: string]: unknown;
  scoring: { subscores: Record<string, ScoreNode>; families: Record<string, ScoreNode>;
    level: ScoreNode; evolution: ScoreNode; metrics: Record<string, number | null> };
}
export interface EntityDetail {
  entity: Entity; monthly: MonthRecord[]; config: ScoringConfig; members: Entity[];
}
export const SCORING_API = API_URL;
export async function scoringRequest<T>(path: string, weights?: Weights, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${SCORING_API}/api/v1/scoring${path}`, {
    signal, headers: { ...API_HEADERS, ...(weights ? { "Content-Type": "application/json" } : {}) },
    ...(weights ? { method: "POST", body: JSON.stringify({ weights }) } : {}),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Scoring service returned ${response.status}.`);
  }
  return response.json() as Promise<T>;
}
export const scoreLabels: Record<string, string> = {
  financial: "Financial capacity", generation: "Cash generation", debt_coverage: "Debt coverage",
  liquidity: "Liquidity", receivables: "Receivables", payables: "Payables",
  activity: "Activity", conversion: "Cash conversion",
};
export const figure = (n: unknown, digits = 1) => typeof n === "number" && Number.isFinite(n)
  ? new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(n) : "Unavailable";
export const monthLabel = (month: string) => new Date(`${month.slice(0, 7)}-01T12:00:00`).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
