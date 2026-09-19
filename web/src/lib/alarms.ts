import { useCallback, useEffect, useState } from "react";
import { API_HEADERS, API_URL } from "./chat";

// One row of the alert rule book, as the API returns it.
export interface Alarm {
  id: number;
  text: string;
  channel: "slack" | "email";
  email_to: string | null;
  enabled: boolean;
  min_urgency: "info" | "warning" | "critical";
  min_severity: number | null;
  level_above: number | null;
  level_below: number | null;
  groups: string[];
  created_at: string;
}

export type AlarmChanges = Partial<
  Pick<
    Alarm,
    | "enabled"
    | "channel"
    | "email_to"
    | "min_urgency"
    | "min_severity"
    | "level_above"
    | "level_below"
    | "groups"
  >
>;

export type AlarmsState =
  | { status: "loading" }
  | { status: "down" }
  | { status: "ready"; alarms: Alarm[] };

const MOVES = {
  info: "raises any alert",
  warning: "moves down",
  critical: "starts falling",
};

// What the alarm waits for, in the rail's words: "GROUP_0130 goes above 80".
export function watches(alarm: Alarm): string {
  const who = alarm.groups.length ? alarm.groups.join(", ") : "Any group";
  const lines = [
    alarm.level_above != null && `above ${alarm.level_above}`,
    alarm.level_below != null && `below ${alarm.level_below}`,
  ].filter(Boolean);
  if (lines.length) return `${who} goes ${lines.join(" or ")}`;
  const floor = alarm.min_severity != null ? `, severity ${alarm.min_severity} or more` : "";
  return `${who} ${MOVES[alarm.min_urgency]}${floor}`;
}

// Where it goes: "Slack", "Email to cfo@example.com".
export function delivers(alarm: Alarm): string {
  if (alarm.channel === "slack") return "Slack";
  return alarm.email_to ? `Email to ${alarm.email_to}` : "Email";
}

// A GET carries no content type, so the poll stays a simple request with no preflight.
async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}/api/v1/alert-rules${path}`, {
    ...init,
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...API_HEADERS },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `The API answered ${res.status}.`);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

// How often the rail re-reads the book, so an alarm set in the chat shows up on its own.
const POLL_MS = 5000;

// The rule book, read when the rail opens and kept in step with every change made from it.
export function useAlarms() {
  const [state, setState] = useState<AlarmsState>({ status: "loading" });

  // A poll that fails keeps the alarms already on screen.
  const load = useCallback(() => {
    call<Alarm[]>("")
      .then((alarms) => setState({ status: "ready", alarms }))
      .catch(() => setState((s) => (s.status === "ready" ? s : { status: "down" })));
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    if (state.status !== "ready") return;
    const id = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(id);
  }, [state.status, load]);

  const replace = (alarm: Alarm) =>
    setState((s) =>
      s.status === "ready"
        ? { ...s, alarms: s.alarms.map((a) => (a.id === alarm.id ? alarm : a)) }
        : s,
    );

  const change = useCallback(async (id: number, changes: AlarmChanges) => {
    replace(await call<Alarm>(`/${id}`, { method: "PATCH", body: JSON.stringify(changes) }));
  }, []);

  const remove = useCallback(async (id: number) => {
    await call<void>(`/${id}`, { method: "DELETE" });
    setState((s) =>
      s.status === "ready" ? { ...s, alarms: s.alarms.filter((a) => a.id !== id) } : s,
    );
  }, []);

  // One test message down the alarm's channel. Rejects with the server's reason when it cannot.
  const test = useCallback(async (id: number) => {
    await call<void>(`/${id}/test`, { method: "POST" });
  }, []);

  // A request in plain words. Resolves to the question still open when the API needs more.
  const create = useCallback(async (text: string, groupId: string): Promise<string | null> => {
    try {
      const saved = await call<Alarm[]>("", {
        method: "POST",
        body: JSON.stringify({ text, group_id: groupId }),
      });
      setState((s) => (s.status === "ready" ? { ...s, alarms: [...s.alarms, ...saved] } : s));
      return null;
    } catch (e) {
      return (e as Error).message;
    }
  }, []);

  return { state, reload: load, change, remove, test, create };
}
