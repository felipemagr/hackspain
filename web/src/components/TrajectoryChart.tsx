import { useEffect, useRef, useState } from "react";
import { monthLong, monthShort } from "../lib/format";
import { alignMacro, type MacroSeries } from "../lib/macro";
import { SERIES_COLORS, STATE_META, toneColor } from "../lib/meta";
import type { AlertRow, ScoreRow } from "../lib/types";
import { useTween } from "../lib/useTween";
import { CHART_COLORS, DEFAULT_CHART, type ChartConfig } from "../lib/viewAgent";

export interface ChartSeries {
  name: string;
  history: ScoreRow[];
}

interface TrajectoryChartProps {
  months: string[];
  month: string;
  onMonth: (month: string) => void;
  primary: ChartSeries;
  /** Market health levels behind the score, on the same 0-100 axis. Empty when none is picked. */
  macros: MacroSeries[];
  compare?: (ChartSeries | null)[];
  /** The group's own companies, drawn as quiet context lines behind the score. */
  members?: ChartSeries[];
  /** Name of the member to lift out of the context lines. */
  hotMember?: string;
  /** Called with the member nearest the pointer, or undefined when none is close. */
  onHotMember?: (name: string | undefined) => void;
  alerts: AlertRow[];
  config?: ChartConfig;
}

const H = 300;
const M = { top: 16, right: 44, bottom: 28, left: 96 };
const THRESHOLDS: Record<number, string> = { 70: "Healthy", 40: "Vulnerable" };
// Narrowest zoom, in months between the two ends of the axis.
const MIN_SPAN = 2;
// How close, in pixels, the pointer must be to a member line to pick it.
const PICK_RADIUS = 8;
export const MACRO_COLORS = ["var(--series-3)", "var(--series-5)", "var(--series-4)", "var(--series-2)"];

function align(months: string[], history: ScoreRow[]): number[] {
  const byMonth = new Map(history.map((s) => [s.month, s.level]));
  return months.map((m) => byMonth.get(m) ?? NaN);
}

