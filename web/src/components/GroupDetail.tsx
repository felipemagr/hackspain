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
import { PILLARS, PILLAR_LABEL, SERIES_COLORS, thinHistory } from "../lib/meta";
import type { Store } from "../lib/load";
import type { ScoreRow } from "../lib/types";
import type { Weights } from "../lib/scoring";
import { useTween } from "../lib/useTween";
import { LowDataNote, PartialDataNote } from "./LowData";
import { Check, Menu } from "./Menu";
import { OwnHistory } from "./OwnHistory";
import { Pillars } from "./Pillars";
import { PromptPay } from "./PromptPay";
import { Star } from "./Star";
import { StateTag } from "./StateTag";
import { MACRO_COLORS, TrajectoryChart } from "./TrajectoryChart";
import { WhatIf } from "./WhatIf";
import { CHART_COLORS, DEFAULT_CHART, type ChartConfig } from "../lib/viewAgent";
import { scoreLabels } from "../lib/scoring";

/** Where a market's level comes from and how it is built. Opens on hover or keyboard focus. */
function MacroInfo({ macros }: { macros: MacroSeries[] }) {
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
          Conditions, not distance to distress. Built from{" "}
          {[...new Set(macros.map((m) => m.source))].join("; ")}, to{" "}
          {macros.map((m) => m.through).sort().slice(-1)[0]}.
        </span>
      </span>
    </span>
  );
}

interface GroupDetailProps {
  store: Store;
  groupId: string;
  /** One group id per comparison slot, "" when free. */
  compareSlots: string[];
  /** Adds the group to a free slot, or removes it. */
  onCompare: (groupId: string) => void;
  onClearCompare: () => void;
  month: string;
  onMonth: (month: string) => void;
  favorite: boolean;
  onFavorite: () => void;
  syncing: boolean;
  onSync: () => void;
  onCompany?: (companyId: string) => void;
  weights?: Weights;
  onWeights?: (weights: Weights) => void;
  evaluating?: boolean;
  onEntity?: (id: string, kind: "group" | "company") => void;
  chart?: ChartConfig;
}

const clock = (d: Date) =>
  d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const stamp = (d: Date) =>
  `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}, ${clock(d)}`;

