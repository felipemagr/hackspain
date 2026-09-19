"""A synthetic dump in the challenge's nine-CSV shape, for a roster of Spanish scale-ups.

The demo needs names the room knows and stories the score can find, and the challenge dump has
neither: ids for names, and whatever trajectories the generator happened to plant. This module
writes the raw trail of a roster of Spanish scale-ups, each with an archetype, and stops there.
Nothing downstream is scripted: the same pipeline that scores the challenge data reads these
files, and the level, the alerts and the offer have to emerge from the transactions, invoices and
balances written here. If a story does not show, the trail was not written well enough.

Every figure is invented. The names are labels for a demo of a synthetic dataset, the revenue
scale is an order of magnitude, and nothing here describes the real companies.

The dump is meant to sit beside the challenge dump in one portfolio (`make demo` replays both),
so every id it mints carries a `SYN_` prefix and cannot collide with a real product, movement,
invoice or counterparty.

    python -m xray.pipeline.synth --out data/demo/raw
"""

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from xray.config import WINDOW_FIRST_MONTH, WINDOW_LAST_MONTH

logger = logging.getLogger(__name__)

SEED = 2026
MONTHS = pd.date_range(WINDOW_FIRST_MONTH, WINDOW_LAST_MONTH, freq="MS")
SNAPSHOT_DATE = pd.Timestamp("2026-09-01")
BANKS = [
    "Banco Santander Empresas",
    "Caixabank Empresas",
    "BBVA Net Cash Empresas",
    "Banco Sabadell Empresas",
    "Bankinter Empresas",
]
# Company suffixes, in the order subsidiaries are created.
ENTITIES = ["Spain SL", "Technologies SL", "Operations SL", "Italia SRL", "Portugal Lda", "GmbH"]


@dataclass(frozen=True)
class Archetype:
    """How a group's trail moves over the 24 months, in multipliers on the monthly baseline."""

    buffer_days: float  # cash at the start, in days of operating outflow
    target_days: float  # the treasury sweeps half of the cash above this into investments
    margin: float  # (inflow - outflow) / inflow at the start
    inflow_shift: float  # multiplicative change of inflow from onset to the end
    margin_shift: float  # additive change of the margin from onset to the end
    ap_late_days: tuple[float, float]  # payables paid this many days after due, start -> end
    ar_late_days: tuple[float, float]  # receivables collected this many days after due
    onset: int  # month index where the move starts
    bump_month: int | None = None  # one outsized payment, refunded the month after


# Margins are before debt service, which takes another 7% of outflow where there is a loan.
ARCHETYPES = {
    "healthy": Archetype(75, 75, 0.12, 1.08, 0.0, (2, 2), (4, 4), 12),
    "stable": Archetype(35, 35, 0.06, 0.98, 0.0, (8, 8), (10, 10), 12),
    "improving": Archetype(12, 55, -0.01, 1.30, 0.12, (32, 3), (35, 5), 4),
    "bending": Archetype(55, 60, 0.10, 0.78, -0.17, (3, 26), (5, 28), 7),
    "falling": Archetype(30, 40, 0.02, 0.45, -0.30, (10, 55), (12, 45), 6),
    "bump": Archetype(50, 50, 0.10, 1.02, 0.0, (3, 3), (5, 5), 12, bump_month=13),
    "weak": Archetype(12, 30, 0.01, 0.95, -0.01, (35, 40), (30, 35), 12),
}
BUMP_SIZE = 2.0  # months of inflow paid out in the bump month and refunded the next
# Month-to-month noise on inflow and outflow. Real groups swing far more; this keeps the
# stories readable while leaving every series enough noise for the monitor's sigma to mean
# something.
INFLOW_NOISE = 0.25
OUTFLOW_NOISE = 0.15
SEASON_AMPLITUDE = 0.10
# The treasury sweeps everything above the target buffer into investments every month.
SWEEP_SHARE = 1.0

