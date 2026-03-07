from __future__ import annotations

"""ILP-based balancer with greedy fallback."""

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np

from .greedy_balance import GreedyBalanceDecoder, GreedyDecoderConfig

try:  # pragma: no cover - optional dependency
    from ortools.linear_solver import pywraplp

    HAS_ORTOOLS = True
except Exception:  # pragma: no cover - executed when OR-Tools is unavailable
    HAS_ORTOOLS = False
    pywraplp = None  # type: ignore


@dataclass
class ILPDecoderConfig:
    min_amount: float = 1.0
    rounding_unit: float = 1.0
    sparsity_penalty: float = 1e-3


class ILPBalanceDecoder:
    def __init__(self, config: ILPDecoderConfig) -> None:
        self.config = config
        self.greedy = GreedyBalanceDecoder(
            GreedyDecoderConfig(min_amount=config.min_amount, rounding_unit=config.rounding_unit)
        )

    def balance(
        self,
        total: float,
        debit_shares: Dict[str, float],
        credit_shares: Dict[str, float],
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        debit_alloc, credit_alloc = self.greedy.balance(total, debit_shares, credit_shares)
        if not HAS_ORTOOLS or not debit_alloc or not credit_alloc:
            return debit_alloc, credit_alloc

        solver = pywraplp.Solver.CreateSolver("CBC")
        if solver is None:
            return debit_alloc, credit_alloc

        flows: Dict[Tuple[str, str], object] = {}
        for d in debit_alloc:
            for c in credit_alloc:
                flows[(d, c)] = solver.NumVar(0.0, solver.infinity(), f"f_{hash((d, c))}")

        # Supply constraints.
        for d, amount in debit_alloc.items():
            solver.Add(sum(flows[(d, c)] for c in credit_alloc) == amount)
        for c, amount in credit_alloc.items():
            solver.Add(sum(flows[(d, c)] for d in debit_alloc) == amount)

        # Objective: encourage flows aligned with share probabilities and sparsity penalty.
        objective = solver.Objective()
        for (d, c), var in flows.items():
            score = np.log(max(debit_shares.get(d, 1e-6), 1e-6)) + np.log(
                max(credit_shares.get(c, 1e-6), 1e-6)
            )
            objective.SetCoefficient(var, score)
        objective.SetMaximization()

        status = solver.Solve()
        if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            return debit_alloc, credit_alloc

        # Reconstruct allocations according to solved flows.
        debit_result: Dict[str, float] = {d: 0.0 for d in debit_alloc}
        credit_result: Dict[str, float] = {c: 0.0 for c in credit_alloc}
        for (d, c), var in flows.items():
            value = var.solution_value()
            if value <= 0:
                continue
            debit_result[d] += value
            credit_result[c] += value

        # Apply min amount filtering.
        debit_result = {
            acc: float(val)
            for acc, val in debit_result.items()
            if abs(val) >= self.config.min_amount - 1e-6
        }
        credit_result = {
            acc: float(val)
            for acc, val in credit_result.items()
            if abs(val) >= self.config.min_amount - 1e-6
        }
        return debit_result, credit_result


__all__ = ["ILPDecoderConfig", "ILPBalanceDecoder", "HAS_ORTOOLS"]
