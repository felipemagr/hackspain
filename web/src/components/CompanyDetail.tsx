import { fmtScore, fmtSigned, monthLong } from "../lib/format";
import type { Store } from "../lib/load";
import { SERIES_COLORS } from "../lib/meta";
import { Pillars } from "./Pillars";
import { StateTag } from "./StateTag";
import { TrajectoryChart } from "./TrajectoryChart";

interface CompanyDetailProps {
  store: Store;
  companyId: string;
  month: string;
  onMonth: (month: string) => void;
  onBack: () => void;
}

export function CompanyDetail({ store, companyId, month, onMonth, onBack }: CompanyDetailProps) {
  const company = store.companyById.get(companyId);
  if (!company) return null;

  const group = store.groupById.get(company.group_id);
  const history = store.scoresByCompany.get(companyId) ?? [];
  const score = store.companyScoreAt(companyId, month);
  const groupScore = store.scoreAt(company.group_id, month);
  const drivers = store.companyDriversAt(companyId, month);
  const impact = store.companyImpactAt(companyId, month)?.impact_points;
  const index = history.findIndex((row) => row.month === month);
  const previous = index > 0 ? history[index - 1].level : null;
  const change = score?.level != null && previous != null ? score.level - previous : null;
  const share = score && groupScore && groupScore.monthly_inflow_eur > 0
    ? score.monthly_inflow_eur / groupScore.monthly_inflow_eur
    : null;

  return (
    <article className="detail" aria-label={company.name}>
      <button className="company-back" onClick={onBack}>← {group?.name ?? company.group_id}</button>
      <header className="detail__head">
        <div>
          <h1>{company.name}</h1>
          <p className="detail__meta">Company in {group?.name ?? company.group_id}</p>
        </div>
        {score && (
          <div className="score">
            <span className="score__level">{fmtScore(score.level)}</span>
            <div>
              <StateTag state={score.state} />
              <p className="score__line">
                {score.trend == null
                  ? "Not enough history for a trend"
                  : `${score.trend >= 0 ? "Gaining" : "Losing"} ${Math.abs(score.trend).toFixed(1)} points a month`}
                {change != null && `, ${fmtSigned(change)} since last month`}
              </p>
            </div>
          </div>
        )}
      </header>

      <section>
        <div className="section-head">
          <h2>Health score, {monthLong(month)}</h2>
        </div>
        <div className="company-legend" aria-label="Chart legend">
          <span className="company-legend__item">
            <span className="company-legend__key" style={{ background: "var(--ink)" }} aria-hidden="true" />
            <span><span className="company-legend__role">Company</span> {company.name}</span>
          </span>
          <span className="company-legend__item">
            <span className="company-legend__key" style={{ background: SERIES_COLORS[0] }} aria-hidden="true" />
            <span><span className="company-legend__role">Group</span> {group?.name ?? company.group_id}</span>
          </span>
        </div>
        <TrajectoryChart
          months={store.months}
          month={month}
          onMonth={onMonth}
          primary={{ name: company.name, history }}
          compare={[group ? { name: group.name, history: store.scoresByGroup.get(company.group_id) ?? [] } : null]}
          macros={[]}
          alerts={store.companyAlerts.filter((a) => a.company_id === companyId).map((a) => ({ ...a, group_id: companyId }))}
        />
      </section>

      {!score ? (
        <p className="empty">{company.name} has no score in {monthLong(month)}. Pick a month with activity on the chart.</p>
      ) : (
        <div className="columns">
          <section>
            <div className="section-head">
              <h2>The five pillars</h2>
              <span className="hint">what each moved this month</span>
            </div>
            <Pillars score={score} drivers={drivers} />
          </section>
          <section>
            <div className="section-head">
              <h2>Effect on the group</h2>
              <span className="hint">{monthLong(month)}</span>
            </div>
            {groupScore && <p className="company-context">Group score <strong>{fmtScore(groupScore.level)}</strong></p>}
            <p className="company-context">Share of operating inflow <strong>{share == null ? "-" : `${(share * 100).toFixed(0)}%`}</strong></p>
            {impact == null ? (
              <p className="empty">{group?.n_companies === 1 ? "This is the group's only company." : "Group pressure cannot be compared this month."}</p>
            ) : (
              <p className="company-context">
                Group pressure <strong className={impact > 0 ? "is-down" : impact < 0 ? "is-up" : ""}>{fmtSigned(impact, 1)} points</strong>
              </p>
            )}
            <p className="hint company-note">
              Positive pressure means the group would score higher without this company. This comparison does not add up across companies.
            </p>
          </section>
        </div>
      )}
    </article>
  );
}
