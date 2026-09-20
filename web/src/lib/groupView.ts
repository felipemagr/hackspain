import { API_HEADERS, API_URL } from "./chat";
import type { Store } from "./load";
import type { ActionRow, AlertRow, DriverRow, OfferRow, Pillar, ScoreRow } from "./types";

export type GroupWeights = Record<Pillar, number>;
export interface GroupView {
  weights: GroupWeights;
  tables: { scores: ScoreRow[]; drivers: DriverRow[]; alerts: AlertRow[]; offers: OfferRow[]; actions: ActionRow[] };
}

export async function evaluateGroup(groupId: string, weights: GroupWeights, signal: AbortSignal): Promise<GroupView> {
  const response = await fetch(`${API_URL}/api/v1/groups/${encodeURIComponent(groupId)}/evaluations`, {
    method: "POST", headers: { "Content-Type": "application/json", ...API_HEADERS },
    body: JSON.stringify(weights), signal,
  });
  if (!response.ok) throw new Error("Could not refresh your custom scores. Please retry.");
  return response.json() as Promise<GroupView>;
}

/** Replace every derived group view together; reset simply removes this overlay. */
export function withGroupViews(store: Store, views: Record<string, GroupView>): Store {
  const ids = Object.keys(views);
  if (!ids.length) return store;
  const scoresByGroup = new Map(store.scoresByGroup);
  const offersByGroup = new Map(store.offersByGroup);
  const actionsByGroup = new Map(store.actionsByGroup);
  for (const [id, view] of Object.entries(views)) {
    scoresByGroup.set(id, view.tables.scores.map(row => ({ ...row, pillarWeights: view.weights })));
    offersByGroup.set(id, view.tables.offers);
    actionsByGroup.set(id, view.tables.actions);
  }
  return {
    ...store, scoresByGroup, offersByGroup, actionsByGroup,
    scoreAt: (id, month) => scoresByGroup.get(id)?.find(row => row.month === month),
    latestMonth: id => scoresByGroup.get(id)?.at(-1),
    offerAt: (id, month) => offersByGroup.get(id)?.find(row => row.month === month),
    driversAt: (id, month) => views[id]
      ? views[id].tables.drivers.filter(row => row.month === month) : store.driversAt(id, month),
    alerts: [...store.alerts.filter(row => !views[row.group_id]), ...Object.values(views).flatMap(view => view.tables.alerts)],
    // The serving export has no leave-one-company-out pillars to recompute this counterfactual.
    companyImpactAt: (id, month) => views[store.companyById.get(id)?.group_id ?? ""]
      ? undefined : store.companyImpactAt(id, month),
  };
}
