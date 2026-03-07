from __future__ import annotations

"""Utility helpers for the journal suggester package."""

import json
import logging
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import yaml

try:  # Optional torch import for seeding convenience.
    import torch
except Exception:  # pragma: no cover - torch is required by the package, but guard anyway.
    torch = None  # type: ignore

LOGGER = logging.getLogger("ml_journal_suggester")


def ensure_dir(path: Path) -> None:
    """Create *path* (and parents) if it does not exist."""

    path.mkdir(parents=True, exist_ok=True)


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    """Load a JSONL file into memory."""

    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def write_jsonl(path: Path, rows: Iterable[Dict[str, object]]) -> None:
    """Write dictionaries to disk using JSONL format."""

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def save_yaml(path: Path, payload: Dict[str, object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def load_yaml(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def set_random_seeds(seed: int = 1337) -> None:
    """Seed random libraries for reproducibility."""

    random.seed(seed)
    np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)


@dataclass
class PipelineConfig:
    """Configuration persisted alongside the trained artifacts."""

    text_encoder: str = "tfidf"
    use_hierarchy: bool = False
    threshold_debit: float = 0.4
    threshold_credit: float = 0.4
    max_k_per_side: int = 4
    blend_external_weight: float = 0.0
    rules_path: Optional[str] = None
    decoder: str = "greedy"
    min_line_amount: float = 1.0
    co_occurrence_weight: float = 0.5
    random_seed: int = 1337
    currency_rounding_unit: float = 1.0
    top_suggestions: int = 3
    training_epochs: int = 20
    learning_rate: float = 1e-3

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "PipelineConfig":
        return cls(**payload)


class RulesEngine:
    """Apply simple allow/block logic for candidate accounts based on description regex."""

    def __init__(self, rules: Sequence[Dict[str, object]]):
        import re

        self._compiled = []
        for rule in rules:
            pattern = rule.get("pattern")
            if not pattern:
                continue
            self._compiled.append(
                (
                    re.compile(pattern, flags=re.IGNORECASE),
                    set(rule.get("force_accounts", []) or []),
                    set(rule.get("block_accounts", []) or []),
                )
            )

    def apply(self, description: str, candidates: Dict[str, List[str]]) -> None:
        if not self._compiled:
            return
        for regex, force, block in self._compiled:
            if not regex.search(description):
                continue
            if force:
                for side, accounts in candidates.items():
                    accounts.extend(a for a in force if a not in accounts)
            if block:
                for side in candidates:
                    candidates[side] = [a for a in candidates[side] if a not in block]


def load_rules(path: Optional[Path]) -> Optional[RulesEngine]:
    if not path or not path.exists():
        return None
    payload = load_yaml(path)
    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    return RulesEngine(rules)


def round_amount(amount: float, unit: float) -> float:
    if unit <= 0:
        return float(amount)
    return round(amount / unit) * unit


def normalise_probabilities(probs: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    probs = np.clip(probs, eps, 1.0 - eps)
    total = probs.sum()
    if total == 0:
        return np.full_like(probs, 1.0 / len(probs))
    return probs / total


def logit(p: float, eps: float = 1e-6) -> float:
    p = min(max(p, eps), 1.0 - eps)
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class ExternalPredictorLoader:
    """Utility used by the inference CLI to optionally load external predictors."""

    @staticmethod
    def load(module_path: Optional[str]):
        if not module_path:
            return None
        import importlib

        module_name, _, attr = module_path.partition(":")
        module = importlib.import_module(module_name)
        factory = getattr(module, attr or "create_predictor")
        predictor = factory()
        return predictor


__all__ = [
    "ensure_dir",
    "read_jsonl",
    "write_jsonl",
    "save_yaml",
    "load_yaml",
    "set_random_seeds",
    "PipelineConfig",
    "RulesEngine",
    "load_rules",
    "round_amount",
    "normalise_probabilities",
    "logit",
    "sigmoid",
    "ExternalPredictorLoader",
]
