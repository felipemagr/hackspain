import { useCallback, useEffect, useRef, useState } from "react";

// The agent service. The rest of the demo reads static JSON and works without it.
export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

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

export interface AgentRun {
  id: string;
  reason: string;
  // Dispatched by the planner after it read the first reports, not in the opening plan.
  followUp: boolean;
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

export type Phase = "planning" | "agents" | "writing" | "done" | "stopped" | "error";

export interface Turn {
  id: number;
  question: string;
  groupName: string;
  month: string;
  phase: Phase;
  purpose: string | null;
  company: string | null;
  agents: AgentRun[];
  suggestion: Suggestion | null;
  answer: string;
  ms?: number;
  error?: string;
}

export type FleetState =
  | { status: "waking" }
  | { status: "down" }
  | { status: "ready"; agents: FleetMember[]; model: string | null };

type Dispatched = { id: string; reason: string };

type ChatEvent =
  | { type: "planning" | "writing" }
  | { type: "plan"; purpose: string; company: string | null; agents: Dispatched[] }
  | { type: "dispatch"; agents: Dispatched[] }
  | ({ type: "agent"; id: string; status: AgentStatus } & Partial<AgentRun>)
  | ({ type: "step"; agent: string } & Step)
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

const queued = (agents: Dispatched[], followUp: boolean): AgentRun[] =>
  agents.map((a) => ({ ...a, followUp, status: "running", steps: [] }));

function apply(turn: Turn, event: ChatEvent): Turn {
  switch (event.type) {
    case "planning":
      return { ...turn, phase: "planning" };
    case "plan":
      return {
        ...turn,
        phase: "agents",
        purpose: event.purpose,
        company: event.company,
        agents: queued(event.agents, false),
      };
    case "dispatch":
      return { ...turn, agents: [...turn.agents, ...queued(event.agents, true)] };
    case "agent": {
      const { type: _type, ...patch } = event;
      return {
        ...turn,
        agents: turn.agents.map((a) => (a.id === event.id ? { ...a, ...patch } : a)),
      };
    }
    case "step": {
      const { type: _type, agent, ...step } = event;
      return {
        ...turn,
        agents: turn.agents.map((a) =>
          a.id === agent
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

export function useChat() {
  const [fleet, setFleet] = useState<FleetState>({ status: "waking" });
  const [turns, setTurns] = useState<Turn[]>([]);
  const abort = useRef<AbortController | null>(null);
  const nextId = useRef(1);

  const load = useCallback(() => {
    fetch(`${API_URL}/api/v1/agents`)
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
  const busy = !!last && ["planning", "agents", "writing"].includes(last.phase);

  const ask = useCallback(
    async (question: string, groupId: string, groupName: string, month: string) => {
      const id = nextId.current++;
      const history = turns
        .filter((t) => t.answer)
        .flatMap((t) => [
          { role: "user", content: t.question },
          { role: "assistant", content: t.answer },
        ]);
      const patch = (fn: (turn: Turn) => Turn) =>
        setTurns((all) => all.map((t) => (t.id === id ? fn(t) : t)));
      setTurns((all) => [
        ...all,
        {
          id,
          question,
          groupName,
          month,
          phase: "planning",
          purpose: null,
          company: null,
          agents: [],
          suggestion: null,
          answer: "",
        },
      ]);
      const controller = new AbortController();
      abort.current = controller;
      try {
        const response = await fetch(`${API_URL}/api/v1/chats`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: question, group_id: groupId, month, history }),
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
    [turns],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  return { fleet, turns, busy, ask, stop, wake };
}
