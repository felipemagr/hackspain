import { useEffect, useRef, useState } from "react";
import { monthLong, monthShort } from "../lib/format";
import { SERIES_COLORS, STATE_META, toneColor } from "../lib/meta";
import type { AlertRow, ScoreRow } from "../lib/types";
import { useTween } from "../lib/useTween";

export interface ChartSeries {
  name: string;
  history: ScoreRow[];
}

interface TrajectoryChartProps {
  months: string[];
  month: string;
  onMonth: (month: string) => void;
  primary: ChartSeries;
  /** One entry per comparison slot, null when free. The slot picks the color. */
  compare: (ChartSeries | null)[];
  alerts: AlertRow[];
}

const H = 300;
const M = { top: 16, right: 44, bottom: 28, left: 96 };
const TICKS = [
  { at: 100, label: "" },
  { at: 70, label: "Healthy" },
  { at: 40, label: "Vulnerable" },
  { at: 0, label: "" },
];

function align(months: string[], history: ScoreRow[]): number[] {
  const byMonth = new Map(history.map((s) => [s.month, s.level]));
  return months.map((m) => byMonth.get(m) ?? NaN);
}

export function TrajectoryChart({
  months,
  month,
  onMonth,
  primary,
  compare,
  alerts,
}: TrajectoryChartProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(880);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const n = months.length;
  const cursor = months.indexOf(month);
  const a = useTween(align(months, primary.history));
  // All slots tween as one flat array, so the hook count does not depend on the selection.
  const flat = useTween(
    compare.flatMap((c) => (c ? align(months, c.history) : months.map(() => NaN))),
  );
  const others = compare.flatMap((c, k) =>
    c ? [{ ...c, color: SERIES_COLORS[k], vals: flat.slice(k * n, (k + 1) * n) }] : [],
  );

  const x = (i: number) => M.left + (i / (n - 1)) * (width - M.left - M.right);
  const y = (v: number) => M.top + (1 - v / 100) * (H - M.top - M.bottom);
  const path = (vals: number[], from: number, to: number) => {
    let d = "";
    let pen = false;
    for (let i = from; i <= to; i++) {
      if (!Number.isFinite(vals[i])) {
        pen = false;
        continue;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(vals[i]).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  const indexAt = (clientX: number) => {
    const rect = wrap.current!.getBoundingClientRect();
    const i = Math.round(((clientX - rect.left - M.left) / (width - M.left - M.right)) * (n - 1));
    return Math.max(0, Math.min(n - 1, i));
  };

  const first = a.findIndex(Number.isFinite);
  const area =
    others.length === 0 && first >= 0 && cursor > first
      ? `${path(a, first, cursor)}L${x(cursor).toFixed(1)},${y(0)}L${x(first).toFixed(1)},${y(0)}Z`
      : "";
  const endLabels = [
    { v: a[cursor], color: "var(--ink)" },
    ...others.map((o) => ({ v: o.vals[cursor], color: o.color })),
  ]
    .filter((l) => Number.isFinite(l.v))
    .map((l) => ({ ...l, py: y(l.v) }))
    .sort((p, q) => p.py - q.py);
  // End labels closer than a line of text get pushed apart, top to bottom, then back inside the plot.
  for (let k = 1; k < endLabels.length; k++) {
    endLabels[k].py = Math.max(endLabels[k].py, endLabels[k - 1].py + 14);
  }
  const overflow = endLabels.length ? endLabels[endLabels.length - 1].py - y(0) : 0;
  if (overflow > 0) endLabels.forEach((l) => (l.py -= overflow));

  const hoverAlert = hover != null ? alerts.find((al) => al.month === months[hover]) : undefined;

  return (
    <div className="chart" ref={wrap}>
      <svg
        width={width}
        height={H}
        role="img"
        aria-label={`Health score of ${primary.name}${others
          .map((o) => ` and ${o.name}`)
          .join("")} over ${n} months. Click to move to a month.`}
        onPointerMove={(e) => setHover(indexAt(e.clientX))}
        onPointerLeave={() => setHover(null)}
        onClick={(e) => onMonth(months[indexAt(e.clientX)])}
      >
        <defs>
          <linearGradient id="wash" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--ink)" stopOpacity="0.07" />
            <stop offset="1" stopColor="var(--ink)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {[0, 100].map((t) => (
          <line key={t} x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} className="chart__grid" />
        ))}
        {TICKS.filter((t) => t.label).map((t) => (
          <line
            key={t.at}
            x1={M.left}
            x2={width - M.right}
            y1={y(t.at)}
            y2={y(t.at)}
            className="chart__threshold"
          />
        ))}
        {TICKS.map((t) => (
          <text key={t.at} x={M.left - 10} y={y(t.at) + 4} textAnchor="end" className="chart__tick">
            {t.label} {t.at}
          </text>
        ))}
        {months.map((m, i) =>
          i % 3 === 0 ? (
            <text key={m} x={x(i)} y={H - 6} textAnchor="middle" className="chart__tick">
              {monthShort(m)}
            </text>
          ) : null,
        )}

        {area && <path d={area} fill="url(#wash)" />}

        {/* months after the selected one stay visible, but recede */}
        <path d={path(a, cursor, n - 1)} className="chart__line chart__line--ahead" />
        {others.map((o) => (
          <path key={`ahead-${o.color}`} d={path(o.vals, cursor, n - 1)} className="chart__line chart__line--ahead" />
        ))}
        {others.map((o) => (
          <path key={o.color} d={path(o.vals, 0, cursor)} className="chart__line" stroke={o.color} />
        ))}
        <path d={path(a, 0, cursor)} className="chart__line" stroke="var(--ink)" />

        {alerts.map((al) => {
          const i = months.indexOf(al.month);
          if (i < 0 || !Number.isFinite(a[i])) return null;
          return (
            <circle
              key={`alert-${al.month}`}
              cx={x(i)}
              cy={y(a[i])}
              r={5}
              className="chart__alert"
              stroke={toneColor(STATE_META[al.state_to].tone)}
            />
          );
        })}

        {hover != null && hover !== cursor && (
          <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={y(0)} className="chart__crosshair" />
        )}
        {cursor >= 0 && (
          <line x1={x(cursor)} x2={x(cursor)} y1={M.top} y2={y(0)} className="chart__cursor" />
        )}
        {others.map(
          (o) =>
            Number.isFinite(o.vals[cursor]) && (
              <circle
                key={o.color}
                cx={x(cursor)}
                cy={y(o.vals[cursor])}
                r={4.5}
                className="chart__dot"
                fill={o.color}
              />
            ),
        )}
        {Number.isFinite(a[cursor]) && (
          <circle cx={x(cursor)} cy={y(a[cursor])} r={4.5} className="chart__dot" fill="var(--ink)" />
        )}
        {endLabels.map((l, i) => (
          <text key={i} x={x(cursor) + 10} y={l.py + 4} className="chart__end" fill={l.color}>
            {l.v.toFixed(0)}
          </text>
        ))}
      </svg>

      {hover != null && (
        <div
          className="tooltip"
          style={{
            left: x(hover),
            transform: `translateX(${hover > n * 0.7 ? "calc(-100% - 12px)" : "12px"})`,
          }}
        >
          <div className="tooltip__title">{monthLong(months[hover])}</div>
          {[
            { s: primary, v: a[hover], color: "var(--ink)" },
            ...others.map((o) => ({ s: o, v: o.vals[hover], color: o.color })),
          ].map(({ s, v, color }) => (
            <div className="tooltip__row" key={color}>
              <span className="key" style={{ background: color }} />
              <strong>{Number.isFinite(v) ? v.toFixed(0) : "-"}</strong>
              <span>{s.name}</span>
            </div>
          ))}
          {hoverAlert && (
            <div className="tooltip__note">
              Alert: {STATE_META[hoverAlert.state_from].label} to{" "}
              {STATE_META[hoverAlert.state_to].label}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
