import { fmtSigned } from "../lib/format";
import { PILLARS } from "../lib/meta";
import type { DriverRow, ScoreRow } from "../lib/types";
import { scoreLabels, type ScoreNode, type Weights } from "../lib/scoring";

interface PillarsProps {
  score: ScoreRow;
  drivers: DriverRow[];
  weights?: Weights;
  cashDate?: string;
}

function LocalRows({ nodes, weights, cashDate }: { nodes: Record<string, ScoreNode>; weights: Record<string, number>; cashDate?: string }) {
  const nominal = Object.values(weights).reduce((sum, weight) => sum + weight, 0);
  const available = Object.entries(weights).reduce((sum, [key, weight]) => sum + (nodes[key]?.score != null ? weight : 0), 0);
  return <>{Object.entries(weights).map(([key, weight]) => {
    const node = nodes[key];
    const effective = node?.score != null && available > 0 ? weight / available * 100 : null;
    const raw = node?.raw_value;
    const metric = raw == null ? "-" : key === "liquidity" ? `${raw.toFixed(1)} d` : key === "debt_coverage" ? `${raw.toFixed(2)}×` : key === "generation" || key === "activity" ? `${(raw * 100).toFixed(1)}%` : key === "conversion" ? `${raw.toFixed(1)} pp` : key === "receivables" || key === "payables" ? `${raw.toFixed(1)}/100` : raw.toFixed(2);
    return <tr key={key}><th scope="row">{scoreLabels[key] ?? key}<span className="pillars__indicator">{key === "liquidity" && cashDate ? `Cash snapshot: ${cashDate}` : node?.reason?.replaceAll("_", " ")}</span></th><td>{effective == null ? "-" : `${effective.toFixed(1)}%`}<span className="pillars__base">base {nominal > 0 ? (weight / nominal * 100).toFixed(1) : "-"}%</span></td><td className="pillars__score">{node?.score == null ? "-" : node.score.toFixed(1)}</td><td>{metric}</td><td>{node?.confidence == null ? "-" : `${node.confidence.toFixed(0)}%`}</td></tr>;
  })}</>;
}

export function Pillars({ score, drivers, weights, cashDate }: PillarsProps) {
  if (score.localScoring && weights) return <>
    <table className="pillars"><thead><tr><th scope="col">Pillar</th><th scope="col">Weight</th><th scope="col">Score</th><th scope="col">Metric</th><th scope="col">Confidence</th></tr></thead><tbody><LocalRows nodes={score.localScoring.families} weights={weights.level} cashDate={cashDate} /></tbody></table>
    <details><summary>Financial capacity breakdown</summary><table className="pillars"><thead><tr><th scope="col">Component</th><th scope="col">Weight</th><th scope="col">Score</th><th scope="col">Metric</th><th scope="col">Confidence</th></tr></thead><tbody><LocalRows nodes={score.localScoring.subscores} weights={weights.financial} /></tbody></table></details>
    <details><summary>Evolution breakdown</summary><table className="pillars"><thead><tr><th scope="col">Component</th><th scope="col">Weight</th><th scope="col">Score</th><th scope="col">Metric</th><th scope="col">Confidence</th></tr></thead><tbody><LocalRows nodes={score.localScoring.subscores} weights={weights.evolution} /></tbody></table></details>
  </>;
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
