# Interfaces

## Training Input Contract

Single-record JSON Schema (Draft 2020-12):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "TrainingTransaction",
  "type": "object",
  "required": [
    "transaction_id",
    "account_id",
    "amount",
    "merchant_type",
    "transaction_hour",
    "risk_label"
  ],
  "additionalProperties": false,
  "properties": {
    "transaction_id": {"type": "string", "minLength": 1, "maxLength": 64},
    "account_id": {"type": "string", "minLength": 1, "maxLength": 64},
    "amount": {"type": "number", "minimum": -1000000, "maximum": 1000000},
    "merchant_type": {
      "type": "string",
      "enum": ["utilities", "payroll", "supplies", "travel", "software"]
    },
    "transaction_hour": {"type": "integer", "minimum": 0, "maximum": 23},
    "risk_label": {"type": "integer", "enum": [0, 1]}
  }
}
```

Table-level notes:

- Primary key = (`transaction_id`). Enforcement is external but the loader will surface duplicates.
- `risk_label` is mandatory for training rows; online prediction omits this field.
- Nulls are disallowed after preprocessing; missing numeric values are imputed prior to modelling.

## Prediction Request Contract (PRED_IN)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "PredictionRequest",
  "type": "object",
  "required": ["request_id", "records"],
  "properties": {
    "request_id": {"type": "string", "minLength": 1},
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
          "transaction_hour"
        ],
        "additionalProperties": false,
        "properties": {
          "transaction_id": {"type": "string", "minLength": 1, "maxLength": 64},
          "account_id": {"type": "string", "minLength": 1, "maxLength": 64},
          "amount": {"type": "number", "minimum": -1000000, "maximum": 1000000},
          "merchant_type": {
            "type": "string",
            "enum": ["utilities", "payroll", "supplies", "travel", "software"]
          },
          "transaction_hour": {"type": "integer", "minimum": 0, "maximum": 23}
        }
      }
    }
  },
  "additionalProperties": false
}
```

## Prediction Response Contract (PRED_OUT)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "PredictionResponse",
  "type": "object",
  "required": ["request_id", "model_name", "model_version", "predictions"],
  "properties": {
    "request_id": {"type": "string", "minLength": 1},
    "model_name": {"type": "string"},
    "model_version": {"type": "integer", "minimum": 1},
    "predictions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["transaction_id", "prediction", "probability", "request_id"],
        "properties": {
          "transaction_id": {"type": "string"},
          "prediction": {"type": "integer", "enum": [0, 1]},
          "probability": {"type": "number", "minimum": 0, "maximum": 1},
          "request_id": {"type": "string", "minLength": 1}
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

## Error Envelope

```json
{
  "status": "error",
  "error_code": "INVALID_REQUEST",
  "message": "Array of validation messages",
  "request_id": "uuid4"
}
```

Error codes:

| Code | Meaning |
| --- | --- |
| `INVALID_REQUEST` | Payload failed schema or contract validation. |
| `MODEL_NOT_AVAILABLE` | Registry has no serving candidate or artifact failed to load. |
| `INTERNAL_ERROR` | Unhandled exception; check logs with `request_id`. |

## Model Card Stub

```json
{
  "model_name": "account_risk_classifier",
  "version": null,
  "data_window": "synthetic-sample",
  "metrics": {
    "val_f1": null,
    "val_accuracy": null,
    "test_f1": null
  },
  "training_time": null,
  "git_sha": null
}
```
