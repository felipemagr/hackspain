from datetime import date

import pandas as pd

from xray.pipeline.lake import land, read_as_of

MARCH, JULY = date(2026, 3, 1), date(2026, 7, 1)


def _invoices(status, pending):
    """One invoice, as it looked in a single daily extract."""
    return pd.DataFrame([{"operation_id": "op1", "status": status, "pending_amount": pending}])


def test_read_as_of_returns_the_version_known_on_that_date(tmp_path):
    land("invoices", _invoices("pending", 500.0), MARCH, tmp_path)
    land("invoices", _invoices("paid", 0.0), JULY, tmp_path)

    march = read_as_of("invoices", "operation_id", MARCH, tmp_path)
    july = read_as_of("invoices", "operation_id", JULY, tmp_path)

    assert march["status"].tolist() == ["pending"]
    assert july["status"].tolist() == ["paid"]


def test_a_row_is_returned_once_however_many_times_it_was_restated(tmp_path):
    land("invoices", _invoices("pending", 500.0), MARCH, tmp_path)
    land("invoices", _invoices("overdue", 500.0), date(2026, 5, 1), tmp_path)
    land("invoices", _invoices("paid", 0.0), JULY, tmp_path)

    assert len(read_as_of("invoices", "operation_id", JULY, tmp_path)) == 1
