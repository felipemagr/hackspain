import { fmtScore } from "../lib/format";
import { DEFAULT_VIEW, type ListView, type SortKey } from "../lib/listView";
import { BUCKETS, STATE_META, thinHistory, toneColor, type Bucket } from "../lib/meta";
import type { Store } from "../lib/load";
import type { GroupRow, ScoreRow, State } from "../lib/types";
import { LowDataMark } from "./LowData";
import { Sparkline } from "./Sparkline";
import { Star } from "./Star";
import { TrendArrow } from "./TrendArrow";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "priority", label: "Priority" },
  { key: "level_desc", label: "Highest score" },
  { key: "level_asc", label: "Lowest score" },
  { key: "trend_desc", label: "Rising fastest" },
  { key: "trend_asc", label: "Falling fastest" },
  { key: "name", label: "Name" },
];

interface Row {
  group: GroupRow;
  score: ScoreRow | undefined;
}

const stateOf = (r: Row): State => r.score?.state ?? "not_enough_data";
const bucketOf = (r: Row): Bucket => STATE_META[stateOf(r)].bucket;

// Groups without the sorted figure go last in either direction.
function by(value: (r: Row) => number | null | undefined, sign: 1 | -1) {
  return (a: Row, b: Row) => {
    const va = value(a);
    const vb = value(b);
    if (va == null || vb == null) return va == null ? (vb == null ? 0 : 1) : -1;
    return sign * (va - vb);
  };
}

const COMPARE: Record<Exclude<SortKey, "priority">, (a: Row, b: Row) => number> = {
  level_desc: by((r) => r.score?.level, -1),
  level_asc: by((r) => r.score?.level, 1),
  trend_desc: by((r) => r.score?.trend, -1),
  trend_asc: by((r) => r.score?.trend, 1),
  name: (a, b) => a.group.name.localeCompare(b.group.name),
};

// The order each section announces in its heading.
const BUCKET_SORT: Record<Bucket, (a: Row, b: Row) => number> = {
  attention: COMPARE.trend_asc,
  improving: COMPARE.trend_desc,
  steady: COMPARE.level_desc,
};

/** Every word must match: ">70" and "<40" test the score, anything else the group's text. */
function matches(r: Row, query: string): boolean {
  const text = [r.group.name, r.group.sector, r.group.country, r.group.group_id, STATE_META[stateOf(r)].label]
    .join(" ")
    .toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => {
      const bound = /^([<>])(\d+)$/.exec(word);
      if (!bound) return text.includes(word);
      const level = r.score?.level;
      if (level == null) return false;
      return bound[1] === ">" ? level > Number(bound[2]) : level < Number(bound[2]);
    });
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

/** Every group at the selected month: three sections, the ones that need a look first, or searched and sorted. */
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
  // The chips count what the search and the favorites toggle leave, so a count never promises rows that are not there.
  const found = all.filter(
    (r) => matches(r, view.query) && (!view.favoritesOnly || favorites.has(r.group.group_id)),
  );
  const rows = view.bucket === "all" ? found : found.filter((r) => bucketOf(r) === view.bucket);
  const filtered = rows.length < all.length;

  const sections =
    view.sort === "priority"
      ? BUCKETS.map((b) => ({
          bucket: b as (typeof BUCKETS)[number] | null,
          rows: rows.filter((r) => bucketOf(r) === b.key).sort(BUCKET_SORT[b.key]),
        })).filter((s) => s.rows.length > 0)
      : [{ bucket: null, rows: [...rows].sort(COMPARE[view.sort]) }];

  return (
    <div className="list">
      <div className="list__tools">
        <div className="list__search">
          <input
            type="search"
            value={view.query}
            onChange={(e) => onView({ ...view, query: e.target.value })}
            placeholder="Search name, sector, state, or >70"
            aria-label="Search groups"
          />
          <button
            className="list__favs"
            aria-pressed={view.favoritesOnly}
            aria-label={`Show only favorites (${favorites.size})`}
            title="Favorites only"
            onClick={() => onView({ ...view, favoritesOnly: !view.favoritesOnly })}
          >
            <Star filled={view.favoritesOnly} />
          </button>
        </div>
        <div className="list__chips" role="group" aria-label="Show">
          {[{ key: "all" as const, label: "All" }, ...BUCKETS].map((b) => (
            <button
              key={b.key}
              className="chip"
              aria-pressed={view.bucket === b.key}
              onClick={() => onView({ ...view, bucket: b.key })}
            >
              {b.key === "attention" ? "Attention" : b.label}
              <span>{b.key === "all" ? found.length : found.filter((r) => bucketOf(r) === b.key).length}</span>
            </button>
          ))}
        </div>
        <p className="list__status">
          {filtered ? `${rows.length} of ${all.length} groups` : `${all.length} groups`}
          {filtered && (
            <button className="link" onClick={() => onView({ ...DEFAULT_VIEW, sort: view.sort })}>
              Clear
            </button>
          )}
          <label className="list__sort">
            Sort
            <select value={view.sort} onChange={(e) => onView({ ...view, sort: e.target.value as SortKey })}>
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </p>
      </div>

      {rows.length === 0 && (
        <p className="empty">
          {view.favoritesOnly && favorites.size === 0
            ? "No favorites yet. Star a group to keep it close."
            : "No group matches this month."}
        </p>
      )}

      {sections.map((section) => (
        <section key={section.bucket?.key ?? "all"}>
          {section.bucket && (
            <h2 className="list__head">
              {section.bucket.label}
              <span className="list__count">{section.rows.length}</span>
              <span className="list__hint">{section.bucket.hint}</span>
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
                      <span
                        className="state__dot"
                        style={{ background: toneColor(STATE_META[state].tone) }}
                      />
                      {STATE_META[state].label}
                      {" · "}
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
