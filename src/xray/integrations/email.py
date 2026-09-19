"""Alert delivery by email over SMTP."""

import logging
import smtplib
from email.message import EmailMessage

from xray.settings import get_settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0


def send_email(subject: str, body: str, to: str | None = None) -> bool:
    """Send one alert, to ``to`` or the configured recipient. Returns False when no SMTP host or
    recipient is configured."""
    settings = get_settings()
    recipient = to or settings.alert_email_to
    if not (settings.smtp_host and recipient):
        logger.info("Email not configured, alert not sent: %s", subject)
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.alert_email_from
    message["To"] = recipient
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_SECONDS) as smtp:
        if settings.smtp_user:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
    return True


if __name__ == "__main__":
    ok = send_email("X Ray: test alert from the monitor", "If you can read this, email works.")
    print("sent" if ok else "no SMTP host or recipient configured")
