import { useCallback, useState } from "react";

function read(key: string): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(key) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

/** A set of ids kept in localStorage, so favourites and cleared alerts survive a reload. */
export function useStoredSet(key: string) {
  const [set, setSet] = useState(() => read(key));

  const update = useCallback(
    (change: (next: Set<string>) => void) =>
      setSet((prev) => {
        const next = new Set(prev);
        change(next);
        try {
          localStorage.setItem(key, JSON.stringify([...next]));
        } catch {
          // private window: the set still works for the session
        }
        return next;
      }),
    [key],
  );

  return [set, update] as const;
}
