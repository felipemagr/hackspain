"""The market level must keep the invariants the company score keeps."""

from xray.pipeline import market_health
from xray.pipeline.market_health import MAX_CARRY_MONTHS, PRICES, _carried, anchor, build


def months(first: str, n: int) -> list[str]:
    y, m = (int(p) for p in first.split("-"))
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_anchors_interpolate_and_clamp():
    assert anchor(2.0, PRICES) == 100.0
    assert anchor(3.0, PRICES) == 85.0  # midway between 2.5 -> 100 and 3.5 -> 70
    assert anchor(20.0, PRICES) == 0.0  # clamped past the last anchor
    assert anchor(None, PRICES) is None


def test_a_release_is_carried_forward_but_not_invented():
    timeline = months("2025-01", 6)
    carried = _carried({"2025-01": 4.0}, timeline)
    assert carried[: MAX_CARRY_MONTHS + 1] == [4.0] * (MAX_CARRY_MONTHS + 1)
    assert carried[MAX_CARRY_MONTHS + 1 :] == [None] * (len(timeline) - MAX_CARRY_MONTHS - 1)


def test_a_month_ignores_what_was_published_after_it():
    history = months("2020-01", 80)
    raw = {
        "ibex": dict.fromkeys(history, 10_000.0),
        "unemp_es": dict.fromkeys(history, 12.0),
        "hicp_es": dict.fromkeys(history, 2.0),
        "euribor_12m": dict.fromkeys(history, 1.0),
    }
    emitted = history[-12:]
    full = build(raw, history, emitted)

    # The same run with every value after the third emitted month deleted must agree up to it.
    cut = emitted[2]
    trimmed = {k: {m: v for m, v in s.items() if m <= cut} for k, s in raw.items()}
    partial = build(trimmed, history, emitted)
    for a, b in zip(full, partial, strict=True):
        assert a["values"][:3] == b["values"][:3]


def test_a_market_scores_the_same_whoever_else_is_in_the_file(monkeypatch):
    history = months("2020-01", 80)
    raw = {
        "ibex": {m: 10_000.0 + i * 50 for i, m in enumerate(history)},
        "unemp_es": dict.fromkeys(history, 12.0),
        "hicp_es": dict.fromkeys(history, 2.4),
        "euribor_12m": dict.fromkeys(history, 2.0),
        "dax": {m: 20_000.0 - i * 80 for i, m in enumerate(history)},
        "unemp_de": dict.fromkeys(history, 3.0),
        "hicp_de": dict.fromkeys(history, 6.0),
    }
    emitted = history[-6:]
    with_germany = next(s for s in build(raw, history, emitted) if s["id"] == "mh_es")

    monkeypatch.setattr(
        market_health, "MARKETS", [m for m in market_health.MARKETS if m["id"] == "mh_es"]
    )
    alone = build(raw, history, emitted)[0]
    assert alone["values"] == with_germany["values"]
