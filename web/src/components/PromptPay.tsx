import { useState } from "react";
import { fmtEur } from "../lib/format";
import type { Store } from "../lib/load";

interface PromptPayProps {
  store: Store;
  groupId: string;
  month: string;
}

const WINDOWS = [30, 60, 90] as const;
// The fifth percentile of a normal: what is left after a bad month, not the average month.
const Z_05 = 1.645;
// Used only when the group has no line this month; it is the reader's own number, not the data's.
const DEFAULT_LINE_COST = 8;

function pdf(z: number): number {
  return Math.exp(-0.5 * z * z) / Math.sqrt(2 * Math.PI);
}

/** Standard normal cdf, Abramowitz and Stegun 26.2.17. Enough for a percentile on a page. */
function cdf(z: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const tail =
    pdf(z) *
    t *
    (0.31938153 +
      t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return z >= 0 ? 1 - tail : tail;
}

/** E[max(0, committed - collected)] when the collection is normal around `mean`. */
function shortfall(committed: number, mean: number, sd: number): number {
  if (sd <= 0) return Math.max(0, committed - mean);
  const z = (committed - mean) / sd;
  // Far in the tail the cdf approximation loses the cancellation between the two terms and comes
  // back a hair under zero, where the true value is vanishingly small. A shortfall is never negative.
  return Math.max(0, (committed - mean) * cdf(z) + sd * pdf(z));
}

export function PromptPay({ store, groupId, month }: PromptPayProps) {
  const [days, setDays] = useState<number>(60);
  const offer = store.offerAt(groupId, month);
  const lineCost = offer?.apr != null ? offer.apr * 100 : DEFAULT_LINE_COST;

  const row = store.promptPayAt(groupId, month, days);
  // Every reason a group can be silent here is worth naming: a jury that sees a blank panel
  // learns nothing, and most of the portfolio is silent for a reason that is itself a finding.
  if (!row) {
    const hasErp = store.groupById.get(groupId)?.has_erp ?? true;
    return (
      <section className="promptpay">
        <div className="section-head">
          <h2>Pay early with the money you can count on</h2>
        </div>
        <p className="empty">
          {store.localScoring ? "Payment timing estimates are not available for this scoring profile." : hasErp
            ? "Nothing to work with this month: this group has no customer invoice open, neither falling due nor already past due."
            : "This group runs no ERP, so it files no invoices at all. Without a receivables book there is nothing to bring forward, and the customer panels are blank for the same reason."}
        </p>
      </section>
    );
  }

  if (row.due_eur === 0) {
    return (
      <section className="promptpay">
        <div className="section-head">
          <h2>Pay early with the money you can count on</h2>
        </div>
        <p className="empty">
          {fmtEur(row.overdue_eur)} is owed to this group across {row.overdue_n}{" "}
          {row.overdue_n === 1 ? "invoice" : "invoices"} that fell due over the past year, and
          every one of them is still unpaid. This panel only commits money that has not fallen due yet: an invoice three months
          late has not been paid despite a good payment history, so that history no longer prices
          it. Chasing it is the collections job, not this one.
        </p>
      </section>
    );
  }

  const sd = Math.sqrt(row.variance);
  // What survives a bad month, not the average one.
  const reliable = Math.max(0, row.expected_eur - Z_05 * sd);
  const cushion = row.expected_eur - reliable;
  const riskDiscounted = row.due_eur - row.thin_eur - row.expected_eur;
  const advance = Math.min(row.payable_eur, reliable);
  const payableDays = row.payable_days ?? 0;
  const missing = shortfall(advance, row.expected_eur, sd);
  const costOfRisk = payableDays > 0 ? missing * (lineCost / 100) * (payableDays / 365) : 0;
  const binding = row.payable_eur <= reliable ? "invoices" : "cash";

  const segments = [
    { key: "reliable", label: "Cash you can count on", value: reliable },
    { key: "cushion", label: "Held back for uncertainty", value: cushion },
    { key: "risk", label: "Written off by how they pay", value: riskDiscounted },
    { key: "thin", label: "Never seen them pay, left out", value: row.thin_eur },
  ].filter((s) => s.value > 0);

  return (
    <section className="promptpay">
      <div className="section-head">
        <h2>Pay early with the money you can count on</h2>
        <div className="promptpay__windows" role="group" aria-label="Window">
          {WINDOWS.map((w) => (
            <button key={w} aria-pressed={w === days} onClick={() => setDays(w)}>
              {w} days
            </button>
          ))}
        </div>
      </div>

      <div className="promptpay__stats">
        <div>
          <span className="promptpay__label">Cash you can count on in {days} days</span>
          <p className="promptpay__figure">{fmtEur(reliable)}</p>
          <span className="hint">
            Of {fmtEur(row.due_eur)} falling due in the window. The fifth percentile, not the
            average.
          </span>
        </div>
        <div>
          <span className="promptpay__label">You can advance</span>
          <p className="promptpay__figure">{fmtEur(advance)}</p>
          <span className="hint">
            {row.payable_n} supplier {row.payable_n === 1 ? "invoice" : "invoices"}
            {row.payable_n > 0 && `, ${payableDays.toFixed(0)} days early on average`}.{" "}
            {binding === "invoices"
              ? `${fmtEur(reliable - row.payable_eur)} of reliable cash left over: the bottleneck is the invoices, not the money.`
              : "The bottleneck is the cash, not the invoices."}
          </span>
        </div>
        <div>
          <span className="promptpay__label">Cost of the risk</span>
          <p className="promptpay__figure">{fmtEur(costOfRisk)}</p>
          <span className="hint">
            {fmtEur(missing)} expected to fall short, at {lineCost.toFixed(2)}% for{" "}
            {payableDays.toFixed(0)} days.
          </span>
        </div>
      </div>

      <div className="promptpay__bar" aria-hidden>
        {segments.map((s) => (
          <span
            key={s.key}
            className={`promptpay__seg promptpay__seg--${s.key}`}
            style={{ flexGrow: s.value }}
          />
        ))}
      </div>
      <ul className="promptpay__legend">
        {segments.map((s) => (
          <li key={s.key}>
            <span className={`promptpay__dot promptpay__seg--${s.key}`} />
            {s.label} <strong>{fmtEur(s.value)}</strong>
          </li>
        ))}
      </ul>
    </section>
  );
}
