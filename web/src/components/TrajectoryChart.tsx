import { useEffect, useRef, useState } from "react";
import { fmtEarly, monthLong, monthShort } from "../lib/format";
import { STATE_META, toneColor } from "../lib/meta";
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
  compare?: ChartSeries;
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
  const b = useTween(compare ? align(months, compare.history) : []);

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
    !compare && first >= 0 && cursor > first
      ? `${path(a, first, cursor)}L${x(cursor).toFixed(1)},${y(0)}L${x(first).toFixed(1)},${y(0)}Z`
      : "";
  const endLabels = [
    { v: a[cursor], color: "var(--ink)" },
    ...(compare ? [{ v: b[cursor], color: "var(--series-2)" }] : []),
  ]
    .filter((l) => Number.isFinite(l.v))
    .map((l) => ({ ...l, py: y(l.v) }));
  // Two end labels closer than a line of text get pushed apart.
  if (endLabels.length === 2 && Math.abs(endLabels[0].py - endLabels[1].py) < 14) {
    const mid = (endLabels[0].py + endLabels[1].py) / 2;
    const top = endLabels[0].v >= endLabels[1].v ? 0 : 1;
    endLabels[top].py = mid - 7;
    endLabels[1 - top].py = mid + 7;
  }

  const hoverAlert = hover != null ? alerts.find((al) => al.month === months[hover]) : undefined;

  return (
    <div className="chart" ref={wrap}>
      <svg
        width={width}
        height={H}
        role="img"
        aria-label={`Health score of ${primary.name}${
          compare ? ` and ${compare.name}` : ""
        } over ${n} months. Click to move to a month.`}
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
        {compare && <path d={path(b, cursor, n - 1)} className="chart__line chart__line--ahead" />}
        {compare && (
          <path d={path(b, 0, cursor)} className="chart__line" stroke="var(--series-2)" />
        )}
        <path d={path(a, 0, cursor)} className="chart__line" stroke="var(--ink)" />

        {/* how early the monitor spoke: from the alert to the tier change it preceded */}
        {alerts
          .filter((al) => al.tier_change_month && fmtEarly(al.anticipation_months))
          .map((al) => {
            const i1 = months.indexOf(al.month);
            const i2 = months.indexOf(al.tier_change_month!);
            if (i1 < 0 || i2 < 0) return null;
            const by = y(0) - 12;
            return (
              <g key={`early-${al.month}`} className="chart__early">
                <path d={`M${x(i1)},${by - 4}V${by}H${x(i2)}V${by - 4}`} />
                <text x={(x(i1) + x(i2)) / 2} y={by - 7} textAnchor="middle">
                  seen {fmtEarly(al.anticipation_months)}
                </text>
              </g>
            );
          })}

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
        {compare && Number.isFinite(b[cursor]) && (
          <circle cx={x(cursor)} cy={y(b[cursor])} r={4.5} className="chart__dot" fill="var(--series-2)" />
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
            ...(compare ? [{ s: compare, v: b[hover], color: "var(--series-2)" }] : []),
          ].map(({ s, v, color }) => (
            <div className="tooltip__row" key={s.name}>
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
