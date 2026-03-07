from __future__ import annotations

import pandas as pd
from src.data import schema


def test_transaction_record_validates_single_row():
    record = schema.TransactionRecord(
        transaction_id="txn_100",
        account_id="acct_100",
        amount=55.2,
        merchant_type="utilities",
        transaction_hour=14,
        risk_label=0,
    )
    assert record.transaction_id == "txn_100"


def test_validate_dataframe_reports_invalid_rows():
    df = pd.DataFrame(
        [
            {
                "transaction_id": "txn_1",
                "account_id": "acct_1",
                "amount": 10.0,
                "merchant_type": "utilities",
                "transaction_hour": 10,
                "risk_label": 1,
            },
            {
                "transaction_id": "",
                "account_id": "acct_2",
                "amount": 10.0,
                "merchant_type": "invalid",
                "transaction_hour": 30,
                "risk_label": None,
            },
        ]
    )
    invalid = schema.validate_dataframe(df, require_label=True)
    assert len(invalid) == 2
    assert any("merchant_type" in err["errors"][0]["loc"] for err in invalid)
