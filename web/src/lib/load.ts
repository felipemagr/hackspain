import { PILLAR_LABEL, STATE_META } from "./meta";
import type {
  ActionRow,
  AlertRow,
  CompanyRow,
  DriverRow,
  GroupRow,
  OfferRow,
  Pillar,
  ScoreRow,
  State,
} from "./types";

export interface Store {
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
  driversAt: (groupId: string, month: string) => DriverRow[];
}

async function fetchTable<T>(name: string): Promise<T[]> {
  const res = await fetch(`/data/${name}.json`);
  if (!res.ok) throw new Error(`table ${name}: ${res.status}`);
  return res.json() as Promise<T[]>;
}

function byMonth<T extends { month: string }>(rows: T[]): Map<string, T> {
  return new Map(rows.map((r) => [r.month, r]));
}

export async function loadStore(): Promise<Store> {
  const [groups, scores, alerts, offers, actions, companies, drivers] = await Promise.all([
    fetchTable<GroupRow>("groups"),
    fetchTable<ScoreRow>("scores"),
    fetchTable<AlertRow>("alerts"),
    fetchTable<OfferRow>("offers"),
    fetchTable<ActionRow>("actions"),
    fetchTable<CompanyRow>("companies"),
    fetchTable<DriverRow>("drivers"),
  ]);

  const norm = (m: string) => m.slice(0, 10);
  const normState = (s: string): State => (s in STATE_META ? (s as State) : "not_enough_data");
  const normPillar = (p: string | null): Pillar | null =>
    p != null && p in PILLAR_LABEL ? (p as Pillar) : null;
  for (const row of [...scores, ...alerts, ...offers, ...actions, ...drivers]) {
    row.month = norm(row.month);
  }
  for (const s of scores) {
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
  const cleanDrivers = drivers.filter((d) => normPillar(d.pillar) != null);
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

  const driversKeyed = new Map<string, DriverRow[]>();
  for (const d of cleanDrivers) {
    const key = `${d.group_id}|${d.month}`;
    const list = driversKeyed.get(key) ?? [];
    list.push(d);
    driversKeyed.set(key, list);
  }

  const alertsSorted = [...alerts].sort((a, b) => b.month.localeCompare(a.month));

  return {
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
    driversAt: (gid, month) => driversKeyed.get(`${gid}|${month}`) ?? [],
  };
}
