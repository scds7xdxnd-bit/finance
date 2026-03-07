from __future__ import annotations

import pandas as pd
from src.data import schema
from src.data.features import build_features as feature_module


def test_feature_transformer_creates_expected_dimensions():
    df = pd.DataFrame(
        [
            {
                "amount": 100.0,
                "transaction_hour": 8,
                "merchant_type": "utilities",
            },
            {
                "amount": 250.0,
                "transaction_hour": 21,
                "merchant_type": "travel",
            },
        ]
    )
    transformer = feature_module.build_feature_transformer()
    transformed, transformer = feature_module.fit_transformer(transformer, df)
    assert transformed.shape[0] == 2
    # numeric -> 2 cols, categorical -> 5 categories
    expected_min_features = len(schema.NUMERIC_COLUMNS) + len(schema.ALLOWED_MERCHANT_TYPES)
    assert transformed.shape[1] >= expected_min_features

    reapplied = feature_module.apply_transformer(transformer, df)
    assert reapplied.shape == transformed.shape
