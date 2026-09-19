import { useCallback, useEffect, useState } from "react";
import { AlertList } from "./components/AlertList";
import { Chat } from "./components/Chat";
import { CurrencyToggle } from "./components/CurrencyToggle";
import { FleetRail } from "./components/FleetRail";
import { GroupDetail } from "./components/GroupDetail";
import { GroupList } from "./components/GroupList";
import { useChat } from "./lib/chat";
import { useDisplayCurrency } from "./lib/currency";
import { monthLong } from "./lib/format";
import { DEFAULT_VIEW } from "./lib/listView";
import { fetchVersion, loadStore, type Store } from "./lib/load";
import { alertKey } from "./lib/meta";
import { useStoredSet } from "./lib/useStoredSet";

// Deep links for the demo: ?group=GROUP_0220&compare=GROUP_0043,GROUP_0173&month=2026-08-01&tab=alerts|agents
const params = new URLSearchParams(window.location.search);
// The brief's Velasco: healthy at 94, bending alarm at 82, tier crossed four months later.
const DEFAULT_GROUP = "GROUP_0220";
// A comparison keeps its slot, and so its color, while others come and go. "" is a free slot.
const COMPARE_SLOTS = 4;
const askedCompare = (params.get("compare") ?? "").split(",").filter(Boolean);
// How often to ask the API whether a new build of the tables was published.
const POLL_MS = 3000;

export default function App() {
  const [store, setStore] = useState<Store | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [month, setMonth] = useState("");
  const [selectedId, setSelectedId] = useState(params.get("group") ?? DEFAULT_GROUP);
  const [compareSlots, setCompareSlots] = useState(() =>
    Array.from({ length: COMPARE_SLOTS }, (_, k) => askedCompare[k] ?? ""),
  );
  const [view, setView] = useState(DEFAULT_VIEW);
  const [favorites, updateFavorites] = useStoredSet("xray.favorites");
  const [cleared, updateCleared] = useStoredSet("xray.clearedAlerts");
  const askedTab = params.get("tab");
  const [tab, setTab] = useState<"groups" | "alerts" | "agents">(
    askedTab === "alerts" || askedTab === "agents" ? askedTab : "groups",
  );
  const [syncing, setSyncing] = useState(false);
  const chat = useChat();
  useDisplayCurrency(month);

  // Held for a moment so a sync that finds nothing new is still seen to have happened.
  const sync = () => {
    setSyncing(true);
    Promise.all([loadStore(), new Promise((done) => setTimeout(done, 700))])
      .then(([s]) => setStore(s))
      .catch((e: Error) => setError(e.message))
      .finally(() => setSyncing(false));
  };

  useEffect(() => {
    loadStore()
      .then((s) => {
        setStore(s);
        const asked = params.get("month");
        setMonth(asked && s.months.includes(asked) ? asked : s.months[s.months.length - 1]);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  // Live mode: the pipeline publishes a new build, the API's version changes, the tables are
  // fetched again. A viewer parked on the latest month follows the data forward; anyone
  // looking at an earlier month is left where they are.
  useEffect(() => {
    if (!store?.version) return;
    const current = store.version.build_id;
    let busy = false;
    const tick = async () => {
      if (busy) return;
      busy = true;
      try {
        const v = await fetchVersion();
        if (v && v.build_id !== current) {
          const next = await loadStore(v);
          setStore(next);
          setMonth((m) => {
            const last = store.months[store.months.length - 1];
            return m === last || !next.months.includes(m) ? next.months[next.months.length - 1] : m;
          });
        }
      } finally {
        busy = false;
      }
    };
    const id = window.setInterval(tick, POLL_MS);
    return () => window.clearInterval(id);
  }, [store]);

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
      if (
        e.target instanceof HTMLSelectElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLInputElement
      )
        return;
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
    setCompareSlots((slots) => slots.map((id) => (id === groupId ? "" : id)));
  };
  const toggleCompare = (groupId: string) =>
    setCompareSlots((slots) => {
      const next = [...slots];
      const at = next.indexOf(groupId);
      if (at >= 0) next[at] = "";
      else if (next.includes("")) next[next.indexOf("")] = groupId;
      return next;
    });
  const toggleFavorite = (groupId: string) =>
    updateFavorites((next) => {
      if (!next.delete(groupId)) next.add(groupId);
    });
  const i = store.months.indexOf(month);
  const alertCount = store.alerts.filter(
    (a) => a.month <= month && !cleared.has(alertKey(a)),
  ).length;

  return (
    <div className="app">
      <aside className="side">
        <div className="side__top">
          <span className="brand">
            <svg width="20" height="20" viewBox="2 2 20 20" aria-hidden>
              <defs>
                <linearGradient id="brand-inside" x1="9.4" y1="17.2" x2="13.1" y2="6.8" gradientUnits="userSpaceOnUse">
                  <stop offset="0" stopColor="#415de6" />
                  <stop offset="1" stopColor="#c357ec" />
                </linearGradient>
              </defs>
              <path fill="currentColor" d="M14 3l6 9-6 9zM4 6.3 14 3 7.6 12zM4 17.7 7.6 12 14 21z" />
              <path fill="url(#brand-inside)" d="M9.4 12l3.7-5.2v10.4z" />
            </svg>
            Lighthouse
          </span>
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
          <CurrencyToggle />
        </div>
        <div className="side__scroll">
          {tab === "agents" ? (
            <FleetRail
              fleet={chat.fleet}
              turn={chat.turns[chat.turns.length - 1]}
              onRetry={chat.wake}
              chats={chat.chats}
              activeId={chat.activeId}
              onOpen={(c) => {
                chat.open(c.id);
                select(c.turns[c.turns.length - 1].groupId);
              }}
              onNew={() => chat.open(null)}
              onRemove={chat.remove}
            />
          ) : tab === "groups" ? (
            <GroupList
              store={store}
              month={month}
              selectedId={selectedId}
              onSelect={select}
              view={view}
              onView={setView}
              favorites={favorites}
              onFavorite={toggleFavorite}
            />
          ) : (
            <AlertList
              store={store}
              month={month}
              selectedId={selectedId}
              onSelect={(groupId, m) => {
                select(groupId);
                setMonth(m);
              }}
              cleared={cleared}
              onClear={(keys) => updateCleared((next) => keys.forEach((k) => next.add(k)))}
              onRestore={() => updateCleared((next) => next.clear())}
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
            compareSlots={compareSlots}
            month={month}
            onMonth={setMonth}
            onCompare={toggleCompare}
            onClearCompare={() => setCompareSlots((slots) => slots.map(() => ""))}
            favorite={favorites.has(selectedId)}
            onFavorite={() => toggleFavorite(selectedId)}
            syncing={syncing}
            onSync={sync}
          />
        )}
      </main>
    </div>
  );
}
