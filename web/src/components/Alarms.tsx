import { useState, type FormEvent } from "react";
import { delivers, watches, type Alarm, type AlarmChanges, type AlarmsState } from "../lib/alarms";

// What an alarm can wait for, as the editor offers it. Score lines and monitor alerts exclude
// each other, so one select covers both.
type Kind = "info" | "warning" | "critical" | "above" | "below";
const KINDS: { value: Kind; label: string }[] = [
  { value: "critical", label: "Starts falling" },
  { value: "warning", label: "Moves down" },
  { value: "info", label: "Raises any alert" },
  { value: "above", label: "Score goes above" },
  { value: "below", label: "Score goes below" },
];

function kindOf(alarm: Alarm): Kind {
  if (alarm.level_above != null) return "above";
  if (alarm.level_below != null) return "below";
  return alarm.min_urgency;
}

interface Draft {
  kind: Kind;
  line: string;
  severity: string;
  groups: string;
  channel: "slack" | "email";
  email: string;
}

function draftOf(alarm: Alarm): Draft {
  return {
    kind: kindOf(alarm),
    line: String(alarm.level_above ?? alarm.level_below ?? ""),
    severity: alarm.min_severity == null ? "" : String(alarm.min_severity),
    groups: alarm.groups.join(", "),
    channel: alarm.channel,
    email: alarm.email_to ?? "",
  };
}

function changesOf(draft: Draft): AlarmChanges {
  const onLine = draft.kind === "above" || draft.kind === "below";
  const line = onLine && draft.line !== "" ? Number(draft.line) : null;
  return {
    min_urgency: draft.kind === "above" || draft.kind === "below" ? "info" : draft.kind,
    level_above: draft.kind === "above" ? line : null,
    level_below: draft.kind === "below" ? line : null,
    min_severity: !onLine && draft.severity !== "" ? Number(draft.severity) : null,
    groups: draft.groups
      .split(/[\s,]+/)
      .map((g) => g.trim().toUpperCase())
      .filter(Boolean),
    channel: draft.channel,
    email_to: draft.channel === "email" ? draft.email.trim() || null : null,
  };
}

