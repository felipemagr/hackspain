from datetime import date

import pytest

from xray.agents.sources import is_social, published_on, tier


@pytest.mark.parametrize(
    "url, published_date, expected",
    [
        ("https://www.expansion.com/empresas/2026/06/26/abc.html", None, date(2026, 6, 26)),
        ("https://cincodias.elpais.com/companias/2026-03-30/x.html", None, date(2026, 3, 30)),
        ("https://www.capitalmadrid.com/2026/6/15/71894/x.html", None, date(2026, 6, 15)),
        ("https://www.eleconomista.es/noticias/12425998/09/23/x.html", None, date(2023, 9, 1)),
        ("https://www.elespanol.com/invertia/empresas/20200205/x/1_0.html", None, date(2020, 2, 5)),
        ("https://example.com/x", "Wed, 28 May 2025 00:00:00 GMT", date(2025, 5, 28)),
        ("https://example.com/x", "not a date", None),
        ("https://example.com/2026/13/40/x", None, None),
    ],
)
def test_published_on(url, published_date, expected):
    assert published_on(url, published_date) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.boe.es/borme/x", 1),
        ("https://empresite.eleconomista.es/CABIFY.html", 2),
        ("https://www.eleconomista.es/x", 3),
        ("https://www.farodevigo.es/x", 4),
    ],
)
def test_tier_matches_most_specific_domain(url, expected):
    assert tier(url) == expected


def test_is_social_covers_subdomains_only():
    assert is_social("https://m.facebook.com/groups/1")
    assert not is_social("https://notfacebook.com/x")