export function TrajectoryChart({
  months: timeline,
  month,
  onMonth,
  primary,
  macros,
  compare = [],
  members = [],
  hotMember,
  onHotMember,
  alerts,
  config = DEFAULT_CHART,
}: TrajectoryChartProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(880);
  const [hover, setHover] = useState<number | null>(null);
  // Kept as months, not indexes: the axis start moves with the group's own history.
  const [zoom, setZoom] = useState<[string, string] | null>(null);
  const [drag, setDrag] = useState<{ from: number; to: number } | null>(null);
  const press = useRef<{ index: number; clientX: number } | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // The axis opens where the oldest drawn series starts, not where the portfolio does.
  const oldest = [primary, ...compare].flatMap((series) => series?.history[0]?.month ?? []).sort()[0];
  const fullMonths = oldest ? timeline.slice(timeline.indexOf(oldest)) : timeline;
  const periodStart = config.months
    ? new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - config.months, 1)).toISOString().slice(0, 10)
    : "";
  const months = config.months
    ? fullMonths.filter(value => value >= periodStart && value <= month)
    : fullMonths;
  const primaryColor = CHART_COLORS[config.color];
  const n = months.length;
  const cursor = months.indexOf(month);
  const target = align(months, primary.history);
  const a = useTween(target);
  const macroLines = macros.map((series, index) => ({
    series,
    color: MACRO_COLORS[index % MACRO_COLORS.length],
    vals: alignMacro(series, months),
  }));
  const compareTargets = compare.map(series => series ? align(months, series.history) : months.map(() => NaN));
  const flat = useTween(compareTargets.flat());
  const others = compare.flatMap((series, index) =>
    series ? [{ ...series, color: SERIES_COLORS[index], vals: flat.slice(index * n, (index + 1) * n) }] : [],
  );

  const memberLines = members.map(series => ({ ...series, vals: align(months, series.history) }));
  const hot = memberLines.find(series => series.name === hotMember);

  const zi = zoom ? [months.indexOf(zoom[0]), months.indexOf(zoom[1])] : [];
  const [i0, i1] = zi[0] >= 0 && zi[1] > zi[0] ? zi : [0, Math.max(n - 1, 0)];
  const zoomed = i0 > 0 || i1 < n - 1;
  // Zoomed in, the score axis closes on what is drawn; the full window keeps the fixed 0 to 100.
  const seen = [target, ...macroLines.map((line) => line.vals), ...compareTargets, ...memberLines.map((line) => line.vals)]
    .flatMap((vals) => vals.slice(i0, i1 + 1))
    .filter(Number.isFinite);
  const yLo =
    zoomed && config.type !== "bar" && seen.length
      ? Math.max(0, Math.floor((Math.min(...seen) - 5) / 10) * 10)
      : 0;
  const yHi =
    zoomed && seen.length
      ? Math.min(100, Math.ceil((Math.max(...seen) + 5) / 10) * 10)
      : 100;
  const [v0, v1, lo, hi] = useTween([i0, i1, yLo, yHi]);

  const bottom = H - M.bottom;
  const plotW = Math.max(0, width - M.left - M.right);
  const slotWidth = plotW / Math.max(v1 - v0 + 1, 1);
  const x = (i: number) => M.left + (config.type === "bar"
    ? (i - v0 + .5) * slotWidth
    : ((i - v0) / Math.max(v1 - v0, 1)) * plotW);
  const y = (v: number) =>
    M.top + (1 - (v - lo) / (hi - lo)) * (bottom - M.top);
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
    const fraction = (clientX - rect.left - M.left) / Math.max(plotW, 1);
    const i = config.type === "bar"
      ? i0 + Math.floor(fraction * (i1 - i0 + 1))
      : Math.round(i0 + fraction * (i1 - i0));
    return Math.max(i0, Math.min(i1, i));
  };
  const setRange = (from: number, to: number) =>
    setZoom(
      from <= 0 && to >= n - 1
        ? null
        : [months[Math.max(0, from)], months[Math.min(n - 1, to)]],
    );
  // Zooms around the selected month while it is on screen, around the middle otherwise.
  const zoomBy = (factor: number) => {
    const size = Math.max(MIN_SPAN, Math.round((i1 - i0) * factor));
    const mid = cursor >= i0 && cursor <= i1 ? cursor : (i0 + i1) / 2;
    const from = Math.max(
      0,
      Math.min(n - 1 - size, Math.round(mid - size / 2)),
    );
    setRange(from, from + size);
  };

  const areaPath = (values: number[]) => {
    let result = "";
    let start = -1;
    for (let index = 0; index <= cursor + 1; index++) {
      if (index <= cursor && Number.isFinite(values[index])) {
        if (start < 0) start = index;
      } else if (start >= 0) {
        result += `${path(values, start, index - 1)}L${x(index - 1)},${bottom}L${x(start)},${bottom}Z`;
        start = -1;
      }
    }
    return result;
  };
  const cursorSeen = cursor >= i0 && cursor <= i1;
  const endLabels = [
    { v: a[cursor], color: primaryColor },
    ...others.map(series => ({ v: series.vals[cursor], color: series.color })),
    ...macroLines.map((line) => ({ v: line.vals[cursor], color: line.color })),
  ]
    .filter((l) => cursorSeen && Number.isFinite(l.v))
    .map((l) => ({ ...l, py: y(l.v) }))
    .sort((p, q) => p.py - q.py);
  // End labels closer than a line of text get pushed apart, top to bottom, then back inside the plot.
  for (let k = 1; k < endLabels.length; k++) {
    endLabels[k].py = Math.max(endLabels[k].py, endLabels[k - 1].py + 14);
  }
  const overflow = endLabels.length
    ? endLabels[endLabels.length - 1].py - bottom
    : 0;
  if (overflow > 0) endLabels.forEach((l) => (l.py -= overflow));

  const yTicks = [yHi, 70, 40, yLo].filter(
    (t, k, all) => t >= yLo && t <= yHi && all.indexOf(t) === k,
  );
  const every = i1 - i0 > 12 ? 3 : i1 - i0 > 6 ? 2 : 1;

  const activeHover = hover != null && hover >= i0 && hover <= i1 && hover < n ? hover : null;
  const hoverAlert = activeHover != null ? alerts.find((al) => al.month === months[activeHover]) : undefined;
  const barSeries = [{ name: primary.name, color: primaryColor, vals: a }, ...others];
  const barWidth = Math.min(24, slotWidth * .7 / barSeries.length);
  const barGap = Math.min(1, barWidth * .15);

  return (
    <div className="chart" ref={wrap}>
      <svg
        width={width}
        height={H}
        role="img"
        aria-label={`${config.type} chart of ${primary.name}${others.map(series => ` and ${series.name}`).join("")} over ${n} months${macros.length ? `, against ${macros.map((series) => series.name).join(", ")}` : ""}. Click to move to a month, drag across months to zoom in.`}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          press.current = { index: indexAt(e.clientX), clientX: e.clientX };
        }}
        onPointerMove={(e) => {
          const i = indexAt(e.clientX);
          setHover(i);
          if (onHotMember) {
            const rect = e.currentTarget.getBoundingClientRect();
            const px = e.clientX - rect.left;
            const py = e.clientY - rect.top;
            // Distance to the drawn segments around the pointer, not to the snapped month.
            const at = Math.floor(v0 + ((px - M.left) / Math.max(plotW, 1)) * (v1 - v0));
            const gapTo = (vals: number[]) => {
              let best = Infinity;
              for (let k = Math.max(at - 1, 0); k <= Math.min(at + 1, cursor - 1); k++) {
                if (!Number.isFinite(vals[k]) || !Number.isFinite(vals[k + 1])) continue;
                const [ax, ay, bx, by] = [x(k), y(vals[k]), x(k + 1), y(vals[k + 1])];
                const t = Math.max(0, Math.min(1, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)));
                best = Math.min(best, Math.hypot(px - ax - t * (bx - ax), py - ay - t * (by - ay)));
              }
              return best;
            };
            // Only a line within reach of the pointer is picked, so the group's own line stays readable.
            const near = memberLines
              .map(series => ({ name: series.name, gap: gapTo(series.vals) }))
              .filter(pick => pick.gap <= PICK_RADIUS)
              .sort((p, q) => p.gap - q.gap)[0];
            onHotMember(near?.name);
          }
          const p = press.current;
          if (p && (drag || Math.abs(e.clientX - p.clientX) > 4))
            setDrag({ from: p.index, to: i });
        }}
        onPointerUp={(e) => {
          const p = press.current;
          press.current = null;
          setDrag(null);
          if (!p) return;
          if (!drag) { if (n) onMonth(months[indexAt(e.clientX)]); return; }
          const from = Math.min(drag.from, drag.to);
          const to = Math.max(drag.from, drag.to);
          // A drag shorter than the narrowest zoom still opens a readable window.
          if (to > from) setRange(from, Math.max(to, from + MIN_SPAN));
        }}
        onPointerCancel={() => {
          press.current = null;
          setDrag(null);
        }}
        onPointerLeave={() => {
          setHover(null);
          onHotMember?.(undefined);
        }}
        onDoubleClick={() => setZoom(null)}
      >
        <defs>
          <linearGradient id="wash" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={primaryColor} stopOpacity="0.07" />
            <stop offset="1" stopColor={primaryColor} stopOpacity="0" />
          </linearGradient>
          {/* A little wider than the plot, so a dot on the edge month is not cut in half. */}
          <clipPath id="plot">
            <rect
              x={M.left - 7}
              y={M.top - 7}
              width={Math.max(plotW, 0) + 14}
              height={bottom - M.top + 14}
            />
          </clipPath>
          <clipPath id="bar-plot">
            <rect x={M.left} y={M.top} width={plotW} height={bottom - M.top} />
          </clipPath>
        </defs>

        {config.show_grid && [M.top, bottom].map((py) => (
          <line
            key={py}
            x1={M.left}
            x2={width - M.right}
            y1={py}
            y2={py}
            className="chart__grid"
          />
        ))}
        {config.show_grid && yTicks
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
          <text
            key={t}
            x={M.left - 10}
            y={y(t) + 4}
            textAnchor="end"
            className="chart__tick"
          >
            {primary.history.some(row => row.localScoring) ? "" : THRESHOLDS[t]} {t}
          </text>
        ))}
        {months.map((m, i) =>
          i % every === 0 && i >= i0 && i <= i1 ? (
            <text
              key={m}
              x={x(i)}
              y={H - 6}
              textAnchor="middle"
              className="chart__tick"
            >
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

          {macroLines.map((line) => (
            <path
              key={line.series.id}
              d={path(line.vals, 0, n - 1)}
              className="chart__line chart__line--macro"
              stroke={line.color}
            />
          ))}

          {config.type === "area" && <>
            <path d={areaPath(a)} fill="url(#wash)" />
            {/* One comparison reads better with a wash under it; several washes overlap into mud. */}
            {others.length === 1 && <path d={areaPath(others[0].vals)} fill={others[0].color} opacity={.06} />}
          </>}

          {config.type !== "bar" && memberLines.map(series => series !== hot && (
            <path key={series.name} d={path(series.vals, 0, cursor)} className="chart__line chart__line--member" />
          ))}
          {config.type !== "bar" && hot && <path d={path(hot.vals, 0, cursor)} className="chart__line chart__line--member is-hot" />}

          {config.type !== "bar" && <>
            {/* months after the selected one stay visible, but recede */}
            <path d={path(a, cursor, n - 1)} className="chart__line chart__line--ahead" />
            {others.map(series => <path key={`ahead-${series.color}`} d={path(series.vals, cursor, n - 1)} className="chart__line chart__line--ahead" />)}
            {others.map(series => <path key={series.color} d={path(series.vals, 0, cursor)} className="chart__line" stroke={series.color} />)}
            <path d={path(a, 0, cursor)} className="chart__line" stroke={primaryColor} />
          </>}
          {config.type === "bar" && <g clipPath="url(#bar-plot)">
            {barSeries.flatMap((series, seriesIndex) => series.vals.map((value, index) =>
              Number.isFinite(value) && index >= i0 && index <= i1
                ? <rect key={`${seriesIndex}-${index}`} x={x(index) - barWidth * barSeries.length / 2 + seriesIndex * barWidth}
                    y={y(value)} width={barWidth - barGap} height={Math.max(0, bottom - y(value))}
                    fill={series.color} opacity={index > cursor ? .25 : .85} />
                : null))}
          </g>}

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

          {activeHover != null && activeHover !== cursor && (
            <line
              x1={x(activeHover)}
              x2={x(activeHover)}
              y1={M.top}
              y2={bottom}
              className="chart__crosshair"
            />
          )}
          {cursor >= 0 && (
            <line
              x1={x(cursor)}
              x2={x(cursor)}
              y1={M.top}
              y2={bottom}
              className="chart__cursor"
            />
          )}
          {config.type !== "bar" && Number.isFinite(a[cursor]) && (
            <circle
              cx={x(cursor)}
              cy={y(a[cursor])}
              r={4.5}
              className="chart__dot"
              fill={primaryColor}
            />
          )}
          {config.type !== "bar" && others.map(series => Number.isFinite(series.vals[cursor]) && (
            <circle key={series.color} cx={x(cursor)} cy={y(series.vals[cursor])} r={4.5} className="chart__dot" fill={series.color} />
          ))}
        </g>
        {config.type !== "bar" && endLabels.map((l, i) => (
          <text
            key={i}
            x={x(cursor) + 10}
            y={l.py + 4}
            className="chart__end"
            fill={l.color}
          >
            {l.v.toFixed(0)}
          </text>
        ))}
      </svg>

      {activeHover != null && (
        <div
          className="tooltip"
          style={{
            left: x(activeHover),
            transform: `translateX(${activeHover - i0 > (i1 - i0) * 0.7 ? "calc(-100% - 12px)" : "12px"})`,
          }}
        >
          <div className="tooltip__title">{monthLong(months[activeHover])}</div>
          {[
            { s: primary, v: a[activeHover], color: primaryColor },
            ...others.map(series => ({ s: series, v: series.vals[activeHover], color: series.color })),
          ].map(
            ({ s, v, color }) => (
              <div className="tooltip__row" key={color}>
                <span className="key" style={{ background: color }} />
                <strong>{Number.isFinite(v) ? v.toFixed(0) : "-"}</strong>
                <span>{s.name}</span>
              </div>
            ),
          )}
          {hot && Number.isFinite(hot.vals[activeHover]) && (
            <div className="tooltip__row">
              <span className="key key--member" />
              <strong>{hot.vals[activeHover].toFixed(0)}</strong>
              <span>{hot.name}</span>
            </div>
          )}
          {macroLines.map((line) => Number.isFinite(line.vals[activeHover]) && (
            <div className="tooltip__row" key={line.series.id}>
              <span
                className="key key--dashed"
                style={{ background: line.color }}
              />
              <strong>{line.vals[activeHover].toFixed(0)}</strong>
              <span>{line.series.name}</span>
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
          {zoomed
            ? `${monthLong(months[i0])} to ${monthLong(months[i1])}`
            : "Drag across the chart to zoom"}
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
