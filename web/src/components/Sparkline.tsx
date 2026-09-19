interface SparklineProps {
  /** Level per observed month, up to the selected one. */
  series: (number | null)[];
  /** Months in the full window, so every row shares one time scale. */
  total: number;
}

const W = 72;
const H = 22;

export function Sparkline({ series, total }: SparklineProps) {
  const finite = series.filter((v): v is number => v != null && Number.isFinite(v));
  if (finite.length < 2) return <svg width={W} height={H} aria-hidden />;
  const offset = total - series.length;
  const x = (i: number) => 2 + ((offset + i) / (total - 1)) * (W - 4);
  // Each row scales to its own range, with a floor so a flat group still reads flat.
  const lo = Math.min(...finite);
  const span = Math.max(Math.max(...finite) - lo, 20);
  const mid = lo + (Math.max(...finite) - lo) / 2;
  const y = (v: number) => H / 2 - ((v - mid) / span) * (H - 4);
  const last = series.length - 1;
  return (
    <svg className="spark" width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden>
      {series.map((v, i) => v != null && Number.isFinite(v) && i > 0 && series[i - 1] != null && Number.isFinite(series[i - 1]) ? <polyline key={i} points={`${x(i - 1).toFixed(1)},${y(series[i - 1]!).toFixed(1)} ${x(i).toFixed(1)},${y(v).toFixed(1)}`} /> : null)}
      {series[last] != null && Number.isFinite(series[last]) && <circle cx={x(last)} cy={y(series[last]!)} r={2} />}
    </svg>
  );
}
