import { fmtMonthsOfData } from "../lib/format";
import { MIN_HISTORY_MONTHS } from "../lib/meta";

const text = (months: number) =>
  `Low confidence: ${fmtMonthsOfData(months)}, the score needs ${MIN_HISTORY_MONTHS}.`;

/** Warning glyph. Ink, never a state color: it says how sure the score is, not how healthy. */
function Glyph({ label }: { label?: string }) {
  return (
    <svg
      className="caveat"
      width="12"
      height="12"
      viewBox="0 0 14 14"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={!label}
    >
      {label && <title>{label}</title>}
      <path d="M7 1.8 12.8 12.2H1.2Z" />
      <path d="M7 5.6v3" />
      <path d="M7 10.6v.01" />
    </svg>
  );
}

/** The glyph alone, for a list row; the sentence is its tooltip. */
export function LowDataMark({ months }: { months: number }) {
  return <Glyph label={text(months)} />;
}

/** The sentence beside the 64px level. */
export function LowDataNote({ months }: { months: number }) {
  return (
    <p className="score__caveat">
      <Glyph />
      <span>
        <strong>Low confidence:</strong> {fmtMonthsOfData(months)},{" "}
        <span className="score__caveat-clause">the score needs {MIN_HISTORY_MONTHS}.</span>
      </span>
    </p>
  );
}

/** Beside the level when pillars are missing. */
export function PartialDataNote({ missing, total }: { missing: number; total: number }) {
  return (
    <p className="score__caveat">
      <Glyph />
      <span>
        <strong>Partial data:</strong> {missing} of {total} pillars missing.
      </span>
    </p>
  );
}

/** Under the pillars table: which pillars have no data. */
export function MissingPillarsNote({ missing }: { missing: string[] }) {
  return (
    <p className="pillars__note">
      <Glyph />
      <span>
        No {new Intl.ListFormat("en", { type: "disjunction" }).format(missing.map((label) => label.toLowerCase()))} data.
      </span>
    </p>
  );
}
