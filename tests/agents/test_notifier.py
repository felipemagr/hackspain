import pytest

from xray.agents.notifier import parse_by_patterns, parse_rules


class TestPatterns:
    @pytest.mark.parametrize(
        ("text", "channel", "urgency"),
        [
            ("Tell me on Slack when any group starts falling", "slack", "critical"),
            ("Email me when this group bends or drops sharply", "email", "warning"),
            ("Avísame por correo cuando alguna empresa empiece a caer", "email", "critical"),
            ("Ping slack when a group drops, bending or worse", "slack", "warning"),
            ("Slack me whatever the monitor raises", "slack", "info"),
        ],
    )
    def test_channel_and_urgency_words(self, text, channel, urgency):
        (parsed,) = parse_by_patterns(text)

        assert (parsed.channel, parsed.min_urgency) == (channel, urgency)

    def test_severity_figure_and_group_ids_but_not_plain_numbers(self):
        (parsed,) = parse_by_patterns("email me about GROUP_0220 and g7 above severity 20 in 2026")

        assert parsed.min_severity == 20
        assert parsed.groups == ["GROUP_0220", "g7"]

    def test_two_channels_in_one_sentence_each_read_their_own_words(self):
        first, second = parse_by_patterns(
            "Slack me when any group starts falling, and email me everything on GROUP_0220"
        )

        assert (first.channel, first.min_urgency, first.groups) == ("slack", "critical", [])
        assert (second.channel, second.min_urgency, second.groups) == (
            "email",
            "info",
            ["GROUP_0220"],
        )

    def test_a_question_about_the_rules_asks_for_no_delivery(self):
        assert parse_by_patterns("which alert rules exist?") == []


class TestParseRules:
    class FakeLLM:
        def __init__(self, answer):
            self.answer = answer

        def complete(self, system, user):
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    def test_the_model_answer_becomes_the_rules_and_this_group_resolves(self):
        llm = self.FakeLLM(
            '```json\n{"rules": [{"channel": "email", "min_urgency": "critical",'
            ' "min_severity": 15, "groups": ["g2"], "this_group": true}]}\n```'
        )

        (rule,) = parse_rules("whatever was typed", "g1", llm)

        assert (rule.channel, rule.min_urgency, rule.min_severity) == ("email", "critical", 15)
        assert rule.groups == ["g2", "g1"]
        assert rule.text == "whatever was typed"

    def test_falls_back_to_patterns_when_the_model_fails(self):
        (rule,) = parse_rules("slack me when it falls", "g1", self.FakeLLM(RuntimeError("down")))

        assert (rule.channel, rule.min_urgency, rule.groups) == ("slack", "critical", [])

    def test_no_channel_means_no_rule(self):
        assert parse_rules("what rules are set?", "g1", None) == []
