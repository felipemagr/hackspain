"""What we know about a source before reading it: how far to trust it and when it was published."""

import re
from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

# Dropped on our side after the search. Passing them as Tavily's `exclude_domains` together
# with `topic="news"` collapses the results to a handful of low-score pages.
SOCIAL_DOMAINS = [
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "reddit.com",
    "threads.net",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
]

# 1 official filings, 2 registry aggregators, 3 financial press, 4 anything else.
# A regional paper at tier 4 still counts: the ERE at Pescanova only appeared there.
TIERS: dict[str, int] = {
    "boe.es": 1,
    "cnmv.es": 1,
    "registradores.org": 1,
    "axesor.es": 2,
    "einforma.com": 2,
    "empresite.eleconomista.es": 2,
    "infocif.es": 2,
    "infonif.economia3.com": 2,
    "libreborme.net": 2,
    "abc.es": 3,
    "alimarket.es": 3,
    "bloomberg.com": 3,
    "capitalmadrid.com": 3,
    "cincodias.elpais.com": 3,
    "efe.com": 3,
    "elconfidencial.com": 3,
    "eleconomista.es": 3,
    "elespanol.com": 3,
    "elmundo.es": 3,
    "elpais.com": 3,
    "elperiodico.com": 3,
    "europapress.es": 3,
    "expansion.com": 3,
    "financialfood.es": 3,
    "ft.com": 3,
    "investing.com": 3,
    "larazon.es": 3,
    "lavanguardia.com": 3,
    "reuters.com": 3,
    "theobjective.com": 3,
    "vozpopuli.com": 3,
}
DEFAULT_TIER = 4
TIER_LABELS = {1: "official", 2: "registry", 3: "financial press", 4: "other"}

# Spanish press puts the date in the path: /2026/06/26/, /2026-03-30/, /2026/6/15/.
_YMD_IN_PATH = re.compile(r"/(20\d\d)[/-](\d{1,2})[/-](\d{1,2})(?:[/-]|$)")
# El Español: /20200205/
_COMPACT_YMD = re.compile(r"/(20\d\d)(\d\d)(\d\d)/")
# El Economista: /<article id>/<MM>/<YY>/
_MY_AFTER_ID = re.compile(r"/\d{6,}/(\d\d)/(\d\d)/")


def domain(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host.removeprefix("www.")


def is_social(url: str) -> bool:
    host = domain(url)
    return any(host == social or host.endswith("." + social) for social in SOCIAL_DOMAINS)


def tier(url: str) -> int:
    """Most specific matching suffix wins, so a subdomain can outrank its parent."""
    host = domain(url)
    for candidate in sorted(TIERS, key=len, reverse=True):
        if host == candidate or host.endswith("." + candidate):
            return TIERS[candidate]
    return DEFAULT_TIER


def published_on(url: str, published_date: str | None) -> date | None:
    """The publication date from Tavily when it gives one, else from the URL, else None."""
    if published_date:
        try:
            return parsedate_to_datetime(published_date).date()
        except (TypeError, ValueError):
            pass
    path = urlparse(url).path
    if match := _YMD_IN_PATH.search(path):
        year, month, day = (int(part) for part in match.groups())
        return _safe_date(year, month, day)
    if match := _COMPACT_YMD.search(path):
        year, month, day = (int(part) for part in match.groups())
        return _safe_date(year, month, day)
    if match := _MY_AFTER_ID.search(path):
        month, year = (int(part) for part in match.groups())
        return _safe_date(2000 + year, month, 1)
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