function heading(score: ScoreRow): string {
  if (score.localScoring) {
    const { level, evolution } = score.localScoring;
    return `Confidence ${level.confidence == null ? "-" : `${level.confidence.toFixed(0)}%`} · Evolution ${evolution.score == null ? "-" : `${evolution.score.toFixed(1)}/100`}`;
  }
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
  compareSlots,
  onCompare,
  onClearCompare,
  month,
  onMonth,
  favorite,
  onFavorite,
  syncing,
  onSync,
  onCompany,
  weights,
  onWeights,
  evaluating,
  onEntity,
  chart = DEFAULT_CHART,
}: GroupDetailProps) {
  const group = store.groupById.get(groupId);
  const history = store.scoresByGroup.get(groupId) ?? [];
  const score = store.scoreAt(groupId, month);
  const idx = history.findIndex((s) => s.month === month);
  const prevLevel = idx > 0 ? history[idx - 1].level : null;
  const since = score?.level != null && prevLevel != null ? score.level - prevLevel : null;
  const way =
    since == null || Math.abs(since) < 0.05
      ? ""
      : since > 0
        ? "is-up"
        : "is-down";
  const line = score ? heading(score) : "";
  const thin = !store.localScoring && thinHistory(score?.months_observed);
  const [level] = useTween([score?.level ?? NaN]);
  const [macroIds, setMacroIds] = useState(() => [
    defaultMacro(group?.country ?? null),
  ]);
  const [query, setQuery] = useState("");
  const [showMembers, setShowMembers] = useState(false);
  const [hotMember, setHotMember] = useState<string>();
  if (!group) return null;

  const drivers = store.driversAt(groupId, month);
  const detail = store.localDetails?.get(groupId);
  const record = detail?.monthly.find((r) => r.month.slice(0, 7) === month.slice(0, 7));
  const activeWeights = weights ?? store.localWeights?.get(groupId) ?? store.localScoring?.config.weights;
  const offer = store.offerAt(groupId, month);
  const actions = [...(store.actionsByGroup.get(groupId) ?? [])].filter(a => a.month === month).sort(
    (a, b) => a.rank - b.rank,
  );
  const companies = [...(store.companiesByGroup.get(groupId) ?? [])].sort(
    (a, b) =>
      (store.companyImpactAt(b.company_id, month)?.impact_points ?? -Infinity) -
      (store.companyImpactAt(a.company_id, month)?.impact_points ?? -Infinity),
  );
  const members = companies.flatMap((c) => {
    const rows = store.scoresByCompany.get(c.company_id);
    return rows?.length ? [{ name: c.name, history: rows }] : [];
  });
  const canShowMembers = members.length > 1;
  const macros = macroIds.flatMap((id) => MACRO_BY_ID.get(id) ?? []);
  const peers = compareSlots.flatMap((id) => store.groupById.get(id) ?? []);
  const slotsFree = peers.length < compareSlots.length;
  const q = query.trim().toLowerCase();
  const candidates = store.groups.filter(
    (g) => g.group_id !== groupId && (!q || g.name.toLowerCase().includes(q)),
  );
  const chartHistory = (metric: string) => metric === "level" ? history : history.map(row => ({ ...row, level: row.localScoring?.families[metric]?.score ?? null }));
  const periodStart = chart.months ? new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - chart.months, 1)).toISOString().slice(0, 10) : "";
  const observed = new Map(chart.series.map(metric => [metric, chartHistory(metric).filter(row => row.month <= month && row.month >= periodStart && row.level != null && Number.isFinite(row.level)).length]));
  const omitted = store.localScoring ? chart.series.filter(metric => observed.get(metric)! < 2) : [];
  const chartSeries = chart.series.filter(metric => !omitted.includes(metric));
  const chartPrimary = chartSeries[0];
  const primaryName = chartPrimary === "level" ? group.name : scoreLabels[chartPrimary];
  const showMarket = chartSeries.length === 1 && chartPrimary === "level";
  const chartComparisons = [
    ...chartSeries.slice(1).map(metric => ({ name: metric === "level" ? "Health score" : scoreLabels[metric], history: chartHistory(metric) })),
    ...(showMarket ? peers.map(peer => ({ name: peer.name, history: store.scoresByGroup.get(peer.group_id) ?? [] })) : []),
  ];

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
              !store.localScoring && `${fmtEur(group.annual_revenue_eur)} revenue`,
              store.updatedAt && `updated ${stamp(store.updatedAt)}`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {detail && (detail.entity.kind === "group" || detail.entity.fx_estimated || detail.entity.fx_partial) && <p className="detail__meta">{detail.entity.fx_partial ? "Partial EUR coverage: some exchange rates are unavailable. " : detail.entity.fx_estimated ? "EUR amounts include estimated currency conversion. " : "EUR aggregation. "}{detail.entity.kind === "group" && "Intragroup flows are not eliminated."}</p>}
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
              {!score.localScoring && <StateTag state={score.state} />}
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
              {thin ? <LowDataNote months={score.months_observed} />
                : !store.localScoring && score.coverage < 0.75 && <PartialDataNote missing={PILLARS.filter((p) => score[p.key] == null).length} total={PILLARS.length} />}
            </div>
          </div>
        )}
      </header>

      <section>
        <div className="section-head">
          <div className="section-title">
            <h2>{(omitted.length ? null : chart.title) ?? (showMarket ? "Health score" : "Pillar scores")}</h2>
            <span className="hint">{monthLong(month)}</span>
          </div>
          {store.localScoring && <span className="hint">{store.localWeights?.has(groupId) ? "Custom weights" : "Default weights"}</span>}
          {showMarket && <div className="compare">
            <span className="legend">
              <span className="legend__item">
                <span className="key" style={{ background: CHART_COLORS[chart.color] }} />
                {group.name}
              </span>
              {peers.map((peer, k) => (
                <button
                  key={peer.group_id}
                  className="legend__item legend__item--remove"
                  aria-label={`Stop comparing with ${peer.name}`}
                  onClick={() => onCompare(peer.group_id)}
                >
                  <span className="key" style={{ background: SERIES_COLORS[k % SERIES_COLORS.length] }} />
                  {peer.name}
                  <svg width="8" height="8" viewBox="0 0 10 10" aria-hidden>
                    <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" />
                  </svg>
                </button>
              ))}
              {showMembers && canShowMembers && (
                <span className="legend__item">
                  <span className="key key--member" />
                  Companies
                </span>
              )}
              {macros.map((series, k) => (
                <span className="legend__item" key={series.id}>
                  <span
                    className="key key--dashed"
                    style={{ background: MACRO_COLORS[k % MACRO_COLORS.length] }}
                  />
                  {series.name}
                </span>
              ))}
            </span>
            {canShowMembers && (
              <button
                className="menu__button menu__button--toggle"
                aria-pressed={showMembers}
                aria-label="Show every company of the group on the chart"
                onClick={() => setShowMembers((on) => !on)}
              >
                Companies · {members.length}
              </button>
            )}
            <Menu
              label={peers.length ? `Compare · ${peers.length}` : "Compare with..."}
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
                      disabled={!on && !slotsFree}
                      onChange={() => onCompare(g.group_id)}
                    >
                      {g.name}
                    </Check>
                  );
                })}
                {candidates.length === 0 && <p className="menu__note">No group by that name.</p>}
              </div>
              <p className="menu__note menu__foot">
                {slotsFree ? `${peers.length} of ${compareSlots.length} selected` : `Up to ${compareSlots.length} at a time`}
                {peers.length > 0 && (
                  <button className="link" onClick={onClearCompare}>
                    Clear
                  </button>
                )}
              </p>
            </Menu>
            <Menu
              label={macros.length === 1 ? macros[0].name : macros.length ? `Markets · ${macros.length}` : "Market health..."}
              ariaLabel="Lay market health behind the score"
              align="right"
            >
              <div className="menu__scroll">
                {MACRO_SERIES.map((series) => (
                  <Check
                    key={series.id}
                    checked={macroIds.includes(series.id)}
                    onChange={() =>
                      setMacroIds((ids) =>
                        ids.includes(series.id) ? ids.filter((id) => id !== series.id) : [...ids, series.id],
                      )
                    }
                  >
                    {series.name}
                    {series.country && (
                      <span className="pick__tag">{series.country}</span>
                    )}
                  </Check>
                ))}
              </div>
              <p className="menu__note menu__foot">
                Published figures, aligned to the score's months.
                {macros.length > 0 && (
                  <button className="link" onClick={() => setMacroIds([])}>
                    Clear
                  </button>
                )}
              </p>
            </Menu>
            {macros.length > 0 && <MacroInfo macros={macros} />}
          </div>}
        </div>
        {chartSeries.length > 0 ? <TrajectoryChart
          config={chart}
          months={store.months}
          month={month}
          onMonth={onMonth}
          primary={{ name: primaryName, history: chartHistory(chartPrimary) }}
          compare={chartComparisons}
          macros={showMarket ? macros : []}
          members={showMarket && showMembers && canShowMembers ? members : []}
          hotMember={hotMember}
          onHotMember={setHotMember}
          alerts={chartPrimary === "level" ? store.alerts.filter((a) => a.group_id === groupId) : []}
        /> : <p className="empty">A time chart needs at least two observations in this period.</p>}
        {chartSeries.length > 0 && !showMarket && <div className="view-chart-legend">{chartSeries.map((metric, index) => <span className="legend__item" key={metric}><span className="key" style={{ background: index === 0 ? CHART_COLORS[chart.color] : SERIES_COLORS[index - 1] }} />{metric === "level" ? "Health score" : scoreLabels[metric]}</span>)}</div>}
        {omitted.length > 0 && <p className="view-chart-note" role="status">{omitted.map(metric => `${metric === "level" ? "Health score" : scoreLabels[metric]} omitted: ${observed.get(metric) === 1 ? "only 1 observation" : "no observations"} in this period.`).join(" ")}</p>}
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
              <h2>{store.localScoring ? "The four pillars" : "The five pillars"}</h2>
              <span className="hint">{store.localScoring ? "available evidence and effective weights" : "what each moved this month"}</span>
            </div>
            <Pillars score={score} drivers={drivers} weights={activeWeights} cashDate={typeof record?.cash_date === "string" ? record.cash_date : undefined} />
            {!store.localScoring && companies.length > 0 && (
              <>
                <div className="section-head section-head--spaced">
                  <h2>Companies in the group</h2>
                  <span className="hint">inflow · score · group pressure</span>
                </div>
                {score.pillarWeights && <p className="hint">Company scores use standard weights. Group pressure is unavailable with custom group weights.</p>}
                {companies.map((c) => {
                  const own = store.companyScoreAt(c.company_id, month);
                  const impact = store.companyImpactAt(c.company_id, month)?.impact_points;
                  const share = own && score.monthly_inflow_eur > 0
                    ? own.monthly_inflow_eur / score.monthly_inflow_eur
                    : null;
                  return (
                    <button
                      className={`company company--open ${showMembers && hotMember === c.name ? "is-hot" : ""}`}
                      key={c.company_id}
                      onClick={() => onCompany?.(c.company_id)}
                      onPointerEnter={() => setHotMember(c.name)}
                      onPointerLeave={() => setHotMember(undefined)}
                      onFocus={() => setHotMember(c.name)}
                      onBlur={() => setHotMember(undefined)}
                    >
                      <span className="company__name">{c.name}</span>
                      <span className="company__share">{share == null ? "-" : `${(share * 100).toFixed(0)}%`}</span>
                      <span className="company__level">{fmtScore(own?.level ?? null)}</span>
                      <span className={`company__impact ${impact == null || Math.abs(impact) < 0.05 ? "" : impact > 0 ? "is-down" : "is-up"}`}>
                        {impact == null ? "-" : Math.abs(impact) < 0.05 ? "0.0" : fmtSigned(impact, 1)}
                      </span>
                    </button>
                  );
                })}
              </>
            )}
            {store.localScoring && companies.length > 0 && (
              <>
                <div className="section-head section-head--spaced">
                  <h2>Companies in the group</h2>
                  <span className="hint">{store.localScoring ? "open company" : "share of inflow"}</span>
                </div>
                {companies.map((c) => {
                  const months = c.months_observed;
                  const short = thinHistory(months);
                  return (
                    <div className="company" key={c.company_id}>
                      <span className="company__name">
                        {store.localScoring && onEntity ? <button className="link" onClick={() => onEntity(c.company_id, "company")}>{c.name}</button> : c.name}
                        {short && (
                          <span className="company__note">
                            {fmtMonthsOfData(months)}
                          </span>
                        )}
                      </span>
                      <span className="company__share">
                        {store.localScoring ? "" : `${((c.inflow_share ?? 0) * 100).toFixed(0)}%`}
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
                {store.localScoring ? "Working-capital offers are not available for this scoring profile." : "No line this month: the score is too low or too young."}
              </p>
            )}
          </section>
        </div>
      )}

      {store.localScoring && score && <OwnHistory history={history} month={month} />}
      {store.localScoring && score && <WhatIf score={score} weights={activeWeights} onWeights={onWeights} evaluating={evaluating} />}
      {score && <PromptPay store={store} groupId={groupId} month={month} />}
    </article>
  );
}
