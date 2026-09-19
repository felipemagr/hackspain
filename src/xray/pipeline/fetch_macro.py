"""Fetch the published series the market health levels are built from.

Writes ``web/src/lib/macro.json``, which the front end imports at build time: one 0-100 level per
market, built by ``market_health.py`` from the series below. The file is committed, so the demo
never depends on these sites being up while the jury watches.

Sources, all public and unauthenticated:

- ECB Data Portal (``data-api.ecb.europa.eu``): Euribor 12m and HICP.
- Eurostat (``ec.europa.eu/eurostat/api``): unemployment.
- ONS (``www.ons.gov.uk``): UK CPI and unemployment.
- OECD SDMX (``sdmx.oecd.org``): UK and US short rates, US inflation. The Bank of England's own
  CSV endpoint no longer serves a script, and FRED did not answer either.
- BLS (``api.bls.gov``): US unemployment.
- Yahoo Finance chart API: month-end closes of the indices.

Run: ``make macro``.
"""

import csv
import io
import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

from xray.config import PROJECT_ROOT
from xray.pipeline import market_health

logger = logging.getLogger(__name__)

OUT_PATH = PROJECT_ROOT / "web" / "src" / "lib" / "macro.json"
FIRST_MONTH = "2024-09"
LAST_MONTH = "2026-09"
# The health levels need trailing windows (a 12m high, a 5y unemployment median), so every
# series is fetched from well before the demo's first month and trimmed on the way out.
HISTORY_FIRST_MONTH = "2018-09"
UA = {"User-Agent": "Mozilla/5.0 (compatible; xray-macro/1.0)"}


def _months(first: str, last: str) -> list[str]:
    y, m = (int(p) for p in first.split("-"))
    ly, lm = (int(p) for p in last.split("-"))
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


MONTHS = _months(FIRST_MONTH, LAST_MONTH)
HISTORY = _months(HISTORY_FIRST_MONTH, LAST_MONTH)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as res:  # noqa: S310
        return res.read()


def ecb(key: str) -> dict[str, float]:
    """One ECB series as month to value. Daily series collapse to their last observation."""
    url = (
        f"https://data-api.ecb.europa.eu/service/data/{key}"
        f"?format=csvdata&startPeriod={HISTORY_FIRST_MONTH}-01"
    )
    rows = csv.DictReader(io.StringIO(_get(url).decode("utf-8")))
    out: dict[str, float] = {}
    for row in rows:
        period, value = row["TIME_PERIOD"], row["OBS_VALUE"]
        if value:
            out[period[:7]] = float(value)
    return out


def eurostat(dataset: str, **filters: str) -> dict[str, float]:
    """One Eurostat series as month to value, from the JSON-stat dissemination API."""
    query = "&".join(f"{k}={v}" for k, v in filters.items())
    url = (
        f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}"
        f"?{query}&sinceTimePeriod={HISTORY_FIRST_MONTH}&format=JSON"
    )
    data = json.loads(_get(url))
    index = data["dimension"]["time"]["category"]["index"]
    by_position = {position: month for month, position in index.items()}
    return {by_position[int(k)]: v for k, v in data["value"].items() if v is not None}


def ons(topic: str, series: str, dataset: str) -> dict[str, float]:
    """One ONS monthly series as month to value. ``topic`` is the site section holding it."""
    url = f"https://www.ons.gov.uk/{topic}/timeseries/{series}/{dataset}/data"
    data = json.loads(_get(url))
    out: dict[str, float] = {}
    for point in data["months"]:
        stamp = datetime.strptime(point["date"], "%Y %b").replace(tzinfo=UTC)
        out[stamp.strftime("%Y-%m")] = float(point["value"])
    return out


