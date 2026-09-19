import { fmtEarly, monthShort } from "../lib/format";
import { STATE_META, toneColor } from "../lib/meta";
import type { Store } from "../lib/load";

interface AlertListProps {
  store: Store;
  month: string;
  selectedId: string;
  onSelect: (groupId: string, month: string) => void;
}

/** What the monitor has raised up to the selected month, newest first. */
export function AlertList({ store, month, selectedId, onSelect }: AlertListProps) {
  const alerts = store.alerts.filter((a) => a.month <= month);
  if (alerts.length === 0) {
    return (
      <p className="empty">
        Nothing raised yet. The monitor speaks when a group starts improving, bending or falling,
        and stays quiet on a single bad month.
      </p>
    );
  }
  return (
    <div className="list">
      {alerts.map((a) => (
        <button
          key={`${a.group_id}-${a.month}`}
          className={`row row--alert ${a.group_id === selectedId ? "is-selected" : ""}`}
          onClick={() => onSelect(a.group_id, a.month)}
        >
          <span className="row__text">
            <span className="row__name">{store.groupById.get(a.group_id)?.name ?? a.group_id}</span>
            <span className="row__sub">
              <span
                className="state__dot"
                style={{ background: toneColor(STATE_META[a.state_to].tone) }}
              />
              {STATE_META[a.state_from].label} to {STATE_META[a.state_to].label}
              {fmtEarly(a.anticipation_months) && ` · ${fmtEarly(a.anticipation_months)}`}
            </span>
          </span>
          <span className="row__when">{monthShort(a.month)}</span>
        </button>
      ))}
    </div>
  );
}
