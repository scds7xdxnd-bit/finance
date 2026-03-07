# ML Journal Suggester

A lightweight, reproducible pipeline that suggests balanced multi-line journal entries for double-entry bookkeeping systems. It learns from historic tidy JSONL exports and can recommend one-line or multi-line debit/credit sets together with per-line amounts.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

By default the package uses a TF-IDF encoder for descriptions. To enable the MiniLM sentence transformer or the ILP decoder install the optional extras:

```bash
pip install 'ml-journal-suggester[minilm,ilp]'
```

*Python 3.10+ is required.*

## Training

The trainer expects tidy JSONL input where each row represents a single journal line and transactions are grouped by `tx_id`.

```
python -m ml_journal_suggester.train \
  --train_jsonl examples/sample_train.jsonl \
  --out_dir artifacts/ \
  --text_encoder tfidf \
  --threshold_debit 0.35 --threshold_credit 0.35 \
  --max_k_per_side 4
```

On completion the command writes:

- Torch model weights (`gate.pt`, `debit_head.pt`, `credit_head.pt`, `*_prop.pt`, embeddings)
- `feature_builder.joblib` with fitted encoders
- `account_vocab.json`, `co_occurrence.json`, and hierarchical hints
- `config.yaml` and `metrics.json`

The example dataset under `examples/` trains end-to-end in a few seconds.

## Inference

```
python -m ml_journal_suggester.infer \
  --model_dir artifacts/ \
  --input_jsonl examples/sample_infer_input.jsonl \
  --out_jsonl suggestions.jsonl \
  --decoder greedy
```

Each output row contains the chosen debit/credit lines, per-line amounts, ranked alternatives, and debug probabilities. All suggestions respect the double-entry constraint (`ΣDR == ΣCR`).

### Decoder options

- `greedy` (default): rounds proportional allocations and repairs drifts.
- `ilp`: uses OR-Tools min-cost flow when available (falls back to greedy otherwise).

### Blending external 1→1 predictors

Legacy single-line models can be plugged in via a small adapter implementing `ExternalPairwisePredictor` (see `src/models/external_pairwise.py`). Expose a factory such as `create_predictor()` and pass the module path at inference time:

```
python -m ml_journal_suggester.infer \
  --model_dir artifacts/ \
  --input_jsonl ... \
  --out_jsonl ... \
  --external_module custom_predictor:factory \
  --threshold_debit 0.3 --threshold_credit 0.3
```

Set the blend weight during training via `--blend_external_weight`.

### Rules and hierarchies

Provide a `rules.yaml` with simple patterns to force or block accounts:

```yaml
rules:
  - pattern: "vat"
    force_accounts: ["Expenses:Taxes:VAT"]
    block_accounts: ["Expenses:Meals"]
```

Point the trainer to the file with `--rules_path`. The path is persisted in `config.yaml` so the inference CLI applies the same rules.

## Project layout

```
ml_journal_suggester/
  src/ml_journal_suggester/
    preprocessing.py     # JSONL → aggregated dataset
    features.py          # TF-IDF or MiniLM encoders + numeric/categorical feats
    models/              # Torch heads (gate, multi-label, proportions)
    decoding/            # Greedy + ILP balancers
    pipeline.py          # Trainer & inference engine
    train.py / infer.py  # CLI entry-points
  examples/
    sample_train.jsonl
    sample_infer_input.jsonl
    run_train.sh
    run_infer.sh
  tests/                 # Pytest suite
```

## Extending

- **New accounts / CoA changes**: retrain on datasets containing the new accounts. The vocabulary is derived from the training file.
- **Custom text encoders**: subclass `FeatureBuilder` or provide an alternative when instantiating the trainer.
- **New decoding strategies**: implement a decoder exposing `balance(total, debit_shares, credit_shares)` and swap it in via the config.

## Tests

Run the full suite with:

```bash
pytest -q
```

The tests cover preprocessing, model shapes, decoder invariants, and a small end-to-end smoke test.
