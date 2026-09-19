"""Turn alert rows into messages and send the ones that have not gone out yet.

The alert table is rebuilt in full every time the pipeline runs, so sending it naively would
re-send two years of history on every build. A ledger of keys already delivered sits next to the
mart and makes `dispatch` idempotent: run it twice, the second run sends nothing.

The messages are deliberately deterministic templates rather than model output. Nothing here can
invent a number, and it reads the same on stage as it did in rehearsal.

Only what was knowable at the time goes into a message. `anticipation_months` and
`tier_change_month` are measured after the fact and stay in the table for the validation view.

Who gets what is either one channel for everything (`--channel slack`) or the rule book
(`--channel rules`): the rules the chat wrote to `data/serving/alert_rules.json`, each naming a
channel, what it waits for and the groups it watches. See `xray.scoring.rules`. A rule waiting
for the level to cross a line gets its own message, built from the scores, the month it crosses.

Replay for the demo: the detector is causal, so the alerts dated a month are exactly what the
system would have raised then. Walking the months forward fills a Slack channel live:

    python -m xray.scoring.notify --month 2026-05
    python -m xray.scoring.notify --month 2026-06
"""

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from xray.config import MARTS_DIR
from xray.integrations.email import send_email
from xray.integrations.slack import send_slack
from xray.scoring.rules import RULES_FILE, Rule, load_rules, urgency_of
from xray.settings import get_settings

logger = logging.getLogger(__name__)

LEDGER_NAME = "_alerts_sent.json"
MESSAGE_COLUMNS = ["key", "group_id", "month", "urgency", "severity", "subject", "body"]

STATE_COPY = {
    "bending": "is bending",
    "falling": "is falling",
    "improving": "is improving",
}


def _deliver(target: str, subject: str, body: str) -> None:
    """One message down one target: ``slack``, ``email``, ``email:x@y.z`` or ``none``."""
    channel, _, address = target.partition(":")
    if channel == "slack":
        send_slack(f"{subject}\n{body}")
    elif channel == "email":
        send_email(subject, body, to=address or None)


def _label(pillar: str | None) -> str:
    return pillar.replace("_", " ") if pillar else ""


def _drivers_line(alert: pd.Series) -> str:
    named = [_label(p) for p in (alert["driver_1"], alert["driver_2"]) if p]
    return f"Moved most: {' and '.join(named)}.\n" if named else ""


def render(alert: pd.Series, name: str | None = None) -> tuple[str, str]:
    """One alert as a subject line and a body.

    Args:
        alert: A row of the ``alerts`` table.
        name: Trading name of the group, when the portfolio has one.

    Returns:
        The subject and the body, in that order.
    """
    who = f"{name} ({alert['group_id']})" if name else alert["group_id"]
    onset = alert["onset_month"].strftime("%B %Y")
    if alert["kind"] == "jump":
        verb = "dropped" if alert["direction"] == "down" else "gained"
        back = "comes back" if alert["direction"] == "down" else "gives that back"
        subject = (
            f"{who} {verb} {abs(alert['delta_level']):.1f} points in one month: "
            f"{alert['level_at_onset']:.1f} to {alert['level_at_alert']:.1f}"
        )
        body = (
            f"{alert['sigmas']:.1f} times this group's own monthly swing, in the {alert['tier']} "
            f"tier.\n"
            f"{_drivers_line(alert)}"
            f"Provisional: if it {back} within two months this closes as a bump, not a trend."
        )
        return subject, body

    subject = (
        f"{who} {STATE_COPY[alert['state_to']]}: "
        f"{alert['level_at_alert']:.1f}, trending {alert['trend']:+.1f} a month"
    )
    direction = "Down" if alert["direction"] == "down" else "Up"
    building = (alert["month"].to_period("M") - alert["onset_month"].to_period("M")).n
    body = (
        f"{direction} {abs(alert['delta_level']):.1f} points since {onset}, {building} months "
        f"of it. In the {alert['tier']} tier, {alert['compound']:.0f} projected four months "
        f"out.\n"
        f"{_drivers_line(alert)}"
        f"Sustained, not a one-month swing: a bump would not have raised this."
    )
    return subject, body


