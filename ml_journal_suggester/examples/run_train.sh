#!/usr/bin/env bash
set -euo pipefail

python -m ml_journal_suggester.train \
  --train_jsonl $(dirname "$0")/sample_train.jsonl \
  --out_dir $(dirname "$0")/../artifacts \
  --text_encoder tfidf \
  --threshold_debit 0.35 \
  --threshold_credit 0.35 \
  --max_k_per_side 4
