from __future__ import annotations

"""Feature extraction utilities."""

from dataclasses import dataclass
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .utils import LOGGER


def _extract_merchant(description: str) -> str:
    import re

    description = description or ""
    description = description.strip().lower()
    description = re.sub(r"[^0-9a-zA-Z\s]+", " ", description)
    tokens = [tok for tok in description.split() if tok]
    return tokens[0] if tokens else "unknown"


@dataclass
class FeatureMatrices:
    text: np.ndarray
    numeric: np.ndarray
    categorical: np.ndarray

    def stack(self) -> np.ndarray:
        pieces = [self.text, self.numeric]
        if self.categorical.size:
            pieces.append(self.categorical)
        return np.hstack(pieces)


class FeatureBuilder:
    """Fit/transform utilities for model features."""

    def __init__(
        self,
        text_encoder: str = "tfidf",
        max_text_features: int = 4096,
        merchant_clusters: bool = True,
        max_clusters: int = 20,
    ) -> None:
        self.text_encoder_name = text_encoder
        self.max_text_features = max_text_features
        self.merchant_clusters = merchant_clusters
        self.max_clusters = max_clusters
        self._text_vectorizer: Optional[TfidfVectorizer] = None
        self._sentence_model = None
        self._scaler = StandardScaler()
        encoder_kwargs = {"handle_unknown": "ignore"}
        if "sparse_output" in OneHotEncoder.__init__.__code__.co_varnames:
            encoder_kwargs["sparse_output"] = False
        else:  # pragma: no cover - older scikit-learn
            encoder_kwargs["sparse"] = False
        self._currency_encoder = OneHotEncoder(**encoder_kwargs)
        self._cluster_encoder = OneHotEncoder(**encoder_kwargs)
        self._cluster_model: Optional[KMeans] = None

    def _fit_text(self, descriptions: List[str]) -> np.ndarray:
        if self.text_encoder_name == "tfidf":
            self._text_vectorizer = TfidfVectorizer(max_features=self.max_text_features, ngram_range=(1, 2))
            matrix = self._text_vectorizer.fit_transform(descriptions)
            return matrix.toarray().astype(np.float32)
        if self.text_encoder_name == "minilm":
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - optional dependency.
                raise RuntimeError(
                    "sentence-transformers is not installed; install it to use the MiniLM encoder"
                ) from exc
            self._sentence_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            embeddings = self._sentence_model.encode(descriptions, show_progress_bar=False)
            return np.asarray(embeddings, dtype=np.float32)
        raise ValueError(f"Unsupported text encoder: {self.text_encoder_name}")

    def _transform_text(self, descriptions: List[str]) -> np.ndarray:
        if self.text_encoder_name == "tfidf":
            if not self._text_vectorizer:
                raise RuntimeError("FeatureBuilder not fitted")
            return self._text_vectorizer.transform(descriptions).toarray().astype(np.float32)
        if self.text_encoder_name == "minilm":
            if not self._sentence_model:
                raise RuntimeError("FeatureBuilder not fitted")
            embeddings = self._sentence_model.encode(descriptions, show_progress_bar=False)
            return np.asarray(embeddings, dtype=np.float32)
        raise ValueError(f"Unsupported text encoder: {self.text_encoder_name}")

    def fit(self, frame: pd.DataFrame) -> FeatureMatrices:
        descriptions = frame["description"].astype(str).tolist()
        amounts = frame["total_amount"].astype(float).to_numpy()
        dates = pd.to_datetime(frame["date"], utc=False)
        currencies = frame.get("currency", pd.Series([None] * len(frame)))
        merchants = frame["description"].apply(_extract_merchant)

        text_features = self._fit_text(descriptions)

        numeric_features = np.stack(
            [
                np.log1p(np.abs(amounts)) * np.sign(amounts),
                dates.dt.weekday.to_numpy(dtype=np.float32),
                dates.dt.month.to_numpy(dtype=np.float32),
                dates.dt.year.to_numpy(dtype=np.float32),
            ],
            axis=1,
        )
        numeric_features = self._scaler.fit_transform(numeric_features).astype(np.float32)

        cat_inputs = pd.DataFrame({
            "currency": currencies.fillna("UNK").astype(str),
            "merchant": merchants.astype(str),
        })
        currency_array = self._currency_encoder.fit_transform(cat_inputs[["currency"]])

        cluster_array = np.empty((len(frame), 0), dtype=np.float32)
        if self.merchant_clusters and len(frame) > 1:
            n_clusters = min(self.max_clusters, max(2, len(frame) // 2))
            try:
                self._cluster_model = KMeans(n_clusters=n_clusters, n_init="auto", random_state=42)
                cluster_labels = self._cluster_model.fit_predict(text_features)
                cluster_array = self._cluster_encoder.fit_transform(cluster_labels.reshape(-1, 1))
            except Exception as exc:  # pragma: no cover - clustering is optional.
                LOGGER.warning("Merchant clustering failed: %s", exc)
                self._cluster_model = None
                cluster_array = np.empty((len(frame), 0), dtype=np.float32)
        categorical = np.hstack([currency_array.astype(np.float32), cluster_array.astype(np.float32)])
        return FeatureMatrices(text=text_features, numeric=numeric_features, categorical=categorical)

    def transform(self, frame: pd.DataFrame) -> FeatureMatrices:
        descriptions = frame["description"].astype(str).tolist()
        amounts = frame["total_amount"].astype(float).to_numpy()
        dates = pd.to_datetime(frame["date"], utc=False)
        currencies = frame.get("currency", pd.Series([None] * len(frame)))
        merchants = frame["description"].apply(_extract_merchant)

        text_features = self._transform_text(descriptions)

        numeric_features = np.stack(
            [
                np.log1p(np.abs(amounts)) * np.sign(amounts),
                dates.dt.weekday.to_numpy(dtype=np.float32),
                dates.dt.month.to_numpy(dtype=np.float32),
                dates.dt.year.to_numpy(dtype=np.float32),
            ],
            axis=1,
        )
        numeric_features = self._scaler.transform(numeric_features).astype(np.float32)

        cat_inputs = pd.DataFrame({
            "currency": currencies.fillna("UNK").astype(str),
            "merchant": merchants.astype(str),
        })
        currency_array = self._currency_encoder.transform(cat_inputs[["currency"]]).astype(np.float32)

        cluster_array = np.empty((len(frame), 0), dtype=np.float32)
        if self._cluster_model is not None:
            cluster_labels = self._cluster_model.predict(text_features).reshape(-1, 1)
            cluster_array = self._cluster_encoder.transform(cluster_labels).astype(np.float32)
        categorical = np.hstack([currency_array, cluster_array])
        return FeatureMatrices(text=text_features, numeric=numeric_features, categorical=categorical)

    def transform_records(self, records: Iterable[dict]) -> FeatureMatrices:
        frame = pd.DataFrame(records)
        return self.transform(frame)


__all__ = ["FeatureBuilder", "FeatureMatrices"]
