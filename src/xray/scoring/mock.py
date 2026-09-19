"""Invented serving tables so the product can be built before the real score exists.

Writes the tables documented in docs/serving-contract.md to data/serving. Every number is made
up, but it follows the design in docs/health-score-research.md: five pillars, renormalised
weights, cap rule, additive drivers, Theil-Sen trend, CUSUM states. The real engine must write
the same tables so the product does not change when it lands.
"""

import numpy as np
import pandas as pd

from xray.config import WINDOW_FIRST_MONTH, WINDOW_LAST_MONTH
from xray.settings import get_settings

SEED = 2026
MONTHS = pd.date_range(WINDOW_FIRST_MONTH, WINDOW_LAST_MONTH, freq="MS")
WEIGHTS = {
    "liquidity": 0.25,
    "cash_generation": 0.25,
    "payment_discipline": 0.20,
    "collections": 0.15,
    "debt_burden": 0.15,
}
PILLARS = list(WEIGHTS)
INVOICE_PILLARS = ["payment_discipline", "collections"]
MIN_HISTORY = 6
COUNTRIES = ["ES", "ES", "PT", "FR", "IT"]
# Compound score: the level projected this many months along its trend.
HORIZON_MONTHS = 4

# archetype -> (n groups, start level range, total level shift range)
ARCHETYPES = {
    "healthy": (11, (74, 90), (-3, 3)),
    "stable": (6, (48, 66), (-4, 4)),
    "improving": (7, (35, 55), (14, 24)),
    "bending": (6, (76, 88), (-18, -11)),
    "falling": (6, (55, 70), (-34, -20)),
    "bump": (6, (62, 84), (-2, 2)),
    "new": (3, (50, 80), (-3, 3)),
}
# Named demo groups: archetype, start level, shift, onset month index. The first two are the
# brief's worked example.
# Slow ramps, so both are still moving at month 24.
HEROES = {
    "Northbrook Foods": ("improving", 45, 20, 8),
    "Velasco Industrial": ("bending", 82, -14, 11),
    # Real name on purpose: it keys the public context cached by the context retrieval agent.
    "Cabify": ("improving", 52, 17, 9),
}

NAMES = [
    ("Northbrook Foods", "Food and beverage"),
    ("Velasco Industrial", "Industrial manufacturing"),
    ("Cabify", "Mobility"),
    ("Alcor Logistica", "Logistics"),
    ("Brisa Hoteles", "Hospitality"),
    ("Cantera Norte", "Construction materials"),
    ("Delfos Pharma", "Pharma distribution"),
    ("Estela Retail", "Retail"),
    ("Fragua Metalurgica", "Metalworking"),
    ("Garbi Energia", "Energy services"),
    ("Helix Software", "Software"),
    ("Iberlact", "Dairy"),
    ("Jara Agro", "Agriculture"),
    ("Kuna Textil", "Textile"),
    ("Lumen Optica", "Optical retail"),
    ("Marea Pesquera", "Fishing"),
    ("Nogal Muebles", "Furniture"),
    ("Orbita Telecom", "Telecom services"),
    ("Pradera Carnicas", "Meat processing"),
    ("Quorum Consulting", "Professional services"),
    ("Ribera Vinos", "Wine"),
    ("Sendero Transportes", "Road transport"),
    ("Tundra Frio", "Cold chain"),
    ("Umbral Seguridad", "Security services"),
    ("Vega Packaging", "Packaging"),
    ("Windmar Nautica", "Marine equipment"),
    ("Xaloc Turismo", "Travel"),
    ("Yunque Forja", "Forging"),
    ("Zenit Clinicas", "Private healthcare"),
    ("Arrecife Surf", "Sporting goods"),
    ("Boreal Climatizacion", "HVAC"),
    ("Cierzo Eolica", "Wind maintenance"),
    ("Dehesa Iberica", "Cured meats"),
    ("Ebro Quimica", "Chemicals"),
    ("Faro Editorial", "Publishing"),
    ("Granito Obras", "Construction"),
    ("Horizonte Formacion", "Education"),
    ("Isla Cosmetics", "Cosmetics"),
    ("Jade Electronica", "Electronics distribution"),
    ("Kilate Joyeria", "Jewellery"),
    ("Levante Citricos", "Citrus export"),
    ("Mistral Aero", "Aerospace parts"),
    ("Nimbus Cloud", "IT services"),
    ("Olmo Papel", "Paper"),
    ("Pico Outdoor", "Outdoor retail"),
]