def render_resolution(alert: pd.Series, name: str | None = None) -> tuple[str, str]:
    """The retraction of a jump that turned out to be a bump."""
    who = f"{name} ({alert['group_id']})" if name else alert["group_id"]
    verb = "drop" if alert["direction"] == "down" else "rise"
    return (
        f"{who}: the {abs(alert['delta_level']):.1f} point {verb} in "
        f"{alert['month'].strftime('%B %Y')} reverted",
        "Half of it or more came back within two months. A bump, not a change of direction. "
        "No action needed.",
    )


def messages(alerts: pd.DataFrame, names: dict[str, str] | None = None) -> pd.DataFrame:
    """Every message the alert table implies, each with the month it could first be sent.

    A reverted jump produces a second message two months after the first, because that is when
    the revert is knowable. Both carry a key, which is what the ledger stores.
    """
    names = names or {}
    rows = []
    for _, alert in alerts.iterrows():
        subject, body = render(alert, names.get(alert["group_id"]))
        rows.append(
            {
                "key": f"{alert['group_id']}|{alert['month']:%Y-%m}|{alert['kind']}|alert",
                "group_id": alert["group_id"],
                "month": alert["month"],
                "urgency": urgency_of(alert["direction"], alert["state_to"]),
                "severity": alert["severity"],
                "subject": subject,
                "body": body,
            }
        )
        if alert["resolution"] != "reverted":
            continue
        subject, body = render_resolution(alert, names.get(alert["group_id"]))
        rows.append(
            {
                "key": f"{alert['group_id']}|{alert['month']:%Y-%m}|{alert['kind']}|reverted",
                "group_id": alert["group_id"],
                "month": alert["resolution_month"],
                "urgency": "info",
                "severity": alert["severity"],
                "subject": subject,
                "body": body,
            }
        )
    return _chronological(pd.DataFrame(rows, columns=MESSAGE_COLUMNS))


def _chronological(pending: pd.DataFrame) -> pd.DataFrame:
    return pending.sort_values(["month", "severity"], ascending=[True, False])


def render_crossing(
    score: pd.Series, side: str, line: float, before: float, name: str | None = None
) -> tuple[str, str]:
    """The level crossing a line a rule drew, from the score row of the month it did."""
    who = f"{name} ({score['group_id']})" if name else score["group_id"]
    return (
        f"{who} went {side} {line:g}: {score['level']:.1f}, from {before:.1f} last month",
        f"State {score['state'].replace('_', ' ')}, {score['tier']} tier, trending "
        f"{score['trend']:+.1f} a month.",
    )


def level_messages(
    scores: pd.DataFrame, rules: list[Rule], names: dict[str, str] | None = None
) -> pd.DataFrame:
    """One message per line a group's level crossed, dated the month it did, with the channels
    of every rule that drew that line over the group.

    Only a crossing between two consecutive scored months counts, so a group's first month never
    sends one.
    """
    names = names or {}
    ordered = scores.sort_values(["group_id", "month"]).reset_index(drop=True)
    level, before = ordered["level"], ordered.groupby("group_id")["level"].shift(1)
    rows: dict[str, dict] = {}
    for rule in rules:
        for side, line in rule.lines():
            crossed = (
                (before <= line) & (level > line)
                if side == "above"
                else (before >= line) & (level < line)
            )
            hit = ordered[crossed & ordered["group_id"].map(rule.watches)]
            for i, score in hit.iterrows():
                key = f"{score['group_id']}|{score['month']:%Y-%m}|level|{side} {line:g}"
                if key not in rows:
                    subject, body = render_crossing(
                        score, side, line, before[i], names.get(score["group_id"])
                    )
                    rows[key] = {
                        "key": key,
                        "group_id": score["group_id"],
                        "month": score["month"],
                        "urgency": "info" if side == "above" else "warning",
                        "severity": 0.0,
                        "subject": subject,
                        "body": body,
                        "channels": [],
                    }
                if rule.target not in rows[key]["channels"]:
                    rows[key]["channels"].append(rule.target)
    return pd.DataFrame(list(rows.values()), columns=[*MESSAGE_COLUMNS, "channels"])


def _route(message: pd.Series, rules: list[Rule]) -> list[str]:
    """The targets whose rules want this message, each once."""
    return sorted(
        {
            rule.target
            for rule in rules
            if rule.matches(message["urgency"], message["severity"], message["group_id"])
        }
    )


