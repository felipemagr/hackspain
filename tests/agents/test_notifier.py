import pytest

from xray.agents.notifier import parse_by_patterns, parse_request


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
        assert parsed.level_above is None

    @pytest.mark.parametrize(
        ("text", "above", "below", "groups"),
        [
            ("Create an alarm whenever the 0130 gets a score above 80", 80, None, ["0130"]),
            ("alert me when GROUP_0220 drops under 50", None, 50, ["GROUP_0220"]),
            ("avísame si el grupo 130 baja de 40 o supera 75", 75, 40, ["130"]),
        ],
    )
    def test_a_score_figure_is_a_level_line_and_names_no_channel(self, text, above, below, groups):
        (parsed,) = parse_by_patterns(text)

        assert parsed.channel is None
        assert (parsed.level_above, parsed.level_below) == (above, below)
        assert parsed.groups == groups
        assert (parsed.min_urgency, parsed.min_severity) == ("info", None)

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

    @pytest.mark.parametrize(
        "text",
        [
            "which alert rules exist?",
            "Could you email this to me?",
            "XRAY_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T0C2SLR64P5/B0C2U353FS9",
        ],
    )
    def test_text_that_asks_to_be_told_nothing_makes_no_rule(self, text):
        assert parse_by_patterns(text) == []


class TestParseRequest:
    class FakeLLM:
        def __init__(self, answer):
            self.answer = answer
            self.asked = []

        def complete(self, system, user):
            self.asked.append(user)
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    def test_the_model_answer_becomes_the_rules_and_this_group_resolves(self):
        llm = self.FakeLLM(
            '```json\n{"rules": [{"channel": "email", "min_urgency": "critical",'
            ' "min_severity": 15, "groups": ["g2"], "this_group": true}]}\n```'
        )

        (parsed,) = parse_request("whatever was typed", "g1", llm)
        rule = parsed.rule("whatever was typed")

        assert (rule.channel, rule.min_urgency, rule.min_severity) == ("email", "critical", 15)
        assert rule.groups == ["g2", "g1"]
        assert rule.text == "whatever was typed"

    def test_the_earlier_request_is_shown_to_the_model_and_read_by_the_patterns(self):
        earlier = "Create an alarm whenever the 0130 gets a score above 80"
        llm = self.FakeLLM(RuntimeError("down"))

        (parsed,) = parse_request("email", None, llm, earlier)

        assert earlier in llm.asked[0] and "email" in llm.asked[0]
        assert (parsed.channel, parsed.level_above, parsed.groups) == ("email", 80, ["0130"])

    def test_falls_back_to_patterns_when_the_model_fails(self):
        (parsed,) = parse_request(
            "slack me when it falls", "g1", self.FakeLLM(RuntimeError("down"))
        )

        assert (parsed.channel, parsed.min_urgency, parsed.groups) == ("slack", "critical", [])

    def test_a_question_means_no_rule(self):
        assert parse_request("what rules are set?", "g1", None) == []
