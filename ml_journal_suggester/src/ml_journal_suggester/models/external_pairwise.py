from __future__ import annotations

"""Protocol for pluggable external single-line predictors."""

from typing import List, Protocol, Tuple


class ExternalPairwisePredictor(Protocol):
    """Interface exposed to integrate legacy 1→1 suggesters."""

    def predict_debit(self, date: str, description: str, amount: float) -> List[Tuple[str, float]]:
        ...

    def predict_credit(
        self, date: str, description: str, debit_account: str, amount: float
    ) -> List[Tuple[str, float]]:
        ...


__all__ = ["ExternalPairwisePredictor"]