# name, sector, annual operating inflow in EUR (an order of magnitude, invented), companies,
# archetype, has an ERP feed. The first two are the brief's worked example.
ROSTER = [
    ("Glovo", "Delivery", 1_100e6, 5, "bending", True),
    ("Cabify", "Mobility", 750e6, 4, "improving", True),
    ("Jobandtalent", "Staffing", 1_900e6, 6, "healthy", True),
    ("Idealista", "Real estate portal", 380e6, 2, "healthy", True),
    ("Wallbox", "EV charging", 180e6, 3, "falling", True),
    ("Factorial", "HR software", 120e6, 2, "improving", True),
    ("TravelPerk", "Business travel", 260e6, 3, "improving", False),
    ("Fever", "Live entertainment", 520e6, 4, "bump", True),
    ("Devo", "Security analytics", 90e6, 2, "stable", True),
    ("Copado", "DevOps software", 110e6, 2, "bending", True),
    ("Typeform", "Forms software", 95e6, 2, "healthy", False),
    ("Wallapop", "Marketplace", 85e6, 1, "improving", True),
    ("Playtomic", "Sports booking", 60e6, 2, "improving", False),
    ("Seedtag", "Contextual advertising", 140e6, 3, "stable", True),
    ("Paack", "Last-mile logistics", 210e6, 3, "falling", True),
    ("Domestika", "Online learning", 130e6, 2, "bending", True),
    ("Genially", "Visual communication", 40e6, 1, "healthy", False),
    ("Clarity AI", "Sustainability data", 55e6, 2, "stable", True),
    ("Freepik", "Stock content", 160e6, 2, "healthy", True),
    ("Lookiero", "Fashion subscription", 70e6, 2, "bump", True),
    ("Spotahome", "Mid-term rentals", 30e6, 1, "falling", False),
    ("Colvin", "Flowers", 25e6, 1, "weak", True),
    ("Ontruck", "Freight", 45e6, 1, "bending", False),
    ("Cobee", "Employee benefits", 35e6, 1, "improving", True),
]

# Share of operating outflow by category, before debt service.
OUTFLOW_MIX = {"payment": 0.46, "salary": 0.30, "tax": 0.11, "utility": 0.05, "bulk_payment": 0.06}
FEE_SHARE = 0.004
DEBT_SHARE = 0.06  # of outflow, for groups with a loan
INTEREST_SHARE = 0.01
CUSTOMERS_PER_COMPANY = 18
SUPPLIERS_PER_COMPANY = 25


def _ramp(n: int, onset: int, width: float = 3.0) -> np.ndarray:
    """0 before the onset, 1 well after it, a smooth S in between."""
    ramp = 1 / (1 + np.exp(-(np.arange(n) - onset - 2 * width) / width))
    return (ramp - ramp[0]) / (ramp[-1] - ramp[0])


def _split(total: float, n: int, rng) -> np.ndarray:
    """Split a monthly total into n lognormal pieces that sum to it."""
    w = rng.lognormal(0, 0.9, n)
    return total * w / w.sum()


def _days(month: pd.Timestamp, n: int, rng) -> pd.DatetimeIndex:
    last = (month + pd.offsets.MonthEnd(0)).day
    return month + pd.to_timedelta(rng.integers(0, last, n), unit="D")


class Writer:
    """Accumulates the rows of every table for one dump."""

    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.rows = {
            name: []
            for name in (
                "companies",
                "banking_products",
                "debt_products",
                "debt_schedule_config",
                "transactions",
                "invoices",
                "balances",
            )
        }
        # Running balance per account, from the movements actually written. The snapshot the
        # bank hands over at the end is this number, so the roll-back lands exactly on it.
        self.balance: dict[str, float] = {}
        self.n_products = 0
        self.n_tx = 0
        self.n_inv = 0

    def product(self, opening: float = 0.0) -> str:
        self.n_products += 1
        pid = f"SYN_PRODUCT_{self.n_products:05d}"
        self.balance[pid] = opening
        return pid

    def tx(self, company: str, account: str, date, amount: float, category: str, cp=None):
        amount = round(amount, 2)
        self.n_tx += 1
        self.balance[account] += amount
        self.rows["transactions"].append(
            (
                f"SYN_TX_{self.n_tx:07d}",
                company,
                account,
                date,
                date,
                amount,
                1.0,
                "booked",
                "RECONCILIATION_COMPLETED",
                category,
                f"{category.upper()} [COMPANY]",
                cp,
            )
        )

    def invoice(self, company: str, issued, due, paid, amount: float, cp: str):
        self.n_inv += 1
        settled = paid is not None and paid < SNAPSHOT_DATE
        # As in the source: an unpaid invoice carries its due date where the payment date goes.
        self.rows["invoices"].append(
            (
                f"SYN_INV_{self.n_inv:07d}",
                company,
                "invoice",
                issued,
                due,
                paid if settled else due,
                round(amount, 2),
                0.0 if settled else round(amount, 2),
                "EUR",
                "EUR",
                1.0,
                "paid" if settled else ("overdue" if due < SNAPSHOT_DATE else "pending"),
                "Factura [REF]",
                cp,
            )
        )


