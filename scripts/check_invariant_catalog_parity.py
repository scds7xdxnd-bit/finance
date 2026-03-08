#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = ROOT / "tests"
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from helpers.invariant_catalog_parity import check_invariant_catalog_parity


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check parity between catalog invariant IDs and unified gate asserted IDs.")
    parser.add_argument(
        "--simulate-missing-id",
        default=None,
        help="Test-only drill. Virtually injects this ID into catalog_ids without editing files.",
    )
    parser.add_argument(
        "--simulate-extra-asserted-id",
        default=None,
        help="Test-only drill. Virtually injects this ID into asserted_ids without editing files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    payload = check_invariant_catalog_parity(
        simulate_missing_id=args.simulate_missing_id,
        simulate_extra_asserted_id=args.simulate_extra_asserted_id,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
