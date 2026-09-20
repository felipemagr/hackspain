import { API_HEADERS, API_URL } from "./chat";
import { PILLAR_LABEL, STATE_META } from "./meta";
import type { EntityDetail, ScoringConfig, Weights } from "./scoring";
import type {
  ActionRow,
  AlertRow,
  CompanyRow,
  CompanyScoreRow,
  CompanyDriverRow,
  CompanyImpactRow,
  CompanyAlertRow,
  DriverRow,
  GroupRow,
  OfferRow,
  Pillar,
  ScoreRow,
  State,
} from "./types";

// The API serves the live tables; the static JSON under /data is the build-time copy the site
// falls back to when no API answers (the deployed static site, or the API asleep).

export interface Version {
  build_id: string;
  built_at: string;
  as_of: string | null;
  latest_month: string | null;
  n_alerts: number | null;
  tables: string[];
}

export interface Store {
  localScoring?: { config: ScoringConfig; kind: "group" | "company" };
  localDetails?: Map<string, EntityDetail>;
  localWeights?: Map<string, Weights>;
  /** Which build the tables came from; null when read from the static copy. */
  version: Version | null;
  /** When the data was last built, or when the static copy last changed. */
  updatedAt: Date | null;
  /** When this browser last fetched the tables. */
  syncedAt: Date;
  groups: GroupRow[];
  groupById: Map<string, GroupRow>;
  months: string[];
  scoresByGroup: Map<string, ScoreRow[]>;
  scoreAt: (groupId: string, month: string) => ScoreRow | undefined;
  latestMonth: (groupId: string) => ScoreRow | undefined;
  alerts: AlertRow[];
  offersByGroup: Map<string, OfferRow[]>;
  offerAt: (groupId: string, month: string) => OfferRow | undefined;
  actionsByGroup: Map<string, ActionRow[]>;
  companiesByGroup: Map<string, CompanyRow[]>;
  companyById: Map<string, CompanyRow>;
  scoresByCompany: Map<string, CompanyScoreRow[]>;
  companyScoreAt: (companyId: string, month: string) => CompanyScoreRow | undefined;
  companyDriversAt: (companyId: string, month: string) => CompanyDriverRow[];
  companyImpactAt: (companyId: string, month: string) => CompanyImpactRow | undefined;
  companyAlerts: CompanyAlertRow[];
  driversAt: (groupId: string, month: string) => DriverRow[];
}

/** The live build, or null when the API is not reachable. Cheap: the front end polls it. */
export async function fetchVersion(): Promise<Version | null> {
  try {
    const res = await fetch(`${API_URL}/api/v1/version`, {
      headers: API_HEADERS,
      signal: AbortSignal.timeout(2500),
    });
    if (!res.ok) return null;
    const v = (await res.json()) as Version;
    return v.tables.includes("scores") ? v : null;
  } catch {
    return null;
  }
}

let modified = 0;

async function fetchTable<T>(name: string, live: boolean): Promise<T[]> {
  const compressed = !live && ["company_scores", "company_drivers", "company_impact", "company_alerts"].includes(name);
  const url = live ? `${API_URL}/api/v1/tables/${name}` : `/data/${name}.json${compressed ? ".gz" : ""}`;
  // Revalidate, so a sync never settles for the browser's copy.
  const res = await fetch(url, { cache: "no-cache", headers: live ? API_HEADERS : {} });
  if (!res.ok) throw new Error(`table ${name}: ${res.status}`);
  modified = Math.max(modified, Date.parse(res.headers.get("last-modified") ?? "") || 0);
  if (compressed && res.headers.get("content-encoding") !== "gzip") {
    const stream = res.body?.pipeThrough(new DecompressionStream("gzip"));
    if (!stream) throw new Error(`table ${name}: empty response`);
    return new Response(stream).json() as Promise<T[]>;
  }
  return res.json() as Promise<T[]>;
}

function byMonth<T extends { month: string }>(rows: T[]): Map<string, T> {
  return new Map(rows.map((r) => [r.month, r]));
}

function fetchTables(live: boolean) {
  modified = 0;
  return Promise.all([
    fetchTable<GroupRow>("groups", live),
    fetchTable<ScoreRow>("scores", live),
    fetchTable<AlertRow>("alerts", live),
    fetchTable<OfferRow>("offers", live),
    fetchTable<ActionRow>("actions", live),
    fetchTable<CompanyRow>("companies", live),
    fetchTable<DriverRow>("drivers", live),
    fetchTable<CompanyScoreRow>("company_scores", live),
    fetchTable<CompanyDriverRow>("company_drivers", live),
    fetchTable<CompanyImpactRow>("company_impact", live),
    fetchTable<CompanyAlertRow>("company_alerts", live),
  ]);
}

