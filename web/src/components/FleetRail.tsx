import { runNote, type Conversation, type FleetState, type Turn } from "../lib/chat";

// A turn id is the time it was asked.
function ago(then: number): string {
  const min = Math.round((Date.now() - then) / 60000);
  if (min < 1) return "now";
  if (min < 60) return `${min} min`;
  if (min < 60 * 24) return `${Math.round(min / 60)} h`;
  return new Date(then).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function Conversations({
  chats,
  activeId,
  onOpen,
  onNew,
  onRemove,
}: {
  chats: Conversation[];
  activeId: number | null;
  onOpen: (chat: Conversation) => void;
  onNew: () => void;
  onRemove: (chatId: number) => void;
}) {
  return (
    <div className="chats">
      <div className="list__head">
        Conversations <span className="list__count">{chats.length}</span>
        <button className="link" onClick={onNew} disabled={activeId == null}>
          New conversation
        </button>
      </div>
      {chats.length === 0 && (
        <p className="empty">Nothing asked yet. Conversations are kept in this browser.</p>
      )}
      <div className="chats__list">
        {chats.map((chat) => {
          const last = chat.turns[chat.turns.length - 1];
          const title = chat.turns[0].question;
          const working = ["planning", "agents", "writing"].includes(last.phase);
          return (
            <div
              key={chat.id}
              className={`row-wrap row-wrap--alert ${chat.id === activeId ? "is-selected" : ""}`}
            >
              <button className="row row--alert" onClick={() => onOpen(chat)}>
                <span className="row__text">
                  <span className="row__name">{title}</span>
                  <span className="row__sub">
                    {last.groupName} · {chat.turns.length}{" "}
                    {chat.turns.length === 1 ? "question" : "questions"}
                  </span>
                </span>
                <span className="row__when">{working ? "answering" : ago(last.id)}</span>
              </button>
              <button
                className="row__clear"
                aria-label={`Delete the conversation: ${title}`}
                onClick={() => onRemove(chat.id)}
              >
                <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                  <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" />
                </svg>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// The fleet at rest and at work: who exists, and what each one is doing for the current question.
function Fleet({
  fleet,
  turn,
  onRetry,
}: {
  fleet: FleetState;
  turn: Turn | undefined;
  onRetry: () => void;
}) {
  if (fleet.status === "waking") {
    return (
      <p className="empty">Waking the agents. On the free tier the first call can take a minute.</p>
    );
  }
  if (fleet.status === "down") {
    return (
      <div className="empty">
        <p>The agent service is not answering. The rest of the demo does not need it.</p>
        <button className="link" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }

  const live = new Map(turn?.agents.map((a) => [a.id, a]));
  const planning = turn?.phase === "planning";
  const writing = turn?.phase === "writing";

  return (
    <>
      <div className="list__head">Plan</div>
      <div className="agent">
        <span className="agent__dot" data-status={planning ? "running" : "idle"} />
        <span className="row__text">
          <span className="row__name">Planner</span>
          <span className="row__sub">
            {turn?.purpose && !planning
              ? `Read as: ${turn.purpose}`
              : "Picks the agents for the question."}
          </span>
        </span>
        <span className="row__when">{planning ? "planning" : ""}</span>
      </div>
      <div className="list__head">
        Agents <span className="list__count">{fleet.agents.length}</span>
      </div>
      {fleet.agents.map((agent) => {
        const run = live.get(agent.id);
        return (
          <div className="agent" key={agent.id}>
            <span className="agent__dot" data-status={run?.status ?? "idle"} />
            <span className="row__text">
              <span className="row__name">{agent.label}</span>
              <span className="row__sub">{agent.purpose}</span>
            </span>
            <span className="row__when">{run ? runNote(run) : ""}</span>
          </div>
        );
      })}
      <div className="list__head">Answer</div>
      <div className="agent">
        <span className="agent__dot" data-status={writing ? "running" : "idle"} />
        <span className="row__text">
          <span className="row__name">Writer</span>
          <span className="row__sub">Writes the answer. Adds no numbers.</span>
        </span>
        <span className="row__when">{writing ? "writing" : ""}</span>
      </div>
      {!fleet.model && (
        <p className="fleet__foot">No model key set: answers are the raw reports.</p>
      )}
    </>
  );
}

// Past conversations stay readable while the agent service is down.
export function FleetRail({
  fleet,
  turn,
  onRetry,
  ...conversations
}: Parameters<typeof Fleet>[0] & Parameters<typeof Conversations>[0]) {
  return (
    <>
      <Conversations {...conversations} />
      <Fleet fleet={fleet} turn={turn} onRetry={onRetry} />
    </>
  );
}
