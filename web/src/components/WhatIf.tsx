import { useEffect, useState } from "react";
import { fmtSigned } from "../lib/format";
import { PILLARS } from "../lib/meta";
import type { Pillar, ScoreRow } from "../lib/types";
import { useTween } from "../lib/useTween";

interface WhatIfProps {
  score: ScoreRow;
}

type Moved = Partial<Record<Pillar, number>>;

/** The engine contract: 50 + sum(w' * (pillar - 50)) over the pillars the group can compute. */
function levelOf(values: Map<Pillar, number>, coverage: number): number {
  let level = 50;
  for (const p of PILLARS) {
    const v = values.get(p.key);
    if (v != null) level += ((p.weight / 100) / coverage) * (v - 50);
  }
  const liq = values.get("liquidity");
  const pay = values.get("payment_discipline");
  const capped = ((liq != null && liq < 25) || (pay != null && pay < 25)) && level > 50;
  return capped ? 50 : level;
}

export function WhatIf({ score }: WhatIfProps) {
  const [moved, setMoved] = useState<Moved>({});
  // A different group or month is a different starting point: drop the moves.
  useEffect(() => setMoved({}), [score.group_id, score.month]);

  const available = PILLARS.filter((p) => score[p.key] != null);
  if (available.length === 0) return null;

  const coverage = available.reduce((sum, p) => sum + p.weight / 100, 0);
  const values = new Map<Pillar, number>(
    available.map((p) => [p.key, moved[p.key] ?? (score[p.key] as number)]),
  );
  const level = levelOf(values, coverage);
  const delta = level - score.level;
  const touched = Object.keys(moved).length > 0;
  const way = Math.abs(delta) < 0.05 ? "" : delta > 0 ? "is-up" : "is-down";
  const [shown, shownDelta] = useTween([level, delta]);

  return (
    <section className="whatif">
      <div className="section-head">
        <h2>What if you moved a lever</h2>
        {touched ? (
          <button className="link" onClick={() => setMoved({})}>
            Back to today
          </button>
        ) : (
          <span className="hint">same contract as the engine</span>
        )}
      </div>

      <div className="whatif__body">
        <div className="whatif__levers">
          {available.map((p) => {
            const today = score[p.key] as number;
            const value = values.get(p.key) as number;
            const evidence = p.evidence(score);
            return (
              <div className="whatif__lever" key={p.key}>
                <label className="whatif__label" htmlFor={`whatif-${p.key}`}>
                  {p.label}
                  <span className="whatif__weight">
                    weight {((p.weight / 100 / coverage) * 100).toFixed(0)}%
                  </span>
                </label>
                <span className="whatif__value">{value.toFixed(1)}</span>
                <input
                  id={`whatif-${p.key}`}
                  className="whatif__slider"
                  type="range"
                  min={0}
                  max={100}
                  step={0.5}
                  value={value}
                  onChange={(e) => setMoved({ ...moved, [p.key]: Number(e.target.value) })}
                />
                <span className="whatif__today">
                  today {today.toFixed(1)}
                  {evidence && ` · ${evidence}`}
                </span>
              </div>
            );
          })}
        </div>

        <aside className="whatif__out">
          <p className={`whatif__level ${way}`}>{shown.toFixed(1)}</p>
          <p className={`whatif__delta ${way}`}>
            {fmtSigned(shownDelta)} against today
          </p>
          <p className="whatif__note">
            Same contract as the engine: <strong>50 + Σ w·(pillar − 50)</strong>, with the weights
            renormalised over the {available.length}{" "}
            {available.length === 1 ? "pillar" : "pillars"} this group can compute. A liquidity or
            payment pillar under 25 still caps the level at 50.
          </p>
        </aside>
      </div>
    </section>
  );
}
