import { useCallback, useEffect, useState } from "react";
import { AlertList } from "./components/AlertList";
import { Chat } from "./components/Chat";
import { FleetRail } from "./components/FleetRail";
import { GroupDetail } from "./components/GroupDetail";
import { GroupList } from "./components/GroupList";
import { useChat } from "./lib/chat";
import { monthLong } from "./lib/format";
import { loadStore, type Store } from "./lib/load";

// Deep links for the demo: ?group=DEMO_002&compare=DEMO_001&month=2026-08-01&tab=alerts|agents
const params = new URLSearchParams(window.location.search);

export default function App() {
  const [store, setStore] = useState<Store | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [month, setMonth] = useState("");
  const [selectedId, setSelectedId] = useState(params.get("group") ?? "DEMO_001");
  const [compareId, setCompareId] = useState(params.get("compare") ?? "");
  const askedTab = params.get("tab");
  const [tab, setTab] = useState<"groups" | "alerts" | "agents">(
    askedTab === "alerts" || askedTab === "agents" ? askedTab : "groups",
  );
  const chat = useChat();

  useEffect(() => {
    loadStore()
      .then((s) => {
        setStore(s);
        const asked = params.get("month");
        setMonth(asked && s.months.includes(asked) ? asked : s.months[s.months.length - 1]);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const stepMonth = useCallback(
    (dir: -1 | 1) => {
      if (!store) return;
      const next = store.months[store.months.indexOf(month) + dir];
      if (next) setMonth(next);
    },
    [store, month],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLSelectElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "ArrowLeft") stepMonth(-1);
      if (e.key === "ArrowRight") stepMonth(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [stepMonth]);

  if (error) {
    return (
      <p className="splash">
        Could not load the data ({error}). Run <code>make web-data</code> and reload.
      </p>
    );
  }
  if (!store) return <p className="splash">Loading</p>;

  const select = (groupId: string) => {
    setSelectedId(groupId);
    if (groupId === compareId) setCompareId("");
  };
  const i = store.months.indexOf(month);
  const alertCount = store.alerts.filter((a) => a.month <= month).length;

  return (
    <div className="app">
      <aside className="side">
        <div className="side__top">
          <span className="brand">X Ray</span>
          <div className="stepper">
            <button onClick={() => stepMonth(-1)} disabled={i <= 0} aria-label="Previous month">
              <svg width="7" height="12" viewBox="0 0 7 12" aria-hidden>
                <path d="M6 1 L1 6 L6 11" />
              </svg>
            </button>
            <span aria-live="polite">{monthLong(month)}</span>
            <button
              onClick={() => stepMonth(1)}
              disabled={i >= store.months.length - 1}
              aria-label="Next month"
            >
              <svg width="7" height="12" viewBox="0 0 7 12" aria-hidden>
                <path d="M1 1 L6 6 L1 11" />
              </svg>
            </button>
          </div>
        </div>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "groups"} onClick={() => setTab("groups")}>
            Groups <span>{store.groups.length}</span>
          </button>
          <button role="tab" aria-selected={tab === "alerts"} onClick={() => setTab("alerts")}>
            Alerts <span>{alertCount}</span>
          </button>
          <button role="tab" aria-selected={tab === "agents"} onClick={() => setTab("agents")}>
            Agents
          </button>
        </div>
        <div className="side__scroll">
          {tab === "agents" ? (
            <FleetRail
              fleet={chat.fleet}
              turn={chat.turns[chat.turns.length - 1]}
              onRetry={chat.wake}
            />
          ) : tab === "groups" ? (
            <GroupList store={store} month={month} selectedId={selectedId} onSelect={select} />
          ) : (
            <AlertList
              store={store}
              month={month}
              selectedId={selectedId}
              onSelect={(groupId, m) => {
                select(groupId);
                setMonth(m);
              }}
            />
          )}
        </div>
      </aside>
      <main className="main">
        {tab === "agents" ? (
          <Chat
            store={store}
            groupId={selectedId}
            month={month}
            fleet={chat.fleet}
            turns={chat.turns}
            busy={chat.busy}
            onAsk={(question) =>
              chat.ask(question, selectedId, store.groupById.get(selectedId)?.name ?? "", month)
            }
            onStop={chat.stop}
            onGroup={select}
          />
        ) : (
          <GroupDetail
            store={store}
            groupId={selectedId}
            compareId={compareId}
            month={month}
            onMonth={setMonth}
            onCompare={setCompareId}
          />
        )}
      </main>
    </div>
  );
}
