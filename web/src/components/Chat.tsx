import { useEffect, useRef, useState } from "react";
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

// What the chat is good for, in the words of the person asking.
const GUIDE: [string, string][] = [
  ["The whole portfolio", "Who is falling, who is improving, rankings, counts, by country or size."],
  ["One group, by its id", "Why its score moved, since when, and whether it is a bump or a fall."],
  ["The trail under a score", "Invoices, customers paying late, cash, debt and what is overdue."],
  ["What a move would do", "Lift a pillar and see the level and the credit line reprice."],
  ["What is happening outside", "The country around a group, or a real company you name."],
];

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
  const note = turn.check ? checkNote(turn.check) : "Writing from the results";
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

function TurnView({ turn, members }: { turn: Turn; members: Map<string, FleetMember> }) {
  const working = ["planning", "agents", "writing"].includes(turn.phase);
  const total = turn.ms ? `${(turn.ms / 1000).toFixed(1)} s` : "";
  return (
    <article className="turn">
      <h2 className="turn__question">{turn.question}</h2>
      <p className="hint">Data as of {monthLong(turn.month)}</p>
      <div className="section-head trace__head">
        <span className="hint">
          {turn.phase === "planning"
            ? turn.agents.length
              ? "Director is reading what came back"
              : "Director is reading the question"
            : `${turn.purpose ? `Read as: ${turn.purpose}. ` : ""}${turn.agents.length} call${turn.agents.length === 1 ? "" : "s"}`}
        </span>
        <span className="hint">{total}</span>
      </div>
      <ol className="trace">
        {turn.agents.map((run) => (
          <AgentLine key={run.run} run={run} member={members.get(run.id)} />
        ))}
        {(turn.phase === "writing" || turn.check) && <WriterLine turn={turn} />}
      </ol>
      {(turn.answer || turn.phase === "writing") && (
        <div className={working ? "answer is-streaming" : "answer"} aria-live="polite">
          {turn.answer.split(/\n{2,}/).map((para, i) => (
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
      {turn.phase === "stopped" && <p className="hint">Stopped.</p>}
    </article>
  );
}

export function Chat({
  month,
  fleet,
  turns,
  busy,
  onAsk,
  onStop,
}: {
  month: string;
  fleet: FleetState;
  turns: Turn[];
  busy: boolean;
  onAsk: (question: string) => void;
  onStop: () => void;
}) {
  const [draft, setDraft] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const ready = fleet.status === "ready";
  const members = new Map(fleet.status === "ready" ? fleet.agents.map((a) => [a.id, a]) : []);

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
      <div className="chat__scroll" ref={scroller}>
        <div className="chat__column">
          {turns.length === 0 ? (
            <div className="guide">
              <p className="guide__lead">
                Ask anything the data holds, in your own words, as of {monthLong(month)}. A
                director writes queries over the tables and sends agents to the groups you name,
                until it can answer. Open any line in the answer to see the query or the steps.
              </p>
              <dl>
                {GUIDE.map(([topic, what]) => (
                  <div key={topic}>
                    <dt>{topic}</dt>
                    <dd>{what}</dd>
                  </div>
                ))}
              </dl>
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
      </form>
    </div>
  );
}