ACTIONS = {
    "liquidity": "Build the cash buffer back: draw the working-capital line before month end "
    "and move idle savings balances into the operating account.",
    "cash_generation": "Operating margin is thin: review the three largest recurring outflows "
    "and reprice or renegotiate the contracts renewing this quarter.",
    "payment_discipline": "Clear the supplier invoices more than 30 days overdue, largest first, "
    "and agree a payment calendar with the top five suppliers.",
    "collections": "Chase the receivables older than 60 days and offer early-payment discount "
    "or factoring on the two largest customers.",
    "debt_burden": "Debt service is heavy against inflows: refinance the short-term facilities "
    "into a longer amortising loan.",
}


def _theil_sen(y: np.ndarray) -> float:
    i, j = np.triu_indices(len(y), k=1)
    return float(np.median((y[j] - y[i]) / (j - i)))


def _pillar_paths(
    rng, archetype: str, start: float, shift: float, onset: int, width: float
) -> pd.DataFrame:
    """24 months of pillar scores whose weighted mean moves from start to start + shift."""
    n = len(MONTHS)
    base = start + rng.normal(0, 7, len(PILLARS))
    base += start - np.dot(base, list(WEIGHTS.values()))
    # Two pillars carry the move, the rest follow weakly, scaled so the level shift is exact.
    mult = np.full(len(PILLARS), 0.4)
    mult[rng.choice(len(PILLARS), 2, replace=False)] = 1.8
    mult /= np.dot(mult, list(WEIGHTS.values()))
    ramp = 1 / (1 + np.exp(-(np.arange(n) - onset - 2.5 * width) / width))
    ramp = (ramp - ramp[0]) / (ramp[-1] - ramp[0])
    noise = np.zeros((n, len(PILLARS)))
    for t in range(1, n):
        noise[t] = 0.5 * noise[t - 1] + rng.normal(0, 2.2, len(PILLARS))
    paths = base + np.outer(ramp, mult * shift) + noise
    if archetype == "bump":
        t = int(rng.integers(8, 21))
        paths[t, :2] -= (38, 22)
        paths[t + 1, :2] -= (6, 3)
    return pd.DataFrame(paths.clip(3, 99), columns=PILLARS)


def _level(pillars: pd.DataFrame) -> pd.DataFrame:
    """Renormalised weights, additive contributions, cap rule."""
    w = pd.Series(WEIGHTS) * pillars.notna()
    w = w.div(w.sum(axis=1), axis=0)
    contrib = w * (pillars.fillna(50) - 50)
    out = pd.DataFrame({"level_uncapped": 50 + contrib.sum(axis=1)})
    out["is_capped"] = (pillars[["liquidity", "payment_discipline"]] < 25).any(axis=1) & (
        out["level_uncapped"] > 50
    )
    out["level"] = out["level_uncapped"].where(~out["is_capped"], 50.0)
    out["coverage"] = (pd.Series(WEIGHTS) * pillars.notna()).sum(axis=1)
    return out.join(contrib.add_prefix("contrib_"))


def _states(level: np.ndarray) -> pd.DataFrame:
    """Trend, robust CUSUM in both directions and the state table of the research doc."""
    rows, s_dn, s_up, zero_dn, zero_up = [], 0.0, 0.0, 0, 0
    down = up = False
    for t in range(len(level)):
        if t + 1 < MIN_HISTORY:
            rows.append((np.nan, "not_enough_data", None))
            continue
        changes = np.diff(level[: t + 1])
        sigma = max(1.4826 * np.median(np.abs(changes - np.median(changes))), 1.5)
        ref = np.median(level[max(0, t - 12) : t])
        # Deviation clipped at 2 sigma so one outlier month cannot raise the alarm alone.
        dev = np.clip((ref - level[t]) / sigma, -2, 2)
        s_dn, s_up = max(0.0, s_dn + dev - 0.75), max(0.0, s_up - dev - 0.75)
        zero_dn, zero_up = (t if s_dn == 0 else zero_dn), (t if s_up == 0 else zero_up)
        slope = _theil_sen(level[t - MIN_HISTORY + 1 : t + 1])
        # Latched: once raised, an alarm holds until its CUSUM is back at zero.
        down, up = s_dn > 4 or (down and s_dn > 0), s_up > 4 or (up and s_up > 0)
        if down:
            state, onset = ("falling" if level[t] < 60 else "bending"), zero_dn + 1
        elif up or slope >= 1.5:
            state, onset = "improving", zero_up + 1 if up else t - MIN_HISTORY + 1
        elif dev >= 2:
            state, onset = "bump", None
        else:
            state = "healthy" if level[t] >= 70 else "stable" if level[t] >= 40 else "weak"
            onset = None
        rows.append((slope, state, onset))
    return pd.DataFrame(rows, columns=["trend", "state", "onset_idx"])


def _tier(level: pd.Series) -> pd.Series:
    return pd.cut(level, [-1, 40, 70, 101], right=False, labels=["vulnerable", "coping", "healthy"])


