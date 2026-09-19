import type { Store } from "./load";
import { API_HEADERS, API_URL, readEvents } from "./chat";
import { displayCurrency } from "./currency";
import { SCORING_API, type ScoreNode, type Weights } from "./scoring";

export type ChartMetric = "level" | "financial" | "liquidity" | "receivables" | "payables";
export interface ChartConfig {
  type: "line" | "area" | "bar";
  series: ChartMetric[];
  months: number | null;
  show_grid: boolean;
  color: "navy" | "blue" | "green" | "purple" | "orange";
  title: string | null;
}
export const DEFAULT_CHART: ChartConfig = { type: "area", series: ["level"], months: null, show_grid: true, color: "navy", title: null };
export const CHART_COLORS = { navy: "#050b2c", blue: "#3878f6", green: "#008c70", purple: "#8041d1", orange: "#b0661a" };
export type ViewAction = { type: "set_weights"; weights: Record<string, number> } | { type: "set_chart"; chart: ChartConfig };
export interface ViewReply { reply: string; actions: ViewAction[]; queries: { tool: string; rows: number }[]; model_available: boolean }
export interface ViewMessage { role: "user" | "assistant"; content: string }

export async function askGroupAgent(request: {
  message: string; groupId: string; month: string; history: ViewMessage[];
}, signal: AbortSignal): Promise<string> {
  const response = await fetch(`${API_URL}/api/v1/chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...API_HEADERS },
    body: JSON.stringify({
      message: `Selected business group: ${request.groupId}.\nQuestion: ${request.message}`,
      group_id: request.groupId,
      month: request.month,
      history: request.history,
      currency: displayCurrency(),
    }),
    signal,
  });
  if (!response.ok) throw new Error(`The agent service answered ${response.status}. Please retry.`);
  let answer = "";
  let completed = false;
  for await (const event of readEvents(response)) {
    if (event.type === "token") answer += event.text;
    if (event.type === "error") throw new Error(event.message);
    if (event.type === "done") completed = true;
  }
  if (!completed || !answer.trim()) throw new Error("The answer was interrupted. Please retry.");
  return answer;
}

export async function askViewAgent(request: {
  message: string; entity_id: string; month: string; current_weights: Record<string, number>;
  current_profile: Weights;
  chart: ChartConfig; history: ViewMessage[]; allow_weights: boolean;
}, signal: AbortSignal): Promise<ViewReply> {
  const response = await fetch(`${SCORING_API}/api/v1/view-chats`, {
    method: "POST", headers: { "Content-Type": "application/json", ...API_HEADERS }, body: JSON.stringify(request), signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `AI service returned ${response.status}. Please retry.`);
  }
  return response.json() as Promise<ViewReply>;
}

function blend(nodes: Record<string, ScoreNode>, weights: Record<string, number>): ScoreNode {
  const nominal = Object.values(weights).reduce((sum, weight) => sum + weight, 0);
  const available = Object.entries(weights).filter(([key, weight]) => weight > 0 && nodes[key]?.score != null);
  const total = available.reduce((sum, [, weight]) => sum + weight, 0);
  return {
    score: total ? available.reduce((sum, [key, weight]) => sum + nodes[key].score! * weight, 0) / total : null,
    confidence: available.every(([key]) => nodes[key].confidence != null)
      ? available.reduce((sum, [key, weight]) => sum + nodes[key].confidence! * weight, 0) / nominal : null,
    coverage: available.reduce((sum, [key, weight]) => sum + (nodes[key].coverage ?? 1) * weight, 0) / nominal,
  };
}

/** Recombine stored pillar scores for this session; no metric or scoring curve runs. */
export function withViewWeights(store: Store, profiles: Record<string, Record<string, number>>): Store {
  if (!store.localScoring || Object.keys(profiles).length === 0) return store;
  const scoresByGroup = new Map(store.scoresByGroup);
  const localWeights = new Map(store.localWeights);
  for (const [id, weights] of Object.entries(profiles)) {
    const rows = store.scoresByGroup.get(id);
    if (!rows) continue;
    scoresByGroup.set(id, rows.map(row => {
      if (!row.localScoring) return row;
      const level = blend(row.localScoring.families, weights);
      return { ...row, level: level.score, level_uncapped: level.score ?? NaN, compound: level.score ?? NaN,
        state: level.score == null ? "not_enough_data" as const : level.score >= 70 ? "healthy" as const : level.score >= 40 ? "stable" as const : "weak" as const,
        tier: level.score != null && level.score >= 70 ? "healthy" as const : level.score != null && level.score >= 40 ? "coping" as const : "vulnerable" as const,
        coverage: level.coverage, localScoring: { ...row.localScoring, level } };
    }));
    const base: Weights = store.localWeights?.get(id) ?? store.localScoring.config.weights;
    localWeights.set(id, { ...base, level: weights });
  }
  return { ...store, scoresByGroup, localWeights,
    scoreAt: (id, month) => scoresByGroup.get(id)?.find(row => row.month === month),
    latestMonth: id => scoresByGroup.get(id)?.at(-1) };
}