export async function loadStore(version?: Version | null): Promise<Store> {
  let live = version === undefined ? await fetchVersion() : version;
  // The API can drop between the version check and the tables: read the static copy instead.
  const tables = await (live
    ? fetchTables(true).catch(() => {
        live = null;
        return fetchTables(false);
      })
    : fetchTables(false));
  const [groups, scores, alerts, offers, actions, companies, drivers, companyScores, companyDrivers, companyImpact, companyAlerts] = tables;

  const norm = (m: string) => m.slice(0, 10);
  const normState = (s: string): State => (s in STATE_META ? (s as State) : "not_enough_data");
  const normPillar = (p: string | null): Pillar | null =>
    p != null && p in PILLAR_LABEL ? (p as Pillar) : null;
  for (const row of [
    ...scores,
    ...alerts,
    ...offers,
    ...actions,
    ...drivers,
    ...companyScores,
    ...companyDrivers,
    ...companyImpact,
    ...companyAlerts,
  ]) {
    row.month = norm(row.month);
  }
  for (const s of scores) {
    s.state = normState(s.state);
  }
  for (const s of companyScores) {
    s.state = normState(s.state);
  }
  for (const a of alerts) {
    a.onset_month = norm(a.onset_month);
    a.state_from = normState(a.state_from);
    a.state_to = normState(a.state_to);
    a.driver_1 = normPillar(a.driver_1);
    a.driver_2 = normPillar(a.driver_2);
    if (a.tier_change_month) a.tier_change_month = norm(a.tier_change_month);
  }
  for (const a of companyAlerts) {
    a.onset_month = norm(a.onset_month);
    a.state_from = normState(a.state_from);
    a.state_to = normState(a.state_to);
    a.driver_1 = normPillar(a.driver_1);
    a.driver_2 = normPillar(a.driver_2);
    if (a.tier_change_month) a.tier_change_month = norm(a.tier_change_month);
  }
  const cleanDrivers = drivers.filter((d) => normPillar(d.pillar) != null);
  const cleanCompanyDrivers = companyDrivers.filter((d) => normPillar(d.pillar) != null);
  for (const a of actions) {
    a.pillar = normPillar(a.pillar) ?? a.pillar;
  }

  const groupById = new Map(groups.map((g) => [g.group_id, g]));
  const scoresByGroup = new Map<string, ScoreRow[]>();
  for (const s of scores) {
    const list = scoresByGroup.get(s.group_id) ?? [];
    list.push(s);
    scoresByGroup.set(s.group_id, list);
  }
  for (const list of scoresByGroup.values()) {
    list.sort((a, b) => a.month.localeCompare(b.month));
  }

  const monthSet = new Set(scores.map((s) => s.month));
  const months = [...monthSet].sort();

  const scoresKeyed = new Map<string, Map<string, ScoreRow>>();
  for (const [gid, list] of scoresByGroup) {
    scoresKeyed.set(gid, byMonth(list));
  }

  const offersByGroup = new Map<string, OfferRow[]>();
  for (const o of offers) {
    const list = offersByGroup.get(o.group_id) ?? [];
    list.push(o);
    offersByGroup.set(o.group_id, list);
  }
  const offersKeyed = new Map<string, Map<string, OfferRow>>();
  for (const [gid, list] of offersByGroup) {
    offersKeyed.set(gid, byMonth(list));
  }

  const actionsByGroup = new Map<string, ActionRow[]>();
  for (const a of actions) {
    const list = actionsByGroup.get(a.group_id) ?? [];
    list.push(a);
    actionsByGroup.set(a.group_id, list);
  }

  const companiesByGroup = new Map<string, CompanyRow[]>();
  for (const c of companies) {
    const list = companiesByGroup.get(c.group_id) ?? [];
    list.push(c);
    companiesByGroup.set(c.group_id, list);
  }
  const companyById = new Map(companies.map((c) => [c.company_id, c]));
  const scoresByCompany = new Map<string, CompanyScoreRow[]>();
  for (const s of companyScores) {
    const list = scoresByCompany.get(s.company_id) ?? [];
    list.push(s);
    scoresByCompany.set(s.company_id, list);
  }
  for (const list of scoresByCompany.values()) {
    list.sort((a, b) => a.month.localeCompare(b.month));
  }
  const companyScoresKeyed = new Map([...scoresByCompany].map(([id, rows]) => [id, byMonth(rows)]));
  const companyDriversKeyed = new Map<string, CompanyDriverRow[]>();
  for (const d of cleanCompanyDrivers) {
    const key = `${d.company_id}|${d.month}`;
    const list = companyDriversKeyed.get(key) ?? [];
    list.push(d);
    companyDriversKeyed.set(key, list);
  }
  const companyImpactKeyed = new Map(companyImpact.map((r) => [`${r.company_id}|${r.month}`, r]));

  const driversKeyed = new Map<string, DriverRow[]>();
  for (const d of cleanDrivers) {
    const key = `${d.group_id}|${d.month}`;
    const list = driversKeyed.get(key) ?? [];
    list.push(d);
    driversKeyed.set(key, list);
  }

  const alertsSorted = [...alerts].sort((a, b) => b.month.localeCompare(a.month));

  return {
    version: live,
    updatedAt: live ? new Date(live.built_at) : modified ? new Date(modified) : null,
    syncedAt: new Date(),
    groups,
    groupById,
    months,
    scoresByGroup,
    scoreAt: (gid, month) => scoresKeyed.get(gid)?.get(month),
    latestMonth: (gid) => {
      const list = scoresByGroup.get(gid);
      return list?.[list.length - 1];
    },
    alerts: alertsSorted,
    offersByGroup,
    offerAt: (gid, month) => offersKeyed.get(gid)?.get(month),
    actionsByGroup,
    companiesByGroup,
    companyById,
    scoresByCompany,
    companyScoreAt: (id, month) => companyScoresKeyed.get(id)?.get(month),
    companyDriversAt: (id, month) => companyDriversKeyed.get(`${id}|${month}`) ?? [],
    companyImpactAt: (id, month) => companyImpactKeyed.get(`${id}|${month}`),
    companyAlerts,
    driversAt: (gid, month) => driversKeyed.get(`${gid}|${month}`) ?? [],
  };
}
