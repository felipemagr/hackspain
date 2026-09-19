interface SparklineProps {
  /** Level per observed month, up to the selected one. */
  series: number[];
  /** Months in the full window, so every row shares one time scale. */
  total: number;
}

const W = 72;
const H = 22;

export function Sparkline({ series, total }: SparklineProps) {
  if (series.length < 2) return <svg width={W} height={H} aria-hidden />;
  const offset = total - series.length;
  const x = (i: number) => 2 + ((offset + i) / (total - 1)) * (W - 4);
  // Each row scales to its own range, with a floor so a flat group still reads flat.
  const lo = Math.min(...series);
  const span = Math.max(Math.max(...series) - lo, 20);
  const mid = lo + (Math.max(...series) - lo) / 2;
  const y = (v: number) => H / 2 - ((v - mid) / span) * (H - 4);
  const last = series.length - 1;
  return (
    <svg className="spark" width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden>
      <polyline points={series.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} />
      <circle cx={x(last)} cy={y(series[last])} r={2} />
    </svg>
  );
}
