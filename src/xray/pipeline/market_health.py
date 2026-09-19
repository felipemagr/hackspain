"""Turn published macro series into a 0-100 health level per market.

The demo lays this behind a group's score, so the two must be readable on the same axis. It is
built the way the company score is built (`docs/scoring.md` 0): fixed anchors, nothing fitted,
nothing read across markets, and month `t` reads only values published by `t`.

Four pillars per market, each 0-100, then a weighted mean:

- Equity, 0.30: drawdown from the trailing 12m high and 6m momentum. An index level says
  nothing on its own; its fall says a lot.
- Labour, 0.25: unemployment against its own trailing 5y median, and its 12m change. Absolute
  unemployment is not comparable between countries, so each market is read against itself.
- Prices, 0.25: headline inflation, two-sided around the 2% target. Inflation and deflation
  both hurt collections.
- Funding, 0.20: the real short rate and the 12m change in the short rate, which is the part
  that reaches a company's cash.

The 0-100 here is not the company 0-100: that one is distance to distress, this one is
conditions. They share a scale so their trajectories can be read together, not so they can be
subtracted.
"""

import logging
from statistics import median

logger = logging.getLogger(__name__)

# Piecewise-linear anchors, ascending in the indicator, clamped outside the ends.
EQUITY_DRAWDOWN = [(-0.35, 0.0), (-0.20, 40.0), (-0.10, 70.0), (0.0, 100.0)]
EQUITY_MOMENTUM = [(-0.15, 0.0), (0.0, 60.0), (0.10, 100.0)]
LABOUR_GAP = [(-1.5, 100.0), (0.0, 60.0), (2.0, 0.0)]
LABOUR_CHANGE = [(-0.5, 100.0), (0.0, 60.0), (1.0, 0.0)]
PRICES = [
    (-1.0, 0.0),
    (0.0, 40.0),
    (1.5, 100.0),
    (2.5, 100.0),
    (3.5, 70.0),
    (5.0, 40.0),
    (8.0, 0.0),
]
FUNDING_REAL = [(0.0, 100.0), (2.0, 50.0), (4.0, 0.0)]
FUNDING_CHANGE = [(-0.5, 85.0), (0.0, 60.0), (1.5, 10.0)]

PILLAR_WEIGHTS = {"equity": 0.30, "labour": 0.25, "prices": 0.25, "funding": 0.20}

DRAWDOWN_WINDOW = 12
MOMENTUM_MONTHS = 6
LABOUR_MEDIAN_WINDOW = 60
LABOUR_MEDIAN_MIN = 36
# A monthly statistic is published weeks after the month it describes: at t the market only knows
# the last release. Carrying it forward past this many months would be inventing data.
MAX_CARRY_MONTHS = 3

# One market per row: which raw series feed its pillars.
MARKETS = [
    {
        "id": "mh_es",
        "name": "Spain market health",
        "country": "ES",
        "equity": "ibex",
        "labour": "unemp_es",
        "prices": "hicp_es",
        "rate": "euribor_12m",
    },
    {
        "id": "mh_de",
        "name": "Germany market health",
        "country": "DE",
        "equity": "dax",
        "labour": "unemp_de",
        "prices": "hicp_de",
        "rate": "euribor_12m",
    },
    {
        "id": "mh_gb",
        "name": "UK market health",
        "country": "GB",
        "equity": "ftse",
        "labour": "unemp_uk",
        "prices": "cpi_uk",
        "rate": "uk_short_rate",
    },
    {
        "id": "mh_us",
        "name": "US market health",
        "country": "US",
        "equity": "sp500",
        "labour": "unemp_us",
        "prices": "cpi_us",
        "rate": "us_short_rate",
    },
    {
        "id": "mh_eu",
        "name": "Europe market health",
        "country": None,
        "equity": "stoxx",
        "labour": "unemp_eu",
        "prices": "hicp_ea",
        "rate": "euribor_12m",
    },
]


def anchor(value: float | None, points: list[tuple[float, float]]) -> float | None:
    """Map an indicator to 0-100 through a piecewise-linear anchor table."""
    if value is None:
        return None
    if value <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if value <= x1:
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return points[-1][1]


