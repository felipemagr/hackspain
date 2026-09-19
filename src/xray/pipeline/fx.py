"""Currency conversion to euros at the average rate of each year.

The rates live in `fx_rates.csv`, next to this module and in git: one row per currency and year,
units of the currency per euro. The pipeline only ever reads that file, so it needs no network
and a group scores the same alone as inside a portfolio. `make fx` rebuilds the file.

Where a rate comes from, best source first:

1. `ecb`: the mean of the ECB monthly reference rates of the year (the current year runs to the
   last month published).
2. `peg`: a currency fixed to the euro, or fixed to one the ECB publishes.
3. `data`: the median `exchange_rate` of the year on invoices booked against the euro. The
   median, because a few rows are off by orders of magnitude.
4. `reference`: a hand-set figure for a currency seen nowhere else. A handful of rows use them.

A year with no rate takes the nearest year that has one.
"""

import argparse
import io
import logging
from functools import lru_cache
from pathlib import Path

import httpx
import pandas as pd

from xray.config import PROCESSED_DATA_DIR

logger = logging.getLogger(__name__)

RATES_FILE = Path(__file__).with_name("fx_rates.csv")
ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/M..EUR.SP00.A"
FIRST_YEAR = 2015
REQUEST_TIMEOUT_SECONDS = 60.0
MIN_OBSERVATIONS = 5

# Units per euro, fixed by treaty or currency board.
EURO_PEGS = {"BAM": 1.95583, "XOF": 655.957, "XAF": 655.957}
# Units per unit of an ECB currency: (anchor, units per anchor).
CROSS_PEGS = {"AED": ("USD", 3.6725), "SAR": ("USD", 3.75), "NAD": ("ZAR", 1.0)}
# Too rare in the data for a yearly median, or never seen against the euro. Approximate.
REFERENCE = {"GHS": 13.5, "VND": 29500.0, "RUB": 98.0, "MAD": 10.6, "AOA": 1075.0}


def fetch_ecb() -> pd.DataFrame:
    """Yearly mean of the ECB monthly reference rates: currency, year, per_eur."""
    response = httpx.get(
        ECB_URL,
        params={"startPeriod": f"{FIRST_YEAR}-01", "format": "csvdata"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    monthly = pd.read_csv(
        io.StringIO(response.text), usecols=["CURRENCY", "TIME_PERIOD", "OBS_VALUE"]
    )
    monthly["year"] = monthly["TIME_PERIOD"].str[:4].astype(int)
    yearly = monthly.groupby(["CURRENCY", "year"], as_index=False)["OBS_VALUE"].mean()
    return yearly.rename(columns={"CURRENCY": "currency", "OBS_VALUE": "per_eur"})


def rates_from_invoices(invoices: pd.DataFrame) -> pd.DataFrame:
    """Yearly median rate against the euro seen on invoices: currency, year, per_eur.

    `exchange_rate` is units of the invoice currency per unit of the accounting currency.
    """
    seen = invoices[invoices["exchange_rate"] > 0]
    to_eur = seen[(seen["accounting_currency"] == "EUR") & (seen["currency"] != "EUR")]
    from_eur = seen[(seen["currency"] == "EUR") & (seen["accounting_currency"] != "EUR")]
    observed = pd.concat(
        [
            pd.DataFrame(
                {
                    "currency": to_eur["currency"],
                    "year": to_eur["issuance_date"].dt.year,
                    "per_eur": to_eur["exchange_rate"],
                }
            ),
            pd.DataFrame(
                {
                    "currency": from_eur["accounting_currency"],
                    "year": from_eur["issuance_date"].dt.year,
                    "per_eur": 1 / from_eur["exchange_rate"],
                }
            ),
        ]
    ).dropna()
    yearly = observed.groupby(["currency", "year"])["per_eur"].agg(["median", "size"])
    enough = yearly[yearly["size"] >= MIN_OBSERVATIONS].reset_index()
    return enough.rename(columns={"median": "per_eur"})[["currency", "year", "per_eur"]]


def build_rates(invoices: pd.DataFrame) -> pd.DataFrame:
    """The full table, each currency from its best source."""
    ecb = fetch_ecb().assign(source="ecb")
    years = sorted(ecb["year"].unique())
    pegs = [
        pd.DataFrame({"currency": currency, "year": years, "per_eur": rate, "source": "peg"})
        for currency, rate in EURO_PEGS.items()
    ]
    for currency, (anchor, units) in CROSS_PEGS.items():
        anchored = ecb[ecb["currency"] == anchor]
        pegs.append(
            anchored.assign(currency=currency, per_eur=anchored["per_eur"] * units, source="peg")
        )
    data = rates_from_invoices(invoices).assign(source="data")
    reference = [
        pd.DataFrame({"currency": currency, "year": years, "per_eur": rate, "source": "reference"})
        for currency, rate in REFERENCE.items()
    ]
    # Earlier sources win, year by year: the ECB stopped publishing ARS in 2019 and RUB in 2022,
    # and the later years of those come from the data or the reference figure.
    table = pd.concat([ecb, *pegs, data, *reference]).drop_duplicates(["currency", "year"])
    return table.sort_values(["currency", "year"]).round({"per_eur": 6}).reset_index(drop=True)


@lru_cache
def load_rates() -> pd.DataFrame:
    return pd.read_csv(RATES_FILE)


def per_eur(currency: pd.Series, year: pd.Series) -> pd.Series:
    """Units of `currency` per euro in `year`, aligned to the inputs. Euro is 1.

    A year without a rate takes the nearest year with one. A currency without any rate is
    logged and left at 1: better a visible warning than a silently dropped row.
    """
    rates = load_rates()
    # No currency on a row means the company's home market: the euro. No date, the latest year.
    asked = pd.DataFrame(
        {
            "currency": currency.fillna("EUR").to_numpy(),
            "year": year.fillna(rates["year"].max()).to_numpy(),
        }
    )
    pairs = asked.dropna().drop_duplicates()
    pairs = pairs[pairs["currency"] != "EUR"]
    known = rates.merge(pairs, on="currency", suffixes=("_rate", ""))
    known["gap"] = (known["year_rate"] - known["year"]).abs()
    nearest = known.sort_values("gap").drop_duplicates(["currency", "year"])
    out = asked.merge(nearest[["currency", "year", "per_eur"]], on=["currency", "year"], how="left")
    missing = set(asked.loc[out["per_eur"].isna() & (asked["currency"] != "EUR"), "currency"])
    if missing:
        logger.warning("No euro rate for %s: amounts left unconverted", sorted(missing))
    return pd.Series(out["per_eur"].fillna(1.0).to_numpy(), index=currency.index)


def to_eur(amount: pd.Series, currency: pd.Series, date: pd.Series) -> pd.Series:
    """`amount` in euros at the average rate of the year of `date`."""
    return amount / per_eur(currency, date.dt.year)


def main() -> None:
    """Rebuild fx_rates.csv from the ECB and the cleaned invoices."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--invoices", type=Path, default=PROCESSED_DATA_DIR / "invoices.parquet")
    args = parser.parse_args()
    table = build_rates(pd.read_parquet(args.invoices))
    table.to_csv(RATES_FILE, index=False)
    by_source = table.groupby("source")["currency"].nunique().to_dict()
    logger.info(
        "%d rates, %d currencies %s -> %s",
        len(table),
        table["currency"].nunique(),
        by_source,
        RATES_FILE,
    )


if __name__ == "__main__":
    main()
