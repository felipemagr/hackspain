import { useCallback, useEffect, useRef, useState } from "react";
import { displayCurrency } from "./currency";
import type { Weights } from "./scoring";

// The agent service. The rest of the demo reads static JSON and works without it.
export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";
// Baked into the bundle, so it keeps strangers off the API, not a reader of this page.
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined;
export const API_HEADERS: Record<string, string> = API_KEY ? { "X-API-Key": API_KEY } : {};

export interface FleetMember {
  id: string;
  label: string;
  purpose: string;
  rules: string[];
  tools: { name: string; does: string }[];
}

export type AgentStatus = "running" | "done" | "failed";

// One tool call by one agent: what it asked, what came back, how long it took.
export interface Step {
  n: number;
  tool: string;
  input: string;
  status: AgentStatus;
  output?: string;
  ms?: number;
}

// One call by the director: a query, or an agent pointed at a group and month.
export interface AgentRun {
  run: string;
  id: string;
  reason: string;
  target: string | null;
  status: AgentStatus;
  steps: Step[];
  summary?: string;
  findings?: string[];
  sources?: string[];
  ms?: number;
  error?: string;
}

export interface Suggestion {
  agent: string;
  title: string;
  detail: string;
}

export interface FigureCheck {
  figures: number;
  untraced: string[];
  ms?: number;
}

export type Phase = "planning" | "agents" | "writing" | "done" | "stopped" | "error";

export interface Turn {
  id: number;
  question: string;
  month: string;
  entityId?: string;
  weights?: Weights;
  phase: Phase;
  purpose: string | null;
  agents: AgentRun[];
  suggestion: Suggestion | null;
  answer: string;
  // The writer's figures, checked against the agent reports once the answer ends.
  check?: FigureCheck;
  ms?: number;
  error?: string;
}

// One conversation. Its title is its first question.
export interface Conversation {
  id: number;
  turns: Turn[];
}

export type FleetState =
  | { status: "waking" }
  | { status: "down" }
  | { status: "ready"; agents: FleetMember[]; model: string | null };

type Dispatched = { run: string; id: string; reason: string; target: string | null };

type ChatEvent =
  | { type: "planning" | "writing" }
  | { type: "plan"; purpose: string; agents: Dispatched[] }
  | ({ type: "check" } & FigureCheck)
  | ({ type: "agent"; run: string; status: AgentStatus } & Partial<AgentRun>)
  | ({ type: "step"; run: string } & Step)
  | ({ type: "suggestion" } & Suggestion)
  | { type: "token"; text: string }
  | { type: "error"; message: string }
  | { type: "done"; ms: number };

export const secs = (ms: number) =>
  ms < 950 ? `${Math.max(ms, 1)} ms` : `${(ms / 1000).toFixed(1)} s`;

// What an agent is doing right now, in the words of its tool.
export function runNote(run: AgentRun): string {
  if (run.status === "failed") return "failed";
  if (run.status === "done") return secs(run.ms ?? 0);
  return run.steps.findLast((step) => step.status === "running")?.tool ?? "starting";
}

// The writer is a member of the fleet like any other: it runs, it ends, and its work is checked.
export const WRITER_RULES = [
  "Writes only from what the queries and the agents returned.",
  "Every figure in the answer is checked against those results, at the precision it has.",
  "Counts up to twelve are words, not figures.",
];

export function writerStatus(turn: Turn | undefined): AgentStatus | "idle" {
  if (turn?.phase === "writing") return "running";
  if (turn?.check?.untraced.length) return "failed";
  return turn?.check || turn?.phase === "done" ? "done" : "idle";
}

export function checkNote(check: FigureCheck): string {
  if (check.untraced.length)
    return `${check.untraced.length} of ${check.figures} figures not in the results`;
  return check.figures ? `${check.figures} figures, all traced` : "no figures to trace";
}

const queued = (agents: Dispatched[]): AgentRun[] =>
  agents.map((a) => ({ ...a, status: "running", steps: [] }));

function apply(turn: Turn, event: ChatEvent): Turn {
  switch (event.type) {
    case "planning":
      return { ...turn, phase: "planning" };
    // The director plans in rounds: each one adds its calls under the ones before.
    case "plan":
      return {
        ...turn,
        phase: "agents",
        purpose: turn.purpose ?? event.purpose,
        agents: [...turn.agents, ...queued(event.agents)],
      };
    case "agent": {
      const { type: _type, ...patch } = event;
      return {
        ...turn,
        agents: turn.agents.map((a) => (a.run === event.run ? { ...a, ...patch } : a)),
      };
    }
    case "step": {
      const { type: _type, run, ...step } = event;
      return {
        ...turn,
        agents: turn.agents.map((a) =>
          a.run === run
            ? { ...a, steps: [...a.steps.filter((known) => known.n !== step.n), step] }
            : a,
        ),
      };
    }
    case "suggestion": {
      const { type: _type, ...suggestion } = event;
      return { ...turn, suggestion };
    }
    case "writing":
      return { ...turn, phase: "writing" };
    case "token":
      return { ...turn, answer: turn.answer + event.text };
    case "check":
      return { ...turn, check: { figures: event.figures, untraced: event.untraced, ms: event.ms } };
    case "error":
      return { ...turn, phase: "error", error: event.message };
    case "done":
      return { ...turn, phase: turn.phase === "error" ? "error" : "done", ms: event.ms };
  }
}

