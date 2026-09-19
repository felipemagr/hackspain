import { fmtScore } from "../lib/format";
import { DEFAULT_VIEW, type Direction, type ListView, type SortKey } from "../lib/listView";
import { STATE_META, STATE_ORDER, thinHistory, toneColor } from "../lib/meta";
import type { Store } from "../lib/load";
import type { GroupRow, ScoreRow, State } from "../lib/types";
import { LowDataMark } from "./LowData";
import { Check, Menu } from "./Menu";
import { Sparkline } from "./Sparkline";
import { Star } from "./Star";
import { TrendArrow } from "./TrendArrow";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "state", label: "By state" },
  { key: "level_desc", label: "Highest score" },
  { key: "level_asc", label: "Lowest score" },
  { key: "trend_desc", label: "Rising fastest" },
  { key: "trend_asc", label: "Falling fastest" },
  { key: "name", label: "Name" },
];

const DIRECTIONS: { key: Direction; label: string }[] = [
  { key: "rising", label: "Going up" },
  { key: "flat", label: "Flat" },
  { key: "falling", label: "Going down" },
];

// Same threshold as TrendArrow, so the filter agrees with the arrow on the row.
function direction(trend: number | null | undefined): Direction | null {
  if (trend == null) return null;
  return trend > 0.15 ? "rising" : trend < -0.15 ? "falling" : "flat";
}

interface Row {
  group: GroupRow;
  score: ScoreRow | undefined;
}

const stateOf = (r: Row): State => r.score?.state ?? "not_enough_data";

// Groups without the sorted figure go last in either direction.
function by(value: (r: Row) => number | null | undefined, sign: 1 | -1) {
  return (a: Row, b: Row) => {
    const va = value(a);
    const vb = value(b);
    if (va == null || vb == null) return va == null ? (vb == null ? 0 : 1) : -1;
    return sign * (va - vb);
  };
}

const COMPARE: Record<Exclude<SortKey, "state">, (a: Row, b: Row) => number> = {
  level_desc: by((r) => r.score?.level, -1),
  level_asc: by((r) => r.score?.level, 1),
  trend_desc: by((r) => r.score?.trend, -1),
  trend_asc: by((r) => r.score?.trend, 1),
  name: (a, b) => a.group.name.localeCompare(b.group.name),
};

function toggle<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

interface GroupListProps {
  store: Store;
  month: string;
  selectedId: string;
  onSelect: (groupId: string) => void;
  view: ListView;
  onView: (view: ListView) => void;
  favorites: Set<string>;
  onFavorite: (groupId: string) => void;
}