def _indicators(p: pd.DataFrame) -> pd.DataFrame:
    """Headline raw indicators, read back from the pillar scores through the published anchors."""
    paydex, days = [20, 30, 40, 50, 60, 70, 80, 100], [120, 90, 60, 30, 22, 15, 0, -5]
    return pd.DataFrame(
        {
            "buffer_days": np.interp(p["liquidity"], [0, 35, 60, 85, 100], [0, 13, 27, 62, 120]),
            "operating_margin": np.interp(p["cash_generation"], [0, 50, 100], [-0.15, 0.04, 0.25]),
            "ap_days_beyond_terms": np.interp(p["payment_discipline"], paydex, days),
            "ar_days_beyond_terms": np.interp(p["collections"], paydex, days),
            "dscr": np.interp(p["debt_burden"], [10, 35, 60, 90], [0.8, 1.0, 1.25, 2.0]),
        }
    ).round(2)


def _alerts(g: pd.DataFrame) -> list[dict]:
    """One alert per transition into bending, falling or improving, with measured anticipation."""
    out = []
    level, tier = g["level"].to_numpy(), g["tier"].astype(str).to_numpy()
    for t in range(1, len(g)):
        state, prev = g["state"].iat[t], g["state"].iat[t - 1]
        if state == prev or state not in ("bending", "falling", "improving"):
            continue
        onset = int(g["onset_idx"].iat[t])
        moved = (
            g[[f"contrib_{p}" for p in PILLARS]].iloc[t]
            - g.iloc[onset][[f"contrib_{p}" for p in PILLARS]]
        ).astype(float)
        moved.index = PILLARS
        top = (moved.nsmallest(2) if state != "improving" else moved.nlargest(2)).index.tolist()
        # Anticipation: months until the tier itself changes, the point a snapshot would notice.
        crossed = [k for k in range(t, len(g)) if tier[k] != tier[onset]]
        out.append(
            {
                "group_id": g["group_id"].iat[t],
                "month": g["month"].iat[t],
                "state_from": prev,
                "state_to": state,
                "onset_month": g["month"].iat[onset],
                "level_at_onset": round(level[onset], 1),
                "level_at_alert": round(level[t], 1),
                "driver_1": top[0],
                "driver_2": top[1],
                "tier_change_month": g["month"].iat[crossed[0]] if crossed else pd.NaT,
                "anticipation_months": crossed[0] - t if crossed else np.nan,
            }
        )
    return out