function Editor({
  alarm,
  onSave,
  onCancel,
}: {
  alarm: Alarm;
  onSave: (changes: AlarmChanges) => Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(() => draftOf(alarm));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const onLine = draft.kind === "above" || draft.kind === "below";
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const incomplete =
    (onLine && draft.line === "") || (draft.channel === "email" && !draft.email.includes("@"));

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onSave(changesOf(draft));
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  return (
    <form className="alarm-edit" onSubmit={save} aria-label={`Edit the alarm: ${watches(alarm)}`}>
      <label className="alarm-edit__field">
        <span>When</span>
        <span className="alarm-edit__pair">
          <select value={draft.kind} onChange={(e) => set({ kind: e.target.value as Kind })}>
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
          {onLine && (
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={draft.line}
              placeholder="70"
              aria-label="Score line"
              onChange={(e) => set({ line: e.target.value })}
            />
          )}
        </span>
      </label>
      {!onLine && (
        <label className="alarm-edit__field">
          <span>Severity</span>
          <span className="alarm-edit__pair">
            <input
              type="number"
              min={0}
              step={1}
              value={draft.severity}
              placeholder="Any"
              onChange={(e) => set({ severity: e.target.value })}
            />
            <span className="alarm-edit__unit">or more</span>
          </span>
        </label>
      )}
      <label className="alarm-edit__field">
        <span>Groups</span>
        <input
          value={draft.groups}
          placeholder="Any group"
          spellCheck={false}
          onChange={(e) => set({ groups: e.target.value })}
        />
      </label>
      <label className="alarm-edit__field">
        <span>Send to</span>
        <span className="alarm-edit__pair">
          <select
            value={draft.channel}
            onChange={(e) => set({ channel: e.target.value as Draft["channel"] })}
          >
            <option value="slack">Slack</option>
            <option value="email">Email</option>
          </select>
          {draft.channel === "email" && (
            <input
              type="email"
              value={draft.email}
              placeholder="name@company.com"
              aria-label="Email address"
              onChange={(e) => set({ email: e.target.value })}
            />
          )}
        </span>
      </label>
      {error && (
        <p className="alarm-edit__error" role="alert">
          {error}
        </p>
      )}
      <div className="alarm-edit__actions">
        <button type="submit" className="alarm-edit__save" disabled={saving || incomplete}>
          {saving ? "Saving" : "Save"}
        </button>
        <button type="button" className="link" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function Switch({
  on,
  label,
  onChange,
}: {
  on: boolean;
  label: string;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className="switch"
      onClick={() => onChange(!on)}
    >
      <span className="switch__knob" />
    </button>
  );
}

function Composer({
  groupId,
  onCreate,
}: {
  groupId: string;
  onCreate: (text: string, groupId: string) => Promise<string | null>;
}) {
  const [text, setText] = useState("");
  const [asked, setAsked] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    const question = await onCreate(text.trim(), groupId);
    setBusy(false);
    setAsked(question ?? "");
    if (!question) setText("");
  };

  return (
    <form className="alarm-add" onSubmit={submit}>
      <div className="list__search">
        <input
          value={text}
          disabled={busy}
          aria-label="New alarm, in plain words"
          placeholder="Slack me when this group starts falling"
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      {asked && (
        <p className="alarm-add__asked" role="status">
          {asked}
        </p>
      )}
    </form>
  );
}

interface AlarmsProps {
  state: AlarmsState;
  groupId: string;
  onChange: (id: number, changes: AlarmChanges) => Promise<void>;
  onRemove: (id: number) => Promise<void>;
  onCreate: (text: string, groupId: string) => Promise<string | null>;
  onRetry: () => void;
}

/** The alarms in the rule book: what each waits for and where it goes. Switch, edit, delete,
 * or add one in plain words. The agents write the same book from the chat. */
export function Alarms({ state, groupId, onChange, onRemove, onCreate, onRetry }: AlarmsProps) {
  const [editing, setEditing] = useState<number | null>(null);
  const alarms = state.status === "ready" ? state.alarms : [];

  return (
    <section className="alarms" aria-label="Alarms">
      <div className="list__head">
        Alarms{" "}
        {state.status === "ready" && <span className="list__count">{alarms.length}</span>}
      </div>
      {state.status === "down" ? (
        <div className="empty">
          <p>The agent service is not answering, and it keeps the alarms.</p>
          <button className="link" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : (
        <>
          <Composer groupId={groupId} onCreate={onCreate} />
          {state.status === "ready" && alarms.length === 0 && (
            <p className="empty">
              None yet. Say what to watch and where to be told, here or in the chat: "email
              cfo@company.com when GROUP_0130 goes above 80".
            </p>
          )}
          {alarms.map((alarm) => {
            const open = editing === alarm.id;
            return (
              <div
                key={alarm.id}
                className={`alarm ${alarm.enabled ? "" : "is-off"} ${open ? "is-open" : ""}`}
              >
                <div className="row-wrap row-wrap--alert">
                  <button
                    className="row row--alert"
                    aria-expanded={open}
                    onClick={() => setEditing(open ? null : alarm.id)}
                  >
                    <span className="row__text">
                      <span className="row__name">{watches(alarm)}</span>
                      <span className="row__sub">
                        {delivers(alarm)}
                        {!alarm.enabled && " · off"}
                      </span>
                    </span>
                  </button>
                  <Switch
                    on={alarm.enabled}
                    label={`${alarm.enabled ? "Switch off" : "Switch on"}: ${watches(alarm)}`}
                    onChange={(on) => onChange(alarm.id, { enabled: on })}
                  />
                  <button
                    className="row__clear"
                    aria-label={`Delete the alarm: ${watches(alarm)}`}
                    onClick={() => onRemove(alarm.id)}
                  >
                    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                      <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" />
                    </svg>
                  </button>
                </div>
                {open && (
                  <Editor
                    key={alarm.id}
                    alarm={alarm}
                    onSave={async (changes) => {
                      await onChange(alarm.id, changes);
                      setEditing(null);
                    }}
                    onCancel={() => setEditing(null)}
                  />
                )}
              </div>
            );
          })}
        </>
      )}
    </section>
  );
}
