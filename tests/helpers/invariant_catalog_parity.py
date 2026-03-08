from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = ROOT / "project" / "docs" / "qa_gate_invariants.md"
DEFAULT_VNEXT_GATE_PATH = ROOT / "tests" / "test_vnext_gate.py"
INVARIANT_ID_RE = re.compile(r"\bINV-[A-Z]+-\d+\b")


def _sorted_unique_ids(values: Iterable[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def parse_catalog_ids(markdown_text: str) -> list[str]:
    return _sorted_unique_ids(INVARIANT_ID_RE.findall(markdown_text or ""))


def load_catalog_ids(catalog_path: str | Path = DEFAULT_CATALOG_PATH) -> list[str]:
    path = Path(catalog_path)
    return parse_catalog_ids(path.read_text(encoding="utf-8"))


def load_asserted_ids(vnext_gate_path: str | Path = DEFAULT_VNEXT_GATE_PATH) -> list[str]:
    path = Path(vnext_gate_path)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    tests_root = ROOT / "tests"
    if str(tests_root) not in sys.path:
        sys.path.insert(0, str(tests_root))
    spec = importlib.util.spec_from_file_location("_vnext_gate_invariant_source", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load vNext gate module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    raw_ids = getattr(module, "ASSERTED_INVARIANT_IDS", None)
    if raw_ids is None:
        raise RuntimeError("ASSERTED_INVARIANT_IDS is missing from tests/test_vnext_gate.py")
    if not isinstance(raw_ids, (set, list, tuple)):
        raise RuntimeError("ASSERTED_INVARIANT_IDS must be a set/list/tuple of invariant ID strings")
    return _sorted_unique_ids(raw_ids)


def check_invariant_catalog_parity(
    *,
    simulate_missing_id: str | None = None,
    simulate_extra_asserted_id: str | None = None,
    asserted_ids: Iterable[str] | None = None,
    catalog_path: str | Path = DEFAULT_CATALOG_PATH,
    vnext_gate_path: str | Path = DEFAULT_VNEXT_GATE_PATH,
) -> dict[str, Any]:
    catalog_ids = load_catalog_ids(catalog_path)
    if simulate_missing_id:
        catalog_ids = _sorted_unique_ids([*catalog_ids, str(simulate_missing_id)])

    asserted_sorted = _sorted_unique_ids(
        asserted_ids if asserted_ids is not None else load_asserted_ids(vnext_gate_path)
    )
    if simulate_extra_asserted_id:
        asserted_sorted = _sorted_unique_ids([*asserted_sorted, str(simulate_extra_asserted_id)])

    missing_ids = sorted(set(catalog_ids) - set(asserted_sorted))
    extra_asserted_ids = sorted(set(asserted_sorted) - set(catalog_ids))
    ok = not missing_ids and not extra_asserted_ids

    payload: dict[str, Any] = {
        "ok": ok,
        "catalog_ids": catalog_ids,
        "asserted_ids": asserted_sorted,
        "missing_ids": missing_ids,
        "extra_asserted_ids": extra_asserted_ids,
        "catalog_count": len(catalog_ids),
        "asserted_count": len(asserted_sorted),
    }
    if not ok:
        payload["message"] = (
            "Invariant catalog parity mismatch: "
            f"missing_ids={missing_ids} "
            f"extra_asserted_ids={extra_asserted_ids} "
            f"catalog_count={len(catalog_ids)} "
            f"asserted_count={len(asserted_sorted)}"
        )
    return payload
