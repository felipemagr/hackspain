import pytest

from xray.scoring.rules import Rule, add_rule, load_rules, remove_rule, urgency_of


@pytest.mark.parametrize(
    ("direction", "state_to", "expected"),
    [
        ("down", "falling", "critical"),
        ("down", "bending", "warning"),
        ("down", "healthy", "warning"),
        ("up", "improving", "info"),
    ],
)
def test_urgency_reads_off_the_alert_row(direction, state_to, expected):
    assert urgency_of(direction, state_to) == expected


class TestMatches:
    def test_the_urgency_floor_is_inclusive(self):
        rule = Rule(text="x", channel="slack", min_urgency="warning")

        assert rule.matches("warning", 1.0, "g1")
        assert rule.matches("critical", 1.0, "g1")
        assert not rule.matches("info", 1.0, "g1")

    def test_severity_and_groups_narrow_further(self):
        rule = Rule(text="x", channel="email", min_severity=20, groups=["g1"])

        assert rule.matches("info", 20.0, "g1")
        assert not rule.matches("critical", 19.9, "g1")
        assert not rule.matches("critical", 50.0, "g2")

    def test_a_level_rule_wants_no_monitor_alert(self):
        rule = Rule(text="x", channel="slack", level_above=80)

        assert not rule.matches("critical", 50.0, "g1")
        assert rule.lines() == [("above", 80.0)]

    def test_describe_says_what_the_rule_does_in_one_line(self):
        assert (
            Rule(text="x", channel="email", min_urgency="critical", min_severity=20).describe()
            == "Email gets critical alerts on any group, severity 20 or more"
        )
        assert (
            Rule(text="x", channel="slack", groups=["g1", "g2"]).describe()
            == "Slack gets every alert on g1, g2"
        )
        assert (
            Rule(
                text="x", channel="email", level_above=80, level_below=50, groups=["g1"]
            ).describe()
            == "Email gets a message when g1 goes above 80 or below 50"
        )


class TestBook:
    def test_ids_grow_and_survive_a_removal(self, tmp_path):
        path = tmp_path / "rules.json"

        first = add_rule(path, Rule(text="a", channel="slack"))
        second = add_rule(path, Rule(text="b", channel="email"))
        assert remove_rule(path, first.id)
        third = add_rule(path, Rule(text="c", channel="slack"))

        assert [r.id for r in load_rules(path)] == [second.id, third.id] == [2, 3]
        assert not remove_rule(path, first.id)

    def test_no_file_means_no_rules(self, tmp_path):
        assert load_rules(tmp_path / "missing.json") == []
