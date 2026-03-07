from ml_journal_suggester.decoding.greedy_balance import balance_amounts
from ml_journal_suggester.decoding.ilp_balance import HAS_ORTOOLS, ILPBalanceDecoder, ILPDecoderConfig


def test_greedy_balance_preserves_total() -> None:
    total = 1000
    debit_shares = {"A": 0.6, "B": 0.4}
    credit_shares = {"C": 0.7, "D": 0.3}
    debits, credits = balance_amounts(total, debit_shares, credit_shares)
    assert abs(sum(debits.values()) - total) < 1e-6
    assert abs(sum(credits.values()) - total) < 1e-6


def test_ilp_decoder_fallback() -> None:
    decoder = ILPBalanceDecoder(ILPDecoderConfig())
    total = 2500
    debits = {"A": 0.5, "B": 0.5}
    credits = {"C": 0.4, "D": 0.6}
    d, c = decoder.balance(total, debits, credits)
    assert abs(sum(d.values()) - total) < 1e-6
    assert abs(sum(c.values()) - total) < 1e-6
    if HAS_ORTOOLS:
        # When ILP is available the solution should still be feasible.
        assert len(d) == len(debits)
