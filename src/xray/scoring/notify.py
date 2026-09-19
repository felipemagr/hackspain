"""Turn alert rows into messages and send the ones that have not gone out yet.

The alert table is rebuilt in full every time the pipeline runs, so sending it naively would
re-send two years of history on every build. A ledger of keys already delivered sits next to the
mart and makes `dispatch` idempotent: run it twice, the second run sends nothing.

The messages are deliberately deterministic templates rather than model output. Nothing here can
invent a number, and it reads the same on stage as it did in rehearsal.

Only what was knowable at the time goes into a message. `anticipation_months` and
`tier_change_month` are measured after the fact and stay in the table for the validation view.

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

logger = logging.getLogger(__name__)

LEDGER_NAME = "_alerts_sent.json"

STATE_COPY = {
    "bending": "is bending",
    "falling": "is falling",
    "improving": "is improving",
}


def _channels() -> dict:
    return {
        "slack": lambda subject, body: send_slack(f"{subject}\n{body}"),
        "email": send_email,
        "none": lambda subject, body: True,
    }


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
                "month": alert["month"],
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
                "month": alert["resolution_month"],
                "severity": alert["severity"],
                "subject": subject,
                "body": body,
            }
        )
    return pd.DataFrame(rows).sort_values(["month", "severity"], ascending=[True, False])


def dispatch(
    alerts: pd.DataFrame,
    channel: str = "slack",
    names: dict[str, str] | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    ledger_path: Path = MARTS_DIR / LEDGER_NAME,
) -> pd.DataFrame:
    """Send every message in the window that the ledger has not seen.

    Args:
        alerts: The ``alerts`` table.
        channel: ``slack``, ``email``, or ``none``. ``none`` records the messages as delivered
            without sending them, which is how a backlog is written off before going live. Use
            ``dry_run`` to record nothing.
        names: Group trading names, when the portfolio has them.
        since: First month to send, ``YYYY-MM``. Open-ended when omitted.
        until: Last month to send, ``YYYY-MM``. Open-ended when omitted.
        limit: Send at most this many, highest severity first.
        dry_run: Render and log, send nothing, leave the ledger alone.
        ledger_path: Where the keys already sent are stored.

    Returns:
        The messages that went out, in the order they were sent.
    """
    sent = set(json.loads(ledger_path.read_text())) if ledger_path.exists() else set()
    pending = messages(alerts, names)
    if since:
        pending = pending[pending["month"] >= pd.Timestamp(since)]
    if until:
        pending = pending[pending["month"] <= pd.Timestamp(until)]
    pending = pending[~pending["key"].isin(sent)]
    if limit:
        pending = pending.nlargest(limit, "severity")

    send = _channels()[channel]
    for _, message in pending.iterrows():
        logger.info("%s | %s", message["month"].strftime("%Y-%m"), message["subject"])
        if dry_run:
            continue
        send(message["subject"], message["body"])
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
        choices=["slack", "email", "none"],
        help="none marks the messages as delivered without sending them",
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
    dispatch(
        pd.read_parquet(args.marts_dir / "alerts.parquet"),
        channel=args.channel,
        since=args.month or args.since,
        until=args.month or args.until,
        limit=args.limit,
        dry_run=args.dry_run,
        ledger_path=args.marts_dir / LEDGER_NAME,
    )


if __name__ == "__main__":
    main()
