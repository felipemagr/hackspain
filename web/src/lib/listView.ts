import type { Bucket } from "./meta";

export type SortKey = "priority" | "level_desc" | "level_asc" | "trend_desc" | "trend_asc" | "name";

/** How the groups rail is filtered and sorted. */
export interface ListView {
  /** Free text: words match name, sector, country or state; ">70" and "<40" match the score. */
  query: string;
  bucket: Bucket | "all";
  favoritesOnly: boolean;
  sort: SortKey;
}

export const DEFAULT_VIEW: ListView = { query: "", bucket: "all", favoritesOnly: false, sort: "priority" };
