import { useEffect, useRef, useState } from "react";
import { runNote, type AgentRun, type FleetState, type Turn } from "../lib/chat";
import { monthLong } from "../lib/format";
import type { Store } from "../lib/load";
import { StateTag } from "./StateTag";

const STARTERS = [
  "Is this a bump or a fall?",
  "Why did the score change this month?",
  "When was this first visible?",
  "Is the whole sector moving, or only us?",
  "What should we do this week?",
  "What happens to our credit line if this continues?",
];

const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

function AgentLine({ run }: { run: AgentRun }) {
  const [open, setOpen] = useState(false);
  const detail = (run.findings?.length ?? 0) + (run.sources?.length ?? 0) > 0;
  const text = run.status === "failed" ? run.error : (run.summary ?? run.reason);
  return (
    <li className="trace__item">
      <button
        className="trace__row"
        onClick={() => setOpen(!open)}
        disabled={!detail}
        aria-expanded={detail ? open : undefined}
      >
        <span className="agent__dot" data-status={run.status} />
        <span className="trace__label">{run.label}</span>
        <span className={run.summary ? "trace__text" : "trace__text is-pending"}>{text}</span>
        <span className="row__when">{runNote(run)}</span>
      </button>
      {open && detail && (
        <div className="trace__detail">
          <ul>
            {run.findings?.map((finding) => {
              // Agents end a finding with "[period, seen date, direction]": evidence, kept quiet.
              const [, fact, meta] = finding.match(/^(.*?)(?: \[([^\]]*)\])?$/s) ?? [];
              return (
                <li key={finding}>
                  {fact} {meta && <span className="hint">{meta}</span>}
                </li>
              );
            })}
          </ul>
          {!!run.sources?.length && (
            <p className="trace__sources">
              {run.sources.map((url) => (
                <a key={url} href={url} target="_blank" rel="noreferrer">
                  {host(url)}
                </a>
              ))}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  const working = ["planning", "agents", "writing"].includes(turn.phase);
  const total = turn.ms ? `${(turn.ms / 1000).toFixed(1)} s` : "";
  return (
    <article className="turn">
      <h2 className="turn__question">{turn.question}</h2>
      <p className="hint">
        {turn.groupName}, {monthLong(turn.month)}
        {turn.company && turn.company !== turn.groupName ? `, reading ${turn.company}` : ""}
      </p>
      <div className="section-head trace__head">
        <span className="hint">
          {turn.phase === "planning"
            ? "Planner is choosing agents"
            : `${turn.agents.length} agent${turn.agents.length === 1 ? "" : "s"} dispatched`}
        </span>
        <span className="hint">{total}</span>
      </div>
      <ol className="trace">
        {turn.agents.map((run) => (
          <AgentLine key={run.id} run={run} />
        ))}
      </ol>
      {(turn.answer || turn.phase === "writing") && (
        <div className={working ? "answer is-streaming" : "answer"} aria-live="polite">
          {turn.answer.split(/\n{2,}/).map((para, i) => (
            <p key={i}>{para}</p>
          ))}
        </div>
      )}
      {turn.phase === "error" && <p className="turn__error">{turn.error}</p>}
      {turn.phase === "stopped" && <p className="hint">Stopped.</p>}
    </article>
  );
}

export function Chat({
  store,
  groupId,
  month,
  fleet,
  turns,
  busy,
  onAsk,
  onStop,
  onGroup,
}: {
  store: Store;
  groupId: string;
  month: string;
  fleet: FleetState;
  turns: Turn[];
  busy: boolean;
  onAsk: (question: string) => void;
  onStop: () => void;
  onGroup: (groupId: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const group = store.groupById.get(groupId);
  const score = store.scoreAt(groupId, month);
  const ready = fleet.status === "ready";

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [turns]);

  const send = (question: string) => {
    const text = question.trim();
    if (!text || busy || !ready) return;
    onAsk(text);
    setDraft("");
  };

  return (
    <div className="chat">
      <header className="chat__head">
        <div>
          <h1>{group?.name}</h1>
          <p className="detail__meta">
            {score ? (
              <>
                <StateTag state={score.state} />, level {Math.round(score.level)} in{" "}
                {monthLong(month)}
              </>
            ) : (
              `No score in ${monthLong(month)}`
            )}
          </p>
        </div>
        <label className="compare">
          <span className="hint">Ask about</span>
          <select value={groupId} onChange={(e) => onGroup(e.target.value)}>
            {store.groups.map((g) => (
              <option key={g.group_id} value={g.group_id}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="chat__scroll" ref={scroller}>
        <div className="chat__column">
          {turns.length === 0 ? (
            <div className="starters">
              <p className="starters__lead">
                Ask anything about this group. A planner picks the agents the question needs, each
                one reports what it found, and the answer is written from those reports only.
              </p>
              {STARTERS.map((question) => (
                <button key={question} onClick={() => send(question)} disabled={!ready}>
                  {question}
                </button>
              ))}
            </div>
          ) : (
            turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
          )}
        </div>
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <div className="composer__field">
          <textarea
            rows={1}
            value={draft}
            placeholder={ready ? `Ask about ${group?.name ?? "this group"}` : "Agents are offline"}
            disabled={!ready}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(draft);
              }
            }}
            aria-label="Your question"
          />
          {busy ? (
            <button type="button" onClick={onStop} aria-label="Stop">
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
                <rect x="1.5" y="1.5" width="9" height="9" rx="1.5" />
              </svg>
            </button>
          ) : (
            <button type="submit" disabled={!draft.trim() || !ready} aria-label="Send">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
                <path d="M7 12V2M2.5 6.5 7 2l4.5 4.5" />
              </svg>
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
