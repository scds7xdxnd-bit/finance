"""Strict policy constants for ledger convergence linking."""

from __future__ import annotations

from enum import Enum


class LinkConfidence(str, Enum):
    """Confidence tier for transaction->journal convergence candidates."""

    EXACT = "exact"
    STRONG = "strong"
    WEAK_AMBIGUOUS = "weak_ambiguous"


class LinkReason(str, Enum):
    """Machine reason codes used by backfill classifier and candidate records."""

    EXACT_LINK_ROW = "exact_link_row"
    EXACT_TX_REF = "exact_tx_ref"
    STRONG_ROW_KEY_UNIQUE = "strong_row_key_unique"
    WEAK_NO_STABLE_ID = "weak_no_stable_id"
    WEAK_AMBIGUOUS_CARDINALITY = "weak_ambiguous_cardinality"


class LinkCandidateStatus(str, Enum):
    """Candidate lifecycle states."""

    PENDING_REVIEW = "pending_review"
    AUTO_LINKED = "auto_linked"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


def is_auto_link_confidence(confidence: LinkConfidence | str) -> bool:
    value = confidence.value if isinstance(confidence, LinkConfidence) else str(confidence)
    return value in {LinkConfidence.EXACT.value, LinkConfidence.STRONG.value}
