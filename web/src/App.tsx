import { useEffect, useState } from "react";
import { AlertList } from "./components/AlertList";
import { Chat } from "./components/Chat";
import { CurrencyToggle } from "./components/CurrencyToggle";
import { FleetRail } from "./components/FleetRail";
import { GroupDetail } from "./components/GroupDetail";
import { GroupList } from "./components/GroupList";
import { useChat } from "./lib/chat";
import { useDisplayCurrency } from "./lib/currency";
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
  // A sync that fails keeps the data already on screen.
  const sync = () => {
    setSyncing(true);
    Promise.all([loadStore(), new Promise((done) => setTimeout(done, 700))])
      .then(([s]) => setStore(s))
      .catch((e: Error) => console.warn("sync failed", e))
      .finally(() => setSyncing(false));
  };

  useEffect(() => {
    loadStore()
      .then((s) => {
        setStore(s);
        const asked = params.get("month");
        setMonth(asked && s.months.includes(asked) ? asked : s.months[s.months.length - 1]);
        // Open on the group worth opening on: a deep link wins; then, when the portfolio holds
        // named groups (the synthetic demo beside the challenge ids), the named one that is
        // bending while still looking fine, the Velasco of that portfolio; then the default id.
        setSelectedId((id) => {
          if (params.get("group") && s.groupById.has(id)) return id;
          const velasco = (pool: typeof s.groups) =>
            [...pool]
              .filter((g) => s.latestMonth(g.group_id)?.state === "bending")
              .sort((a, b) => (s.latestMonth(b.group_id)?.level ?? 0) - (s.latestMonth(a.group_id)?.level ?? 0))[0] ??
            pool[0];
          const named = s.groups.filter((g) => g.name !== g.group_id);
          if (named.length) return velasco(named).group_id;
          return s.groupById.has(id) ? id : (velasco(s.groups)?.group_id ?? id);
        });
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
  const alertCount = store.alerts.filter(
    (a) => a.month <= month && !cleared.has(alertKey(a)),
  ).length;

  return (
    <div className="app">
      <aside className="side">
        <div className="side__top">
          <span className="brand">
            <svg className="brand__embat" height="20" viewBox="0 0 96 20" role="img" aria-label="Embat">
              <g transform="translate(-2.9 -3.3) scale(1.11)">
                <defs>
                  <linearGradient id="brand-inside" x1="9.4" y1="17.2" x2="13.1" y2="6.8" gradientUnits="userSpaceOnUse">
                    <stop offset="0" stopColor="#415de6" />
                    <stop offset="1" stopColor="#c357ec" />
                  </linearGradient>
                </defs>
                <path fill="currentColor" d="M14 3l6 9-6 9zM4 6.3 14 3 7.6 12zM4 17.7 7.6 12 14 21z" />
                <path fill="url(#brand-inside)" d="M9.4 12l3.7-5.2v10.4z" />
              </g>
              <path fill="currentColor" fillRule="evenodd" clipRule="evenodd" d="M29.866 2.352h10.687v2.337h-7.946v3.865h7.204v2.337h-7.204v4.396h8.027v2.337H29.866zm29.77 7.935v7.335h-2.68v-6.67c0-1.39-.745-2.298-1.994-2.298-1.633 0-2.62 1.492-2.62 4.07v4.897h-2.68v-6.67c0-1.39-.726-2.297-1.996-2.297-1.612 0-2.599 1.471-2.599 4.07v4.897h-2.68V6.458h2.68V7.97c.524-.886 1.814-1.672 3.366-1.672s2.861.766 3.426 2.076c.967-1.41 2.418-2.076 3.869-2.076 2.277 0 3.909 1.592 3.909 3.99Zm4.979 5.904v1.429h-2.68V3.275l2.68-.884v5.495c.685-.967 2.035-1.591 3.526-1.591 3.164 0 5.34 2.236 5.34 5.743s-2.176 5.744-5.38 5.744c-1.471 0-2.8-.624-3.486-1.59Zm6.167-4.154c0 2.056-1.27 3.446-3.084 3.446s-3.083-1.391-3.083-3.447 1.27-3.465 3.083-3.465 3.084 1.41 3.084 3.466m4.127 2.524c0-2.075 1.45-3.324 4.736-3.667l2.499-.282v-.221c0-1.27-.927-2.015-2.277-2.015s-2.237.725-2.378 1.974h-2.58c.283-2.337 2.278-4.05 4.958-4.05 2.881 0 4.937 1.572 4.937 4.393v6.932h-2.66v-1.471c-.523.988-1.854 1.633-3.365 1.633-2.399 0-3.87-1.27-3.87-3.225Zm4.333 1.17c1.713 0 2.902-1.17 2.902-3.144l-2.459.261c-1.431.161-2.096.746-2.096 1.612 0 .745.666 1.27 1.653 1.27Zm8.364-7.091v5.46c0 2.378 1.612 3.668 3.728 3.668.564 0 1.028-.102 1.491-.263V15.25c-.342.12-.785.221-1.128.221-.846 0-1.41-.564-1.41-1.612V8.64h2.398V6.463h-2.399V3.084l-2.68.884v2.495h-1.612V8.64z" />
            </svg>
            <span className="brand__rule" aria-hidden />
            Lighthouse
          </span>
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
