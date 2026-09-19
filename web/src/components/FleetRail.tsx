import { runNote, type FleetState, type Turn } from "../lib/chat";

// The fleet at rest and at work: who exists, and what each one is doing for the current question.
export function FleetRail({
  fleet,
  turn,
  onRetry,
}: {
  fleet: FleetState;
  turn: Turn | undefined;
  onRetry: () => void;
}) {
  if (fleet.status === "waking") {
    return (
      <p className="empty">
        Waking the agents. On the free tier the first call can take a minute.
      </p>
    );
  }
  if (fleet.status === "down") {
    return (
      <div className="empty">
        <p>The agent service is not answering. The rest of the demo does not need it.</p>
        <button className="link" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }

  const live = new Map(turn?.agents.map((a) => [a.id, a]));
  const planning = turn?.phase === "planning";
  const writing = turn?.phase === "writing";
  const groups = [
    { title: "Read the score", agents: fleet.agents.filter((a) => a.kind === "data") },
    { title: "Read the outside", agents: fleet.agents.filter((a) => a.kind === "web") },
  ];

  return (
    <>
      <div className="list__head">Orchestration</div>
      <div className="agent">
        <span className="agent__dot" data-status={planning ? "running" : "idle"} />
        <span className="row__text">
          <span className="row__name">Planner</span>
          <span className="row__sub">picks the agents a question needs</span>
        </span>
        <span className="row__when">{planning ? "choosing" : ""}</span>
      </div>
      {groups.map((group) => (
        <div key={group.title}>
          <div className="list__head">
            {group.title} <span className="list__count">{group.agents.length}</span>
          </div>
          {group.agents.map((agent) => {
            const run = live.get(agent.id);
            return (
              <div className="agent" key={agent.id}>
                <span className="agent__dot" data-status={run?.status ?? "idle"} />
                <span className="row__text">
                  <span className="row__name">{agent.label}</span>
                  <span className="row__sub">{agent.reads}</span>
                </span>
                <span className="row__when">{run ? runNote(run) : ""}</span>
              </div>
            );
          })}
        </div>
      ))}
      <div className="list__head">Answer</div>
      <div className="agent">
        <span className="agent__dot" data-status={writing ? "running" : "idle"} />
        <span className="row__text">
          <span className="row__name">Writer</span>
          <span className="row__sub">answers from the reports, nothing else</span>
        </span>
        <span className="row__when">{writing ? "writing" : ""}</span>
      </div>
      <p className="fleet__foot">
        {fleet.model ? `Model: ${fleet.model}` : "No model key set: answers are the raw reports."}
      </p>
    </>
  );
}
