import { useEffect, useSyncExternalStore } from "react";

// Every amount in the data is in euros. The page can show it in dollars instead, at the average
// rate of the year being looked at: the same yearly rates the pipeline converts with.
export type Currency = "EUR" | "USD";

const KEY = "xray.currency";
const listeners = new Set<() => void>();
let usdPerEur = new Map<number, number>();
let state = {
  currency: (localStorage.getItem(KEY) === "USD" ? "USD" : "EUR") as Currency,
  year: new Date().getFullYear(),
};

function set(next: Partial<typeof state>) {
  state = { ...state, ...next };
  listeners.forEach((notify) => notify());
}

function subscribe(notify: () => void) {
  listeners.add(notify);
  return () => listeners.delete(notify);
}

export function loadRates() {
  fetch("/data/fx.json")
    .then((res) => res.json())
    .then((rows: { year: number; usd_per_eur: number }[]) => {
      usdPerEur = new Map(rows.map((r) => [r.year, r.usd_per_eur]));
      set({});
    })
    .catch(() => {});
}

export function setCurrency(currency: Currency) {
  localStorage.setItem(KEY, currency);
  set({ currency });
}

/** Subscribes the caller to the chosen currency, and pins the rate to the year of `month`. */
export function useDisplayCurrency(month?: string): Currency {
  const current = useSyncExternalStore(subscribe, () => state);
  useEffect(() => {
    const year = Number(month?.slice(0, 4));
    if (year && year !== state.year) set({ year });
  }, [month]);
  return current.currency;
}

export const displayCurrency = () => state.currency;

/** An amount held in euros, in the currency on display. Euros until the rates have loaded. */
export function toDisplay(eur: number): { value: number; symbol: string } {
  const rate = state.currency === "USD" ? usdPerEur.get(state.year) : undefined;
  return rate ? { value: eur * rate, symbol: "$" } : { value: eur, symbol: "€" };
}