/** Every group at the selected month: bucketed by state, worst news first, or filtered and sorted. */
export function GroupList({
  store,
  month,
  selectedId,
  onSelect,
  view,
  onView,
  favorites,
  onFavorite,
}: GroupListProps) {
  const all: Row[] = store.groups.map((g) => ({ group: g, score: store.scoreAt(g.group_id, month) }));
  const rows = all.filter(
    (r) =>
      (view.states.length === 0 || view.states.includes(stateOf(r))) &&
      (view.directions.length === 0 || view.directions.includes(direction(r.score?.trend)!)) &&
      (!view.favoritesOnly || favorites.has(r.group.group_id)),
  );
  const present = STATE_ORDER.filter((s) => all.some((r) => stateOf(r) === s));
  const nFilters = view.states.length + view.directions.length;
  const filtered = nFilters > 0 || view.favoritesOnly;

  const sections =
    view.sort === "state"
      ? STATE_ORDER.map((state) => ({
          state: state as State | null,
          rows: rows.filter((r) => stateOf(r) === state).sort(COMPARE.level_desc),
        })).filter((b) => b.rows.length > 0)
      : [{ state: null, rows: [...rows].sort(COMPARE[view.sort]) }];

  return (
    <div className="list">
      <div className="list__tools">
        <Menu label={nFilters > 0 ? `Filter · ${nFilters}` : "Filter"} ariaLabel="Filter groups">
          <p className="menu__title">State</p>
          {present.map((s) => (
            <Check
              key={s}
              checked={view.states.includes(s)}
              onChange={() => onView({ ...view, states: toggle(view.states, s) })}
            >
              <span className="state__dot" style={{ background: toneColor(STATE_META[s].tone) }} />
              {STATE_META[s].label}
              <span className="check__count">{all.filter((r) => stateOf(r) === s).length}</span>
            </Check>
          ))}
          <p className="menu__title">Trend</p>
          {DIRECTIONS.map((d) => (
            <Check
              key={d.key}
              checked={view.directions.includes(d.key)}
              onChange={() => onView({ ...view, directions: toggle(view.directions, d.key) })}
            >
              {d.label}
              <span className="check__count">
                {all.filter((r) => direction(r.score?.trend) === d.key).length}
              </span>
            </Check>
          ))}
        </Menu>
        <select
          value={view.sort}
          onChange={(e) => onView({ ...view, sort: e.target.value as SortKey })}
          aria-label="Sort groups"
        >
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
        <button
          className="list__favs"
          aria-pressed={view.favoritesOnly}
          onClick={() => onView({ ...view, favoritesOnly: !view.favoritesOnly })}
        >
          <Star filled={view.favoritesOnly} />
          Favorites <span>{favorites.size}</span>
        </button>
      </div>

      {filtered && (
        <p className="list__status">
          {rows.length} of {all.length} groups
          <button className="link" onClick={() => onView({ ...DEFAULT_VIEW, sort: view.sort })}>
            Clear filters
          </button>
        </p>
      )}

      {rows.length === 0 && (
        <p className="empty">
          {view.favoritesOnly && favorites.size === 0
            ? "No favorites yet. Star a group to keep it close."
            : "No group matches these filters this month."}
        </p>
      )}

      {sections.map((section) => (
        <section key={section.state ?? "all"}>
          {section.state && (
            <h2 className="list__head">
              <span
                className="state__dot"
                style={{ background: toneColor(STATE_META[section.state].tone) }}
              />
              {STATE_META[section.state].label}
              <span className="list__count">{section.rows.length}</span>
            </h2>
          )}
          {section.rows.map(({ group, score }) => {
            const series = (store.scoresByGroup.get(group.group_id) ?? [])
              .filter((s) => s.month <= month)
              .map((s) => s.level);
            const state = score?.state ?? "not_enough_data";
            const months = score?.months_observed;
            const thin = thinHistory(months);
            const favorite = favorites.has(group.group_id);
            return (
              <div
                key={group.group_id}
                className={`row-wrap ${group.group_id === selectedId ? "is-selected" : ""}`}
              >
                <button
                  className={`row__star ${favorite ? "is-on" : ""}`}
                  aria-pressed={favorite}
                  aria-label={`${favorite ? "Remove" : "Add"} ${group.name} ${favorite ? "from" : "to"} favorites`}
                  onClick={() => onFavorite(group.group_id)}
                >
                  <Star filled={favorite} />
                </button>
                <button
                  className="row"
                  aria-current={group.group_id === selectedId}
                  onClick={() => onSelect(group.group_id)}
                >
                  <span className="row__text">
                    <span className="row__name">{group.name}</span>
                    <span className="row__sub">
                      {!section.state && (
                        <>
                          <span
                            className="state__dot"
                            style={{ background: toneColor(STATE_META[state].tone) }}
                          />
                          {STATE_META[state].label}
                          {" · "}
                        </>
                      )}
                      {group.sector ??
                        [group.country, `${group.n_companies} ${group.n_companies === 1 ? "company" : "companies"}`]
                          .filter(Boolean)
                          .join(" · ")}
                    </span>
                  </span>
                  <Sparkline series={series} total={store.months.length} />
                  <span className={`row__level ${thin ? "is-thin" : ""}`}>{fmtScore(score?.level)}</span>
                  {/* Under six months there is no trend to draw, so the cell says why instead. */}
                  {thin ? (
                    <span className="trend row__caveat">
                      <LowDataMark months={months} />
                    </span>
                  ) : (
                    <TrendArrow trend={score?.trend ?? null} />
                  )}
                </button>
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}
