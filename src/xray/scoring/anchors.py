"""Indicator anchors: the one table that turns raw ratios into 0-100 sub-scores.

Every indicator maps through a piecewise-linear curve with breakpoints fixed here. Fixed anchors,
not population percentiles, so a hidden-test group scores the same whoever else is in the file.

The breakpoints were calibrated once against the percentiles of the 250 training groups and then
checked for monotonicity against the proxy events in `xray.scoring.events`. Weights follow the
same evidence rather than the opening guess in `docs/health-score-research.md`: liquidity carries
the signal (buffer days separate forward negative cash 43.6% to 1.3% across quintiles), payment
discipline is real but secondary, and cash generation measures flat against liquidity events and
is kept for its explanatory value at a reduced weight.

`higher_is_better` records the direction so the sub-score can be read back to the raw number for
the UI. Curves are written low-to-high on the raw value.
"""

PILLAR_WEIGHTS = {
    "liquidity": 0.35,
    "payment_discipline": 0.25,
    "cash_generation": 0.15,
    "collections": 0.15,
    "debt_burden": 0.10,
}

# Pillars that need invoices. A group without an ERP is scored on the rest, weights renormalised.
INVOICE_PILLARS = ("payment_discipline", "collections")

# indicator -> (pillar, weight within pillar, [(raw, score)...])
ANCHORS = {
    "buffer_days": ("liquidity", 0.70, [(0, 0), (13, 35), (27, 60), (62, 85), (120, 100)]),
    "negative_cash_share": ("liquidity", 0.30, [(0, 100), (0.34, 50), (0.67, 20), (1, 0)]),
    "ap_overdue_ratio": (
        "payment_discipline",
        0.60,
        [(0, 100), (0.30, 80), (0.70, 50), (0.93, 25), (1, 5)],
    ),
    "ap_days_late": (
        "payment_discipline",
        0.40,
        [(0, 100), (5, 80), (15, 60), (30, 40), (60, 15), (90, 0)],
    ),
    "op_margin": (
        "cash_generation",
        0.60,
        [(-0.50, 0), (-0.20, 25), (0, 50), (0.15, 75), (0.40, 100)],
    ),
    "inflow_growth": (
        "cash_generation",
        0.40,
        [(0.5, 0), (0.8, 30), (1.0, 55), (1.25, 80), (1.6, 100)],
    ),
    "ar_overdue_ratio": (
        "collections",
        0.60,
        [(0, 100), (0.30, 80), (0.70, 50), (0.93, 25), (1, 5)],
    ),
    "ar_days_late": (
        "collections",
        0.40,
        [(0, 100), (7, 80), (20, 60), (40, 40), (75, 15), (110, 0)],
    ),
    # No debt is not proof of capacity, so a zero burden anchors neutral-high rather than perfect.
    "debt_burden": ("debt_burden", 1.0, [(0, 75), (0.05, 65), (0.12, 50), (0.20, 30), (0.35, 5)]),
}

# Below this, a pillar cannot be averaged away: the level is capped at CAP_LEVEL.
CAP_PILLARS = ("liquidity", "payment_discipline")
CAP_PILLAR_SCORE = 25
CAP_LEVEL = 50.0

TIER_BOUNDS = [(70, "healthy"), (40, "coping"), (0, "vulnerable")]
