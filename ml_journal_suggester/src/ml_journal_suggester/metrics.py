from __future__ import annotations

"""Metric helpers used during training and evaluation."""

from typing import Dict, Iterable, List, Sequence

import numpy as np
from sklearn import metrics

from .data_schemas import AggregatedTransaction, Suggestion


def compute_gate_metrics(y_true: Sequence[int], y_prob: Sequence[float]) -> Dict[str, float]:
    y_true_arr = np.asarray(y_true)
    y_prob_arr = np.asarray(y_prob)
    y_pred = (y_prob_arr >= 0.5).astype(int)
    result: Dict[str, float] = {
        "accuracy": float(metrics.accuracy_score(y_true_arr, y_pred)),
        "f1": float(metrics.f1_score(y_true_arr, y_pred)),
    }
    try:
        result["roc_auc"] = float(metrics.roc_auc_score(y_true_arr, y_prob_arr))
    except ValueError:
        result["roc_auc"] = float("nan")
    return result


def compute_multilabel_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float = 0.5,
) -> Dict[str, float]:
    y_pred = (y_prob >= threshold).astype(int)
    micro_f1 = metrics.f1_score(y_true, y_pred, average="micro")
    macro_f1 = metrics.f1_score(y_true, y_pred, average="macro")
    jaccard = metrics.jaccard_score(y_true, y_pred, average="samples")
    precision_at_k = _precision_at_k(y_true, y_prob, k=3)
    return {
        "micro_f1": float(micro_f1),
        "macro_f1": float(macro_f1),
        "jaccard": float(jaccard),
        "precision_at_3": float(precision_at_k),
    }


def _precision_at_k(y_true: np.ndarray, y_prob: np.ndarray, k: int = 3) -> float:
    hits = 0
    total = y_true.shape[0]
    for true_row, prob_row in zip(y_true, y_prob):
        top_indices = np.argsort(prob_row)[-k:]
        hits += int(true_row[top_indices].sum() > 0)
    return hits / max(total, 1)


def proportion_mae(targets: Sequence[Sequence[float]], preds: Sequence[Sequence[float]]) -> float:
    errors: List[float] = []
    for target, pred in zip(targets, preds):
        t = np.asarray(target, dtype=np.float32)
        p = np.asarray(pred, dtype=np.float32)
        length = min(len(t), len(p))
        if length == 0:
            continue
        errors.append(float(np.mean(np.abs(t[:length] - p[:length]))))
    return float(np.mean(errors)) if errors else 0.0


def end_to_end_metrics(
    gold: Iterable[AggregatedTransaction],
    suggestions: Iterable[Suggestion],
) -> Dict[str, float]:
    gold_map = {g.tx_id: g for g in gold}
    match = 0
    balanced = 0
    total = 0
    avg_lines: List[int] = []
    for suggestion in suggestions:
        gold_tx = gold_map.get(suggestion.tx_id)
        if not gold_tx:
            continue
        total += 1
        debit_sum = sum(line.amount for line in suggestion.debits)
        credit_sum = sum(line.amount for line in suggestion.credits)
        if abs(debit_sum - credit_sum) <= 1e-6:
            balanced += 1
        predicted_sets = {
            "debit": sorted(line.account for line in suggestion.debits),
            "credit": sorted(line.account for line in suggestion.credits),
        }
        gold_sets = {
            "debit": sorted(gold_tx.debit_accounts),
            "credit": sorted(gold_tx.credit_accounts),
        }
        if predicted_sets == gold_sets:
            match += 1
        avg_lines.append(len(suggestion.debits) + len(suggestion.credits))
    return {
        "exact_match_rate": match / max(total, 1),
        "balanced_success": balanced / max(total, 1),
        "avg_line_count": float(np.mean(avg_lines)) if avg_lines else 0.0,
    }


__all__ = [
    "compute_gate_metrics",
    "compute_multilabel_metrics",
    "proportion_mae",
    "end_to_end_metrics",
]