def _carried(series: dict[str, float], months: list[str]) -> list[float | None]:
    """The value known at each month: the last published one, carried at most MAX_CARRY_MONTHS."""
    out: list[float | None] = []
    last: float | None = None
    age = 0
    for month in months:
        if month in series:
            last, age = series[month], 0
        else:
            age += 1
        out.append(last if last is not None and age <= MAX_CARRY_MONTHS else None)
    return out


def _weighted(pillars: dict[str, float | None]) -> float | None:
    """Weighted mean of the pillars that exist, renormalised over their weights."""
    got = {k: v for k, v in pillars.items() if v is not None}
    if not got:
        return None
    weight = sum(PILLAR_WEIGHTS[k] for k in got)
    return sum(PILLAR_WEIGHTS[k] * v for k, v in got.items()) / weight


def _equity(values: list[float | None], i: int) -> float | None:
    now = values[i]
    if now is None:
        return None
    window = [v for v in values[max(0, i - DRAWDOWN_WINDOW) : i + 1] if v is not None]
    drawdown = now / max(window) - 1 if window else None
    back = values[i - MOMENTUM_MONTHS] if i >= MOMENTUM_MONTHS else None
    momentum = now / back - 1 if back else None
    return _blend(anchor(drawdown, EQUITY_DRAWDOWN), anchor(momentum, EQUITY_MOMENTUM), 0.6)


def _labour(values: list[float | None], i: int) -> float | None:
    now = values[i]
    if now is None:
        return None
    history = [v for v in values[max(0, i - LABOUR_MEDIAN_WINDOW) : i] if v is not None]
    gap = now - median(history) if len(history) >= LABOUR_MEDIAN_MIN else None
    year_ago = values[i - 12] if i >= 12 else None
    change = now - year_ago if year_ago is not None else None
    return _blend(anchor(gap, LABOUR_GAP), anchor(change, LABOUR_CHANGE), 0.5)


def _funding(rates: list[float | None], prices: list[float | None], i: int) -> float | None:
    now = rates[i]
    if now is None:
        return None
    real = now - prices[i] if prices[i] is not None else None
    year_ago = rates[i - 12] if i >= 12 else None
    change = now - year_ago if year_ago is not None else None
    return _blend(anchor(real, FUNDING_REAL), anchor(change, FUNDING_CHANGE), 0.6)


def _blend(first: float | None, second: float | None, weight: float) -> float | None:
    """Two sub-scores into one, renormalised when only one of them exists."""
    if first is None:
        return second
    if second is None:
        return first
    return weight * first + (1 - weight) * second


def build(raw: dict[str, dict[str, float]], history: list[str], months: list[str]) -> list[dict]:
    """One health series per market, aligned to ``months``.

    Args:
        raw: every published series as id to {month: value}, over the full history window.
        history: every month to compute, oldest first. Must cover the trailing windows.
        months: the months to emit, a suffix of ``history``.

    Returns:
        One row per market: its metadata, the last month it could be scored, and the values.
    """
    start = history.index(months[0])
    out = []
    for market in MARKETS:
        equity = _carried(raw.get(market["equity"], {}), history)
        labour = _carried(raw.get(market["labour"], {}), history)
        prices = _carried(raw.get(market["prices"], {}), history)
        rates = _carried(raw.get(market["rate"], {}), history)

        values: list[float | None] = []
        for i in range(len(history)):
            level = _weighted(
                {
                    "equity": _equity(equity, i),
                    "labour": _labour(labour, i),
                    "prices": anchor(prices[i], PRICES),
                    "funding": _funding(rates, prices, i),
                }
            )
            values.append(round(level, 1) if level is not None else None)
        values = values[start:]

        through = max(
            (m for m, v in zip(months, values, strict=True) if v is not None), default=None
        )
        if through is None:
            logger.warning("%s: no month could be scored", market["id"])
            continue
        out.append(
            {
                "id": market["id"],
                "name": market["name"],
                "country": market["country"],
                "source": "X Ray, from the ECB, Eurostat, the ONS, the OECD and Yahoo Finance",
                "through": through,
                "values": values,
            }
        )
        logger.info("%s: scored to %s", market["id"], through)
    return out
