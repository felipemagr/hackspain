"""Alert delivery to Slack through an incoming webhook."""

import logging

import httpx

from xray.settings import get_settings

logger = logging.getLogger(__name__)


def send_slack(text: str) -> bool:
    """Post a message to the configured webhook. Returns False when none is configured."""
    url = get_settings().slack_webhook_url
    if not url:
        logger.info("Slack webhook not configured, alert not sent: %s", text)
        return False
    httpx.post(url, json={"text": text}, timeout=10).raise_for_status()
    return True


if __name__ == "__main__":
    print("sent" if send_slack("X Ray: test alert from the monitor") else "no webhook configured")
