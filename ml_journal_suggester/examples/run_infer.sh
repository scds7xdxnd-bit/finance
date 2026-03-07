#!/usr/bin/env bash
set -euo pipefail

ARTIFACTS_DIR=$(dirname "$0")/../artifacts

python -m ml_journal_suggester.infer \
  --model_dir ${ARTIFACTS_DIR} \
  --input_jsonl $(dirname "$0")/sample_infer_input.jsonl \
  --out_jsonl suggestions.jsonl \
  --decoder greedy