async function* readEvents(response: Response): AsyncGenerator<ChatEvent> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      if (frame.startsWith("data: ")) yield JSON.parse(frame.slice(6)) as ChatEvent;
    }
  }
}

const CHATS_KEY = "xray.chats.v2";
const WORKING: Phase[] = ["planning", "agents", "writing"];

// A turn cut short by a reload never finished: it comes back as stopped.
function readChats(key: string): Conversation[] {
  try {
    const chats = JSON.parse(localStorage.getItem(key) ?? "[]") as Conversation[];
    return chats.map((chat) => ({
      ...chat,
      turns: chat.turns.map((t) => (WORKING.includes(t.phase) ? { ...t, phase: "stopped" } : t)),
    }));
  } catch {
    return [];
  }
}

export function useChat(localScoring = false) {
  const storageKey = localScoring ? "xray.localScoring.chats" : CHATS_KEY;
  const [fleet, setFleet] = useState<FleetState>({ status: "waking" });
  // Newest first. activeId null is a new conversation nobody has asked in yet.
  const [chats, setChats] = useState(() => readChats(storageKey));
  const [activeId, setActiveId] = useState<number | null>(null);
  const abort = useRef<AbortController | null>(null);
  const turns = chats.find((chat) => chat.id === activeId)?.turns ?? [];

  const load = useCallback(() => {
    fetch(`${API_URL}/api/v1/agents`, { headers: API_HEADERS })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((body) => setFleet({ status: "ready", agents: body.agents, model: body.model }))
      .catch(() => setFleet({ status: "down" }));
  }, []);

  useEffect(load, [load]);

  const wake = useCallback(() => {
    setFleet({ status: "waking" });
    load();
  }, [load]);

  const last = turns[turns.length - 1];
  const busy = !!last && WORKING.includes(last.phase);
  const streaming = chats.some((chat) => WORKING.includes(chat.turns[chat.turns.length - 1].phase));

  useEffect(() => {
    if (streaming) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify(chats));
    } catch {
      // private window: the conversations still work for the session
    }
  }, [chats, streaming, storageKey]);

  const ask = useCallback(
    async (question: string, month: string, context?: { entityId: string; weights?: Weights }) => {
      const entityId = context?.entityId;
      const weights = context?.weights;
      const id = Date.now();
      const chatId = activeId ?? id;
      const history = turns
        .filter((t) => t.answer && (!localScoring || (t.entityId === entityId && t.month === month && JSON.stringify(t.weights) === JSON.stringify(weights))))
        .flatMap((t) => [
          { role: "user", content: t.question },
          { role: "assistant", content: t.answer },
        ]);
      const patch = (fn: (turn: Turn) => Turn) =>
        setChats((all) =>
          all.map((chat) =>
            chat.id === chatId
              ? { ...chat, turns: chat.turns.map((t) => (t.id === id ? fn(t) : t)) }
              : chat,
          ),
        );
      const turn: Turn = {
        id,
        question,
        month,
        entityId,
        weights,
        phase: "planning",
        purpose: null,
        agents: [],
        suggestion: null,
        answer: "",
      };
      // The conversation just asked in moves to the top.
      setChats((all) => [
        { id: chatId, turns: [...(all.find((chat) => chat.id === chatId)?.turns ?? []), turn] },
        ...all.filter((chat) => chat.id !== chatId),
      ]);
      setActiveId(chatId);
      const controller = new AbortController();
      abort.current = controller;
      try {
        const response = await fetch(`${API_URL}/api/v1/chats`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...API_HEADERS },
          body: JSON.stringify({
            message: question,
            ...(localScoring ? { entity_id: entityId, weights } : {}),
            month: localScoring ? month.slice(0, 7) : month,
            history,
            currency: displayCurrency(),
          }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`The agent service answered ${response.status}.`);
        for await (const event of readEvents(response)) patch((t) => apply(t, event));
      } catch (e) {
        if (controller.signal.aborted) patch((t) => ({ ...t, phase: "stopped" }));
        else
          patch((t) => ({
            ...t,
            phase: "error",
            error: `${(e as Error).message} Check that the agent service is running, then ask again.`,
          }));
      }
    },
    [turns, activeId, localScoring],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  const remove = useCallback(
    (chatId: number) => {
      if (chatId === activeId) {
        abort.current?.abort();
        setActiveId(null);
      }
      setChats((all) => all.filter((chat) => chat.id !== chatId));
    },
    [activeId],
  );

  return { fleet, chats, activeId, open: setActiveId, remove, turns, busy, ask, stop, wake };
}
