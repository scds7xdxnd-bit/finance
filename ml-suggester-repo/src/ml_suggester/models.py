from __future__ import annotations

import warnings
from typing import Tuple

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import top_k_accuracy_score
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, LabelEncoder, OneHotEncoder
from sklearn.utils.class_weight import compute_class_weight


def select_description(X):
    # X is a pandas DataFrame
    return X["Description"].astype(str).fillna("")

def _maybe_xgb_classifier(num_classes: int):
    try:
        from xgboost import XGBClassifier
        # Reasonable defaults; tweak later if needed
        return XGBClassifier(
            n_estimators=300,
            max_depth=8,
            learning_rate=0.1,
            subsample=0.9,
            colsample_bytree=0.9,
            tree_method="hist",
            objective="multi:softprob",
            num_class=num_classes,
            eval_metric="mlogloss",
            n_jobs=0,
        )
    except Exception:
        return None

def build_pipeline(X, y, max_features_text: int = 12000) -> Tuple[Pipeline, list, list, list]:
    """Create a sklearn Pipeline with TF-IDF + OHE + classifier (XGB if present, else LogisticRegression)."""
    from sklearn.pipeline import FeatureUnion, Pipeline
    # Column groups
    numeric_cols = ["Amount", "Relative_Amount", "Num_Debit_Lines", "Num_Credit_Lines", "year", "month", "dow", "is_month_end"]
    cat_cols = ["Currency", "Line_Type"]
    text_col = "Description"

    # Word-level TF-IDF
    word_tfidf = TfidfVectorizer(max_features=max_features_text, ngram_range=(1,2))

    # Char-level TF-IDF (inside word boundaries)
    char_tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3,5), max_features=20000)


    # Combine word + char on Description
    # ColumnTransformer can’t apply two transformers to same column directly,
    # so wrap them in a FeatureUnion and feed just the text column via a selector.
    from sklearn.base import BaseEstimator, TransformerMixin

    class TextSelector(BaseEstimator, TransformerMixin):
        def __init__(self, key): self.key = key
        def fit(self, X, y=None): return self
        def transform(self, X): return X[self.key].astype(str).fillna("")

    text_union = Pipeline([
        ("select", FunctionTransformer(select_description, validate=False)),
        ("tfidf_union", FeatureUnion([
            ("word", word_tfidf),
            ("char", char_tfidf),
        ])),
    ])

    pre = ColumnTransformer(
        transformers=[
            ("num", "passthrough", numeric_cols),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=5), cat_cols),
            ("txt", text_union, ["Description"]),  # we still pass the column so shapes align
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


    classes = np.unique(y)
    num_classes = len(classes)

    # Class weights for imbalance (LogReg only)
    class_weight = None
    if num_classes > 2:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            class_weight = {
                c: w for c, w in zip(
                    classes,
                    compute_class_weight("balanced", classes=classes, y=y)
                )
            }

    clf = _maybe_xgb_classifier(num_classes)
    if clf is None:
        clf = LogisticRegression(
            max_iter=5000,
            n_jobs=None,
            C = 2.0,
            class_weight=class_weight,
            verbose=0,
        )

    pipe = Pipeline([("pre", pre), ("clf", clf)])
    return pipe, numeric_cols, cat_cols, [text_col]

def evaluate_topk(model: Pipeline, X_val, y_val, ks=(1,3,5)) -> dict:
    """Compute top-k accuracy using predict_proba (or decision_function fallback)."""
    out = {}
    try:
        proba = model.predict_proba(X_val)
    except Exception:
        # some classifiers don’t implement predict_proba—approximate with decision_function
        df = model.decision_function(X_val)
        # convert to pseudo-proba
        exp = np.exp(df - df.max(axis=1, keepdims=True))
        proba = exp / exp.sum(axis=1, keepdims=True)

    for k in ks:
        out[f"top{k}_acc"] = float(top_k_accuracy_score(y_val, proba, k=k, labels=model.classes_))
    return out

def train_eval_pipeline(
    X,
    y,
    groups=None,
    test_size: float = 0.15,
    random_state: int = 42,
    min_class_count: int = 2,
) -> Tuple[Pipeline, dict]:
    # drop ultra-rare labels if requested
    if min_class_count and min_class_count > 1:
        y_counts = y.value_counts()
        keep = set(y_counts[y_counts >= min_class_count].index)
        mask = y.isin(keep)
        X = X.loc[mask].reset_index(drop=True)
        y = y.loc[mask].reset_index(drop=True)
        if groups is not None:
            groups = groups.loc[mask].reset_index(drop=True)

    # group-wise split (prevents transaction leakage)
    if groups is not None:
        gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
        tr_idx, val_idx = next(gss.split(X, y, groups=groups))
        X_tr, X_val = X.iloc[tr_idx], X.iloc[val_idx]
        y_tr, y_val = y.iloc[tr_idx], y.iloc[val_idx]
    else:
        can_strat = (y.value_counts().min() >= 2)
        X_tr, X_val, y_tr, y_val = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y if can_strat else None
        )

    pipe, *_ = build_pipeline(X, y)

    # If final estimator is XGB, encode y to 0..K-1
    use_xgb = type(pipe.named_steps["clf"]).__name__ == "XGBClassifier"
    if use_xgb:
        le = LabelEncoder()
        y_tr_enc = le.fit_transform(y_tr)
        y_val_enc = le.transform(y_val)

        pipe.fit(X_tr, y_tr_enc)

        # Store metadata on the pipeline (safe custom attrs)
        pipe._label_encoder = le
        pipe._classes = le.classes_              # <-- use this instead of classes_
        pipe._uses_label_encoding = True

        metrics = evaluate_topk(pipe, X_val, y_val_enc, ks=(1, 3, 5))
    else:
        pipe.fit(X_tr, y_tr)

        # For LR (and most sklearn classifiers), classes_ is on the estimator
        est_classes = getattr(pipe.named_steps["clf"], "classes_", None)
        pipe._classes = est_classes if est_classes is not None else np.unique(y_tr)
        pipe._uses_label_encoding = False

        metrics = evaluate_topk(pipe, X_val, y_val, ks=(1, 3, 5))

    return pipe, metrics