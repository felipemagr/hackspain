import numpy as np
import pandas as pd
import pytest

from xray.scoring.anchors import PILLAR_WEIGHTS
from xray.scoring.explain import drivers
from xray.scoring.offer import MIN_COMPOUND, actions, offers

PILLARS = list(PILLAR_WEIGHTS)
MONTHS = pd.date_range("2025-01-01", periods=3, freq="MS")


def _scores(**overrides):
    """Three months of one group scored 60 on every pillar, with the columns serve.py carries."""
    weights = pd.Series(PILLAR_WEIGHTS)
    base = {
        "group_id": "g1",
        "month": MONTHS,
        **dict.fromkeys(PILLARS, 60.0),
        **{f"contrib_{p}": weights[p] * 10.0 for p in PILLARS},
        "buffer_days": 30.0,
        "op_margin": 0.1,
        "ap_days_late": 2.0,
        "ar_days_late": 3.0,
        "debt_service_ratio": 0.05,
        "level": 60.0,
        "level_uncapped": 60.0,
        "coverage": 1.0,
        "compound": [35.0, 50.0, 90.0],
        "state": ["stable", "stable", "improving"],
        "monthly_inflow_eur": 1_000_000.0,
    }
    return pd.DataFrame({**base, **overrides})


class TestDrivers:
    def test_delta_contributions_sum_to_the_level_change(self):
        s = _scores(level_uncapped=[60.0, 64.0, 58.0])
        for p in PILLARS:
            s[f"contrib_{p}"] = PILLAR_WEIGHTS[p] * (s["level_uncapped"] - 50)
        d = drivers(s)
        total = d.groupby("month")["delta_contribution"].sum()
        assert total.loc[MONTHS[1]] == pytest.approx(4.0)
        assert total.loc[MONTHS[2]] == pytest.approx(-6.0)

    def test_absent_pillar_has_no_row(self):
        s = _scores(collections=np.nan, contrib_collections=0.0)
        d = drivers(s)
        assert "collections" not in set(d["pillar"])
        assert len(d) == 3 * (len(PILLARS) - 1)


class TestOffers:
    def test_no_offer_under_the_compound_floor(self):
        o = offers(_scores()).set_index("month")
        assert not o.loc[MONTHS[0], "eligible"]
        assert o.loc[MONTHS[0], "limit_eur"] == 0
        assert pd.isna(o.loc[MONTHS[0], "apr"])

    def test_limit_and_price_move_with_the_compound(self):
        o = offers(_scores()).set_index("month")
        assert o.loc[MONTHS[2], "limit_eur"] > o.loc[MONTHS[1], "limit_eur"]
        assert o.loc[MONTHS[2], "apr"] < o.loc[MONTHS[1], "apr"]
        assert o.loc[MONTHS[2], "limit_change_eur"] == pytest.approx(
            o.loc[MONTHS[2], "limit_eur"] - o.loc[MONTHS[1], "limit_eur"]
        )

    def test_not_enough_data_is_never_eligible(self):
        o = offers(_scores(compound=MIN_COMPOUND + 20, state="not_enough_data"))
        assert not o["eligible"].any()


class TestActions:
    def test_three_actions_on_the_weakest_pillars_at_the_last_month(self):
        s = _scores(liquidity=20.0, contrib_liquidity=-12.0)
        a = actions(s)
        assert len(a) == 3
        assert a["month"].eq(MONTHS[-1]).all()
        assert a.loc[a["rank"] == 1, "pillar"].iat[0] == "liquidity"
        assert (a["expected_level_gain"] > 0).all()
