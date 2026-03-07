import pandas as pd
from ml_suggester.parse_blocks import explode_to_lines, infer_transactions


def test_smoke_transform_multicurrency():
    df = pd.DataFrame([
        {"Date": "2025-01-01", "Affected Accounts": "Cash", "Transaction Description": "Lunch",
         "Debited Amount KRW": 10000, "Credited Amount KRW": 0,
         "Debited Amount MYR": 0, "Credited Amount MYR": 0,
         "Debited Amount CNY": 0, "Credited Amount CNY": 0},
        {"Date": "2025-01-01", "Affected Accounts": "Food Expense", "Transaction Description": "Lunch",
         "Debited Amount KRW": 0, "Credited Amount KRW": 10000,
         "Debited Amount MYR": 0, "Credited Amount MYR": 0,
         "Debited Amount CNY": 0, "Credited Amount CNY": 0},
        {"Date": "2025-01-01", "Affected Accounts": "Total", "Transaction Description": "Lunch",
         "Debited Amount KRW": 10000, "Credited Amount KRW": 10000,
         "Debited Amount MYR": 0, "Credited Amount MYR": 0,
         "Debited Amount CNY": 0, "Credited Amount CNY": 0},
    ])
    blocks = infer_transactions(df)
    lines, imb = explode_to_lines(blocks)
    assert len(blocks) == 1
    # 2 posting lines × 1 currency with nonzero = 2 rows
    assert len(lines) == 2
    assert set(lines["Currency"]) == {"KRW"}
    assert imb.empty
