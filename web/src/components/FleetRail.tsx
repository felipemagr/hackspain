import type { Conversation, FleetState } from "../lib/chat";

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
                    {chat.turns.length} {chat.turns.length === 1 ? "question" : "questions"}
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

// Only what the person needs to know about the service: whether it can answer.
function Service({ fleet, onRetry }: { fleet: FleetState; onRetry: () => void }) {
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
  return fleet.model ? null : (
    <p className="fleet__foot">No model key set: answers are the raw results.</p>
  );
}

// Past conversations stay readable while the agent service is down.
export function FleetRail({
  fleet,
  onRetry,
  ...conversations
}: Parameters<typeof Service>[0] & Parameters<typeof Conversations>[0]) {
  return (
    <>
      <Conversations {...conversations} />
      <Service fleet={fleet} onRetry={onRetry} />
    </>
  );
}
