import { toDisplay } from "./currency";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export function monthShort(month: string): string {
  const name = MONTHS[Number(month.slice(5, 7)) - 1];
  return name ? `${name} ${month.slice(2, 4)}` : month;
}

export function monthLong(month: string): string {
  const name = MONTHS_LONG[Number(month.slice(5, 7)) - 1];
  return name ? `${name} ${month.slice(0, 4)}` : month;
}

export function fmtScore(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "-" : v.toFixed(0);
}

export function fmtSigned(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "-";
  // Round before the sign: a move too small to show at this many digits is not a fall, and
  // would otherwise read as "-0.0".
  const rounded = Number(v.toFixed(digits));
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(digits)}`;
}

/** An amount held in euros, shown in the currency picked in the side rail. */
export function fmtEur(eur: number | null | undefined): string {
  if (eur == null || !Number.isFinite(eur)) return "-";
  const { value: v, symbol } = toDisplay(eur);
  if (Math.abs(v) >= 1_000_000) return `${symbol}${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${symbol}${(v / 1_000).toFixed(0)}K`;
  return `${symbol}${v.toFixed(0)}`;
}

export function fmtMonthsOfData(months: number): string {
  return `${months.toFixed(0)} ${months === 1 ? "month" : "months"} of data`;
}

/** "4 months early", or null when the alert did not run ahead of the tier change. */
export function fmtEarly(months: number | null | undefined): string | null {
  if (!months || months <= 0) return null;
  return `${months.toFixed(0)} ${months === 1 ? "month" : "months"} early`;
}
