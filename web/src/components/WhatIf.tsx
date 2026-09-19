import { useEffect, useState } from "react";
import { fmtSigned } from "../lib/format";
import { PILLARS } from "../lib/meta";
import type { Pillar, ScoreRow } from "../lib/types";
import { useTween } from "../lib/useTween";
import { scoreLabels, type Weights } from "../lib/scoring";

interface WhatIfProps {
  score: ScoreRow;
  weights?: Weights;
  onWeights?: (weights: Weights) => void;
  evaluating?: boolean;
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

interface LeverValueProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
}

/** The lever's number, typed instead of dragged. The draft only lives while the field has focus. */
function LeverValue({ label, value, onChange }: LeverValueProps) {
  const [draft, setDraft] = useState<string | null>(null);

  return (
    <input
      className="whatif__value"
      type="text"
      inputMode="decimal"
      aria-label={`${label} value`}
      value={draft ?? value.toFixed(1)}
      onFocus={(e) => {
        setDraft(value.toFixed(1));
        e.target.select();
      }}
      onChange={(e) => {
        setDraft(e.target.value);
        const typed = parseFloat(e.target.value.replace(",", "."));
        if (!Number.isNaN(typed)) onChange(Math.min(100, Math.max(0, typed)));
      }}
      onBlur={() => setDraft(null)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === "Escape") e.currentTarget.blur();
      }}
    />
  );
}

export function WhatIf(props: WhatIfProps) {
  return props.score.localScoring ? <WeightWhatIf {...props} /> : <BaselineWhatIf score={props.score} />;
}

function WeightWhatIf({ score, weights, onWeights, evaluating }: WhatIfProps) {
  const [section, setSection] = useState<keyof Weights>("level");
  const [draft, setDraft] = useState(weights);
  useEffect(() => setDraft(weights), [weights, score.group_id]);
  if (!draft || !onWeights) return null;
  const total = Object.values(draft[section]).reduce((sum, value) => sum + value, 0);
  const changed = JSON.stringify(draft) !== JSON.stringify(weights);
  const valid = Object.values(draft).every((values) => Object.values(values).some((v) => v > 0));
  const update = (key: string, value: number) => setDraft({ ...draft, [section]: { ...draft[section], [key]: value } });
  return <section className="whatif"><div className="section-head"><h2>What if you changed the weights</h2><select aria-label="Weight family" value={section} onChange={(e) => setSection(e.target.value as keyof Weights)}><option value="level">Health score</option><option value="financial">Financial capacity</option><option value="evolution">Evolution</option></select></div>
    <div className="whatif__body"><div className="whatif__levers">{Object.entries(draft[section]).map(([key, value]) => <div className="whatif__lever" key={key}><label className="whatif__label" htmlFor={`weight-${key}`}>{scoreLabels[key] ?? key}<span className="whatif__weight">{total > 0 ? (value / total * 100).toFixed(1) : "-"}% nominal</span></label><LeverValue label={`${scoreLabels[key] ?? key} weight`} value={value * 100} onChange={(v) => update(key, v / 100)} /><input id={`weight-${key}`} className="whatif__slider" type="range" min={0} max={100} step={0.5} value={value * 100} onChange={(e) => update(key, Number(e.target.value) / 100)} /><span className="whatif__today">applied weight {weights?.[section][key] == null ? "-" : (weights[section][key] * 100).toFixed(1)}</span></div>)}</div>
      <aside className="whatif__out"><p className="whatif__level">{score.level == null ? "-" : score.level.toFixed(1)}</p><p className="whatif__note">Weights are renormalised over available components. Apply to recalculate this entity's history and explanations.</p><button disabled={!changed || !valid || evaluating} onClick={() => onWeights(draft)}>{evaluating ? "Recalculating…" : "Apply weights"}</button>{changed && <button className="link" onClick={() => setDraft(weights)}>Discard changes</button>}{!valid && <p className="empty">Keep at least one positive weight in each family.</p>}</aside></div>
  </section>;
}

function BaselineWhatIf({ score }: WhatIfProps) {
  const [moved, setMoved] = useState<Moved>({});
  // A different group or month is a different starting point: drop the moves.
  useEffect(() => setMoved({}), [score.group_id, score.month]);

  const available = PILLARS.filter((p) => score[p.key] != null);

  const coverage = available.reduce((sum, p) => sum + p.weight / 100, 0);
  const values = new Map<Pillar, number>(
    available.map((p) => [p.key, moved[p.key] ?? (score[p.key] as number)]),
  );
  const level = levelOf(values, coverage);
  const delta = score.level == null ? NaN : level - score.level;
  const touched = Object.keys(moved).length > 0;
  const way = Math.abs(delta) < 0.05 ? "" : delta > 0 ? "is-up" : "is-down";
  const [shown, shownDelta] = useTween([level, delta]);
  if (available.length === 0) return null;

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
                <LeverValue
                  label={p.label}
                  value={value}
                  onChange={(v) => setMoved({ ...moved, [p.key]: v })}
                />
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
