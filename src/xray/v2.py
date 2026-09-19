"""Build an auditable, descriptive treasury dashboard from processed tables."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from xray.config import PROCESSED_DATA_DIR
from xray.v2_scores import load_score_config, score_entity

MONTHS = pd.date_range("2024-09-01", "2026-08-01", freq="MS")
SNAPSHOT = "2026-09-01"
EXCLUDED = {
    "transfer",
    "investment_deployment",
    "investment_return",
    "cash_withdrawal",
    "cash_settlement",
}
BUCKETS = {
    "payroll": {"salary", "social_security"},
    "debt_service": {"debt_repayment", "interest_charge"},
    "fees": {"fee"},
    "suppliers": {"payment", "bulk_payment", "utility"},
    "tax": {"tax"},
    "uncategorized": {"uncategorized"},
}
AGES = ["current", "d1_30", "d31_60", "d61_90", "d90_plus", "unknown_due"]
TABLES = ["companies", "banking_products", "debt_products", "balances", "transactions", "invoices"]


def ratio(numerator: float, denominator: float) -> float | None:
    """Return a ratio only when its denominator is positive and both values are finite."""
    if pd.isna(numerator) or pd.isna(denominator) or denominator <= 0:
        return None
    result = numerator / denominator
    return float(result) if np.isfinite(result) else None


def transaction_panel(
    tx: pd.DataFrame, banking: pd.DataFrame, companies: pd.DataFrame
) -> pd.DataFrame:
    """Aggregate same-currency movements with an exhaustive outflow decomposition."""
    currencies = banking.set_index("product_id").currency
    company_currency = companies.set_index("company_id").currency
    t = tx.copy()
    t["valid"] = (
        t.product_id.map(currencies).eq(t.company_id.map(company_currency)) & t.amount.notna()
    )
    t["month"] = t.date.dt.to_period("M").dt.to_timestamp()
    if "fx_per_eur" in t:
        t["valid"] &= t.fx_per_eur.notna()
    t["fx_estimated_tx_count"] = (
        (t.valid & t.original_currency.ne("EUR")).astype(int) if "original_currency" in t else 0
    )
    t = t[t.month.isin(MONTHS)]
    t["tx_count"] = 1
    t["excluded_tx_count"] = (~t.valid).astype(int)
    amount = t.amount.where(t.valid, 0)
    t["total_inflow"] = amount.clip(lower=0)
    t["total_outflow"] = -amount.clip(upper=0)
    included = ~t.category.isin(EXCLUDED)
    t["inflow"] = t.total_inflow.where(included, 0)
    t["outflow"] = t.total_outflow.where(included, 0)
    for name, categories in BUCKETS.items():
        t[name] = t.outflow.where(t.category.isin(categories), 0)
    t["other"] = t.outflow - t[list(BUCKETS)].sum(axis=1)
    t["interest"] = t.outflow.where(t.category.eq("interest_charge"), 0)
    t["transfer_in"] = t.total_inflow.where(t.category.eq("transfer"), 0)
    t["transfer_out"] = t.total_outflow.where(t.category.eq("transfer"), 0)
    cols = [
        "tx_count",
        "excluded_tx_count",
        "fx_estimated_tx_count",
        "inflow",
        "outflow",
        "total_inflow",
        "total_outflow",
        *BUCKETS,
        "other",
        "interest",
        "transfer_in",
        "transfer_out",
    ]
    panel = t.groupby(["company_id", "month"])[cols].sum()
    panel["flow_companies"] = t.groupby(["company_id", "month"]).valid.any().astype(int)
    panel["account_signature"] = t.groupby(["company_id", "month"]).product_id.agg(
        lambda x: "|".join(sorted(x.unique()))
    )
    return panel


def invoice_panel(invoices: pd.DataFrame, companies: pd.DataFrame) -> pd.DataFrame:
    """Rebuild invoice stocks at each month end without extraction-state fields."""
    inv = invoices[invoices.document_type.isin(["invoice", "invoiceGroup"])].copy()
    currency = inv.company_id.map(companies.set_index("company_id").currency)
    inv = inv[
        inv.currency.eq(currency)
        & inv.amount.notna()
        & inv.issuance_date.notna()
        & ~(inv.status.eq("paid") & inv.payment_date.isna())
    ]
    inv["value"] = inv.amount.abs()
    age_curve = np.array(load_score_config()["curves"]["invoice_age"])
    ids = companies.company_id
    rows = []
    for month in MONTHS:
        end = month + pd.offsets.MonthEnd(0)
        known = inv[inv.issuance_date <= end]
        row = pd.DataFrame(index=pd.Index(ids, name="company_id"))
        row["invoice_companies"] = row.index.isin(known.company_id).astype(int)
        for side, prefix in [("receivable", "rec"), ("payable", "pay")]:
            documents = known[known.side.eq(side)]
            row[f"{prefix}_companies"] = row.index.isin(documents.company_id).astype(int)
            issued = documents[documents.issuance_date >= month]
            opened = documents[
                documents.payment_date.isna() | (documents.payment_date > end)
            ].copy()
            age = (end - opened.due_date).dt.days
            opened["score_mass"] = opened.value * np.interp(age, age_curve[:, 0], age_curve[:, 1])
            dated = opened[opened.due_date.notna()]
            row[f"{prefix}_score_mass"] = dated.groupby("company_id").score_mass.sum()
            row[f"{prefix}_known_due_open"] = dated.groupby("company_id").value.sum()
            opened["age_bucket"] = (
                pd.cut(age, [-np.inf, 0, 30, 60, 90, np.inf], labels=AGES[:5])
                .astype(object)
                .fillna("unknown_due")
            )
            row[f"{prefix}_issued"] = issued.groupby("company_id").value.sum()
            row[f"{prefix}_invoice_count"] = issued.groupby("company_id").size()
            row[f"{prefix}_open"] = opened.groupby("company_id").value.sum()
            for bucket in AGES:
                row[f"{prefix}_{bucket}"] = (
                    opened[opened.age_bucket.eq(bucket)].groupby("company_id").value.sum()
                )
        row = row.fillna(0)
        row["month"] = month
        rows.append(row.reset_index())
    return pd.concat(rows, ignore_index=True).set_index(["company_id", "month"])


def build_payload(tables: dict[str, pd.DataFrame]) -> dict:
    """Build company and group records using the same amount aggregation rules."""
    companies = tables["companies"]
    score_config = load_score_config()
    registry = pd.concat([tables["banking_products"], tables["debt_products"]], ignore_index=True)
    txp = transaction_panel(tables["transactions"], registry, companies)
    invp = invoice_panel(tables["invoices"], companies)
    source_inv = tables["invoices"]
    supported = source_inv.document_type.isin(["invoice", "invoiceGroup"])
    same_currency = source_inv.currency.eq(
        source_inv.company_id.map(companies.set_index("company_id").currency)
    )
    invalid_payment = source_inv.status.eq("paid") & source_inv.payment_date.isna()
    eligible_inv = source_inv[
        supported
        & same_currency
        & ~invalid_payment
        & source_inv.issuance_date.notna()
        & (source_inv.issuance_date < SNAPSHOT)
    ]
    entities = {}
    definitions = [
        (r.company_id, "company", r.group_id, [r.company_id]) for r in companies.itertuples()
    ]
    definitions += [
        (gid, "group", gid, list(frame.company_id)) for gid, frame in companies.groupby("group_id")
    ]
    banking = tables["banking_products"]
    balances = tables["balances"]
    debt = tables["debt_products"]
    for entity_id, kind, group_id, members in definitions:
        member_currencies = companies[companies.company_id.isin(members)].currency
        currencies = member_currencies.dropna().unique()
        mixed = bool(len(currencies) != 1 or member_currencies.isna().any())
        currency = str(currencies[0]) if not mixed else None
        flows = txp.loc[txp.index.get_level_values(0).isin(members)]
        signatures = flows.account_signature.groupby("month").agg(lambda s: "|".join(sorted(s)))
        flows = (
            flows.drop(columns="account_signature")
            .groupby("month")
            .sum()
            .reindex(MONTHS, fill_value=0)
        )
        invoices = (
            invp.loc[invp.index.get_level_values(0).isin(members)]
            .groupby("month")
            .sum()
            .reindex(MONTHS, fill_value=0)
        )
        active = flows.tx_count > 0
        inv_history = invoices.invoice_companies.gt(0).cumsum()
        side_history = {p: invoices[f"{p}_companies"].gt(0).cumsum() for p in ["rec", "pay"]}
        products = banking[
            banking.company_id.isin(members) & banking.type.isin(["checking", "saving"])
        ]
        liquid = products.merge(
            balances[["product_id", "date", "balance"]], on="product_id", how="left"
        )
        cash_rows = liquid[
            liquid.currency.eq(currency)
            & liquid.date.eq(pd.Timestamp(SNAPSHOT))
            & liquid.balance.notna()
        ]
        cash = float(cash_rows.balance.sum()) if len(cash_rows) and not mixed else None
        facilities = debt[debt.company_id.isin(members)]
        guarantee = facilities.get("type", pd.Series(index=facilities.index, dtype=str)).eq(
            "guarantee"
        )
        known = facilities[
            facilities.currency.eq(currency) & facilities.outstanding.le(0) & ~guarantee
        ]
        guarantees = facilities[
            guarantee & facilities.currency.eq(currency) & facilities.outstanding.le(0)
        ]
        owed = float((-known.outstanding).clip(lower=0).sum()) if len(known) and not mixed else None
        records = []
        for i, month in enumerate(MONTHS):
            f, inv = flows.loc[month], invoices.loc[month]
            record = {key: float(value) for key, value in f.items()}
            record.update(
                {
                    "month": month.strftime("%Y-%m"),
                    "active": bool(active.iloc[i]),
                    "total_companies": len(members),
                    "invoice_companies": int(inv.invoice_companies),
                    "invoice_history_months": int(inv_history.iloc[i]),
                    "invoice_estimated": True,
                    "notes": [],
                    "observations": [],
                }
            )
            measured = active.iloc[i] and f.tx_count > f.excluded_tx_count and not mixed
            if not measured:
                for key in set(flows.columns) - {
                    "tx_count",
                    "excluded_tx_count",
                    "fx_estimated_tx_count",
                    "flow_companies",
                }:
                    record[key] = None
            record["net"] = record["inflow"] - record["outflow"] if measured else None
            record["perimeter_changed"] = bool(
                i > 0 and signatures.get(month) != signatures.get(MONTHS[i - 1])
            )
            for field in ["inflow", "outflow"]:
                for label, lag in [("mom", 1), ("yoy", 12)]:
                    value = None
                    if (
                        measured
                        and i >= lag
                        and active.iloc[i - lag]
                        and flows.excluded_tx_count.iloc[i - lag] < flows.tx_count.iloc[i - lag]
                    ):
                        value = ratio(f[field], flows[field].iloc[i - lag])
                        value = value - 1 if value is not None else None
                    record[f"{field}_{label}"] = value
            for window in [3, 12]:
                eligible = (
                    i >= window - 1 and active.iloc[i - window + 1 : i + 1].all() and not mixed
                )
                trailing = flows.iloc[max(0, i - window + 1) : i + 1]
                eligible = eligible and (trailing.tx_count > trailing.excluded_tx_count).all()
                record[f"dsr_{window}m"] = (
                    ratio(trailing.debt_service.sum(), trailing.inflow.sum()) if eligible else None
                )
                if window == 3:
                    record["outflow_3m"] = float(trailing.outflow.sum()) if eligible else None
                    days = (month + pd.offsets.MonthEnd(0) - MONTHS[max(0, i - 2)]).days + 1
                    record["window_days_3m"] = days if i >= 2 else None
                    record["daily_outflow"] = ratio(record["outflow_3m"], days)
            record["cash"] = cash if i == len(MONTHS) - 1 else None
            record["cash_date"] = SNAPSHOT if record["cash"] is not None else None
            record["buffer_days"] = ratio(record["cash"], record["daily_outflow"])
            covered = inv.invoice_companies > 0 and not mixed
            for prefix in ["rec", "pay"]:
                side_covered = inv[f"{prefix}_companies"] > 0 and not mixed
                record[f"{prefix}_companies"] = int(inv[f"{prefix}_companies"])
                record[f"{prefix}_history_months"] = int(side_history[prefix].iloc[i])
                for field in ["issued", "open", "invoice_count", "score_mass", "known_due_open"]:
                    record[f"{prefix}_{field}"] = (
                        float(inv[f"{prefix}_{field}"]) if side_covered else None
                    )
                aging = {
                    bucket: float(inv[f"{prefix}_{bucket}"]) if side_covered else None
                    for bucket in AGES
                }
                record[f"{prefix}_aging"] = aging
                overdue = sum(aging[b] for b in AGES[1:5]) if side_covered else None
                record[f"{prefix}_overdue"] = overdue
                record[f"{prefix}_overdue_share"] = ratio(overdue, record[f"{prefix}_open"])
                issued3 = invoices[f"{prefix}_issued"].iloc[max(0, i - 2) : i + 1].sum()
                record[f"{prefix}_issued_3m"] = (
                    float(issued3) if side_covered and side_history[prefix].iloc[i] >= 3 else None
                )
                days3 = (month + pd.offsets.MonthEnd(0) - MONTHS[max(0, i - 2)]).days + 1
                record["dso" if prefix == "rec" else "dpo"] = (
                    ratio(record[f"{prefix}_open"], issued3 / days3)
                    if side_covered and side_history[prefix].iloc[i] >= 3
                    else None
                )
            for label, lag in [("mom", 1), ("yoy", 12)]:
                growth = (
                    ratio(inv.rec_issued, invoices.rec_issued.iloc[i - lag])
                    if covered
                    and inv.rec_companies > 0
                    and i >= lag
                    and invoices.rec_companies.iloc[i - lag] > 0
                    else None
                )
                record[f"rec_issued_{label}"] = growth - 1 if growth is not None else None
            if f.excluded_tx_count:
                record["notes"].append(
                    f"{int(f.excluded_tx_count)} movimientos excluidos por moneda "
                    "o producto sin correspondencia."
                )
            if not measured:
                record["observations"].append(
                    {
                        "tone": "neutral",
                        "text": "Sin movimientos comparables suficientes en este mes.",
                    }
                )
            if (
                i >= 2
                and active.iloc[i - 2 : i + 1].all()
                and not mixed
                and (flows.inflow.iloc[i - 2 : i + 1] < flows.outflow.iloc[i - 2 : i + 1]).all()
            ):
                record["observations"].append(
                    {
                        "tone": "warning",
                        "text": "Las salidas superan las entradas durante tres meses observados.",
                    }
                )
            if record["inflow_yoy"] is not None and record["inflow_yoy"] < 0:
                record["observations"].append(
                    {
                        "tone": "warning",
                        "text": "Las entradas son inferiores al mismo mes del año anterior.",
                    }
                )
            if record["inflow_yoy"] is not None and record["inflow_yoy"] > 0:
                record["observations"].append(
                    {
                        "tone": "positive",
                        "text": "Las entradas superan el mismo mes del año anterior.",
                    }
                )
            if (
                i >= 2
                and not mixed
                and active.iloc[i - 2 : i + 1].all()
                and (flows.inflow.iloc[i - 2 : i + 1] > flows.outflow.iloc[i - 2 : i + 1]).all()
            ):
                record["observations"].append(
                    {
                        "tone": "positive",
                        "text": "Las entradas superan las salidas durante tres meses observados.",
                    }
                )
            if record["cash"] is not None:
                record["notes"].append(
                    f"Caja observada el {SNAPSHOT}: posterior al cierre de agosto; "
                    f"{len(cash_rows)}/{len(products)} cuentas líquidas cubiertas."
                )
                if record["cash"] < 0:
                    record["observations"].append(
                        {
                            "tone": "warning",
                            "text": "Saldo negativo en las cuentas cubiertas del snapshot.",
                        }
                    )
            if covered and inv.rec_d90_plus > 0:
                record["observations"].append(
                    {
                        "tone": "warning",
                        "text": "Hay facturas a cobrar con más de 90 días de vencimiento estimado.",
                    }
                )
            if covered and (inv.rec_unknown_due > 0 or inv.pay_unknown_due > 0):
                record["notes"].append(
                    "Hay pendientes sin vencimiento conocido: no se clasifican como al día "
                    "ni como vencidos."
                )
            records.append(record)
        entities[entity_id] = {
            "id": entity_id,
            "kind": kind,
            "group_id": group_id,
            "members": members,
            "currency": currency,
            "currency_mixed": mixed,
            "cash_fx_estimated": bool(
                cash_rows.get("original_currency", pd.Series(dtype=str)).ne("EUR").any()
            ),
            "liquid_accounts_covered": len(cash_rows) if not mixed else 0,
            "liquid_accounts_total": len(products),
            "monthly": records,
            "debt_snapshot": {
                "date": SNAPSHOT,
                "product_count": len(facilities),
                "known_balance_count": len(known) if not mixed else 0,
                "owed": owed,
                "guarantee_product_count": int(guarantee.sum()),
                "guarantees": float(-guarantees.outstanding.sum())
                if len(guarantees) and not mixed
                else None,
                "coverage_note": "Deuda registrada, no deuda total garantizada; "
                "ausencia de productos "
                "no demuestra ausencia de deuda. Saldos de signo positivo se excluyen "
                "por interpretación no confirmada.",
            },
            "notes": ["Agregados monetarios bloqueados: monedas distintas o desconocidas."]
            if mixed
            else [
                "Pendientes reconstruidos al cierre mensual, también en agosto: no son el "
                "pending_amount del snapshot posterior; pagos parciales desconocidos."
            ],
        }
        for record, scoring in zip(
            records, score_entity(entities[entity_id], score_config), strict=True
        ):
            record["scoring"] = scoring
    return {
        "score_config": score_config,
        "meta": {
            "months": [m.strftime("%Y-%m") for m in MONTHS],
            "snapshot_date": SNAPSHOT,
            "coverage": {
                "companies": len(companies),
                "groups": companies.group_id.nunique(),
                "transactions": len(tables["transactions"]),
                "invoices": len(tables["invoices"]),
                "invoice_paid_without_payment_date": int(
                    (
                        tables["invoices"].status.eq("paid")
                        & tables["invoices"].payment_date.isna()
                    ).sum()
                ),
                "invoice_selected_documents": int(
                    tables["invoices"].document_type.isin(["invoice", "invoiceGroup"]).sum()
                ),
                "invoice_excluded_currency": int((supported & ~same_currency).sum()),
                "invoice_eligible_historical_documents": len(eligible_inv),
                "invoice_companies": int(eligible_inv.company_id.nunique()),
                "invoice_groups": int(
                    companies.loc[
                        companies.company_id.isin(eligible_inv.company_id), "group_id"
                    ].nunique()
                ),
                "excluded_transactions_currency_or_product": int(txp.excluded_tx_count.sum()),
                "debt_positive_balance_uninterpreted": int(debt.outstanding.gt(0).sum()),
            },
            "methodology": [
                "Descripción de tesorería; no rating, probabilidad de impago ni predicción.",
                "Entradas y salidas excluyen transferencias, inversión y movimientos de efectivo; "
                "los totales permiten conciliarlas. Sólo moneda producto igual a empresa; "
                "grupos multimoneda no se suman.",
                "Intereses incluidos en servicio de deuda; no se suman dos veces. "
                "Otros y sin clasificar conservan todos los gastos incluidos.",
                "Caja sólo del snapshot fechado 2026-09-01, sin reconstrucción histórica. "
                "Buffer = caja cubierta / salidas diarias de tres meses completos observados.",
                "Facturas invoice/invoiceGroup en moneda de empresa. Signo positivo interpreta "
                "cobros y negativo pagos. Pendiente histórico estimado: importe íntegro desde "
                "emisión hasta pago; pagos parciales desconocidos. "
                "No se usa pending_amount histórico.",
                "Cobertura de facturas basada en primera emisión observada; cero documentos nuevos "
                "no demuestra ausencia de actividad. DSO/DPO requieren tres meses de historia "
                "y base positiva.",
                "Crecimiento mensual y anual sin ajuste estacional: base positiva y ambos meses "
                "observados. Cambio de perímetro compara cuentas con movimientos.",
                "Observaciones deterministas: tres meses de déficit o superávit, entradas "
                "interanuales, caja negativa o cobros vencidos más de 90 días. "
                "No anticipan insolvencia.",
            ],
        },
        "entities": entities,
    }


def main() -> None:
    """Write the standalone V2 and its input provenance manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROCESSED_DATA_DIR)
    args = parser.parse_args()
    tables = {name: pd.read_parquet(PROCESSED_DATA_DIR / f"{name}.parquet") for name in TABLES}
    from xray.v2_fx import normalize_tables_eur

    tables, fx_metadata = normalize_tables_eur(tables)
    payload = build_payload(tables)
    payload["fx_metadata"] = fx_metadata
    for entity in payload["entities"].values():
        fx_members = [fx_metadata["by_company"][member] for member in entity["members"]]
        entity["original_currency"] = sorted(
            {m["native_currency"] for m in fx_members if m["native_currency"]}
        )
        entity["fx_estimated"] = any(m["fx_estimated"] for m in fx_members)
        entity["fx_partial"] = any(m["partial"] for m in fx_members)
        entity["fx_covered_companies"] = sum(not m["partial"] for m in fx_members)
        for record, scoring in zip(
            entity["monthly"], score_entity(entity, payload["score_config"]), strict=True
        ):
            record["scoring"] = scoring
    blob = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    template_path = Path(__file__).parent / "templates" / "mvp_v2.html"
    template = template_path.read_text(encoding="utf-8")
    if template.count("__DATA_JSON__") != 1:
        raise ValueError("Template must contain exactly one __DATA_JSON__ placeholder")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "xray-v2.html"
    output.write_text(template.replace("__DATA_JSON__", blob), encoding="utf-8")
    inputs = [PROCESSED_DATA_DIR / f"{name}.parquet" for name in TABLES] + [
        Path(__file__),
        template_path,
        Path(__file__).with_name("v2_scores.py"),
        Path(__file__).with_name("v2_score_config.json"),
        Path(__file__).with_name("v2_fx.py"),
        Path(__file__).with_name("v2_fx_rates.csv"),
    ]
    manifest = {
        "version": 2,
        "snapshot_date": SNAPSHOT,
        "inputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "coverage": payload["meta"]["coverage"],
    }
    (args.output_dir / "xray-v2.manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Built {output}: {len(payload['entities'])} entities")


if __name__ == "__main__":
    main()
