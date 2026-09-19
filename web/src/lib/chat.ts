import { useCallback, useEffect, useRef, useState } from "react";
import { displayCurrency } from "./currency";

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

export interface FigureCheck {
  figures: number;
  untraced: string[];
}

export type Phase = "planning" | "agents" | "writing" | "done" | "stopped" | "error";

export interface Turn {
  id: number;
  question: string;
  groupId: string;
  groupName: string;
  month: string;
  phase: Phase;
  purpose: string | null;
  company: string | null;
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

type Dispatched = { id: string; reason: string };

type ChatEvent =
  | { type: "planning" | "writing" }
  | { type: "plan"; purpose: string; company: string | null; agents: Dispatched[] }
  | ({ type: "check" } & FigureCheck)
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

// The writer is a member of the fleet like any other: it runs, it ends, and its work is checked.
export const WRITER_RULES = [
  "Writes only from the agent reports.",
  "Every figure in the answer is checked against those reports, at the precision it has.",
  "Counts up to twelve are words, not figures.",
];

export function writerStatus(turn: Turn | undefined): AgentStatus | "idle" {
  if (turn?.phase === "writing") return "running";
  if (turn?.check?.untraced.length) return "failed";
  return turn?.check ? "done" : "idle";
}

export function checkNote(check: FigureCheck): string {
  if (check.untraced.length)
    return `${check.untraced.length} of ${check.figures} figures not in the reports`;
  return check.figures ? `${check.figures} figures, all traced` : "no figures to trace";
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
    case "check":
      return { ...turn, check: { figures: event.figures, untraced: event.untraced } };
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

const CHATS_KEY = "xray.chats";
const MAX_CHATS = 30;
const WORKING: Phase[] = ["planning", "agents", "writing"];

// A turn cut short by a reload never finished: it comes back as stopped.
function readChats(): Conversation[] {
  try {
    const chats = JSON.parse(localStorage.getItem(CHATS_KEY) ?? "[]") as Conversation[];
    return chats.map((chat) => ({
      ...chat,
      turns: chat.turns.map((t) => (WORKING.includes(t.phase) ? { ...t, phase: "stopped" } : t)),
    }));
  } catch {
    return [];
  }
}

export function useChat() {
  const [fleet, setFleet] = useState<FleetState>({ status: "waking" });
  // Newest first. activeId null is a new conversation nobody has asked in yet.
  const [chats, setChats] = useState(readChats);
  const [activeId, setActiveId] = useState<number | null>(null);
  const abort = useRef<AbortController | null>(null);
  const turns = chats.find((chat) => chat.id === activeId)?.turns ?? [];

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
  const busy = !!last && WORKING.includes(last.phase);
  const streaming = chats.some((chat) => WORKING.includes(chat.turns[chat.turns.length - 1].phase));

  useEffect(() => {
    if (streaming) return;
    try {
      localStorage.setItem(CHATS_KEY, JSON.stringify(chats));
    } catch {
      // private window: the conversations still work for the session
    }
  }, [chats, streaming]);

  const ask = useCallback(
    async (question: string, groupId: string, groupName: string, month: string) => {
      const id = Date.now();
      const chatId = activeId ?? id;
      const history = turns
        .filter((t) => t.answer)
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
        groupId,
        groupName,
        month,
        phase: "planning",
        purpose: null,
        company: null,
        agents: [],
        suggestion: null,
        answer: "",
      };
      // The conversation just asked in moves to the top.
      setChats((all) =>
        [
          { id: chatId, turns: [...(all.find((chat) => chat.id === chatId)?.turns ?? []), turn] },
          ...all.filter((chat) => chat.id !== chatId),
        ].slice(0, MAX_CHATS),
      );
      setActiveId(chatId);
      const controller = new AbortController();
      abort.current = controller;
      try {
        const response = await fetch(`${API_URL}/api/v1/chats`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: question,
            group_id: groupId,
            month,
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
    [turns, activeId],
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
