import { fmtEur, fmtSigned, monthLong } from "../lib/format";
import { PILLARS, PILLAR_LABEL } from "../lib/meta";
import type { Store } from "../lib/load";
import type { ScoreRow } from "../lib/types";
import { useTween } from "../lib/useTween";
import { StateTag } from "./StateTag";
import { TrajectoryChart } from "./TrajectoryChart";

interface GroupDetailProps {
  store: Store;
  groupId: string;
  compareId: string;
  month: string;
  onMonth: (month: string) => void;
  onCompare: (groupId: string) => void;
}

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
  compareId,
  month,
  onMonth,
  onCompare,
}: GroupDetailProps) {
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
  const compare = compareId ? store.groupById.get(compareId) : undefined;

  return (
    <article className="detail" aria-label={group.name}>
      <header className="detail__head">
        <div>
          <h1>{group.name}</h1>
          <p className="detail__meta">
            {[
              group.sector,
              group.country,
              `${group.n_companies} ${group.n_companies === 1 ? "company" : "companies"}`,
              `${fmtEur(group.annual_revenue_eur)} revenue`,
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
            {compare && (
              <span className="legend">
                <span className="key" style={{ background: "var(--ink)" }} />
                {group.name}
                <span className="key" style={{ background: "var(--series-2)" }} />
                {compare.name}
              </span>
            )}
            <select
              value={compareId}
              onChange={(e) => onCompare(e.target.value)}
              aria-label="Compare with another group"
            >
              <option value="">Compare with...</option>
              {store.groups
                .filter((g) => g.group_id !== groupId)
                .map((g) => (
                  <option key={g.group_id} value={g.group_id}>
                    {g.name}
                  </option>
                ))}
            </select>
          </div>
        </div>
        <TrajectoryChart
          months={store.months}
          month={month}
          onMonth={onMonth}
          primary={{ name: group.name, history }}
          compare={
            compare && {
              name: compare.name,
              history: store.scoresByGroup.get(compare.group_id) ?? [],
            }
          }
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
              <h2>What drives the score</h2>
              <span className="hint">change since last month</span>
            </div>
            {PILLARS.map((p) => {
              const value = score[p.key];
              const delta = drivers.find((d) => d.pillar === p.key)?.delta_score ?? null;
              return (
                <div className="pillar" key={p.key}>
                  <span className="pillar__name">
                    {p.label}
                    <span className="pillar__evidence">{p.evidence(score)}</span>
                  </span>
                  <span className="pillar__track">
                    <span className="pillar__fill" style={{ transform: `scaleX(${(value ?? 0) / 100})` }} />
                  </span>
                  <span className="pillar__value">{value == null ? "-" : value.toFixed(0)}</span>
                  <span
                    className={`pillar__delta ${
                      delta == null || Math.abs(delta) < 0.05 ? "" : delta > 0 ? "is-up" : "is-down"
                    }`}
                  >
                    {delta == null ? "" : fmtSigned(delta)}
                  </span>
                </div>
              );
            })}
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
                    <span className="company__share">{(c.inflow_share * 100).toFixed(0)}%</span>
                    <span className="company__level">{c.level.toFixed(0)}</span>
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
    </article>
  );
}
