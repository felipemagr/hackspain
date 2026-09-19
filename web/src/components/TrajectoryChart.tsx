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
const THRESHOLDS: Record<number, string> = { 70: "Healthy", 40: "Vulnerable" };
// Narrowest zoom, in months between the two ends of the axis.
const MIN_SPAN = 2;

function align(months: string[], history: ScoreRow[]): number[] {
  const byMonth = new Map(history.map((s) => [s.month, s.level]));
  return months.map((m) => byMonth.get(m) ?? NaN);
}

export function TrajectoryChart({
  months: timeline,
  month,
  onMonth,
  primary,
  compare,
  alerts,
}: TrajectoryChartProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(880);
  const [hover, setHover] = useState<number | null>(null);
  // Kept as months, not indexes: the axis start moves when a compared group comes or goes.
  const [zoom, setZoom] = useState<[string, string] | null>(null);
  const [drag, setDrag] = useState<{ from: number; to: number } | null>(null);
  const press = useRef<{ index: number; clientX: number } | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // The axis opens where the oldest drawn series starts, not where the portfolio does.
  const oldest = [primary, ...compare].flatMap((c) => c?.history[0]?.month ?? []).sort()[0];
  const months = oldest ? timeline.slice(timeline.indexOf(oldest)) : timeline;
  const n = months.length;
  const cursor = months.indexOf(month);
  const target = align(months, primary.history);
  const targets = compare.flatMap((c) => (c ? align(months, c.history) : months.map(() => NaN)));
  const a = useTween(target);
  // All slots tween as one flat array, so the hook count does not depend on the selection.
  const flat = useTween(targets);
  const others = compare.flatMap((c, k) =>
    c ? [{ ...c, color: SERIES_COLORS[k], vals: flat.slice(k * n, (k + 1) * n) }] : [],
  );

  const zi = zoom ? [months.indexOf(zoom[0]), months.indexOf(zoom[1])] : [];
  const [i0, i1] = zi[0] >= 0 && zi[1] > zi[0] ? zi : [0, Math.max(n - 1, 1)];
  const zoomed = i0 > 0 || i1 < n - 1;
  // Zoomed in, the score axis closes on what is drawn; the full window keeps the fixed 0 to 100.
  const seen = [target, ...compare.map((_, k) => targets.slice(k * n, (k + 1) * n))]
    .flatMap((vals) => vals.slice(i0, i1 + 1))
    .filter(Number.isFinite);
  const yLo = zoomed && seen.length ? Math.max(0, Math.floor((Math.min(...seen) - 5) / 10) * 10) : 0;
  const yHi = zoomed && seen.length ? Math.min(100, Math.ceil((Math.max(...seen) + 5) / 10) * 10) : 100;
  const [v0, v1, lo, hi] = useTween([i0, i1, yLo, yHi]);

  const bottom = H - M.bottom;
  const plotW = width - M.left - M.right;
  const x = (i: number) => M.left + ((i - v0) / (v1 - v0)) * plotW;
  const y = (v: number) => M.top + (1 - (v - lo) / (hi - lo)) * (bottom - M.top);
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
    const i = Math.round(i0 + ((clientX - rect.left - M.left) / plotW) * (i1 - i0));
    return Math.max(i0, Math.min(i1, i));
  };
  const setRange = (from: number, to: number) =>
    setZoom(from <= 0 && to >= n - 1 ? null : [months[Math.max(0, from)], months[Math.min(n - 1, to)]]);
  // Zooms around the selected month while it is on screen, around the middle otherwise.
  const zoomBy = (factor: number) => {
    const size = Math.max(MIN_SPAN, Math.round((i1 - i0) * factor));
    const mid = cursor >= i0 && cursor <= i1 ? cursor : (i0 + i1) / 2;
    const from = Math.max(0, Math.min(n - 1 - size, Math.round(mid - size / 2)));
    setRange(from, from + size);
  };

  const first = a.findIndex(Number.isFinite);
  const area =
    others.length === 0 && first >= 0 && cursor > first
      ? `${path(a, first, cursor)}L${x(cursor).toFixed(1)},${bottom}L${x(first).toFixed(1)},${bottom}Z`
      : "";
  const cursorSeen = cursor >= i0 && cursor <= i1;
  const endLabels = [
    { v: a[cursor], color: "var(--ink)" },
    ...others.map((o) => ({ v: o.vals[cursor], color: o.color })),
  ]
    .filter((l) => cursorSeen && Number.isFinite(l.v))
    .map((l) => ({ ...l, py: y(l.v) }))
    .sort((p, q) => p.py - q.py);
  // End labels closer than a line of text get pushed apart, top to bottom, then back inside the plot.
  for (let k = 1; k < endLabels.length; k++) {
    endLabels[k].py = Math.max(endLabels[k].py, endLabels[k - 1].py + 14);
  }
  const overflow = endLabels.length ? endLabels[endLabels.length - 1].py - bottom : 0;
  if (overflow > 0) endLabels.forEach((l) => (l.py -= overflow));

  const yTicks = [yHi, 70, 40, yLo].filter((t, k, all) => t >= yLo && t <= yHi && all.indexOf(t) === k);
  const every = i1 - i0 > 12 ? 3 : i1 - i0 > 6 ? 2 : 1;

  const hoverAlert = hover != null ? alerts.find((al) => al.month === months[hover]) : undefined;

  return (
    <div className="chart" ref={wrap}>
      <svg
        width={width}
        height={H}
        role="img"
        aria-label={`Health score of ${primary.name}${others
          .map((o) => ` and ${o.name}`)
          .join("")} over ${n} months. Click to move to a month, drag across months to zoom in.`}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          press.current = { index: indexAt(e.clientX), clientX: e.clientX };
        }}
        onPointerMove={(e) => {
          const i = indexAt(e.clientX);
          setHover(i);
          const p = press.current;
          if (p && (drag || Math.abs(e.clientX - p.clientX) > 4)) setDrag({ from: p.index, to: i });
        }}
        onPointerUp={(e) => {
          const p = press.current;
          press.current = null;
          setDrag(null);
          if (!p) return;
          if (!drag) return onMonth(months[indexAt(e.clientX)]);
          const from = Math.min(drag.from, drag.to);
          const to = Math.max(drag.from, drag.to);
          // A drag shorter than the narrowest zoom still opens a readable window.
          if (to > from) setRange(from, Math.max(to, from + MIN_SPAN));
        }}
        onPointerCancel={() => {
          press.current = null;
          setDrag(null);
        }}
        onPointerLeave={() => setHover(null)}
        onDoubleClick={() => setZoom(null)}
      >
        <defs>
          <linearGradient id="wash" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--ink)" stopOpacity="0.07" />
            <stop offset="1" stopColor="var(--ink)" stopOpacity="0" />
          </linearGradient>
          {/* A little wider than the plot, so a dot on the edge month is not cut in half. */}
          <clipPath id="plot">
            <rect x={M.left - 7} y={M.top - 7} width={Math.max(plotW, 0) + 14} height={bottom - M.top + 14} />
          </clipPath>
        </defs>

        {[M.top, bottom].map((py) => (
          <line key={py} x1={M.left} x2={width - M.right} y1={py} y2={py} className="chart__grid" />
        ))}
        {yTicks
          .filter((t) => THRESHOLDS[t] && t > yLo && t < yHi)
          .map((t) => (
            <line
              key={t}
              x1={M.left}
              x2={width - M.right}
              y1={y(t)}
              y2={y(t)}
              className="chart__threshold"
            />
          ))}
        {yTicks.map((t) => (
          <text key={t} x={M.left - 10} y={y(t) + 4} textAnchor="end" className="chart__tick">
            {THRESHOLDS[t]} {t}
          </text>
        ))}
        {months.map((m, i) =>
          i % every === 0 && i >= i0 && i <= i1 ? (
            <text key={m} x={x(i)} y={H - 6} textAnchor="middle" className="chart__tick">
              {monthShort(m)}
            </text>
          ) : null,
        )}

        <g clipPath="url(#plot)">
        {drag && (
          <rect
            x={x(Math.min(drag.from, drag.to))}
            y={M.top}
            width={Math.abs(x(drag.to) - x(drag.from))}
            height={bottom - M.top}
            className="chart__brush"
          />
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
          <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={bottom} className="chart__crosshair" />
        )}
        {cursor >= 0 && (
          <line x1={x(cursor)} x2={x(cursor)} y1={M.top} y2={bottom} className="chart__cursor" />
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
        </g>
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
            transform: `translateX(${hover - i0 > (i1 - i0) * 0.7 ? "calc(-100% - 12px)" : "12px"})`,
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

      <div className="chart__zoom">
        <span className="chart__range">
          {zoomed ? `${monthLong(months[i0])} to ${monthLong(months[i1])}` : "Drag across the chart to zoom"}
        </span>
        {zoomed && (
          <button className="link" onClick={() => setZoom(null)}>
            Reset
          </button>
        )}
        <button
          className="icon-button"
          aria-label="Zoom out"
          title="Zoom out"
          disabled={!zoomed}
          onClick={() => zoomBy(2)}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
            <path d="M2.5 7h9" />
          </svg>
        </button>
        <button
          className="icon-button"
          aria-label="Zoom in"
          title="Zoom in"
          disabled={i1 - i0 <= MIN_SPAN}
          onClick={() => zoomBy(0.5)}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
            <path d="M2.5 7h9M7 2.5v9" />
          </svg>
        </button>
      </div>
    </div>
  );
}
