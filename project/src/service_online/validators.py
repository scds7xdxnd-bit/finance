"""Pydantic validators wrapping the JSON contracts."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator

from ..data.schema import ALLOWED_MERCHANT_TYPES


class PredictionRecord(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=64)
    account_id: str = Field(min_length=1, max_length=64)
    amount: float = Field(ge=-1_000_000.0, le=1_000_000.0)
    merchant_type: str
    transaction_hour: int = Field(ge=0, le=23)

    @field_validator("merchant_type")
    @classmethod
    def check_merchant_type(cls, value: str) -> str:
        if value not in ALLOWED_MERCHANT_TYPES:
            raise ValueError("merchant_type not allowed")
        return value


class PredictionRequest(BaseModel):
    request_id: str = Field(min_length=1)
    records: List[PredictionRecord] = Field(min_length=1)


class PredictionResponse(BaseModel):
    request_id: str
    model_name: str
    model_version: int
    predictions: List[dict]


def validate_request(payload: dict) -> PredictionRequest:
    return PredictionRequest.model_validate(payload)


__all__ = [
    "PredictionRecord",
    "PredictionRequest",
    "PredictionResponse",
    "validate_request",
]
