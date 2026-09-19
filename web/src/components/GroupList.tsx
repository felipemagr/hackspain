import { fmtScore } from "../lib/format";
import { STATE_META, STATE_ORDER, toneColor } from "../lib/meta";
import type { Store } from "../lib/load";
import { Sparkline } from "./Sparkline";
import { TrendArrow } from "./TrendArrow";

interface GroupListProps {
  store: Store;
  month: string;
  selectedId: string;
  onSelect: (groupId: string) => void;
}

/** Every group at the selected month, bucketed by state, worst news first. */
export function GroupList({ store, month, selectedId, onSelect }: GroupListProps) {
  const rows = store.groups.map((g) => ({ group: g, score: store.scoreAt(g.group_id, month) }));
  const buckets = STATE_ORDER.map((state) => ({
    state,
    rows: rows
      .filter((r) => (r.score?.state ?? "not_enough_data") === state)
      .sort((a, b) => (b.score?.level ?? -1) - (a.score?.level ?? -1)),
  })).filter((b) => b.rows.length > 0);

  return (
    <div className="list">
      {buckets.map((bucket) => (
        <section key={bucket.state}>
          <h2 className="list__head">
            <span
              className="state__dot"
              style={{ background: toneColor(STATE_META[bucket.state].tone) }}
            />
            {STATE_META[bucket.state].label}
            <span className="list__count">{bucket.rows.length}</span>
          </h2>
          {bucket.rows.map(({ group, score }) => {
            const series = (store.scoresByGroup.get(group.group_id) ?? [])
              .filter((s) => s.month <= month)
              .map((s) => s.level);
            return (
              <button
                key={group.group_id}
                className={`row ${group.group_id === selectedId ? "is-selected" : ""}`}
                aria-current={group.group_id === selectedId}
                onClick={() => onSelect(group.group_id)}
              >
                <span className="row__text">
                  <span className="row__name">{group.name}</span>
                  <span className="row__sub">{group.sector}</span>
                </span>
                <Sparkline series={series} total={store.months.length} />
                <span className="row__level">{fmtScore(score?.level)}</span>
                <TrendArrow trend={score?.trend ?? null} />
              </button>
            );
          })}
        </section>
      ))}
    </div>
  );
}
