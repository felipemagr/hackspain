import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  WRITER_RULES,
  checkNote,
  runNote,
  secs,
  writerStatus,
  type AgentRun,
  type FleetMember,
  type FleetState,
  type Suggestion,
  type Turn,
} from "../lib/chat";
import { monthLong } from "../lib/format";

// What the chat is good for, in the words of the person asking. Each row carries a 16px stroke icon.
const GUIDE: [string, string, string][] = [
  [
    "The whole portfolio",
    "Who is falling, who is improving, rankings, counts, by country or size.",
    "M2.5 2.5h4.5v4.5H2.5zM9 2.5h4.5v4.5H9zM2.5 9h4.5v4.5H2.5zM9 9h4.5v4.5H9z",
  ],
  [
    "One group, by its id",
    "Why its score moved, since when, and whether it is a bump or a fall.",
    "M8 2.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 1 0 0-11zM8 6.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 1 0 0-3z",
  ],
  [
    "The trail under a score",
    "Invoices, customers paying late, cash, debt and what is overdue.",
    "M3 4h10M3 8h10M3 12h6",
  ],
  [
    "What a move would do",
    "Lift a pillar and see the level and the credit line reprice.",
    "M2.5 11.5l4-4 3 3 4-5M10 5.5h3.5V9",
  ],
  [
    "What is happening outside",
    "The country around a group, or a real company you name.",
    "M8 2.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 1 0 0-11zM2.5 8h11M8 2.5c-2 2-2 9 0 11M8 2.5c2 2 2 9 0 11",
  ],
];

const WORKING = ["planning", "agents", "writing"];

const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

