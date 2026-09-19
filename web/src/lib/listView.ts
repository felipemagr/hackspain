import type { State } from "./types";

export type Direction = "rising" | "flat" | "falling";
export type SortKey = "state" | "level_desc" | "level_asc" | "trend_desc" | "trend_asc" | "name";

/** How the groups rail is filtered and sorted. Empty filter lists mean "all". */
export interface ListView {
  states: State[];
  directions: Direction[];
  favoritesOnly: boolean;
  sort: SortKey;
}

export const DEFAULT_VIEW: ListView = { states: [], directions: [], favoritesOnly: false, sort: "state" };
