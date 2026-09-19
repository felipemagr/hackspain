import { useState } from "react";
import {
  fmtEur,
  fmtMonthsOfData,
  fmtScore,
  fmtSigned,
  monthLong,
} from "../lib/format";
import {
  MACRO_BY_ID,
  MACRO_PILLARS,
  MACRO_SERIES,
  defaultMacro,
} from "../lib/macro";
import type { MacroSeries } from "../lib/macro";
import { PILLAR_LABEL, thinHistory } from "../lib/meta";
import type { Store } from "../lib/load";
import type { ScoreRow } from "../lib/types";
import { useTween } from "../lib/useTween";
import { LowDataNote } from "./LowData";
import { Menu } from "./Menu";
import { OwnHistory } from "./OwnHistory";
import { Pillars } from "./Pillars";
import { PromptPay } from "./PromptPay";
import { Star } from "./Star";
import { StateTag } from "./StateTag";
import { TrajectoryChart } from "./TrajectoryChart";
import { WhatIf } from "./WhatIf";

/** Where a market's level comes from and how it is built. Opens on hover or keyboard focus. */
function MacroInfo({ macro }: { macro: MacroSeries }) {
  return (
    <span className="info">
      <button
        className="info__mark"
        aria-label="How market health is built"
        aria-describedby="macro-info"
      >
        i
      </button>
      <span className="info__pop" id="macro-info" role="tooltip">
        <strong className="info__title">How market health is built</strong>
        <span className="info__rows">
          {MACRO_PILLARS.map((p) => (
            <span className="info__row" key={p.name}>
              <span className="info__name">{p.name}</span>
              <span className="info__weight">{p.weight}</span>
              <span className="info__what">{p.what}</span>
            </span>
          ))}
        </span>
        <span className="info__note">
          Each pillar is 0-100 on fixed anchors, then a weighted mean.
          Conditions, not distance to distress. Built from {macro.source}, to{" "}
          {macro.through}.
        </span>
      </span>
    </span>
  );
}

interface GroupDetailProps {
  store: Store;
  groupId: string;
  month: string;
  onMonth: (month: string) => void;
  favorite: boolean;
  onFavorite: () => void;
  syncing: boolean;
  onSync: () => void;
}

const clock = (d: Date) =>
  d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const stamp = (d: Date) =>
  `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}, ${clock(d)}`;

function heading(score: ScoreRow): string {
  const parts: string[] = [];
  if (score.trend != null && Math.abs(score.trend) > 0.15) {
    parts.push(
      `${score.trend > 0 ? "Gaining" : "Losing"} ${Math.abs(score.trend).toFixed(1)} points a month`,
      `heading to ${score.compound.toFixed(0)}`,
    );
  } else if (score.trend != null) {
    parts.push("Holding steady");
  }
  return parts.join(", ");
}

