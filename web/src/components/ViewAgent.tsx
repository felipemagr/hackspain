import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { askGroupAgent, askViewAgent, type ChartConfig, type ViewAction, type ViewMessage } from "../lib/viewAgent";
import type { Weights } from "../lib/scoring";
import type { GroupWeights } from "../lib/groupView";
import { viewActionContext, type Turn } from "../lib/chat";
import { monthLong } from "../lib/format";
import "./view-agent.css";

const SUGGESTIONS = [
  "Why did the score move this month?",
  "Is this a bump or a structural fall?",
  "How early was this visible?",
  "What if liquidity weighed 50%?",
];

interface Props {
  entityId: string;
  entityName: string;
  parentGroupId?: string;
  month: string;
  weights?: Weights;
  groupWeights?: GroupWeights;
  onRecord: (chatId: number, turn: Turn) => void;
  chart: ChartConfig;
  onApply: (actions: ViewAction[]) => void;
  onReset: () => void;
  customized: boolean;
  evaluating: boolean;
}

export function ViewAgent({ entityId, entityName, parentGroupId, month, weights, groupWeights, onRecord, chart, onApply, onReset, customized, evaluating }: Props) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ViewMessage[]>([]);
  const conversationId = useRef<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const latest = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const profileKey = JSON.stringify(weights ?? groupWeights);
  const chartKey = JSON.stringify(chart);
  const hasContent = messages.length > 0 || busy || evaluating || Boolean(error);

  useEffect(() => {
    request.current?.abort();
    request.current = null;
    setBusy(false);
    setError("");
    return () => request.current?.abort();
  }, [entityId, month, profileKey, chartKey, evaluating]);
  useEffect(() => { if (open) input.current?.focus(); }, [open]);
  useEffect(() => {
    if (!input.current) return;
    input.current.style.height = "auto";
    input.current.style.height = `${Math.min(input.current.scrollHeight, 112)}px`;
  }, [draft, open, expanded]);
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); button.current?.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);
  // A new answer is read from its first line; everything else keeps the end in view.
  useEffect(() => {
    if (!busy && !error && messages.at(-1)?.role === "assistant") latest.current?.scrollIntoView({ block: "start" });
    else end.current?.scrollIntoView({ block: "nearest" });
  }, [messages, busy, error, open]);

  const close = () => { setOpen(false); button.current?.focus(); };
  const send = async (text = draft) => {
    const message = text.trim();
    if (!message || busy || evaluating) return;
    const controller = new AbortController();
    const chatId = conversationId.current ?? Date.now();
    conversationId.current = chatId;
    const started = Date.now();
    const turn: Turn = { id: started, question: message, month, entityId, parentGroupId, weights, groupWeights,
      viewChart: chart, phase: "planning", purpose: "Group view assistant", agents: [], suggestion: null, answer: "" };
    onRecord(chatId, turn);
    request.current = controller;
    setMessages(current => [...current, { role: "user", content: message }]);
    setDraft("");
    setError("");
    setBusy(true);
    try {
      const result = weights
        ? await askViewAgent({ message, entity_id: entityId, month: month.slice(0, 7), current_weights: weights.level, current_profile: weights,
          chart, history: messages.slice(-12), allow_weights: true }, controller.signal)
        : await askGroupAgent({ message, groupId: parentGroupId ?? entityId, companyId: parentGroupId ? entityId : undefined,
          month, history: messages.slice(-12), currentWeights: groupWeights }, controller.signal);
      if (controller.signal.aborted) { onRecord(chatId, { ...turn, phase: "stopped" }); return; }
      onApply(result.actions);
      onRecord(chatId, { ...turn, ...viewActionContext(turn, result.actions), phase: "done", answer: result.reply, ms: Date.now() - started });
      setMessages(current => [...current, { role: "assistant", content: result.reply }]);
    } catch (cause) {
      onRecord(chatId, { ...turn, phase: controller.signal.aborted ? "stopped" : "error",
        error: controller.signal.aborted ? undefined : cause instanceof Error ? cause.message : "Could not reach the AI service." });
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "Could not reach the AI service. Please retry.");
        setDraft(message);
      }
    } finally {
      if (request.current === controller) { request.current = null; setBusy(false); }
    }
  };

  return <>
    <button ref={button} className="view-ai-button" aria-label="Ask Lighthouse" aria-expanded={open} aria-controls="view-ai-panel" onClick={() => setOpen(value => !value)}>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9.5 6.5 12 3.5l2.5 3M9.5 6.5v4M14.5 6.5v4M8 10.5h8M9.5 10.5 8.25 20.5h7.5L14.5 10.5M6 20.5h12M6.5 7 3.5 6M6.5 9.5l-3 1M17.5 7l3-1M17.5 9.5l3 1" /></svg>
    </button>
    {open && <section id="view-ai-panel" className={`view-ai${hasContent ? "" : " view-ai--empty"}${expanded ? " view-ai--expanded" : ""}`} role="dialog" aria-labelledby="view-ai-title">
      <div className="view-ai__toolbar">
        <div className="view-ai__heading">
          <h2 id="view-ai-title">Ask Lighthouse</h2>
          <p>{entityName} · {monthLong(month)}</p>
        </div>
        <button className="view-ai__icon" aria-label={expanded ? "Collapse chat" : "Expand chat"} title={expanded ? "Collapse chat" : "Expand chat"} aria-pressed={expanded} onClick={() => setExpanded(value => !value)}>
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={expanded ? "M3 7h4V3m6 0v4h4M3 13h4v4m6 0v-4h4" : "M7 3H3v4m10-4h4v4M3 13v4h4m6 0h4v-4"} /></svg>
        </button>
        <button className="view-ai__icon" aria-label="Close AI" title="Close" onClick={close}><svg width="16" height="16" viewBox="0 0 20 20" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg></button>
      </div>
      {hasContent && <div className="view-ai__messages" role="log" aria-label="AI conversation" aria-live="polite">
        {messages.map((message, index) => message.role === "assistant"
          ? <div key={index} ref={index === messages.length - 1 ? latest : undefined} className="view-ai__message view-ai__message--assistant"><Markdown remarkPlugins={[remarkGfm]} skipHtml components={{
            a: ({ href, children }) => href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
            img: ({ alt }) => <span>{alt}</span>,
          }}>{message.content}</Markdown></div>
          : <p key={index} className="view-ai__message view-ai__message--user">{message.content}</p>)}
        {busy && <p className="view-ai__status" role="status">Checking the data and your view…</p>}
        {evaluating && <p className="view-ai__status" role="status">Waiting for the current scores…</p>}
        {error && <p className="view-ai__error" role="alert">{error}</p>}
        <div ref={end} />
      </div>}
      {!hasContent && <ul className="view-ai__suggestions" aria-label="Suggested questions">
        {SUGGESTIONS.map(question => <li key={question}><button type="button" onClick={() => void send(question)}>{question}</button></li>)}
      </ul>}
      <form className="view-ai__form" onSubmit={event => { event.preventDefault(); void send(); }}>
        <div className="view-ai__composer">
          <textarea ref={input} value={draft} maxLength={4000} rows={2} placeholder="Ask about this view…" aria-label="Ask AI about this view" onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} />
          <div className="view-ai__controls">
            {customized && <button type="button" className="view-ai__reset" disabled={busy || evaluating} onClick={() => { onReset(); setMessages(current => [...current, { role: "assistant", content: "Weights and chart restored to the defaults." }]); }}>
              <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7a6 6 0 1 1 0 6M4 3v4h4" /></svg>Reset AI changes
            </button>}
            {busy ? <button className="view-ai__send" type="button" onClick={() => { request.current?.abort(); request.current = null; setBusy(false); }}><svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true"><rect x="2" y="2" width="8" height="8" rx="1" /></svg>Stop</button>
              : <button className="view-ai__send" type="submit" disabled={!draft.trim() || evaluating}>Send<svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 16V4m-5 5 5-5 5 5" /></svg></button>}
          </div>
        </div>
      </form>
    </section>}
  </>;
}
