import type { Store } from "./load";
import { scoringRequest } from "./scoring";
import type { Entity, EntityDetail, MonthRecord, ScoringConfig, ScoreNode, Weights } from "./scoring";
import type { GroupRow, ScoreRow } from "./types";

interface Observation {
  entity_id: string; month: string; level: number | null; confidence: number | null;
  evolution: number | null; evolution_confidence: number | null; coverage: number;
  subscores: Record<string, ScoreNode>; families: Record<string, ScoreNode>;
}
interface Portfolio { entities: (Entity & { entity_id?: string; country?: string; has_erp?: boolean })[]; observations: Observation[]; config: ScoringConfig }
const date = (month: string) => `${month.slice(0, 7)}-01`;

function scoreRow(id: string, row: MonthRecord, index: number): ScoreRow {
  const scoring = row.scoring;
  const level = scoring.level.score;
  const subs = scoring.subscores;
  return {
    group_id: id, month: date(row.month), level, localScoring: scoring,
    level_uncapped: level ?? NaN, is_capped: false, coverage: scoring.level.coverage,
    liquidity: subs.liquidity?.score ?? null, cash_generation: subs.generation?.score ?? null,
    payment_discipline: subs.payables?.score ?? null, collections: subs.receivables?.score ?? null,
    debt_burden: subs.debt_coverage?.score ?? null,
    buffer_days: subs.liquidity?.raw_value ?? null, operating_margin: null,
    ap_days_beyond_terms: null, ar_days_beyond_terms: null, dscr: subs.debt_coverage?.raw_value ?? null,
    trend: null, state: level == null ? "not_enough_data" : level >= 70 ? "healthy" : level >= 40 ? "stable" : "weak",
    months_observed: index + 1, compound: level ?? NaN,
    tier: level != null && level >= 70 ? "healthy" : level != null && level >= 40 ? "coping" : "vulnerable",
    monthly_inflow_eur: typeof row.inflow === "number" ? row.inflow : NaN,
  };
}

function bind(store: Store): Store {
  const indexed = new Map([...store.scoresByGroup].map(([id, rows]) => [id, new Map(rows.map(row => [row.month, row]))]));
  return { ...store, scoreAt: (id, month) => indexed.get(id)?.get(month), latestMonth: id => store.scoresByGroup.get(id)?.at(-1) };
}

export async function loadLocalStore(kind: "group" | "company", signal?: AbortSignal): Promise<Store> {
  const portfolio = await scoringRequest<Portfolio>(`/portfolio?kind=${kind}`, undefined, signal);
  const groups: GroupRow[] = portfolio.entities.map(entity => ({
    group_id: entity.id ?? entity.entity_id!, name: entity.name, sector: null,
    country: entity.country ?? null, n_companies: entity.member_count ?? 1,
    has_erp: entity.has_erp ?? false, annual_revenue_eur: NaN,
  }));
  const scoresByGroup = new Map<string, ScoreRow[]>();
  for (const observation of portfolio.observations) {
    const rows = scoresByGroup.get(observation.entity_id) ?? [];
    rows.push(scoreRow(observation.entity_id, { month: observation.month, scoring: {
      level: { score: observation.level, confidence: observation.confidence, coverage: observation.coverage },
      evolution: { score: observation.evolution, confidence: observation.evolution_confidence, coverage: 0 },
      subscores: observation.subscores, families: observation.families, metrics: {},
    } }, rows.length));
    scoresByGroup.set(observation.entity_id, rows);
  }
  for (const rows of scoresByGroup.values()) rows.sort((a, b) => a.month.localeCompare(b.month));
  return bind({
    localScoring: { config: portfolio.config, kind }, localDetails: new Map(), localWeights: new Map(),
    version: null, updatedAt: null, syncedAt: new Date(), groups, groupById: new Map(groups.map(group => [group.group_id, group])),
    months: [...new Set(portfolio.observations.map(row => date(row.month)))].sort(), scoresByGroup,
    scoreAt: () => undefined, latestMonth: () => undefined, alerts: [], offersByGroup: new Map(), offerAt: () => undefined,
    actionsByGroup: new Map(), companiesByGroup: new Map(),
    companyById: new Map(), scoresByCompany: new Map(), companyScoreAt: () => undefined,
    companyDriversAt: () => [], companyImpactAt: () => undefined, companyAlerts: [],
    driversAt: () => [], promptPayAt: () => undefined, promptPayCustomers: () => [],
  });
}

export function withLocalDetail(store: Store, detail: EntityDetail, weights?: Weights): Store {
  const id = detail.entity.id;
  const scoresByGroup = new Map(store.scoresByGroup);
  scoresByGroup.set(id, detail.monthly.map((row, index) => scoreRow(id, row, index)));
  const localDetails = new Map(store.localDetails).set(id, detail);
  const localWeights = new Map(store.localWeights);
  if (weights) localWeights.set(id, weights); else localWeights.delete(id);
  const companiesByGroup = new Map(store.companiesByGroup);
  if (detail.entity.kind === "group") companiesByGroup.set(id, detail.members.map(member => ({
    company_id: member.id, group_id: id, name: member.name, inflow_share: null, level: null, is_weakest: false,
  })));
  return bind({ ...store, scoresByGroup, localDetails, localWeights, companiesByGroup });
}