export function GroupDetail({
  store,
  groupId,
  month,
  onMonth,
  favorite,
  onFavorite,
  syncing,
  onSync,
}: GroupDetailProps) {
  const group = store.groupById.get(groupId);
  const history = store.scoresByGroup.get(groupId) ?? [];
  const score = store.scoreAt(groupId, month);
  const idx = history.findIndex((s) => s.month === month);
  const prevLevel = idx > 0 ? history[idx - 1].level : null;
  const since = score && prevLevel != null ? score.level - prevLevel : null;
  const way =
    since == null || Math.abs(since) < 0.05
      ? ""
      : since > 0
        ? "is-up"
        : "is-down";
  const line = score ? heading(score) : "";
  const thin = thinHistory(score?.months_observed);
  const [level] = useTween([score?.level ?? NaN]);
  const [macroId, setMacroId] = useState(() =>
    defaultMacro(group?.country ?? null),
  );
  if (!group) return null;

  const drivers = store.driversAt(groupId, month);
  const offer = store.offerAt(groupId, month);
  const actions = [...(store.actionsByGroup.get(groupId) ?? [])].sort(
    (a, b) => a.rank - b.rank,
  );
  const companies = store.companiesByGroup.get(groupId) ?? [];
  const macro = MACRO_BY_ID.get(macroId) ?? null;

  return (
    <article className="detail" aria-label={group.name}>
      <header className="detail__head">
        <div>
          <h1>
            {group.name}
            <button
              className={`fav ${favorite ? "is-on" : ""}`}
              aria-pressed={favorite}
              aria-label={
                favorite ? "Remove from favorites" : "Add to favorites"
              }
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
            <span
              className={`score__level ${way} ${thin ? "is-thin" : ""}`}
              key={`${groupId}-${month}`}
            >
              {Number.isFinite(level) ? level.toFixed(0) : "-"}
            </span>
            <div>
              <StateTag state={score.state} />
              <p className="score__line">
                {line}
                {since != null && (
                  <>
                    {line && ", "}
                    <span className={`score__since ${way}`}>
                      {fmtSigned(since)}
                    </span>{" "}
                    since last month
                  </>
                )}
              </p>
              {thin && <LowDataNote months={score.months_observed} />}
            </div>
          </div>
        )}
      </header>

      <section>
        <div className="section-head">
          <h2>Health score, {monthLong(month)}</h2>
          <div className="compare">
            {macro && (
              <span className="legend">
                <span className="legend__item">
                  <span className="key" style={{ background: "var(--ink)" }} />
                  {group.name}
                </span>
                <span className="legend__item">
                  <span
                    className="key key--dashed"
                    style={{ background: "var(--series-3)" }}
                  />
                  {macro.name}
                </span>
              </span>
            )}
            <Menu
              label={macro ? `Against ${macro.name}` : "Against the market..."}
              ariaLabel="Lay a market's health behind the score"
              align="right"
            >
              <div className="menu__scroll">
                {MACRO_SERIES.map((series) => (
                  <button
                    key={series.id}
                    className={`pick ${series.id === macroId ? "is-on" : ""}`}
                    aria-pressed={series.id === macroId}
                    onClick={() =>
                      setMacroId(series.id === macroId ? "" : series.id)
                    }
                  >
                    {series.name}
                    {series.country && (
                      <span className="pick__tag">{series.country}</span>
                    )}
                  </button>
                ))}
              </div>
              <p className="menu__note menu__foot">
                Published figures, aligned to the score's months.
                {macro && (
                  <button className="link" onClick={() => setMacroId("")}>
                    Clear
                  </button>
                )}
              </p>
            </Menu>
            {macro && <MacroInfo macro={macro} />}
          </div>
        </div>
        <TrajectoryChart
          months={store.months}
          month={month}
          onMonth={onMonth}
          primary={{ name: group.name, history }}
          macro={macro}
          alerts={store.alerts.filter((a) => a.group_id === groupId)}
        />
      </section>

      {!score ? (
        <p className="empty">
          {group.name} has no score in {monthLong(month)}. Pick a later month on
          the chart.
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
                {companies.map((c) => {
                  const months = c.months_observed;
                  const short = thinHistory(months);
                  return (
                    <div className="company" key={c.company_id}>
                      <span className="company__name">
                        {c.name}
                        {c.is_weakest && (
                          <span className="company__flag">drags the group</span>
                        )}
                        {short && (
                          <span className="company__note">
                            {fmtMonthsOfData(months)}
                          </span>
                        )}
                      </span>
                      <span className="company__share">
                        {((c.inflow_share ?? 0) * 100).toFixed(0)}%
                      </span>
                      <span
                        className={`company__level ${short ? "is-thin" : ""}`}
                      >
                        {fmtScore(c.level)}
                      </span>
                    </div>
                  );
                })}
              </>
            )}
          </section>

          <section>
            <div className="section-head">
              <h2>Next moves</h2>
              <span className="hint">expected gain</span>
            </div>
            {actions.length === 0 && (
              <p className="empty">No moves computed for this group.</p>
            )}
            <ol className="moves">
              {actions.map((a) => (
                <li key={a.rank}>
                  <div>
                    <span className="moves__pillar">
                      {PILLAR_LABEL[a.pillar] ?? a.pillar}
                    </span>
                    <p>{a.action}</p>
                  </div>
                  <span className="moves__gain">
                    +{a.expected_level_gain.toFixed(1)}
                  </span>
                </li>
              ))}
            </ol>

            <div className="section-head section-head--spaced">
              <h2>Working-capital line</h2>
              <span className="hint">repriced monthly</span>
            </div>
            {offer?.eligible ? (
              <p className="offer">
                <strong>{fmtEur(offer.limit_eur)}</strong> at{" "}
                {offer.apr == null ? "-" : (offer.apr * 100).toFixed(1)}% APR
                {offer.limit_change_eur != null &&
                  offer.limit_change_eur !== 0 && (
                    <span
                      className={
                        offer.limit_change_eur > 0 ? "is-up" : "is-down"
                      }
                    >
                      {offer.limit_change_eur > 0 ? "+" : "-"}
                      {fmtEur(Math.abs(offer.limit_change_eur))} this month
                    </span>
                  )}
              </p>
            ) : (
              <p className="empty">
                No line this month: the score is too low or too young.
              </p>
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
