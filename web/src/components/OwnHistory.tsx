import { monthLong, monthShort } from "../lib/format";
import type { ScoreRow } from "../lib/types";
import { useTween } from "../lib/useTween";

interface OwnHistoryProps {
  /** The whole history of the group, sorted by month. */
  history: ScoreRow[];
  month: string;
}

const R = 100;
const CX = 150;
const CY = 146;

const pt = (deg: number, r = R) => [
  CX + r * Math.cos((deg * Math.PI) / 180),
  CY - r * Math.sin((deg * Math.PI) / 180),
];

const arc = (from: number, to: number) => {
  const [x1, y1] = pt(from);
  const [x2, y2] = pt(to);
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${R} ${R} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`;
};

// Thirds of the group's own range, a degree of surface between them.
const ZONES = [
  { d: arc(180, 121), color: "var(--bad)", label: "low", at: 150, anchor: "end" },
  { d: arc(119, 61), color: "var(--warn)", label: "mid", at: 90, anchor: "middle" },
  { d: arc(59, 0), color: "var(--good)", label: "high", at: 30, anchor: "start" },
] as const;

const ZONE_LABEL = ["low in its range", "mid of its range", "high in its range"];

function suffix(n: number): string {
  const rest = n % 100;
  if (rest >= 11 && rest <= 13) return "th";
  return ["th", "st", "nd", "rd"][n % 10] ?? "th";
}

const ordinal = (n: number) => `${n}${suffix(n)}`;

/** Position counted from the best month down, so 1st is the group's own record. */
function rankOf(values: number[], v: number): number {
  return values.filter((x) => x > v).length + 1;
}

export function OwnHistory({ history, month }: OwnHistoryProps) {
  const measured = history.filter((s): s is ScoreRow & { level: number } => s.level != null && Number.isFinite(s.level) && (s.localScoring != null || s.state !== "not_enough_data"));
  const today = measured.find((s) => s.month === month);
  const levels = measured.map((s) => s.level);
  const lo = levels.length ? Math.min(...levels) : 0;
  const hi = levels.length ? Math.max(...levels) : 0;
  const frac = today && hi > lo ? (today.level - lo) / (hi - lo) : 0.5;
  const [needle, shown] = useTween([frac, today?.level ?? NaN]);

  if (measured.length < 2 || !today) {
    return (
      <section>
        <div className="section-head">
          <h2>Its place in its own history</h2>
          <span className="hint">own range, not the portfolio</span>
        </div>
        <p className="empty">
          No reading in {monthLong(month)}: placing a month needs at least two scored months and an available score for the selected month.
        </p>
      </section>
    );
  }

  const worst = measured.reduce((a, b) => (b.level < a.level ? b : a));
  const best = measured.reduce((a, b) => (b.level > a.level ? b : a));
  const rank = rankOf(levels, today.level);
  const beaten = measured.length - rank;
  const zone = Math.min(2, Math.floor(frac * 3));

  const isLow = rank > measured.length / 2;
  const idx = measured.findIndex((s) => s.month === month);
  let streak = 0;
  for (let j = idx - 1; j >= 0; j--) {
    const clears = isLow ? measured[j].level > today.level : measured[j].level < today.level;
    if (!clears) break;
    streak += 1;
  }

  const place = (level: number) => 180 - (hi > lo ? (level - lo) / (hi - lo) : 0.5) * 180;
  const needleDeg = 180 - needle * 180;
  const needlePath = [pt(needleDeg, 90), pt(needleDeg + 90, 2.5), pt(needleDeg - 90, 2.5)]
    .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");

  return (
    <section className="own">
      <div className="section-head">
        <h2>Its place in its own history</h2>
        <span className="hint">own range, not the portfolio</span>
      </div>
      <p className="own__lede">
        Measured against its own {measured.length} scored months, not against the rest of the
        portfolio. A 65 can be its ceiling or its floor.
      </p>

      <div className="own__top">
        <figure className="own__gauge">
          <svg
            viewBox="0 0 300 194"
            role="img"
            aria-label={`Level ${today.level.toFixed(1)}, ${ordinal(rank)} of its ${measured.length} scored months`}
          >
            {ZONES.map((z, k) => (
              <path
                key={z.label}
                d={z.d}
                stroke={k === zone ? z.color : "var(--line-strong)"}
                strokeWidth="6"
                fill="none"
              />
            ))}
            {measured.map((s) => {
              const [x1, y1] = pt(place(s.level), 108);
              const [x2, y2] = pt(place(s.level), s.month === month ? 117 : 114);
              return (
                <line
                  key={s.month}
                  className={`own__tick${s.month === month ? " is-today" : ""}`}
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                />
              );
            })}
            {ZONES.map((z, k) => {
              const [x, y] = pt(z.at, 134);
              return (
                <text
                  key={z.label}
                  className={`own__zone-name${k === zone ? " is-on" : ""}`}
                  x={x}
                  y={y}
                  textAnchor={z.anchor}
                >
                  {z.label}
                </text>
              );
            })}
            <polygon points={needlePath} fill="var(--ink)" />
            <circle cx={CX} cy={CY} r="5.5" fill="var(--ink)" />
            <circle cx={CX} cy={CY} r="1.75" fill="var(--surface)" />
            <text className="own__figure" x={CX} y="188" textAnchor="middle">
              {Number.isFinite(shown) ? shown.toFixed(1) : "-"}
            </text>
            <text className="own__end" x="50" y="168" textAnchor="middle">
              {lo.toFixed(1)}
            </text>
            <text className="own__end-note" x="50" y="184" textAnchor="middle">
              worst · {monthShort(worst.month)}
            </text>
            <text className="own__end" x="250" y="168" textAnchor="middle">
              {hi.toFixed(1)}
            </text>
            <text className="own__end-note" x="250" y="184" textAnchor="middle">
              best · {monthShort(best.month)}
            </text>
          </svg>
          <figcaption className="own__zone">
            <span className="state__dot" style={{ background: ZONES[zone].color }} />
            {ZONE_LABEL[zone]}
          </figcaption>
        </figure>

        <div className="own__read">
          <p className="own__rank">
            {rank}
            <span>
              {suffix(rank)} of {measured.length}
            </span>
          </p>
          <p>
            Its level today beats{" "}
            <strong>
              {beaten} of its {measured.length} scored months
            </strong>
            . The arc is not a grade: it runs from its own worst month to its own best,{" "}
            {(hi - lo).toFixed(1)} points apart. Each tick on it is one scored month.
          </p>
          {streak > 0 && (
            <p>
              {streak} {streak === 1 ? "month" : "months"} without being this{" "}
              {isLow ? "low" : "high"}.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
