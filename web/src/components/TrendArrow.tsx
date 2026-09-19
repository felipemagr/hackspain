interface TrendArrowProps {
  trend: number | null;
}

/** Signed monthly slope with a drawn arrow, so direction never rests on color alone. */
export function TrendArrow({ trend }: TrendArrowProps) {
  if (trend == null) return <span className="trend trend--flat">-</span>;
  const up = trend > 0.15;
  const down = trend < -0.15;
  return (
    <span className={`trend ${up ? "trend--up" : down ? "trend--down" : "trend--flat"}`}>
      <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden>
        {up && <path d="M4 1 L7.5 7 L0.5 7 Z" />}
        {down && <path d="M4 7 L7.5 1 L0.5 1 Z" />}
        {!up && !down && <rect x="1" y="3.3" width="6" height="1.4" />}
      </svg>
      {Math.abs(trend).toFixed(1)}
    </span>
  );
}