function AgentLine({ run, member }: { run: AgentRun; member: FleetMember | undefined }) {
  const [open, setOpen] = useState(false);
  const text = run.status === "failed" ? run.error : (run.summary ?? run.reason);
  return (
    <li className="trace__item">
      <button className="trace__row" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="agent__dot" data-status={run.status} />
        <span className="trace__label">{member?.label ?? run.id}</span>
        <span className={run.summary ? "trace__text" : "trace__text is-pending"}>
          {run.target && <span className="hint">{run.target} </span>}
          {text}
        </span>
        <span className="row__when">{runNote(run)}</span>
      </button>
      {open && (
        <div className="trace__detail">
          {member && (
            <>
              <p className="inspect__purpose">{member.purpose}</p>
              <h3>Rules it works under</h3>
              <ul>
                {member.rules.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
            </>
          )}
          <h3>What it did</h3>
          <ol className="steps">
            {run.steps.map((step) => (
              <li key={step.n}>
                <span className="agent__dot" data-status={step.status} />
                <code>
                  {step.tool}({step.input})
                </code>
                <span className="steps__out">{step.output ?? "running"}</span>
                <span className="row__when">{step.ms == null ? "" : secs(step.ms)}</span>
              </li>
            ))}
          </ol>
          {!!run.findings?.length && (
            <>
              <h3>What it found</h3>
              <ul>
                {run.findings.map((finding) => {
                  // Agents end a finding with "[period, seen date, direction]": evidence, kept quiet.
                  const [, fact, meta] = finding.match(/^(.*?)(?: \[([^\]]*)\])?$/s) ?? [];
                  return (
                    <li key={finding}>
                      {fact} {meta && <span className="hint">{meta}</span>}
                    </li>
                  );
                })}
              </ul>
            </>
          )}
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

// Anything that moves money is a draft until a person signs it.
function Draft({ suggestion, by }: { suggestion: Suggestion; by: string }) {
  const [signedAt, setSignedAt] = useState<string | null>(null);
  return (
    <aside className="draft">
      <div>
        <p className="hint">Draft suggestion from {by}</p>
        <p className="draft__title">{suggestion.title}</p>
        <p className="draft__detail">{suggestion.detail}</p>
      </div>
      {signedAt ? (
        <span className="hint">Signed at {signedAt}</span>
      ) : (
        <button
          onClick={() =>
            setSignedAt(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))
          }
        >
          Sign
        </button>
      )}
    </aside>
  );
}

function WriterLine({ turn }: { turn: Turn }) {
  const [open, setOpen] = useState(false);
  const note = turn.check ? checkNote(turn.check) : "writing from the results";
  return (
    <li className="trace__item">
      <button className="trace__row" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="agent__dot" data-status={writerStatus(turn)} />
        <span className="trace__label">Writer</span>
        <span className={turn.check ? "trace__text" : "trace__text is-pending"}>{note}</span>
        <span className="row__when">{turn.check ? secs(turn.check.ms ?? 0) : "writing"}</span>
      </button>
      {open && (
        <div className="trace__detail">
          <p className="inspect__purpose">Writes the answer. Every figure is checked.</p>
          <h3>Rules it works under</h3>
          <ul>
            {WRITER_RULES.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
          {turn.check && (
            <>
              <h3>What it did</h3>
              <ol className="steps">
                <li>
                  <span className="agent__dot" data-status={writerStatus(turn)} />
                  <code>figures.check(answer, results)</code>
                  <span className="steps__out">
                    {turn.check.untraced.length
                      ? `not in the results: ${turn.check.untraced.join(", ")}`
                      : checkNote(turn.check)}
                  </span>
                  <span className="row__when" />
                </li>
              </ol>
            </>
          )}
        </div>
      )}
    </li>
  );
}

// The fleet at work, in one block. Open while the turn runs so the rows land live; folded to
// its summary line once it ends, unless the reader opens it.
function Trace({ turn, members }: { turn: Turn; members: Map<string, FleetMember> }) {
  const [opened, setOpened] = useState<boolean | null>(null);
  const working = WORKING.includes(turn.phase);
  const open = opened ?? working;
  const reading = turn.phase === "planning";
  const head = reading
    ? turn.agents.length
      ? "Director is reading what came back"
      : "Director is reading the question"
    : turn.purpose
      ? `Read as: ${turn.purpose}`
      : turn.phase === "error"
        ? "The director could not plan"
        : "Stopped before the director planned";
  const names = [...new Set(turn.agents.map((run) => members.get(run.id)?.label ?? run.id))];
  const status = working
    ? "running"
    : turn.phase === "error"
      ? "failed"
      : turn.phase === "stopped"
        ? undefined
        : "done";
  const rows = turn.agents.length > 0 || turn.phase === "writing" || turn.check;
  return (
    <div className={open && rows ? "trace is-open" : "trace"}>
      <button className="trace__summary" onClick={() => setOpened(!open)} aria-expanded={open}>
        <span className="agent__dot" data-status={status} />
        <span className={reading ? "trace__purpose is-pending" : "trace__purpose"}>{head}</span>
        {names.length > 0 && <span className="trace__names">{names.join(", ")}</span>}
        <span className="row__when">
          {turn.phase === "stopped" ? "stopped" : turn.ms ? secs(turn.ms) : ""}
        </span>
        <svg className="trace__chevron" width="12" height="12" viewBox="0 0 12 12" aria-hidden>
          <path d="M3 4.5l3 3 3-3" />
        </svg>
      </button>
      {open && rows && (
        <ol className="trace__rows">
          {turn.agents.map((run) => (
            <AgentLine key={run.run} run={run} member={members.get(run.id)} />
          ))}
          {(turn.phase === "writing" || turn.check) && <WriterLine turn={turn} />}
        </ol>
      )}
    </div>
  );
}

function TurnView({ turn, members }: { turn: Turn; members: Map<string, FleetMember> }) {
  const working = WORKING.includes(turn.phase);
  return (
    <article className="turn">
      <p className="turn__question">{turn.question}</p>
      {turn.viewChart
        ? <p className="hint">AI view · {turn.entityId} · {monthLong(turn.month)}{turn.phase === "stopped" ? " · stopped" : ""}</p>
        : <Trace turn={turn} members={members} />}
      {(turn.answer || turn.phase === "writing") && (
        <div className={working ? "answer is-streaming" : "answer"} aria-live="polite">
          {turn.viewChart ? <Markdown remarkPlugins={[remarkGfm]} skipHtml>{turn.answer}</Markdown> : turn.answer.split(/\n{2,}/).map((para, i) => (
            <p key={i}>{para}</p>
          ))}
        </div>
      )}
      {turn.suggestion && turn.phase !== "planning" && (
        <Draft
          suggestion={turn.suggestion}
          by={members.get(turn.suggestion.agent)?.label ?? turn.suggestion.agent}
        />
      )}
      {turn.phase === "error" && <p className="turn__error">{turn.error}</p>}
    </article>
  );
}

// Mounted once per conversation: scroll, open inspectors and the draft belong to it.
export function Chat({
  month,
  fleet,
  turns,
  busy,
  onAsk,
  onStop,
  onNew,
}: {
  month: string;
  fleet: FleetState;
  turns: Turn[];
  busy: boolean;
  onAsk: (question: string) => void;
  onStop: () => void;
  onNew: () => void;
}) {
  const [draft, setDraft] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  // Follows the answer as it streams unless the reader has scrolled up to read.
  const following = useRef(true);
  const ready = fleet.status === "ready";
  const members = new Map(fleet.status === "ready" ? fleet.agents.map((a) => [a.id, a]) : []);

  useEffect(() => {
    if (following.current) scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [turns]);

  const send = (question: string) => {
    const text = question.trim();
    if (!text || busy || !ready) return;
    following.current = true;
    onAsk(text);
    setDraft("");
  };

  return (
    <div className="chat">
      <div
        className="chat__scroll"
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
        }}
      >
        <div className={turns.length === 0 ? "chat__column is-empty" : "chat__column"}>
          {turns.length === 0 ? (
            <div className="guide">
              <h2 className="guide__title">Ask anything the data holds.</h2>
              <p className="guide__lead">
                A director writes queries over the tables and sends agents to the groups you name.
                Every figure in an answer is traced back to a result you can open.
              </p>
              <ul className="guide__list">
                {GUIDE.map(([topic, what, icon]) => (
                  <li key={topic}>
                    <span className="guide__icon">
                      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
                        <path d={icon} />
                      </svg>
                    </span>
                    <span className="guide__text">
                      <span className="guide__topic">{topic}</span>
                      <span className="guide__what">{what}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            turns.map((turn) => <TurnView key={turn.id} turn={turn} members={members} />)
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
            autoFocus
            value={draft}
            placeholder={ready ? "Ask about the portfolio, a group or the data" : "Agents are offline"}
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
        <div className="composer__foot">
          {turns.length > 0 ? (
            <button type="button" className="chat__new" onClick={onNew}>
              <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden>
                <path d="M8 2.5H3.5A1.5 1.5 0 0 0 2 4v8.5A1.5 1.5 0 0 0 3.5 14H12a1.5 1.5 0 0 0 1.5-1.5V8" />
                <path d="M12.7 1.8a1.4 1.4 0 0 1 2 2L9 9.5l-2.7.7.7-2.7z" />
              </svg>
              New conversation
            </button>
          ) : (
            <span />
          )}
          <span className="hint">Data as of {monthLong(month)}</span>
        </div>
      </form>
    </div>
  );
}
