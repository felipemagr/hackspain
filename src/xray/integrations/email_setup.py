"""`make email-setup`: the address, its password, and email alerts work.

The SMTP host follows from the address (Gmail, Outlook, Yahoo, iCloud), the address is proposed
from the newest email alarm in the rule book, and the six mail lines of `.env` are written for
the user. A test message closes the loop.
"""

import getpass
import re
import smtplib
import sys
from pathlib import Path

from xray.config import PROJECT_ROOT
from xray.integrations.email import send_email
from xray.scoring.rules import RULES_FILE, load_rules
from xray.settings import Settings

ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_PORT = 587
SMTP_HOSTS = {
    "gmail.com": "smtp.gmail.com",
    "googlemail.com": "smtp.gmail.com",
    "outlook.com": "smtp.office365.com",
    "hotmail.com": "smtp.office365.com",
    "live.com": "smtp.office365.com",
    "yahoo.com": "smtp.mail.yahoo.com",
    "icloud.com": "smtp.mail.me.com",
    "me.com": "smtp.mail.me.com",
}
# These providers refuse the account password over SMTP: an app password is what works.
APP_PASSWORDS = {
    "smtp.gmail.com": "https://myaccount.google.com/apppasswords (2-step verification must be on)",
    "smtp.mail.yahoo.com": "https://login.yahoo.com/account/security",
    "smtp.mail.me.com": "https://appleid.apple.com/account/manage",
}


def proposed_address(settings: Settings) -> str:
    """The address alerts already go to: the newest email alarm's, else the configured one."""
    rules = load_rules(settings.serving_dir / RULES_FILE)
    addressed = [r.email_to for r in rules if r.channel == "email" and r.email_to]
    return addressed[-1] if addressed else (settings.alert_email_to or "")


def write_env(path: Path, values: dict[str, str]) -> None:
    """Set each key in the env file, replacing its line (commented or not) or appending it."""
    lines = path.read_text().splitlines() if path.exists() else []
    for key, value in values.items():
        pattern = re.compile(rf"^#?\s*{re.escape(key)}=")
        line = f"{key}={value}"
        at = next((i for i, existing in enumerate(lines) if pattern.match(existing)), None)
        if at is None:
            lines.append(line)
        else:
            lines[at] = line
    path.write_text("\n".join(lines) + "\n")


def ask(prompt: str, default: str = "") -> str:
    answer = input(f"{prompt} [{default}]: " if default else f"{prompt}: ").strip()
    return answer or default


def main() -> int:
    settings = Settings()
    address = ask("Email address for the alerts", proposed_address(settings))
    if "@" not in address:
        print("That is not an email address.", file=sys.stderr)
        return 1
    domain = address.rpartition("@")[2].lower()
    host = SMTP_HOSTS.get(domain) or ask("SMTP host of that mailbox")
    port = ask("SMTP port", str(DEFAULT_PORT))
    if help_url := APP_PASSWORDS.get(host):
        print(f"Use an app password, not the account password: {help_url}")
    password = getpass.getpass(f"Password for {address}: ")

    write_env(
        ENV_FILE,
        {
            "XRAY_SMTP_HOST": host,
            "XRAY_SMTP_PORT": port,
            "XRAY_SMTP_USER": address,
            "XRAY_SMTP_PASSWORD": password,
            "XRAY_ALERT_EMAIL_FROM": address,
            "XRAY_ALERT_EMAIL_TO": address,
        },
    )
    print(f"Written to {ENV_FILE.name}. Sending a test to {address}...")
    try:
        send_email(
            "Lighthouse: email is set up",
            "The monitor's email alerts will arrive here. Alarms are set in the chat or the "
            "Alerts rail; make notify CHANNEL=rules sends what is due.",
            to=address,
        )
    except (smtplib.SMTPException, OSError) as e:
        print(f"{host} refused: {e}", file=sys.stderr)
        print("Check the password (an app password where noted) and run make email-setup again.")
        return 1
    print("Sent. Check the inbox, then make notify CHANNEL=rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
