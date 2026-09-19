import { fmtEarly, monthShort } from "../lib/format";
import { alertKey, STATE_META, toneColor } from "../lib/meta";
import type { Store } from "../lib/load";

interface AlertListProps {
  store: Store;
  month: string;
  selectedId: string;
  onSelect: (groupId: string, month: string) => void;
  cleared: Set<string>;
  onClear: (keys: string[]) => void;
}

/** What the monitor has raised up to the selected month and nobody has cleared, newest first. */
export function AlertList({
  store,
  month,
  selectedId,
  onSelect,
  cleared,
  onClear,
}: AlertListProps) {
  const raised = store.alerts.filter((a) => a.month <= month);
  const alerts = raised.filter((a) => !cleared.has(alertKey(a)));

  if (raised.length === 0) {
    return (
      <p className="empty">
        {store.localScoring ? "Alerts have not been computed for this scoring profile." : "Nothing raised yet. The monitor speaks when a group starts improving, bending or falling, and stays quiet on a single bad month."}
      </p>
    );
  }
  return (
    <div className="list">
      <p className="list__status list__status--top">
        {alerts.length === 0 ? "All clear" : `${alerts.length} open`}
        {alerts.length > 0 && (
          <button className="link" onClick={() => onClear(alerts.map(alertKey))}>
            Clear all
          </button>
        )}
      </p>
      {alerts.length === 0 && (
        <p className="empty">
          Every alert up to this month has been cleared. The monitor will raise its hand again when
          a group really moves.
        </p>
      )}
      {alerts.map((a) => {
        const name = store.groupById.get(a.group_id)?.name ?? a.group_id;
        return (
          <div
            key={alertKey(a)}
            className={`row-wrap row-wrap--alert ${a.group_id === selectedId ? "is-selected" : ""}`}
          >
            <button className="row row--alert" onClick={() => onSelect(a.group_id, a.month)}>
              <span className="row__text">
                <span className="row__name">{name}</span>
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
            <button
              className="row__clear"
              aria-label={`Clear the ${monthShort(a.month)} alert on ${name}`}
              onClick={() => onClear([alertKey(a)])}
            >
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" />
              </svg>
            </button>
          </div>
        );
      })}
    </div>
  );
}
