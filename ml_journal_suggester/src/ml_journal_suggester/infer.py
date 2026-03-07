from __future__ import annotations

"""CLI for running inference with trained artifacts."""

import argparse
from datetime import date
from pathlib import Path

from .data_schemas import InferenceInput
from .pipeline import InferenceEngine
from .utils import read_jsonl, write_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate journal suggestions")
    parser.add_argument("--model_dir", type=Path, required=True, help="Directory with trained artifacts")
    parser.add_argument("--input_jsonl", type=Path, required=True, help="Input transactions JSONL")
    parser.add_argument("--out_jsonl", type=Path, required=True, help="Where to write suggestions")
    parser.add_argument("--decoder", choices=["greedy", "ilp"], default=None)
    parser.add_argument("--external_module", type=str, default=None, help="Optional module path for external pairwise predictor")
    parser.add_argument("--threshold_debit", type=float, default=None)
    parser.add_argument("--threshold_credit", type=float, default=None)
    parser.add_argument("--max_k_per_side", type=int, default=None)
    return parser.parse_args()


def _to_inference_input(payload: dict) -> InferenceInput:
    return InferenceInput(
        tx_id=str(payload["tx_id"]),
        date=date.fromisoformat(payload["date"]),
        description=str(payload.get("description", "")),
        total_amount=float(payload.get("total_amount", 0.0)),
        currency=payload.get("currency"),
        known_debits=payload.get("known_debits", []) or [],
        known_credits=payload.get("known_credits", []) or [],
    )


def main() -> None:
    args = parse_args()
    engine = InferenceEngine(args.model_dir, external_module=args.external_module)
    if args.decoder:
        engine.config.decoder = args.decoder
        engine.decoder = engine._build_decoder()
    if args.threshold_debit is not None:
        engine.config.threshold_debit = args.threshold_debit
    if args.threshold_credit is not None:
        engine.config.threshold_credit = args.threshold_credit
    if args.max_k_per_side is not None:
        engine.config.max_k_per_side = args.max_k_per_side
    rows = read_jsonl(args.input_jsonl)
    inputs = [_to_inference_input(row) for row in rows]
    suggestions = engine.suggest(inputs)
    write_jsonl(args.out_jsonl, [suggestion.as_dict() for suggestion in suggestions])


if __name__ == "__main__":
    main()
