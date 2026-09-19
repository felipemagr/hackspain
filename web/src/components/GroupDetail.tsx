import { useState } from "react";
import { fmtEur, fmtScore, fmtSigned, monthLong } from "../lib/format";
import { PILLAR_LABEL, SERIES_COLORS } from "../lib/meta";
import type { Store } from "../lib/load";
import type { ScoreRow } from "../lib/types";
import { useTween } from "../lib/useTween";
import { Check, Menu } from "./Menu";
import { OwnHistory } from "./OwnHistory";
import { Pillars } from "./Pillars";
import { PromptPay } from "./PromptPay";
import { Star } from "./Star";
import { StateTag } from "./StateTag";
import { TrajectoryChart } from "./TrajectoryChart";
import { WhatIf } from "./WhatIf";

interface GroupDetailProps {
  store: Store;
  groupId: string;
  /** One group id per comparison slot, "" when free. */
  compareSlots: string[];
  month: string;
  onMonth: (month: string) => void;
  /** Adds the group to a free slot, or removes it. */
  onCompare: (groupId: string) => void;
  onClearCompare: () => void;
  favorite: boolean;
  onFavorite: () => void;
  syncing: boolean;
  onSync: () => void;
}

const clock = (d: Date) => d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const stamp = (d: Date) =>
  `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}, ${clock(d)}`;

function heading(score: ScoreRow, prevLevel: number | null): string {
  const parts: string[] = [];
  if (score.trend != null && Math.abs(score.trend) > 0.15) {
    parts.push(
      `${score.trend > 0 ? "Gaining" : "Losing"} ${Math.abs(score.trend).toFixed(1)} points a month`,
      `heading to ${score.compound.toFixed(0)}`,
    );
  } else if (score.trend != null) {
    parts.push("Holding steady");
  }
  if (prevLevel != null) parts.push(`${fmtSigned(score.level - prevLevel)} since last month`);
  return parts.join(", ");
}

