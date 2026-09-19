import { useEffect, useState } from "react";
import { fmtEur } from "../lib/format";
import type { Store } from "../lib/load";
import type { PromptPayCustomerRow } from "../lib/types";

interface PromptPayProps {
  store: Store;
  groupId: string;
  month: string;
}

const WINDOWS = [30, 60, 90] as const;
// The fifth percentile of a normal: what is left after a bad month, not the average month.
const Z_05 = 1.645;
const DEFAULT_DISCOUNT = 2;
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
  return (committed - mean) * cdf(z) + sd * pdf(z);
}

function inWindow(c: PromptPayCustomerRow, days: number): { due: number; expected: number } {
  if (days === 30) return { due: c.due_30_eur, expected: c.exp_30_eur };
  if (days === 60) return { due: c.due_60_eur, expected: c.exp_60_eur };
  return { due: c.due_90_eur, expected: c.exp_90_eur };
}

export function PromptPay({ store, groupId, month }: PromptPayProps) {
  const [days, setDays] = useState<number>(60);
  const [signedAt, setSignedAt] = useState<string | null>(null);
  const [discount, setDiscount] = useState(DEFAULT_DISCOUNT);
  const offer = store.offerAt(groupId, month);
  const lineDefault = offer?.apr != null ? offer.apr * 100 : DEFAULT_LINE_COST;
  const [lineCost, setLineCost] = useState(lineDefault);
  // A different group or month is a different line and a different supplier: back to its
  // starting point, the way WhatIf drops its moves.
  useEffect(() => {
    setDiscount(DEFAULT_DISCOUNT);
    setLineCost(lineDefault);
    setSignedAt(null);
  }, [groupId, month, lineDefault]);

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
          {hasErp
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
  const captured = advance * (discount / 100);
  const equivalentApr = payableDays > 0 ? (discount / 100) * (365 / payableDays) * 100 : 0;
  const binding = row.payable_eur <= reliable ? "invoices" : "cash";

  const shown = store
    .promptPayCustomers(groupId, month)
    .map((c) => ({ customer: c, ...inWindow(c, days) }))
    .filter((r) => r.due > 0)
    .sort((a, b) => b.due - a.due);
  // Rounding at export can leave the remainder a euro under zero; the rest of the book is real.
  const restDue = Math.max(0, row.due_eur - shown.reduce((sum, r) => sum + r.due, 0));
  const restExpected = Math.max(
    0,
    row.expected_eur - shown.reduce((sum, r) => sum + r.expected, 0),
  );
  const restCount = row.n_customers - shown.length;

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
      {row.overdue_eur > 0 && (
        <p className="promptpay__aside">
          Another {fmtEur(row.overdue_eur)} across {row.overdue_n}{" "}
          {row.overdue_n === 1 ? "invoice" : "invoices"} fell due over the past year and is still
          unpaid. None of it is counted here: once an invoice is late, the customer's history
          stops pricing it.
        </p>
      )}

      {shown.length === 0 ? (
        <p className="empty">
          {row.n_customers === 1
            ? "The one customer owing here has not paid this group six times yet"
            : `None of the ${row.n_customers} customers owing here has paid this group six times yet`}
          , so there is no payment history to read. All {fmtEur(row.due_eur)} sits in the thin file: the
          money may well arrive, but nothing in the record says it will, so none of it can be
          committed to a supplier.
        </p>
      ) : (
        <>
          <table className="pillars promptpay__table">
            <thead>
              <tr>
                <th scope="col">Customer</th>
                <th scope="col">Paid</th>
                <th scope="col">Delay</th>
                <th scope="col">File</th>
                <th scope="col">Due in {days} days</th>
                <th scope="col">p</th>
                <th scope="col">Adds to cash</th>
              </tr>
            </thead>
            <tbody>
              {shown.map(({ customer: c, due, expected }) => (
                <tr key={c.counterparty_id}>
                  <th scope="row">{c.name}</th>
                  <td>{c.n_paid}</td>
                  <td>{c.median_late == null ? "-" : `${c.median_late.toFixed(0)} d`}</td>
                  <td>{c.solid ? "solid" : "indicative"}</td>
                  <td>{fmtEur(due)}</td>
                  <td>{(expected / due).toFixed(2)}</td>
                  <td>{fmtEur(expected)}</td>
                </tr>
              ))}
              {restCount > 0 && (
                <tr className="promptpay__rest">
                  <th scope="row">
                    Rest of the book
                    <span className="pillars__indicator">
                      {restCount} more {restCount === 1 ? "customer" : "customers"},{" "}
                      {row.n_thin} never seen paying
                    </span>
                  </th>
                  <td>-</td>
                  <td>-</td>
                  <td>-</td>
                  <td>{fmtEur(restDue)}</td>
                  <td>-</td>
                  <td>{fmtEur(restExpected)}</td>
                </tr>
              )}
            </tbody>
          </table>

          {advance <= 0 ? (
            <p className="empty">
              {row.payable_n === 0
                ? "No supplier bills fall due inside the window, so there is nothing to advance the money to."
                : "None of what falls due is reliable enough to commit this month: the book pays too unpredictably."}
            </p>
          ) : (
            <>
              <div className="promptpay__deal">
                <div className="promptpay__levers">
                  <div className="whatif__lever">
                    <label className="whatif__label" htmlFor="promptpay-discount">
                      Discount the supplier offers
                    </label>
                    <span className="whatif__value">{discount.toFixed(1)}%</span>
                    <input
                      id="promptpay-discount"
                      className="whatif__slider"
                      type="range"
                      min={0}
                      max={5}
                      step={0.1}
                      value={discount}
                      onChange={(e) => setDiscount(Number(e.target.value))}
                    />
                    <span className="whatif__today">
                      what you negotiate, not something the data knows
                    </span>
                  </div>
                  <div className="whatif__lever">
                    <label className="whatif__label" htmlFor="promptpay-line">
                      Cost of your credit line
                    </label>
                    <span className="whatif__value">{lineCost.toFixed(2)}%</span>
                    <input
                      id="promptpay-line"
                      className="whatif__slider"
                      type="range"
                      min={0}
                      max={25}
                      step={0.01}
                      value={lineCost}
                      onChange={(e) => setLineCost(Number(e.target.value))}
                    />
                    <span className="whatif__today">
                      {offer?.apr == null
                        ? "no line this month, so this one is yours to set"
                        : `starts at the ${(offer.apr * 100).toFixed(2)}% this group is offered`}
                    </span>
                  </div>
                </div>

                <aside className="whatif__out">
                  <span className="promptpay__label">With the discount above</span>
                  <p className="whatif__level">{fmtEur(captured)}</p>
                  <p className="whatif__note">
                    Taken on {fmtEur(advance)} paid {payableDays.toFixed(0)} days early, inside{" "}
                    {days} days. Worth {equivalentApr.toFixed(1)}% a year against{" "}
                    {fmtEur(costOfRisk)} of risk.
                  </p>
                </aside>
              </div>

              <aside className="draft">
                <div>
                  <p className="draft__title">Draft suggestion</p>
                  <p className="draft__detail">
                    Nothing here moves a euro. It writes the offer: the invoices, the amount and
                    the saving. A person signs it.
                  </p>
                </div>
                {signedAt ? (
              <span className="hint">Signed at {signedAt}</span>
            ) : (
              <button
                type="button"
                onClick={() =>
                  setSignedAt(
                    new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                  )
                }
              >
                Sign
              </button>
            )}
              </aside>
            </>
          )}
        </>
      )}
    </section>
  );
}
