import pandas as pd
import pytest

from xray.scoring.notify import dispatch, messages, render

ALERT = {
    "group_id": "g1",
    "month": pd.Timestamp("2026-05-01"),
    "kind": "shift",
    "direction": "down",
    "state_from": "healthy",
    "state_to": "bending",
    "onset_month": pd.Timestamp("2026-01-01"),
    "level_at_onset": 82.0,
    "level_at_alert": 68.4,
    "delta_level": -13.6,
    "trend": -2.1,
    "compound": 60.0,
    "tier": "coping",
    "driver_1": "payment_discipline",
    "driver_2": "liquidity",
    "sigmas": float("nan"),
    "resolution": "",
    "resolution_month": pd.NaT,
    "monthly_inflow_eur": 300_000.0,
    "severity": 12.0,
    "tier_change_month": pd.Timestamp("2026-08-01"),
    "anticipation_months": 3.0,
    "late": False,
}
JUMP = {
    **ALERT,
    "kind": "jump",
    "onset_month": pd.Timestamp("2026-04-01"),
    "state_from": "healthy",
    "state_to": "healthy",
    "sigmas": 4.2,
    "resolution": "reverted",
    "resolution_month": pd.Timestamp("2026-07-01"),
}


@pytest.fixture
def alerts() -> pd.DataFrame:
    return pd.DataFrame([ALERT, JUMP])


class TestRender:
    def test_shift_leads_with_the_trend_and_names_the_drivers(self):
        subject, body = render(pd.Series(ALERT), name="Example Corp")

        assert subject.startswith("Example Corp (g1) is bending: 68.4, trending -2.1 a month")
        assert "13.6 points since January 2026" in body
        assert "payment discipline and liquidity" in body

    def test_jump_says_it_is_provisional(self):
        subject, body = render(pd.Series(JUMP))

        assert "dropped 13.6 points in one month" in subject
        assert "4.2 times this group's own monthly swing" in body
        assert "bump" in body

    def test_hindsight_never_reaches_a_message(self):
        subject, body = render(pd.Series(ALERT))

        # The tier change is three months after the alert: it cannot be known when it is sent.
        assert "August" not in subject + body
        assert "anticipat" not in (subject + body).lower()


class TestMessages:
    def test_a_reverted_jump_is_retracted_when_the_revert_is_knowable(self, alerts):
        out = messages(alerts)
        retraction = out[out["key"].str.endswith("reverted")]

        assert len(retraction) == 1
        assert retraction["month"].iat[0] == JUMP["resolution_month"]
        assert "reverted" in retraction["subject"].iat[0]

    def test_a_sustained_alert_is_sent_once(self, alerts):
        out = messages(alerts)

        assert (out["key"] == "g1|2026-05|shift|alert").sum() == 1


class TestDispatch:
    def test_the_second_run_sends_nothing(self, alerts, tmp_path):
        ledger = tmp_path / "sent.json"

        first = dispatch(alerts, channel="none", ledger_path=ledger)
        second = dispatch(alerts, channel="none", ledger_path=ledger)

        assert len(first) == 3
        assert second.empty

    def test_a_dry_run_leaves_the_ledger_alone(self, alerts, tmp_path):
        ledger = tmp_path / "sent.json"

        dispatch(alerts, channel="none", dry_run=True, ledger_path=ledger)

        assert not ledger.exists()
        assert len(dispatch(alerts, channel="none", ledger_path=ledger)) == 3

    def test_one_month_of_the_replay_sends_only_that_month(self, alerts, tmp_path):
        out = dispatch(
            alerts,
            channel="none",
            since="2026-07",
            until="2026-07",
            ledger_path=tmp_path / "sent.json",
        )

        assert out["month"].tolist() == [pd.Timestamp("2026-07-01")]
