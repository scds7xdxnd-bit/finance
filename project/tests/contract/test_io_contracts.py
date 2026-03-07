from __future__ import annotations

from jsonschema import Draft202012Validator
from src.common import settings
from src.service_online import contracts


def test_prediction_request_schema_accepts_valid_payload():
    payload = {
        "request_id": "req-123",
        "records": [
            {
                "transaction_id": "txn_1",
                "account_id": "acct_1",
                "amount": 10.5,
                "merchant_type": "utilities",
                "transaction_hour": 12,
            }
        ],
    }
    Draft202012Validator(contracts.PREDICTION_REQUEST_SCHEMA).validate(payload)


def test_prediction_response_schema_accepts_valid_payload():
    payload = {
        "request_id": "req-123",
        "model_name": settings.MODEL_NAME,
        "model_version": 1,
        "predictions": [
            {
                "transaction_id": "txn_1",
                "prediction": 0,
                "probability": 0.4,
                "request_id": "uuid"
            }
        ],
    }
    Draft202012Validator(contracts.PREDICTION_RESPONSE_SCHEMA).validate(payload)


def test_error_envelope_contract():
    payload = {
        "status": "error",
        "error_code": "INVALID_REQUEST",
        "message": "Invalid payload",
        "request_id": "uuid",
    }
    Draft202012Validator(contracts.ERROR_ENVELOPE_SCHEMA).validate(payload)
