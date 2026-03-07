from pathlib import Path

import pytest
from trial_balance_pdf import generate_trial_balance_pdf

SAMPLE = {
    "rows": [
        {"group": "Asset", "category": "Cash", "currency": "KRW", "bd": 1_000_000, "debit": 250_000, "credit": 100_000},
        {"group": "Asset", "category": "Bank", "currency": "KRW", "bd": 500_000, "debit": 0, "credit": 50_000},
        {"group": "Liability", "category": "Payables", "currency": "KRW", "bd": 0, "debit": 0, "credit": 100_000},
    ],
    "totals": {"bd": 1_500_000, "debit": 250_000, "credit": 250_000},
}


@pytest.mark.parametrize("engine", ["auto"])  # keep it simple; env may only have one engine
def test_generate_pdf(tmp_path: Path, engine: str):
    out = tmp_path / "tb.pdf"
    try:
        pages, sha = generate_trial_balance_pdf(
            data=SAMPLE,
            org="UnitTest Org",
            start_date="2025-01-01",
            end_date="2025-12-31",
            out_pdf=out,
            engine=engine,
        )
    except RuntimeError as exc:
        if "WeasyPrint" in str(exc):
            pytest.skip("WeasyPrint not installed in test environment")
        raise
    assert out.exists(), "PDF file was not created"
    assert out.stat().st_size > 10 * 1024, "PDF seems too small to be valid"
    assert isinstance(sha, str) and len(sha) == 64