export function GroupDetail({
  store,
  groupId,
  compareSlots,
  month,
  onMonth,
  onCompare,
  onClearCompare,
  favorite,
  onFavorite,
  syncing,
  onSync,
}: GroupDetailProps) {
  const [query, setQuery] = useState("");
  const group = store.groupById.get(groupId);
  const history = store.scoresByGroup.get(groupId) ?? [];
  const score = store.scoreAt(groupId, month);
  const idx = history.findIndex((s) => s.month === month);
  const prevLevel = idx > 0 ? history[idx - 1].level : null;
  const [level] = useTween([score?.level ?? NaN]);
  if (!group) return null;

  const drivers = store.driversAt(groupId, month);
  const offer = store.offerAt(groupId, month);
  const actions = [...(store.actionsByGroup.get(groupId) ?? [])].sort((a, b) => a.rank - b.rank);
  const companies = store.companiesByGroup.get(groupId) ?? [];
  const compare = compareSlots.map((id) => store.groupById.get(id) ?? null);
  const nCompare = compare.filter(Boolean).length;
  const full = nCompare === compareSlots.length;
  const q = query.trim().toLowerCase();
  const candidates = store.groups.filter(
    (g) => g.group_id !== groupId && (!q || g.name.toLowerCase().includes(q)),
  );

  return (
    <article className="detail" aria-label={group.name}>
      <header className="detail__head">
        <div>
          <h1>
            {group.name}
            <button
              className={`fav ${favorite ? "is-on" : ""}`}
              aria-pressed={favorite}
              aria-label={favorite ? "Remove from favorites" : "Add to favorites"}
              onClick={onFavorite}
            >
              <Star filled={favorite} />
            </button>
            <button
              className="fav"
              onClick={onSync}
              disabled={syncing}
              aria-label="Sync the data"
              title={`Synced ${clock(store.syncedAt)}`}
            >
              <svg
                className={syncing ? "sync is-spinning" : "sync"}
                width="15"
                height="15"
                viewBox="0 0 14 14"
                aria-hidden
              >
                <path d="M12 7a5 5 0 1 1-1.6-3.7M12 1.5V4H9.5" />
              </svg>
            </button>
          </h1>
          <p className="detail__meta">
            {[
              group.sector,
              group.country,
              `${group.n_companies} ${group.n_companies === 1 ? "company" : "companies"}`,
              `${fmtEur(group.annual_revenue_eur)} revenue`,
              store.updatedAt && `updated ${stamp(store.updatedAt)}`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        {score && (
          <div className="score">
            <span className="score__level">{Number.isFinite(level) ? level.toFixed(0) : "-"}</span>
            <div>
              <StateTag state={score.state} />
              <p className="score__line">{heading(score, prevLevel)}</p>
            </div>
          </div>
        )}
      </header>

      <section>
        <div className="section-head">
          <h2>Health score, {monthLong(month)}</h2>
          <div className="compare">
            {nCompare > 0 && (
              <span className="legend">
                <span className="legend__item">
                  <span className="key" style={{ background: "var(--ink)" }} />
                  {group.name}
                </span>
                {compare.map(
                  (c, k) =>
                    c && (
                      <button
                        key={c.group_id}
                        className="legend__item legend__item--remove"
                        aria-label={`Stop comparing with ${c.name}`}
                        onClick={() => onCompare(c.group_id)}
                      >
                        <span className="key" style={{ background: SERIES_COLORS[k] }} />
                        {c.name}
                        <svg width="8" height="8" viewBox="0 0 10 10" aria-hidden>
                          <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" />
                        </svg>
                      </button>
                    ),
                )}
              </span>
            )}
            <Menu
              label={nCompare > 0 ? `Compare · ${nCompare}` : "Compare with..."}
              ariaLabel="Compare with other groups"
              align="right"
            >
              <input
                className="menu__search"
                type="search"
                placeholder="Find a group"
                aria-label="Find a group"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoFocus
              />
              <div className="menu__scroll">
                {candidates.map((g) => {
                  const on = compareSlots.includes(g.group_id);
                  return (
                    <Check
                      key={g.group_id}
                      checked={on}
                      disabled={!on && full}
                      onChange={() => onCompare(g.group_id)}
                    >
                      {g.name}
                    </Check>
                  );
                })}
                {candidates.length === 0 && <p className="menu__note">No group by that name.</p>}
              </div>
              <p className="menu__note menu__foot">
                {full ? `Up to ${compareSlots.length} at a time` : `${nCompare} of ${compareSlots.length} selected`}
                {nCompare > 0 && (
                  <button className="link" onClick={onClearCompare}>
                    Clear
                  </button>
                )}
              </p>
            </Menu>
          </div>
        </div>
        <TrajectoryChart
          months={store.months}
          month={month}
          onMonth={onMonth}
          primary={{ name: group.name, history }}
          compare={compare.map(
            (c) => c && { name: c.name, history: store.scoresByGroup.get(c.group_id) ?? [] },
          )}
          alerts={store.alerts.filter((a) => a.group_id === groupId)}
        />
      </section>

      {!score ? (
        <p className="empty">
          {group.name} has no score in {monthLong(month)}. Pick a later month on the chart.
        </p>
      ) : (
        <div className="columns">
          <section>
            <div className="section-head">
              <h2>The five pillars</h2>
              <span className="hint">what each moved this month</span>
            </div>
            <Pillars score={score} drivers={drivers} />
            {companies.length > 1 && (
              <>
                <div className="section-head section-head--spaced">
                  <h2>Companies in the group</h2>
                  <span className="hint">share of inflow</span>
                </div>
                {companies.map((c) => (
                  <div className="company" key={c.company_id}>
                    <span className="company__name">
                      {c.name}
                      {c.is_weakest && <span className="company__flag">drags the group</span>}
                    </span>
                    <span className="company__share">{((c.inflow_share ?? 0) * 100).toFixed(0)}%</span>
                    <span className="company__level">{fmtScore(c.level)}</span>
                  </div>
                ))}
              </>
            )}
          </section>

          <section>
            <div className="section-head">
              <h2>Next moves</h2>
              <span className="hint">expected gain</span>
            </div>
            {actions.length === 0 && <p className="empty">No moves computed for this group.</p>}
            <ol className="moves">
              {actions.map((a) => (
                <li key={a.rank}>
                  <div>
                    <span className="moves__pillar">{PILLAR_LABEL[a.pillar] ?? a.pillar}</span>
                    <p>{a.action}</p>
                  </div>
                  <span className="moves__gain">+{a.expected_level_gain.toFixed(1)}</span>
                </li>
              ))}
            </ol>

            <div className="section-head section-head--spaced">
              <h2>Working-capital line</h2>
              <span className="hint">repriced monthly</span>
            </div>
            {offer?.eligible ? (
              <p className="offer">
                <strong>{fmtEur(offer.limit_eur)}</strong> at {offer.apr == null ? "-" : (offer.apr * 100).toFixed(1)}% APR
                {offer.limit_change_eur != null && offer.limit_change_eur !== 0 && (
                  <span className={offer.limit_change_eur > 0 ? "is-up" : "is-down"}>
                    {offer.limit_change_eur > 0 ? "+" : "-"}
                    {fmtEur(Math.abs(offer.limit_change_eur))} this month
                  </span>
                )}
              </p>
            ) : (
              <p className="empty">No line this month: the score is too low or too young.</p>
            )}
          </section>
        </div>
      )}

      {score && <OwnHistory history={history} month={month} />}
      {score && <WhatIf score={score} />}
      {score && <PromptPay store={store} groupId={groupId} month={month} />}
    </article>
  );
}
