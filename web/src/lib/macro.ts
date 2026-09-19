/**
 * Market health levels the trajectory chart can lay behind a group's score.
 *
 * Embat's markets are Spain, Germany and the UK, with Europe and the US for context. Each level
 * is 0-100, built by src/xray/pipeline/market_health.py from published series (ECB, Eurostat,
 * ONS, OECD, BLS, Yahoo Finance) and written into macro.json by `make macro`. The file is
 * committed: nothing is fetched while the demo runs. Each market carries the last month it could
 * be scored, and is never drawn past it.
 *
 * This 0-100 is not the company's 0-100: that one is distance to distress, this one is
 * conditions. They share an axis so the two trajectories can be read together.
 */

import table from "./macro.json";

export interface MacroSeries {
  id: string;
  /** Shown in the picker and the legend. */
  name: string;
  /** Country whose groups get this market by default; null for the wider ones. */
  country: string | null;
  /** Who published the inputs. */
  source: string;
  /** Last month that could be scored. */
  through: string;
  /** One value per month of `MACRO_MONTHS`, null where the market could not be scored. */
  values: (number | null)[];
}

export const MACRO_SERIES = table.series as MacroSeries[];
/** The months the levels are aligned on, oldest first. */
export const MACRO_MONTHS: string[] = table.months;
/** When the inputs were last fetched from their sources. */
export const MACRO_FETCHED_AT: string = table.fetched_at;

export const MACRO_BY_ID = new Map(MACRO_SERIES.map((s) => [s.id, s]));

/** Levels aligned to a list of dataset months; NaN where the market has no level. */
export function alignMacro(series: MacroSeries, months: string[]): number[] {
  const byMonth = new Map(MACRO_MONTHS.map((m, i) => [m, series.values[i]]));
  return months.map((m) => byMonth.get(m.slice(0, 7)) ?? NaN);
}

/** Which market to lay behind a group by default: its own. */
export function defaultMacro(country: string | null): string {
  const own = MACRO_SERIES.find((s) => s.country === country);
  return own?.id ?? "mh_eu";
}

/** The four pillars behind a market level, mirroring src/xray/pipeline/market_health.py. */
export const MACRO_PILLARS = [
  {
    name: "Equity",
    weight: "30%",
    what: "Fall from the trailing 12m high, and 6m momentum.",
  },
  {
    name: "Labour",
    weight: "25%",
    what: "Unemployment against its own 5y median, and its 12m change.",
  },
  {
    name: "Prices",
    weight: "25%",
    what: "Headline inflation, two-sided around the 2% target.",
  },
  {
    name: "Funding",
    weight: "20%",
    what: "The real short rate, and the 12m change in the short rate.",
  },
];
