from __future__ import annotations

from helpers.invariant_catalog_parity import (
    check_invariant_catalog_parity,
    load_asserted_ids,
    load_catalog_ids,
)


def test_invariant_catalog_parity_pass_case():
    payload = check_invariant_catalog_parity()
    assert payload["ok"] is True
    assert payload["missing_ids"] == []
    assert payload["extra_asserted_ids"] == []
    assert payload["catalog_count"] == len(payload["catalog_ids"])
    assert payload["asserted_count"] == len(payload["asserted_ids"])


def test_invariant_catalog_parity_simulated_missing_id_case():
    payload = check_invariant_catalog_parity(simulate_missing_id="INV-DRIFT-999")
    assert payload["ok"] is False
    assert "INV-DRIFT-999" in payload["missing_ids"]
    assert payload["message"].startswith("Invariant catalog parity mismatch:")


def test_invariant_catalog_parity_extra_asserted_ids_case():
    base_asserted_ids = load_asserted_ids()
    payload = check_invariant_catalog_parity(asserted_ids=[*base_asserted_ids, "INV-FAKE-999"])
    assert payload["ok"] is False
    assert "INV-FAKE-999" in payload["extra_asserted_ids"]
    assert payload["message"].startswith("Invariant catalog parity mismatch:")


def test_invariant_catalog_parity_simulated_extra_asserted_id_case():
    payload = check_invariant_catalog_parity(simulate_extra_asserted_id="INV-DRIFT-998")
    assert payload["ok"] is False
    assert "INV-DRIFT-998" in payload["extra_asserted_ids"]
    assert payload["message"].startswith("Invariant catalog parity mismatch:")


def test_catalog_ids_are_sorted_unique_and_non_empty():
    catalog_ids = load_catalog_ids()
    assert catalog_ids == sorted(catalog_ids)
    assert len(catalog_ids) == len(set(catalog_ids))
    assert all(isinstance(inv_id, str) and inv_id for inv_id in catalog_ids)
