from __future__ import annotations

"""CLI entry-point for training the ML journal suggester."""

import argparse
import json
from pathlib import Path

from .pipeline import Trainer
from .utils import PipelineConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the ML journal suggester")
    parser.add_argument("--train_jsonl", type=Path, required=True, help="Path to training JSONL file")
    parser.add_argument("--out_dir", type=Path, required=True, help="Directory to store artifacts")
    parser.add_argument("--cache_parquet", type=Path, default=None, help="Optional parquet cache path")
    parser.add_argument("--text_encoder", choices=["tfidf", "minilm"], default="tfidf")
    parser.add_argument("--use_hierarchy", action="store_true")
    parser.add_argument("--threshold_debit", type=float, default=0.35)
    parser.add_argument("--threshold_credit", type=float, default=0.35)
    parser.add_argument("--max_k_per_side", type=int, default=4)
    parser.add_argument("--blend_external_weight", type=float, default=0.0)
    parser.add_argument("--rules_path", type=Path, default=None)
    parser.add_argument("--decoder", choices=["greedy", "ilp"], default="greedy")
    parser.add_argument("--min_line_amount", type=float, default=1.0)
    parser.add_argument("--co_occurrence_weight", type=float, default=0.5)
    parser.add_argument("--random_seed", type=int, default=1337)
    parser.add_argument("--currency_rounding_unit", type=float, default=1.0)
    parser.add_argument("--training_epochs", type=int, default=20)
    parser.add_argument("--learning_rate", type=float, default=1e-3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = PipelineConfig(
        text_encoder=args.text_encoder,
        use_hierarchy=args.use_hierarchy,
        threshold_debit=args.threshold_debit,
        threshold_credit=args.threshold_credit,
        max_k_per_side=args.max_k_per_side,
        blend_external_weight=args.blend_external_weight,
        rules_path=str(args.rules_path) if args.rules_path else None,
        decoder=args.decoder,
        min_line_amount=args.min_line_amount,
        co_occurrence_weight=args.co_occurrence_weight,
        random_seed=args.random_seed,
        currency_rounding_unit=args.currency_rounding_unit,
        training_epochs=args.training_epochs,
        learning_rate=args.learning_rate,
    )
    trainer = Trainer(config)
    metrics = trainer.train(args.train_jsonl, args.out_dir, cache_parquet=args.cache_parquet)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