def yahoo(symbol: str) -> dict[str, float]:
    """Month-end closes of an index."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
        "?interval=1mo&range=10y"
    )
    result = json.loads(_get(url))["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    # Each bucket is stamped at the market's local open, so a European index lands in the
    # previous month when read as UTC. Shift by the exchange's offset before taking the month.
    offset = result["meta"]["gmtoffset"]
    out: dict[str, float] = {}
    for stamp, close in zip(result["timestamp"], closes, strict=True):
        if close is not None:
            out[datetime.fromtimestamp(stamp + offset, UTC).strftime("%Y-%m")] = round(close)
    return out


def oecd(measure: str, area: str) -> dict[str, float]:
    """One OECD short-term statistics rate as month to value."""
    url = (
        "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/"
        f"{area}.M.{measure}......?startPeriod={HISTORY_FIRST_MONTH}&format=csvfile"
    )
    rows = csv.DictReader(io.StringIO(_get(url).decode("utf-8")))
    return {r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows if r["OBS_VALUE"]}


def oecd_price(area: str) -> dict[str, float]:
    """Headline CPI, annual rate of change, as month to value."""
    url = (
        "https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/"
        f"{area}.M.N.CPI.PA._T.N.GY?startPeriod={HISTORY_FIRST_MONTH}&format=csvfile"
    )
    rows = csv.DictReader(io.StringIO(_get(url).decode("utf-8")))
    return {r["TIME_PERIOD"]: round(float(r["OBS_VALUE"]), 1) for r in rows if r["OBS_VALUE"]}


def bls(series: str) -> dict[str, float]:
    """One BLS monthly series as month to value. The public v1 API needs no key."""
    first, last = int(HISTORY_FIRST_MONTH[:4]), int(LAST_MONTH[:4])
    url = (
        f"https://api.bls.gov/publicAPI/v1/timeseries/data/{series}"
        f"?startyear={first}&endyear={last}"
    )
    data = json.loads(_get(url))["Results"]["series"][0]["data"]
    # M13 is the annual average, and a withheld month comes back as "-".
    return {
        f"{d['year']}-{d['period'][1:]}": float(d["value"])
        for d in data
        if d["period"] != "M13" and d["value"].replace(".", "", 1).isdigit()
    }


def _unemployment(geo: str) -> dict[str, float]:
    return eurostat("une_rt_m", geo=geo, sex="T", age="TOTAL", unit="PC_ACT", s_adj="SA")


# Every published series a health level reads, under the ids ``market_health.MARKETS`` points at.
SOURCES: dict[str, Callable[[], dict[str, float]]] = {
    "sp500": lambda: yahoo("^GSPC"),
    "stoxx": lambda: yahoo("^STOXX"),
    "ibex": lambda: yahoo("^IBEX"),
    "dax": lambda: yahoo("^GDAXI"),
    "ftse": lambda: yahoo("^FTSE"),
    "unemp_eu": lambda: _unemployment("EU27_2020"),
    "unemp_es": lambda: _unemployment("ES"),
    "unemp_de": lambda: _unemployment("DE"),
    "unemp_uk": lambda: ons(
        "employmentandlabourmarket/peoplenotinwork/unemployment", "mgsx", "lms"
    ),
    "unemp_us": lambda: bls("LNS14000000"),
    "hicp_ea": lambda: ecb("HICP/M.U2.N.000000.4D0.ANR"),
    "hicp_es": lambda: ecb("HICP/M.ES.N.000000.4D0.ANR"),
    "hicp_de": lambda: ecb("HICP/M.DE.N.000000.4D0.ANR"),
    "cpi_uk": lambda: ons("economy/inflationandpriceindices", "d7g7", "mm23"),
    "cpi_us": lambda: oecd_price("USA"),
    "euribor_12m": lambda: ecb("FM/M.U2.EUR.RT.MM.EURIBOR1YD_.HSTA"),
    "uk_short_rate": lambda: oecd("IRSTCI", "GBR"),
    "us_short_rate": lambda: oecd("IRSTCI", "USA"),
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    published: dict[str, dict[str, float]] = {}
    for series_id, fetch in SOURCES.items():
        try:
            published[series_id] = fetch()
        except Exception as exc:  # the demo ships the committed file; a dead source is not fatal
            logger.warning("%s: fetch failed (%s)", series_id, exc)
            continue
        last = max((m for m in published[series_id] if m <= LAST_MONTH), default="nothing")
        logger.info("%s: published to %s", series_id, last)

    health = market_health.build(published, HISTORY, MONTHS)

    OUT_PATH.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).strftime("%Y-%m-%d"),
                "first_month": FIRST_MONTH,
                "months": MONTHS,
                "series": health,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    logger.info("wrote %s (%d markets)", OUT_PATH, len(health))


if __name__ == "__main__":
    main()
