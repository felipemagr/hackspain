import { setCurrency, useDisplayCurrency, type Currency } from "../lib/currency";
import "./currency.css";

const OPTIONS: Currency[] = ["EUR", "USD"];

/** Two-way switch for the currency every amount is shown in. */
export function CurrencyToggle() {
  const current = useDisplayCurrency();
  return (
    <div className="currency" role="group" aria-label="Currency">
      {OPTIONS.map((option) => (
        <button key={option} aria-pressed={current === option} onClick={() => setCurrency(option)}>
          {option}
        </button>
      ))}
    </div>
  );
}
