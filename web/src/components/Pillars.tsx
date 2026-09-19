import { fmtSigned } from "../lib/format";
import { PILLARS } from "../lib/meta";
import type { DriverRow, ScoreRow } from "../lib/types";

interface PillarsProps {
  score: ScoreRow;
  drivers: DriverRow[];
}

export function Pillars({ score, drivers }: PillarsProps) {
  return (
    <table className="pillars">
      <thead>
        <tr>
          <th scope="col">Pillar</th>
          <th scope="col">Weight</th>
          <th scope="col">Score</th>
          <th scope="col">Metric</th>
          <th scope="col">Moved</th>
        </tr>
      </thead>
      <tbody>
        {PILLARS.map((p) => {
          const value = score[p.key];
          const driver = drivers.find((d) => d.pillar === p.key);
          const moved = driver?.delta_contribution ?? null;
          // Missing pillars have their weight spread over the rest, so what a pillar really
          // weighs is its base weight over the coverage.
          const effective = value == null ? 0 : p.weight / score.coverage;
          return (
            <tr key={p.key}>
              <th scope="row">
                {p.label}
                <span className="pillars__indicator">{p.indicator}</span>
              </th>
              <td>
                {value == null ? "-" : `${effective.toFixed(1)}%`}
                {value != null && Math.abs(effective - p.weight) > 0.05 && (
                  <span className="pillars__base">base {p.weight}%</span>
                )}
              </td>
              <td className="pillars__score">{value == null ? "-" : value.toFixed(1)}</td>
              <td>{p.metric(score) ?? "-"}</td>
              <td
                className={
                  moved == null || Math.abs(moved) < 0.05 ? "" : moved > 0 ? "is-up" : "is-down"
                }
              >
                {moved == null ? "" : fmtSigned(moved, 2)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
