from __future__ import annotations

"""Typed schemas used across the journal suggester package."""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class JournalLine:
    """Single entry parsed from the raw JSONL training rows."""

    tx_id: str
    date: date
    description: str
    side: str
    account: str
    amount: float
    currency: Optional[str] = None


@dataclass
class AggregatedTransaction:
    """Grouped representation of a transaction used for training."""

    tx_id: str
    date: date
    description: str
    total_amount: float
    debit_accounts: List[str]
    credit_accounts: List[str]
    debit_sums_by_account: Dict[str, float]
    credit_sums_by_account: Dict[str, float]
    is_multiline: bool
    currency: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class InferenceInput:
    """Schema expected by the inference engine."""

    tx_id: str
    date: date
    description: str
    total_amount: float
    currency: Optional[str] = None
    known_debits: List[Dict[str, float]] = field(default_factory=list)
    known_credits: List[Dict[str, float]] = field(default_factory=list)

    @property
    def has_known_lines(self) -> bool:
        return bool(self.known_debits or self.known_credits)


@dataclass
class SuggestionLine:
    """Debit or credit line emitted by a decoder."""

    account: str
    amount: float


@dataclass
class Suggestion:
    """Full decoded recommendation for a transaction."""

    tx_id: str
    is_multiline: bool
    debits: List[SuggestionLine]
    credits: List[SuggestionLine]
    debug_info: Dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {
            "tx_id": self.tx_id,
            "is_multiline": self.is_multiline,
            "suggestion": {
                "debits": [line.__dict__ for line in self.debits],
                "credits": [line.__dict__ for line in self.credits],
            },
            "debug": self.debug_info,
        }


def sum_amounts(lines: Iterable[SuggestionLine]) -> float:
    """Compute the total of the provided lines."""

    return float(sum(line.amount for line in lines))
