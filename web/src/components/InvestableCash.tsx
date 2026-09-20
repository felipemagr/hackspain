import { useState } from "react";
import { fmtEur } from "../lib/format";
import type { Store } from "../lib/load";

interface InvestableCashProps {
  store: Store;
  groupId: string;
  month: string;
}

const WINDOWS = [30, 60, 90] as const;
const HISTORY_MONTHS_PER_30_DAYS = 3;

export function InvestableCash({ store, groupId, month }: InvestableCashProps) {
  const [days, setDays] = useState<number>(60);
  const [risk, setRisk] = useState<number>(50);
  const score = store.scoreAt(groupId, month);
  const cash = score?.cash_eur;
  const hasInputs = cash != null && Number.isFinite(cash) && !score?.cash_is_extrapolated &&
    score?.monthly_inflow_eur != null &&
    score?.monthly_outflow_eur != null && score?.monthly_debt_service_eur != null &&
    score?.net_flow_volatility_eur != null;
  const availableWindows = WINDOWS.filter((window) => hasInputs &&
    (score?.months_observed ?? 0) >= window / 30 * HISTORY_MONTHS_PER_30_DAYS);
  const selectedDays = availableWindows.includes(days as typeof WINDOWS[number])
    ? days : availableWindows.filter((window) => window <= days).at(-1) ?? availableWindows[0];
  const hasEstimate = selectedDays != null;

  // Risk is a user preference, not a calibrated probability of missing a payment.
  const stress = 1.1 - risk / 100 * 0.8;
  const reserveDays = 30 - risk / 100 * 20;
  const receipts = hasEstimate ? (score?.monthly_inflow_eur ?? 0) : 0;
  const payments = hasEstimate ? (score?.monthly_outflow_eur ?? 0) + (score?.monthly_debt_service_eur ?? 0) : 0;
  const stressedNet = receipts - payments - stress * (score?.net_flow_volatility_eur ?? 0);
  const reserve = payments * reserveDays / 30;
  const lowestProjectedCash = hasEstimate ? (cash ?? 0) + Math.min(0, stressedNet * selectedDays / 30) : 0;
  const investable = hasEstimate ? Math.min(Math.max(cash ?? 0, 0), Math.max(0, lowestProjectedCash - reserve)) : 0;
  const protectedCash = hasEstimate ? Math.max(0, (cash ?? 0) - investable) : 0;

  return (
    <section className="investable">
      <div className="section-head">
        <h2>How much cash can you put to work?</h2>
        <div className="investable__windows" role="group" aria-label="Investment term">
          {WINDOWS.map((window) => (
            <button key={window} aria-pressed={window === selectedDays}
              disabled={!availableWindows.includes(window)}
              title={!availableWindows.includes(window) ? `Needs ${window / 30 * HISTORY_MONTHS_PER_30_DAYS} observed months of cash flow` : undefined}
              onClick={() => setDays(window)}>
              {window} days
            </button>
          ))}
        </div>
      </div>

      <div className="investable__stats">
        <div>
          <span className="investable__label">Cash at month end</span>
          <p className="investable__figure">{cash == null ? "Unavailable" : fmtEur(cash)}</p>
          <span className="hint">Checking and savings balances at month end.</span>
        </div>
        <div className="investable__primary">
          <span className="investable__label">Estimated to invest{selectedDays == null ? "" : ` for ${selectedDays} days`}</span>
          <p className="investable__figure">{hasEstimate ? fmtEur(investable) : "Unavailable"}</p>
          <span className="hint">Cash that can stay invested for the full term under this safety setting.</span>
        </div>
        <div>
          <span className="investable__label">Kept in cash</span>
          <p className="investable__figure">{hasEstimate ? fmtEur(protectedCash) : "Unavailable"}</p>
          <span className="hint">Held for projected payments and the safety reserve.</span>
        </div>
      </div>

      <div className="investable__control">
        <div className="investable__control-head">
          <label htmlFor="cash-risk">Risk appetite</label>
          <output htmlFor="cash-risk">{risk}%</output>
        </div>
        <input id="cash-risk" type="range" min="0" max="100" step="5" value={risk}
          disabled={!hasEstimate}
          onChange={(event) => setRisk(Number(event.target.value))} />
        <div className="investable__endpoints"><span>More protection</span><span>More capacity</span></div>
      </div>

      {hasEstimate ? (
        <p className="investable__method">
          Uses the last three months of operating cash flow, six months of net-flow variation and observed debt service.
          It holds {reserveDays.toFixed(0)} days of stressed payments as a reserve. This setting is a
          preference, not the probability of a missed payment. Confirm dated obligations before investing.
          {availableWindows.length < WINDOWS.length && " Longer terms need three observed months of cash flow per 30 days invested."}
        </p>
      ) : (
        <p className="investable__method">
          An investment estimate needs a reliable cash balance and at least three observed months of cash flow.
        </p>
      )}
    </section>
  );
}
