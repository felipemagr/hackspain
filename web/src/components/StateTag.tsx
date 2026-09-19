import { STATE_META, toneColor } from "../lib/meta";
import type { State } from "../lib/types";

export function StateTag({ state }: { state: State }) {
  const meta = STATE_META[state];
  return (
    <span className="state">
      <span className="state__dot" style={{ background: toneColor(meta.tone) }} />
      {meta.label}
    </span>
  );
}