def _company(
    w: Writer,
    gid: str,
    cid: str,
    name: str,
    monthly_inflow: float,
    a: Archetype,
    has_erp: bool,
    has_debt: bool,
    first_month: int,
) -> None:
    rng = w.rng
    n = len(MONTHS)
    ramp = _ramp(n, a.onset)
    season = 1 + SEASON_AMPLITUDE * np.sin(2 * np.pi * (np.arange(n) + rng.integers(0, 12)) / 12)
    noise = rng.lognormal(0, INFLOW_NOISE, n)
    inflow = monthly_inflow * season * noise * (1 + (a.inflow_shift - 1) * ramp)
    margin = a.margin + a.margin_shift * ramp
    outflow = inflow * (1 - margin) * rng.lognormal(0, OUTFLOW_NOISE, n)
    if a.bump_month is not None:
        outflow[a.bump_month] += BUMP_SIZE * monthly_inflow
        inflow[a.bump_month + 1] += BUMP_SIZE * monthly_inflow
    ap_late = a.ap_late_days[0] + (a.ap_late_days[1] - a.ap_late_days[0]) * ramp
    ar_late = a.ar_late_days[0] + (a.ar_late_days[1] - a.ar_late_days[0]) * ramp

    account = w.product(opening=a.buffer_days * outflow[:3].mean() / 30.4)
    card = w.product()
    for pid, label, kind in ((account, "CHECKING_01", "checking"), (card, "CARD_01", "card")):
        w.rows["banking_products"].append(
            (pid, cid, label, kind, rng.choice(BANKS), "corporate", "EUR", "2024-06-01")
        )
    loan = None
    if has_debt:
        loan = w.product()
        granted = round(monthly_inflow * 6, -3)
        outstanding = round(granted * rng.uniform(0.35, 0.8), 2)
        w.rows["debt_products"].append(
            (
                loan,
                cid,
                "LOAN_01",
                "loan",
                rng.choice(BANKS),
                "corporate",
                "EUR",
                "2023-03-01",
                granted,
                -outstanding,
                None,
            )
        )
        w.rows["debt_schedule_config"].append(
            (
                loan,
                cid,
                account,
                "EUR",
                "constant quote",
                "30/360",
                "monthly",
                granted,
                outstanding,
                60,
                "2026-09-30",
                "2026-08-30",
                0.045,
                "fixed",
            )
        )
    customers = [f"SYN_CP_{rng.integers(10_000, 99_999)}" for _ in range(CUSTOMERS_PER_COMPANY)]
    suppliers = [f"SYN_CP_{rng.integers(10_000, 99_999)}" for _ in range(SUPPLIERS_PER_COMPANY)]
    weights = 1 / np.arange(1, CUSTOMERS_PER_COMPANY + 1) ** 0.9
    weights /= weights.sum()

    pot = 0.0  # what the treasury has parked in investments so far
    for t, month in enumerate(MONTHS):
        if t < first_month:
            continue
        # Money in: collections against the customers, a few dozen a month.
        k = int(rng.integers(35, 70))
        pieces = _split(inflow[t], k, rng)
        for amount, day in zip(pieces, _days(month, k, rng), strict=True):
            w.tx(cid, account, day, amount, "collection", rng.choice(customers, p=weights))
        # Money out by category, on the days those things happen.
        for category, share in OUTFLOW_MIX.items():
            total = outflow[t] * share
            if category == "salary":
                w.tx(cid, account, month + pd.Timedelta(days=27), -total, "salary")
            elif category == "tax":
                w.tx(cid, account, month + pd.Timedelta(days=19), -total, "tax")
            else:
                k = int(rng.integers(15, 40))
                for amount, day in zip(_split(total, k, rng), _days(month, k, rng), strict=True):
                    w.tx(cid, account, day, -amount, category, rng.choice(suppliers))
        w.tx(cid, account, month + pd.Timedelta(days=1), -outflow[t] * FEE_SHARE, "fee")
        w.tx(cid, card, month + pd.Timedelta(days=15), -outflow[t] * 0.01, "payment")
        if loan:
            w.tx(
                cid,
                account,
                month + pd.Timedelta(days=4),
                -outflow[t] * DEBT_SHARE,
                "debt_repayment",
            )
            w.tx(
                cid,
                account,
                month + pd.Timedelta(days=4),
                -outflow[t] * INTEREST_SHARE,
                "interest_charge",
            )
        # Treasury policy: cash above the target buffer goes to short-term investments, and a
        # shortfall is topped up from them while they last. Neither is operating flow, so the
        # policy moves the buffer and nothing else; a group that burns cash runs the pot dry.
        excess = w.balance[account] - a.target_days * outflow[t] / 30.4
        if excess > 0:
            w.tx(
                cid,
                account,
                month + pd.Timedelta(days=25),
                -SWEEP_SHARE * excess,
                "investment_deployment",
            )
            pot += SWEEP_SHARE * excess
        elif pot > 0:
            back = min(-excess, pot)
            w.tx(cid, account, month + pd.Timedelta(days=25), back, "investment_return")
            pot -= back

        if has_erp:
            # Receivables: what the month's collections were billed as, collected late or not.
            k = int(rng.integers(20, 45))
            for amount, day in zip(_split(inflow[t], k, rng), _days(month, k, rng), strict=True):
                due = day + pd.Timedelta(days=int(rng.choice([30, 30, 60])))
                late = max(0.0, rng.normal(ar_late[t], 6))
                paid = due + pd.Timedelta(days=int(late)) if rng.random() > 0.03 else None
                w.invoice(cid, day, due, paid, amount, rng.choice(customers, p=weights))
            # Payables: the supplier side, paid with the group's own discipline.
            k = int(rng.integers(20, 45))
            for amount, day in zip(
                _split(outflow[t] * 0.5, k, rng), _days(month, k, rng), strict=True
            ):
                due = day + pd.Timedelta(days=int(rng.choice([30, 60])))
                late = max(0.0, rng.normal(ap_late[t], 5))
                paid = due + pd.Timedelta(days=int(late)) if rng.random() > 0.02 else None
                w.invoice(cid, day, due, paid, -amount, rng.choice(suppliers))

    # The final snapshot the bank hands over: where the movements above leave each account.
    for pid in (account, card):
        w.rows["balances"].append(
            (pid, cid, SNAPSHOT_DATE, round(w.balance[pid], 2), None, None, None, None)
        )
    w.rows["companies"].append(
        (cid, gid, "ES", "EUR", "netsuite" if has_erp else None, MONTHS[first_month].date(), name)
    )


