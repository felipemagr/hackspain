import { useEffect, useRef, useState } from "react";

/**
 * Eases an array of numbers towards `target`, so lines and figures glide between
 * groups and months. NaN marks a gap and jumps without easing.
 */
export function useTween(target: number[], ms = 420): number[] {
  const [value, setValue] = useState(target);
  const current = useRef(target);
  const key = target.join(",");

  useEffect(() => {
    const span = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : ms;
    const from = current.current;
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = span === 0 ? 1 : Math.min(1, (now - start) / span);
      const e = 1 - (1 - t) ** 4;
      const next = target.map((b, i) => {
        const a = from[i];
        return Number.isFinite(a) && Number.isFinite(b) ? a + (b - a) * e : b;
      });
      current.current = next;
      setValue(next);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // `key` stands in for `target`, which is a fresh array on every render.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ms]);

  return value;
}
