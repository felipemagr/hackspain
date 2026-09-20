"""Give the groups of a dump trading names and sectors, for the demo.

The challenge dump identifies groups and companies by id only. This step labels them from a
roster of real companies: Embat's published customers first (embat.io/success-stories, with the
sector, country and ERP stated there), then companies of the same profile in the industries Embat
serves. A name lands on a group that shares its ERP and country where the dump says so, and
bigger names land on groups with more entities.

Cosmetic only: no score, feature or prediction reads a name. Every figure under a name is
synthetic and says nothing about the real company.
"""

from pathlib import Path

import pandas as pd

ROSTER_PATH = Path(__file__).with_name("names_roster.csv")

COUNTRY_NAMES = {
    "ES": "España",
    "PT": "Portugal",
    "FR": "France",
    "DE": "Deutschland",
    "IT": "Italia",
    "NL": "Nederland",
    "BE": "Belgium",
    "GB": "UK",
    "US": "USA",
    "SE": "Sverige",
    "AT": "Österreich",
    "PL": "Polska",
    "MY": "Malaysia",
}
ENTITIES = [
    "Holding",
    "Operaciones",
    "Servicios",
    "Distribución",
    "Logística",
    "Digital",
    "Inmuebles",
    "Internacional",
    "Iberia",
    "Norte",
    "Sur",
    "Levante",
    "Canarias",
    "Baleares",
    "Catalunya",
    "Madrid",
    "Andalucía",
    "Galicia",
    "Euskadi",
    "Franquicias",
    "Compras",
    "Finance",
    "Ventures",
    "Labs",
]


def _assign(profile: pd.DataFrame, roster: pd.DataFrame) -> dict[str, int]:
    """Group id -> roster row. ERP matches first, then country, then whatever is left by size."""
    biggest_first = profile.sort_values(["n_companies", "group_id"], ascending=[False, True])
    roster = roster.sort_values("size", ascending=False, kind="stable")
    free_groups = list(biggest_first["group_id"])
    free_names = list(roster.index)
    group_erp = profile.set_index("group_id")["erp"]
    group_country = profile.set_index("group_id")["country"]
    assigned: dict[str, int] = {}

    def take(gid: str, row: int) -> None:
        assigned[gid] = row
        free_groups.remove(gid)
        free_names.remove(row)

    for row in [r for r in free_names if pd.notna(roster.at[r, "erp"])]:
        same_erp = [g for g in free_groups if group_erp[g] == roster.at[row, "erp"]]
        same_country = [g for g in same_erp if group_country[g] == roster.at[row, "country"]]
        if same_erp:
            take((same_country or same_erp)[0], row)
    for gid in [g for g in free_groups if pd.notna(group_country[g])]:
        same_country = [r for r in free_names if roster.at[r, "country"] == group_country[gid]]
        if same_country:
            take(gid, same_country[0])
    # What is left has no stated country (or its country ran out of names): home market first.
    rest = sorted(free_names, key=lambda r: roster.at[r, "country"] != "ES")
    assigned.update(zip(free_groups, rest, strict=False))
    return assigned


def _company_names(companies: pd.DataFrame, group_names: pd.Series, home: pd.Series) -> pd.Series:
    """A legal-entity style name per company: the country when it is abroad, else a division."""
    out = pd.Series(index=companies.index, dtype=object)
    for gid, rows in companies.sort_values("company_id").groupby("group_id"):
        name = group_names.get(gid)
        if name is None:
            continue
        if len(rows) == 1:
            out[rows.index[0]] = name
            continue
        divisions = iter(ENTITIES)
        seen: dict[str, int] = {}
        for idx, country in rows["country"].items():
            abroad = pd.notna(country) and country != home.get(gid) and country in COUNTRY_NAMES
            label = COUNTRY_NAMES[country] if abroad else next(divisions, "Filial")
            seen[label] = seen.get(label, 0) + 1
            suffix = f" {seen[label]}" if seen[label] > 1 else ""
            out[idx] = f"{name} {label}{suffix}"
    return out


def apply(groups: pd.DataFrame, companies: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add ``name`` and ``sector`` to groups and ``name`` to companies.

    Reads only what never changes between extracts of a dump (ERP, country, entity count), so a
    group keeps its name while the replay lands it month by month.

    A dump that already names its groups (the synthetic demo) is returned untouched. Groups
    beyond the roster keep no name, and the serving layer falls back to the id.
    """
    if "name" in groups:
        return groups, companies
    roster = pd.read_csv(ROSTER_PATH)
    by_group = companies.groupby("group_id")
    profile = pd.DataFrame(
        {
            "group_id": groups["group_id"],
            "erp": groups["erp"] if "erp" in groups else None,
            "country": groups["group_id"].map(
                by_group["country"].agg(lambda s: s.mode().iat[0] if s.notna().any() else None)
            ),
            "n_companies": groups["n_companies_in_sample"]
            if "n_companies_in_sample" in groups
            else groups["group_id"].map(by_group.size()).fillna(0),
        }
    )
    rows = groups["group_id"].map(_assign(profile, roster))
    groups = groups.assign(
        name=rows.map(roster["name"]).to_numpy(), sector=rows.map(roster["sector"]).to_numpy()
    )
    group_names = groups.dropna(subset=["name"]).set_index("group_id")["name"]
    home = profile.set_index("group_id")["country"]
    companies = companies.assign(name=_company_names(companies, group_names, home))
    return groups, companies
