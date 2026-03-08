import json
from pathlib import Path

from flask import Flask

from ml.journal_model import JournalModel


def test_journal_model_state_path_and_json_safety(tmp_path):
    app = Flask(__name__, instance_path=str(tmp_path))

    with app.app_context():
        model = JournalModel()
        # Simulate legacy in-memory tuple-key shape; writer should normalize it.
        model.feedback_counts = {"accept": 5, "reject": 1}
        model.account_cooccurrence = {("Cash", "Revenue"): 2}
        model._save_state()
        state_path = Path(model._state_path())
        embeds_path = Path(model._embeds_path())

    assert state_path == tmp_path / "ml_state" / "journal_state.json"
    assert embeds_path.parent == tmp_path / "ml_state"

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["feedback_counts"] == {"accept": 5, "reject": 1}
    assert payload["account_cooccurrence"]["Cash"]["Revenue"] == 2

    # JSON-safe keys: persisted keys are plain strings, never tuple-string artifacts.
    for key, nested in payload["account_cooccurrence"].items():
        assert isinstance(key, str)
        assert not key.startswith("(")
        assert isinstance(nested, dict)
        for nested_key in nested:
            assert isinstance(nested_key, str)
            assert not nested_key.startswith("(")
