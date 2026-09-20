import pandas as pd

from xray.pipeline import names
from xray.pipeline.synth import ROSTER

GROUPS = pd.DataFrame({"group_id": ["g1", "g2", "g3"], "erp": ["Sage 200", None, None]})
COMPANIES = pd.DataFrame(
    {
        "company_id": ["c1", "c2", "c3", "c4"],
        "group_id": ["g1", "g2", "g2", "g3"],
        "country": ["ES", "ES", "PT", "DE"],
    }
)


def test_names_follow_erp_and_country():
    roster = pd.read_csv(names.ROSTER_PATH).set_index("name")

    groups, companies = names.apply(GROUPS, COMPANIES)

    named = groups.set_index("group_id")["name"]
    assert roster.loc[named["g1"], "erp"] == "Sage 200"
    assert roster.loc[named["g3"], "country"] == "DE"
    assert companies["name"].tolist()[1:3] == [f"{named['g2']} Holding", f"{named['g2']} Portugal"]
    assert companies["name"].iat[0] == named["g1"]


def test_named_dump_is_left_alone():
    groups = GROUPS.assign(name=["a", "b", "c"])

    out, _ = names.apply(groups, COMPANIES)

    assert out is groups


def test_roster_is_unique_and_clear_of_the_demo_groups():
    roster = pd.read_csv(names.ROSTER_PATH)

    assert roster["name"].is_unique
    assert not set(roster["name"]) & {row[0] for row in ROSTER}
