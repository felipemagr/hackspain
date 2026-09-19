from xray.integrations.email_setup import SMTP_HOSTS, proposed_address, write_env
from xray.scoring.rules import RULES_FILE, Rule, add_rule
from xray.settings import Settings


def test_write_env_replaces_live_and_commented_lines_and_appends_the_rest(tmp_path):
    env = tmp_path / ".env"
    env.write_text("XRAY_SMTP_HOST=\n# XRAY_SMTP_PORT=587\nTAVILY_API_KEY=t\n")

    write_env(
        env,
        {"XRAY_SMTP_HOST": "smtp.gmail.com", "XRAY_SMTP_PORT": "587", "XRAY_SMTP_USER": "a@b.c"},
    )

    assert env.read_text() == (
        "XRAY_SMTP_HOST=smtp.gmail.com\nXRAY_SMTP_PORT=587\nTAVILY_API_KEY=t\nXRAY_SMTP_USER=a@b.c\n"
    )


def test_the_address_is_proposed_from_the_newest_email_alarm(tmp_path):
    settings = Settings(_env_file=None, serving_dir=tmp_path, alert_email_to="old@example.com")
    assert proposed_address(settings) == "old@example.com"

    add_rule(tmp_path / RULES_FILE, Rule(text="", channel="slack"))
    add_rule(tmp_path / RULES_FILE, Rule(text="", channel="email", email_to="cfo@example.com"))

    assert proposed_address(settings) == "cfo@example.com"
    assert SMTP_HOSTS["gmail.com"] == "smtp.gmail.com"
