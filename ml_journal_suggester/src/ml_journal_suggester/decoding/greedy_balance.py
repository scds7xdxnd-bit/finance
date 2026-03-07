from __future__ import annotations

"""Greedy balancer that rounds and repairs per-account amounts."""

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np

from ..utils import round_amount


@dataclass
class GreedyDecoderConfig:
    min_amount: float = 1.0
    rounding_unit: float = 1.0


class GreedyBalanceDecoder:
    def __init__(self, config: GreedyDecoderConfig) -> None:
        self.config = config

    def _allocate(self, total: float, shares: Dict[str, float]) -> Dict[str, float]:
        if not shares:
            return {}
        total = float(total)
        base = np.array([max(v, 0.0) for v in shares.values()], dtype=np.float64)
        if base.sum() == 0:
            base = np.ones_like(base) / len(base)
        else:
            base = base / base.sum()
        raw_amounts = base * total
        rounded = {
            acc: round_amount(val, self.config.rounding_unit)
            for acc, val in zip(shares.keys(), raw_amounts)
        }
        current_total = sum(rounded.values())
        diff = total - current_total
        if abs(diff) >= 1e-6:
            # Adjust the account with the largest residual magnitude.
            residuals = {
                acc: raw - rounded[acc] for acc, raw in zip(shares.keys(), raw_amounts)
            }
            if diff > 0:
                target = max(residuals, key=residuals.get)
            else:
                target = min(residuals, key=residuals.get)
            rounded[target] = rounded.get(target, 0.0) + diff
        # Drop tiny lines.
        result = {
            acc: float(amount)
            for acc, amount in rounded.items()
            if abs(amount) >= self.config.min_amount - 1e-6
        }
        return result

    def balance(
        self,
        total: float,
        debit_shares: Dict[str, float],
        credit_shares: Dict[str, float],
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        debit_alloc = self._allocate(total, debit_shares)
        credit_alloc = self._allocate(total, credit_shares)
        debit_total = sum(debit_alloc.values())
        credit_total = sum(credit_alloc.values())
        if abs(debit_total - credit_total) > 1e-6:
            residual = debit_total - credit_total
            # Repair on credit side by adjusting largest line.
            if credit_alloc:
                target = max(credit_alloc, key=credit_alloc.get)
                credit_alloc[target] += residual
            elif debit_alloc:
                target = max(debit_alloc, key=debit_alloc.get)
                debit_alloc[target] -= residual
        return debit_alloc, credit_alloc


def balance_amounts(
    total: float,
    debit_shares: Dict[str, float],
    credit_shares: Dict[str, float],
    min_amount: float = 1.0,
    rounding_unit: float = 1.0,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    decoder = GreedyBalanceDecoder(GreedyDecoderConfig(min_amount=min_amount, rounding_unit=rounding_unit))
    return decoder.balance(total, debit_shares, credit_shares)


__all__ = ["GreedyBalanceDecoder", "GreedyDecoderConfig", "balance_amounts"]