def dispatch(
    alerts: pd.DataFrame,
    channel: str = "slack",
    names: dict[str, str] | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    ledger_path: Path = MARTS_DIR / LEDGER_NAME,
    rules: list[Rule] | None = None,
    scores: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Send every message in the window that the ledger has not seen.

    Args:
        alerts: The ``alerts`` table.
        channel: ``slack``, ``email``, ``rules`` or ``none``. ``rules`` sends each message to the
            channels of the rules it matches; a message no rule wants is left unsent, for a rule
            added later. ``none`` records the messages as delivered without sending them, which
            is how a backlog is written off before going live. Use ``dry_run`` to record nothing.
        names: Group trading names, when the portfolio has them.
        since: First month to send, ``YYYY-MM``. Open-ended when omitted.
        until: Last month to send, ``YYYY-MM``. Open-ended when omitted.
        limit: Send at most this many, highest severity first.
        dry_run: Render and log, send nothing, leave the ledger alone.
        ledger_path: Where the keys already sent are stored.
        rules: The rule book, for ``channel="rules"``. Read from the serving directory when
            omitted.
        scores: The ``scores`` table, for the rules that watch the level crossing a line. Those
            rules send nothing when omitted.

    Returns:
        The messages that went out, in the order they were sent, with the ``channels`` each took.
    """
    sent = set(json.loads(ledger_path.read_text())) if ledger_path.exists() else set()
    pending = messages(alerts, names)
    if channel == "rules":
        if rules is None:
            rules = load_rules(get_settings().serving_dir / RULES_FILE)
        pending = pending.assign(channels=[_route(m, rules) for _, m in pending.iterrows()])
        if scores is not None:
            crossings = level_messages(scores, rules, names)
            pending = _chronological(pd.concat([pending, crossings], ignore_index=True))
        pending = pending[pending["channels"].str.len() > 0]
    else:
        pending = pending.assign(channels=[[channel]] * len(pending))
    if since:
        pending = pending[pending["month"] >= pd.Timestamp(since)]
    if until:
        pending = pending[pending["month"] <= pd.Timestamp(until)]
    pending = pending[~pending["key"].isin(sent)]
    if limit:
        pending = pending.nlargest(limit, "severity")

    for _, message in pending.iterrows():
        logger.info(
            "%s | %s | %s",
            message["month"].strftime("%Y-%m"),
            "+".join(message["channels"]),
            message["subject"],
        )
        if dry_run:
            continue
        for target in message["channels"]:
            _deliver(target, message["subject"], message["body"])
        sent.add(message["key"])

    if not dry_run and len(pending):
        ledger_path.write_text(json.dumps(sorted(sent), indent=0) + "\n")
    logger.info("%d message(s) %s over %s", len(pending), "to send" if dry_run else "sent", channel)
    return pending


def main() -> None:
    """Send, or with --dry-run just show, the alerts not yet delivered."""
    parser = argparse.ArgumentParser(description="Send pending alerts.")
    parser.add_argument(
        "--channel",
        default="slack",
        choices=["slack", "email", "rules", "none"],
        help="rules routes by the rule book; none marks the messages as delivered without "
        "sending them",
    )
    parser.add_argument("--since", help="first month to send, YYYY-MM")
    parser.add_argument("--until", help="last month to send, YYYY-MM")
    parser.add_argument("--month", help="one month only, YYYY-MM: the demo replay")
    parser.add_argument("--limit", type=int, help="send at most this many, worst first")
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would go out, send nothing"
    )
    parser.add_argument("--marts-dir", type=Path, default=MARTS_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # The level rules read the served scores: state and trend are only there, next to the book.
    served = get_settings().serving_dir / "scores.parquet"
    dispatch(
        pd.read_parquet(args.marts_dir / "alerts.parquet"),
        channel=args.channel,
        since=args.month or args.since,
        until=args.month or args.until,
        limit=args.limit,
        dry_run=args.dry_run,
        ledger_path=args.marts_dir / LEDGER_NAME,
        scores=pd.read_parquet(served) if args.channel == "rules" and served.exists() else None,
    )


if __name__ == "__main__":
    main()
