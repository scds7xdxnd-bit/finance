from pathlib import Path

from ml_journal_suggester.preprocessing import build_parent_map, prepare_training_data


def test_prepare_training_data(tmp_path: Path) -> None:
    dataset = Path("ml_journal_suggester/examples/sample_train.jsonl")
    cache = tmp_path / "cache.parquet"
    data = prepare_training_data(dataset, cache)
    assert len(data.dataframe) == 10
    assert data.dataframe["is_multiline"].sum() >= 5
    assert len(data.chart_of_accounts) >= 12
    if cache.exists():
        assert cache.exists()
    parent_map = build_parent_map(data.chart_of_accounts)
    for account, parent in parent_map.items():
        assert parent in account

    # Cached load should reuse parquet quickly.
    cached = prepare_training_data(dataset, cache)
    assert len(cached.dataframe) == len(data.dataframe)
