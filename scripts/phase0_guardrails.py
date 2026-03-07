#!/usr/bin/env python3
"""
Phase 0 guardrails:
- Block new files under legacy routes/ and blueprints/.
- Block new route decorators in those legacy paths.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

LEGACY_DIRS = ("routes", "blueprints")
ROUTE_DECORATOR_RE = re.compile(r"^\+\s*@\w+\.(route|get|post|put|delete|patch)\(")
ADD_URL_RULE_RE = re.compile(r"^\+\s*.*add_url_rule\(")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _ref_exists(ref: str) -> bool:
    try:
        _git("rev-parse", "--verify", ref)
        return True
    except subprocess.CalledProcessError:
        return False


def _resolve_base_ref() -> str | None:
    env_ref = os.environ.get("GUARDRAIL_BASE_REF")
    if env_ref and _ref_exists(env_ref):
        return env_ref

    gh_base_ref = os.environ.get("GITHUB_BASE_REF")
    if gh_base_ref:
        candidate = f"origin/{gh_base_ref}"
        if _ref_exists(candidate):
            return candidate

    for candidate in ("origin/main", "origin/master"):
        if _ref_exists(candidate):
            return candidate

    if _ref_exists("HEAD~1"):
        return "HEAD~1"

    return None


def _print_list(header: str, items: list[str]) -> None:
    print(header)
    for item in items:
        print(f"  - {item}")


def main() -> int:
    base_ref = _resolve_base_ref()
    if not base_ref:
        print(
            "Phase 0 guardrail: unable to determine base ref. "
            "Set GUARDRAIL_BASE_REF or fetch origin/main."
        )
        return 2

    name_status = _git(
        "diff",
        "--name-status",
        "--diff-filter=A",
        f"{base_ref}...HEAD",
        "--",
        *LEGACY_DIRS,
    )
    added_files = []
    for line in name_status.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            added_files.append(parts[1])

    if added_files:
        _print_list(
            "Phase 0 guardrail: new files under legacy routes/ or blueprints/ are not allowed:",
            added_files,
        )
        return 1

    diff = _git(
        "diff",
        "--no-color",
        "--unified=0",
        "--diff-filter=AM",
        f"{base_ref}...HEAD",
        "--",
        *LEGACY_DIRS,
    )
    violations: list[tuple[str, str]] = []
    current_file = "<unknown>"
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[len("+++ b/") :].strip()
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if ROUTE_DECORATOR_RE.match(line) or ADD_URL_RULE_RE.match(line):
            violations.append((current_file, line[1:].strip()))

    if violations:
        print("Phase 0 guardrail: new route definitions detected in legacy directories:")
        for path, snippet in violations:
            print(f"  - {path}: {snippet}")
        print("New endpoints must be added under finance_app/blueprints/ instead.")
        return 1

    print("Phase 0 guardrails ok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
