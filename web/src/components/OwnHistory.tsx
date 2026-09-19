import { monthLong, monthShort } from "../lib/format";
import { PILLARS } from "../lib/meta";
import type { Pillar, ScoreRow } from "../lib/types";
import { useTween } from "../lib/useTween";

interface OwnHistoryProps {
  /** The whole history of the group, sorted by month. */
  history: ScoreRow[];
  month: string;
}

const R = 72;
const CX = 100;
const CY = 100;

const pt = (deg: number, r = R) => [
  CX + r * Math.cos((deg * Math.PI) / 180),
  CY - r * Math.sin((deg * Math.PI) / 180),
];

const arc = (from: number, to: number) => {
  const [x1, y1] = pt(from);
  const [x2, y2] = pt(to);
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${R} ${R} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`;
};

const ZONES = [
  { d: arc(180, 122), color: "var(--bad)" },
  { d: arc(118, 62), color: "var(--warn)" },
  { d: arc(58, 0), color: "var(--good)" },
];

const ZONE_LABEL = [
  { label: "low in its range", color: "var(--bad-ink)" },
  { label: "mid of its range", color: "var(--warn)" },
  { label: "high in its range", color: "var(--good-ink)" },
];

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

function pillarStrip(measured: ScoreRow[], today: ScoreRow, key: Pillar) {
  const points = measured
    .map((s) => ({ month: s.month, value: s[key] }))
    .filter((p): p is { month: string; value: number } => p.value != null);
  const value = today[key];
  if (points.length < 2 || value == null) return null;
  const values = points.map((p) => p.value);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  // A pillar that never moved has nothing to place or rank.
  if (hi === lo) return null;
  return { points, value, lo, hi, rank: rankOf(values, value) };
}

export function OwnHistory({ history, month }: OwnHistoryProps) {
  const measured = history.filter((s) => s.state !== "not_enough_data");
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
          No reading in {monthLong(month)}: the first five months of a group come out without
          enough history, and placing a month needs at least two scored ones.
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

  const needleTip = pt(180 - needle * 180, 52);

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
            viewBox="0 0 200 124"
            role="img"
            aria-label={`Level ${today.level.toFixed(1)}, ${ordinal(rank)} of its ${measured.length} scored months`}
          >
            {ZONES.map((z) => (
              <path
                key={z.d}
                d={z.d}
                stroke={z.color}
                strokeWidth="13"
                strokeLinecap="round"
                fill="none"
              />
            ))}
            <line
              x1={CX}
              y1={CY}
              x2={needleTip[0]}
              y2={needleTip[1]}
              stroke="var(--ink)"
              strokeWidth="2.5"
              strokeLinecap="round"
            />
            <circle cx={CX} cy={CY} r="4.5" fill="var(--ink)" />
            <text className="own__figure" x={CX} y="74" textAnchor="middle">
              {Number.isFinite(shown) ? shown.toFixed(1) : "-"}
            </text>
            <text className="own__end" x="18" y="120" textAnchor="start">
              {lo.toFixed(1)}
            </text>
            <text className="own__end" x="182" y="120" textAnchor="end">
              {hi.toFixed(1)}
            </text>
          </svg>
          <figcaption className="own__zone" style={{ color: ZONE_LABEL[zone].color }}>
            {ZONE_LABEL[zone].label}
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
            . The arc is not a grade: it runs from its own worst month to its own best.
          </p>
          {streak > 0 && (
            <p>
              {streak} {streak === 1 ? "month" : "months"} without being this{" "}
              {isLow ? "low" : "high"}.
            </p>
          )}
          <div className="own__stats">
            <span>
              worst {worst.level.toFixed(1)} · {monthShort(worst.month)}
            </span>
            <span>
              best {best.level.toFixed(1)} · {monthShort(best.month)}
            </span>
            <span>range {(hi - lo).toFixed(1)} pts</span>
          </div>
        </div>
      </div>

      <div className="own__strips">
        {PILLARS.map((p) => {
          const strip = pillarStrip(measured, today, p.key);
          if (!strip) return null;
          const place = (v: number) => (v - strip.lo) / (strip.hi - strip.lo);
          return (
            <div className="own__row" key={p.key}>
              <span className="own__label">
                {p.label}
                <span className="own__range">
                  {strip.lo.toFixed(1)} – {strip.hi.toFixed(1)} · today {strip.value.toFixed(1)}
                </span>
              </span>
              <span className="own__track">
                {strip.points.map((pointRow) => (
                  <span
                    key={pointRow.month}
                    className={`own__dot${pointRow.month === month ? " is-today" : ""}`}
                    // 12px clear of each end so the extreme months do not sit on the round cap.
                    style={{ left: `calc(12px + (100% - 24px) * ${place(pointRow.value)})` }}
                  />
                ))}
              </span>
              <span className="own__place">{ordinal(strip.rank)}</span>
            </div>
          );
        })}
      </div>

      <p className="own__note">
        Each dot on a strip is one of its {measured.length} scored months; the big one is today.
        The rank counts only the months the engine speaks about: the first five of every group come
        out without enough history and do not enter.
      </p>
    </section>
  );
}