def build(seed: int = SEED) -> dict[str, pd.DataFrame]:
    """Generate every serving table. Deterministic for a given seed."""
    rng = np.random.default_rng(seed)
    plan = [a for a, (n, _, _) in ARCHETYPES.items() for _ in range(n)]
    for _, (archetype, *_rest) in HEROES.items():
        plan.remove(archetype)
    rng.shuffle(plan)
    plan = [HEROES[n][0] for n, _ in NAMES[: len(HEROES)]] + plan

    groups, scores, companies = [], [], []
    for i, ((name, sector), archetype) in enumerate(zip(NAMES, plan, strict=True), start=1):
        gid = f"DEMO_{i:03d}"
        _, start_rng, shift_rng = ARCHETYPES[archetype]
        if name in HEROES:
            _, start, shift, onset = HEROES[name]
            has_erp, first, width = True, 0, 3.0
        else:
            start, shift = rng.uniform(*start_rng), rng.uniform(*shift_rng)
            onset = int(rng.integers(6, 15))
            has_erp = rng.random() < 0.67
            first = 20 if archetype == "new" else int(rng.choice([0, 0, 0, 3, 6]))
            width = rng.uniform(1.5, 3.0)
        pillars = _pillar_paths(rng, archetype, start, shift, onset, width)
        if not has_erp:
            pillars[INVOICE_PILLARS] = np.nan
        pillars = pillars.iloc[first:].reset_index(drop=True)
        g = pd.concat([pillars.round(1), _level(pillars), _indicators(pillars)], axis=1)
        g = g.join(_states(g["level"].to_numpy()))
        g.insert(0, "group_id", gid)
        g.insert(1, "month", MONTHS[first:])
        g["months_observed"] = np.arange(1, len(g) + 1)
        g["compound"] = (g["level"] + HORIZON_MONTHS * g["trend"].fillna(0)).clip(0, 100)
        g["tier"] = _tier(g["level"])
        # Inflow follows the cash generation pillar, with a yearly season.
        revenue = float(np.exp(rng.normal(np.log(12e6), 0.9)))
        season = 1 + 0.08 * np.sin(2 * np.pi * (g["month"].dt.month / 12 + rng.random()))
        growth = np.cumprod(1 + (g["cash_generation"] - 55) / 2500)
        g["monthly_inflow_eur"] = (revenue / 12 * season * growth).round(-2)
        scores.append(g)

        n_comp = int(min(1 + rng.geometric(0.45), 8))
        share = rng.dirichlet(np.full(n_comp, 1.5))
        comp_level = (g["level"].iat[-1] + rng.normal(0, 9, n_comp)).clip(5, 98)
        for k in range(n_comp):
            companies.append(
                {
                    "company_id": f"{gid}_C{k + 1:02d}",
                    "group_id": gid,
                    "name": name if k == 0 else f"{name.split()[0]} {'BCDEFGHI'[k - 1]} SL",
                    "inflow_share": round(share[k], 3),
                    "level": round(comp_level[k], 1),
                    "is_weakest": bool(n_comp > 1 and k == comp_level.argmin()),
                }
            )
        groups.append(
            {
                "group_id": gid,
                "name": name,
                "sector": sector,
                "country": "ES" if name in HEROES else str(rng.choice(COUNTRIES)),
                "n_companies": n_comp,
                "has_erp": has_erp,
                "annual_revenue_eur": round(revenue, -3),
                "archetype": archetype,
            }
        )

    scores = pd.concat(scores, ignore_index=True)
    alerts = pd.DataFrame([a for _, g in scores.groupby("group_id") for a in _alerts(g)])

    # Working-capital offer, repriced monthly from the compound score. No offer under 40.
    offers = scores[["group_id", "month", "compound", "monthly_inflow_eur"]].copy()
    eligible = (offers["compound"] >= 40) & (scores["state"] != "not_enough_data")
    factor = np.interp(offers["compound"], [40, 90], [0.2, 1.5])
    offers["eligible"] = eligible
    offers["limit_eur"] = (offers["monthly_inflow_eur"] * factor).where(eligible, 0).round(-3)
    offers["apr"] = (
        pd.Series(np.interp(offers["compound"], [40, 90], [0.125, 0.045])).where(eligible).round(4)
    )
    offers["limit_change_eur"] = offers.groupby("group_id")["limit_eur"].diff()
    offers = offers.drop(columns=["compound", "monthly_inflow_eur"])

    # Three ranked actions on the weakest drivers of the last month.
    last = scores.groupby("group_id").tail(1).set_index("group_id")
    contrib = last[[f"contrib_{p}" for p in PILLARS]].set_axis(PILLARS, axis=1)
    actions = []
    for gid, row in contrib.iterrows():
        weakest = row.where(last.loc[gid, PILLARS].notna()).dropna().nsmallest(3)
        for rank, (pillar, _) in enumerate(weakest.items(), start=1):
            gap = max(70 - last.loc[gid, pillar], 5)
            weight = WEIGHTS[pillar] / last.loc[gid, "coverage"]
            actions.append(
                {
                    "group_id": gid,
                    "month": last.loc[gid, "month"],
                    "rank": rank,
                    "pillar": pillar,
                    "action": ACTIONS[pillar],
                    "expected_level_gain": round(0.4 * gap * weight, 1),
                }
            )

    # Long driver table: one row per group, month and pillar, with the month-on-month move.
    drivers = scores.melt(["group_id", "month"], PILLARS, "pillar", "score").dropna()
    contrib_cols = [f"contrib_{p}" for p in PILLARS]
    contrib = scores.melt(["group_id", "month"], contrib_cols, "pillar", "contribution")
    contrib["pillar"] = contrib["pillar"].str.removeprefix("contrib_")
    drivers = drivers.merge(contrib, on=["group_id", "month", "pillar"]).sort_values(
        ["group_id", "pillar", "month"]
    )
    drivers["delta_score"] = drivers.groupby(["group_id", "pillar"])["score"].diff()
    drivers["delta_contribution"] = drivers.groupby(["group_id", "pillar"])["contribution"].diff()

    scores = scores.drop(columns=["onset_idx"] + [f"contrib_{p}" for p in PILLARS])
    scores["tier"] = scores["tier"].astype(str)
    round_cols = ["level", "level_uncapped", "compound", "trend", "coverage"]
    scores[round_cols] = scores[round_cols].round(2)
    return {
        "groups": pd.DataFrame(groups),
        "companies": pd.DataFrame(companies),
        "scores": scores,
        "drivers": drivers.round({c: 2 for c in drivers.columns if "score" in c or "contrib" in c}),
        "alerts": alerts,
        "offers": offers,
        "actions": pd.DataFrame(actions),
    }


def main() -> None:
    serving_dir = get_settings().serving_dir
    for name, table in build().items():
        table.to_parquet(serving_dir / f"{name}.parquet", index=False)
        print(f"{name:10s} {len(table):5d} rows -> {serving_dir / name}.parquet")


if __name__ == "__main__":
    main()
