import pandas as pd

from xray.scoring.mock import PILLARS, build


def test_mock_tables_hold_the_contract():
    tables = build()
    scores, drivers, groups = tables["scores"], tables["drivers"], tables["groups"]

    assert {"Northbrook Foods", "Velasco Industrial", "Cabify"} <= set(groups["name"])
    assert not scores.duplicated(["group_id", "month"]).any()
    assert scores[["level", "compound"]].stack().between(0, 100).all()

    # Drivers are additive: they rebuild the uncapped level.
    rebuilt = 50 + drivers.groupby(["group_id", "month"])["contribution"].sum()
    level = scores.set_index(["group_id", "month"])["level_uncapped"]
    pd.testing.assert_series_equal(rebuilt, level, check_names=False, atol=0.05)

    no_erp = scores.merge(groups[~groups["has_erp"]], on="group_id")
    assert no_erp[["payment_discipline", "collections"]].isna().all().all()
    assert set(drivers["pillar"]) == set(PILLARS)


def test_compound_separates_the_worked_example():
    tables = build()
    last = tables["scores"].groupby("group_id").tail(1).set_index("group_id")
    northbrook, velasco = last.loc["DEMO_001"], last.loc["DEMO_002"]

    assert abs(northbrook["level"] - velasco["level"]) < 6
    assert northbrook["level"] < velasco["level"]
    assert northbrook["compound"] > velasco["compound"]
    assert set(tables["alerts"].query("group_id == 'DEMO_002'")["state_to"]) == {"bending"}
