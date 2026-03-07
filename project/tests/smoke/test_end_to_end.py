from __future__ import annotations

from fastapi.testclient import TestClient
from src.common import settings
from src.models import evaluate, train

from scripts import download_sample_data


def test_end_to_end(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    artifact_dir = tmp_path / "artifacts"
    data_dir.mkdir()
    artifact_dir.mkdir()

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("SEED", "42")
    monkeypatch.setenv("HOT_RELOAD_MODEL", "0")

    download_sample_data.main()
    train.main()
    evaluate.main()

    with TestClient(app) as client:
        payload = {
            "request_id": "smoke",
            "records": [
                {
                    "transaction_id": "txn_smoke",
                    "account_id": "acct_smoke",
                    "amount": 120.5,
                    "merchant_type": "utilities",
                    "transaction_hour": 9,
                }
            ],
        }

        response = client.post("/predict", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["request_id"] == "smoke"
        assert body["model_name"] == settings.MODEL_NAME
        assert "predictions" in body
        assert body["predictions"][0]["transaction_id"] == "txn_smoke"
        assert 0 <= body["predictions"][0]["probability"] <= 1

    # Ensure artifacts were materialised
    model_dir = next((artifact_dir / settings.MODEL_NAME).glob("run_*"))
    assert (model_dir / "model.joblib").exists()
    assert (model_dir / "metrics.json").exists()
