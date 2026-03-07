"""JSON schema contracts for online prediction APIs."""
from __future__ import annotations

from ..data import schema

MERCHANT_TYPES = sorted(schema.ALLOWED_MERCHANT_TYPES)

PREDICTION_REQUEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.com/schemas/prediction-request.json",
    "title": "PredictionRequest",
    "type": "object",
    "required": ["request_id", "records"],
    "additionalProperties": False,
    "properties": {
        "request_id": {
            "type": "string",
            "minLength": 1,
        },
        "records": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "transaction_id",
                    "account_id",
                    "amount",
                    "merchant_type",
                    "transaction_hour",
                ],
                "additionalProperties": False,
                "properties": {
                    "transaction_id": {"type": "string", "minLength": 1, "maxLength": 64},
                    "account_id": {"type": "string", "minLength": 1, "maxLength": 64},
                    "amount": {
                        "type": "number",
                        "minimum": schema.AMOUNT_MIN,
                        "maximum": schema.AMOUNT_MAX,
                    },
                    "merchant_type": {
                        "type": "string",
                        "enum": MERCHANT_TYPES,
                    },
                    "transaction_hour": {
                        "type": "integer",
                        "minimum": schema.HOUR_MIN,
                        "maximum": schema.HOUR_MAX,
                    },
                },
            },
        },
    },
}

PREDICTION_RESPONSE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.com/schemas/prediction-response.json",
    "title": "PredictionResponse",
    "type": "object",
    "required": ["request_id", "model_name", "model_version", "predictions"],
    "additionalProperties": False,
    "properties": {
        "request_id": {"type": "string", "minLength": 1},
        "model_name": {"type": "string"},
        "model_version": {"type": "integer", "minimum": 1},
        "predictions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "transaction_id",
                    "prediction",
                    "probability",
                    "request_id",
                ],
                "additionalProperties": False,
                "properties": {
                    "transaction_id": {"type": "string", "minLength": 1},
                    "prediction": {"type": "integer", "enum": [schema.RISK_MIN, schema.RISK_MAX]},
                    "probability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "request_id": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}

ERROR_ENVELOPE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.com/schemas/error-envelope.json",
    "title": "ErrorEnvelope",
    "type": "object",
    "required": ["status", "error_code", "message", "request_id"],
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "const": "error"},
        "error_code": {"type": "string"},
        "message": {"type": "string"},
        "request_id": {"type": "string", "minLength": 1},
    },
}

ERROR_CODE_TABLE = {
    "INVALID_REQUEST": "Input payload failed validation",
    "MODEL_NOT_AVAILABLE": "Requested model could not be loaded",
    "INTERNAL_ERROR": "Unexpected server error",
}

MODEL_CARD_TEMPLATE = {
    "model_name": None,
    "version": None,
    "data_window": None,
    "metrics": None,
    "training_time": None,
    "git_sha": None,
}


__all__ = [
    "PREDICTION_REQUEST_SCHEMA",
    "PREDICTION_RESPONSE_SCHEMA",
    "ERROR_ENVELOPE_SCHEMA",
    "ERROR_CODE_TABLE",
    "MODEL_CARD_TEMPLATE",
]