def build(seed: int = SEED, roster=ROSTER) -> dict[str, pd.DataFrame]:
    """Generate every table of the dump, keyed by file name."""
    w = Writer(seed)
    groups = []
    for i, (name, sector, revenue, n_companies, archetype, has_erp) in enumerate(roster, start=1):
        gid = name.upper().replace(" ", "_")
        a = ARCHETYPES[archetype]
        shares = w.rng.dirichlet(np.full(n_companies, 2.0))
        has_debt = w.rng.random() < 0.6
        # Three groups onboard late, as in the challenge data.
        first_month = 0 if i % 8 else 9
        for k in range(n_companies):
            cid = f"{gid}_C{k + 1:02d}"
            _company(
                w,
                gid,
                cid,
                f"{name} {ENTITIES[k]}",
                revenue / 12 * shares[k],
                a,
                has_erp,
                has_debt and k == 0,
                first_month,
            )
        groups.append((gid, "netsuite" if has_erp else None, n_companies, name, sector, archetype))

    columns = {
        "groups": ["group_id", "erp", "n_companies_in_sample", "name", "sector", "archetype"],
        "companies": ["company_id", "group_id", "country", "currency", "erp", "created_at", "name"],
        "banking_products": [
            "product_id",
            "company_id",
            "label",
            "type",
            "bank_name",
            "service",
            "currency",
            "created_at",
        ],
        "debt_products": [
            "product_id",
            "company_id",
            "label",
            "type",
            "bank_name",
            "service",
            "currency",
            "created_at",
            "granted",
            "outstanding",
            "liquidity",
        ],
        "debt_schedule_config": [
            "product_id",
            "company_id",
            "settlement_product_id",
            "currency",
            "amortization_type",
            "interest_calc_method",
            "amortising_frequency",
            "granted_balance",
            "outstanding_balance",
            "total_periods",
            "next_payment_date",
            "last_payment_date",
            "annual_interest_rate_or_spread",
            "interest_type",
        ],
        "transactions": [
            "transaction_id",
            "company_id",
            "product_id",
            "date",
            "value_date",
            "amount",
            "exchange_rate",
            "status",
            "accounting_status",
            "category",
            "description",
            "counterparty_id",
        ],
        "invoices": [
            "operation_id",
            "company_id",
            "document_type",
            "issuance_date",
            "due_date",
            "payment_date",
            "amount",
            "pending_amount",
            "currency",
            "accounting_currency",
            "exchange_rate",
            "status",
            "concept",
            "counterparty_id",
        ],
        "balances": [
            "product_id",
            "company_id",
            "date",
            "balance",
            "available",
            "granted",
            "liquidity",
            "countable",
        ],
    }
    tables = {"groups": pd.DataFrame(groups, columns=columns["groups"])}
    for name, cols in columns.items():
        if name != "groups":
            tables[name] = pd.DataFrame(w.rows[name], columns=cols)
    return tables


def main() -> None:
    """Write the dump as CSVs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/demo/raw"))
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    for name, table in build(args.seed).items():
        table.to_csv(args.out / f"{name}.csv", index=False)
        logger.info("%-22s %8d rows -> %s", name, len(table), args.out / f"{name}.csv")


if __name__ == "__main__":
    main()
