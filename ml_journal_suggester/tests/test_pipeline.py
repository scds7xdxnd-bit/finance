from datetime import date
from pathlib import Path

from ml_journal_suggester.data_schemas import InferenceInput
from ml_journal_suggester.pipeline import InferenceEngine, Trainer
from ml_journal_suggester.utils import PipelineConfig


def test_end_to_end_pipeline(tmp_path: Path) -> None:
    train_path = Path("ml_journal_suggester/examples/sample_train.jsonl")
    config = PipelineConfig(training_epochs=5, threshold_debit=0.3, threshold_credit=0.3)
    trainer = Trainer(config)
    metrics = trainer.train(train_path, tmp_path)
    assert "gate_accuracy" in metrics
    assert metrics["e2e_balanced_success"] <= 1.0

    engine = InferenceEngine(tmp_path)
    inputs = [
        InferenceInput(
            tx_id="X1",
            date=date.fromisoformat("2025-09-18"),
            description="Restaurant + tip",
            total_amount=38000,
            currency="KRW",
        ),
        InferenceInput(
            tx_id="X2",
            date=date.fromisoformat("2025-09-19"),
            description="Inventory restock with vat",
            total_amount=68000,
            currency="KRW",
        ),
    ]
    suggestions = engine.suggest(inputs)
    assert len(suggestions) == 2
    for suggestion in suggestions:
        debit_total = sum(line.amount for line in suggestion.debits)
        credit_total = sum(line.amount for line in suggestion.credits)
        assert abs(debit_total - credit_total) < 1e-5
