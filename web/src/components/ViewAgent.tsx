import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { askGroupAgent, askViewAgent, type ChartConfig, type ViewAction, type ViewMessage } from "../lib/viewAgent";
import type { Weights } from "../lib/scoring";
import "./view-agent.css";

interface Props {
  entityId: string;
  month: string;
  weights?: Weights;
  chart: ChartConfig;
  onApply: (actions: ViewAction[]) => void;
  onReset: () => void;
  customized: boolean;
  evaluating: boolean;
}

export function ViewAgent({ entityId, month, weights, chart, onApply, onReset, customized, evaluating }: Props) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ViewMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const profileKey = JSON.stringify(weights);
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
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); button.current?.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [messages, busy, error, open]);

  const close = () => { setOpen(false); button.current?.focus(); };
  const send = async () => {
    const message = draft.trim();
    if (!message || busy || evaluating) return;
    const controller = new AbortController();
    request.current = controller;
    setMessages(current => [...current, { role: "user", content: message }]);
    setDraft("");
    setError("");
    setBusy(true);
    try {
      const result = weights
        ? await askViewAgent({ message, entity_id: entityId, month: month.slice(0, 7), current_weights: weights.level, current_profile: weights,
          chart, history: messages.slice(-12), allow_weights: true }, controller.signal)
        : { reply: await askGroupAgent({ message, groupId: entityId, month, history: messages.slice(-12) }, controller.signal), actions: [] };
      if (controller.signal.aborted) return;
      onApply(result.actions);
      setMessages(current => [...current, { role: "assistant", content: result.reply }]);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "Could not reach the AI service. Please retry.");
        setDraft(message);
      }
    } finally {
      if (request.current === controller) { request.current = null; setBusy(false); }
    }
  };

  return <>
    <button ref={button} className="view-ai-button" aria-label="AI" aria-expanded={open} aria-controls="view-ai-panel" onClick={() => setOpen(value => !value)}>✨</button>
    {open && <section id="view-ai-panel" className={`view-ai${hasContent ? "" : " view-ai--empty"}`} role="dialog" aria-label="AI view assistant">
      <button className="view-ai__close" aria-label="Close AI" onClick={close}><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="m2 2 8 8M10 2l-8 8" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg></button>
      {hasContent && <div className="view-ai__messages" role="log" aria-label="AI conversation" aria-live="polite">
        {messages.map((message, index) => message.role === "assistant"
          ? <div key={index} className="view-ai__message view-ai__message--assistant"><Markdown remarkPlugins={[remarkGfm]} skipHtml components={{
            a: ({ href, children }) => href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
            img: ({ alt }) => <span>{alt}</span>,
          }}>{message.content}</Markdown></div>
          : <p key={index} className="view-ai__message view-ai__message--user">{message.content}</p>)}
        {busy && <p className="view-ai__status" role="status">Checking the data and your view…</p>}
        {evaluating && <p className="view-ai__status" role="status">Waiting for the current scores…</p>}
        {error && <p className="view-ai__error" role="alert">{error}</p>}
        <div ref={end} />
      </div>}
      <form className="view-ai__form" onSubmit={event => { event.preventDefault(); void send(); }}>
        <textarea ref={input} value={draft} maxLength={4000} rows={3} aria-label="Ask AI about this view" onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} />
        <div className="view-ai__controls">{customized && <button type="button" className="link" disabled={busy || evaluating} onClick={onReset}>Reset AI changes</button>}{busy ? <button type="button" onClick={() => { request.current?.abort(); request.current = null; setBusy(false); }}>Stop</button> : <button type="submit" disabled={!draft.trim() || evaluating}>Send</button>}</div>
      </form>
    </section>}
  </>;
}
