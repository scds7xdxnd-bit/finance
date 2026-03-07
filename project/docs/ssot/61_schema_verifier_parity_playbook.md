# Schema Verifier Parity Playbook
_Last updated: 2026-03-07_

## 61.1 Scope
This playbook defines mandatory parity between runtime schema-guard artifact requirements and SQL verifier checks used by migration smoke.

## 61.2 Problem Statement
Runtime schema guard enforces capability requirements from `finance_app/services/schema_guard_service.py::_CAPABILITY_REQUIREMENTS`.

Migration smoke relies on `scripts/verify_schema_capabilities.sql`.

If SQL verifier checks are fewer or different than runtime requirements, migration smoke can pass while guarded runtime behavior is actually non-compliant. This is forbidden.

## 61.3 Formal Definitions
### Required artifact
A required artifact is one atomic requirement declared under `_CAPABILITY_REQUIREMENTS` in any of:
- `tables`
- `columns` (each column counts separately)
- `indexes`
- `uniques`
- `checks`

### Canonical artifact identifier
Each required artifact must map to a canonical `artifact_id`:
- `table:<table_name>`
- `column:<table_name>.<column_name>`
- `index:<table_name>.<index_name>`
- `unique:<table_name>.<constraint_name>`
- `check:<table_name>.<constraint_name>`

### Required artifact set
`required_artifact_set` is the deduplicated global set of canonical `artifact_id` values derived from `_CAPABILITY_REQUIREMENTS`.

If the same artifact appears in multiple capabilities, it is counted once in `required_artifact_set`.

### Required artifact count
`required_artifact_count := len(required_artifact_set)`.

### SQL verifier check count
`total_checks` is the number of verifier rows returned by `scripts/verify_schema_capabilities.sql` after enforcing one row per canonical `artifact_id`.

### Parity condition
`parity_ok := (total_checks == required_artifact_count)`.

## 61.4 Release Rule
- Parity is release-blocking.
- If `parity_ok=false`, `GATE-SCHEMA` fails and release is blocked.
- Operator is not allowed to proceed to migration/backfill/cutover while parity is failing.

## 61.5 Required Migration Smoke Output Contract
`python3 scripts/migration_smoke_vnext.py` output must include:
- `ok` (boolean)
- `failed_checks` (array)
- `total_checks` (integer)
- `required_artifact_count` (integer)
- `parity_ok` (boolean)
- `parity_message` (string; required when `parity_ok=false`)
- `parity_delta` (integer; `total_checks - required_artifact_count`)

Parity failure must set:
- `ok=false`
- `parity_ok=false`
- non-zero process exit code
- `parity_message` with prefix `Schema verifier parity mismatch:`

Top-level `ok` semantics are strict:
- `ok := (len(failed_checks) == 0) AND parity_ok`.

`failed_checks` semantics are strict:
- `failed_checks` lists artifact verification failures only (`ok=0` verifier rows).
- parity mismatch alone may produce `failed_checks=[]`.
- if parity fails, `ok=false` even when `failed_checks=[]`.

Verifier row schema (stable contract):
- `scope` (string; for global deduped parity this must be `global`)
- `artifact_type` (`table|column|index|unique|check`)
- `artifact_id` (canonical identifier from 61.3)
- `ok` (`0|1`)
- `message` (string, optional; required when `ok=0`)

## 61.6 Team Checklists
### DB team checklist
- Align SQL verifier checks with `_CAPABILITY_REQUIREMENTS` so each required artifact has exactly one SQL check row.
- Build verifier rows using canonical `artifact_id` and deduplicated global artifact set semantics from 61.3.
- Ensure SQL check identifiers are stable and deterministic across runs.
- Ensure migration smoke computes and emits `required_artifact_count` using the formal definition in 61.3.

### QA team checklist
- Add a gate test that fails when `total_checks != required_artifact_count`.
- Add a negative parity test fixture or mutation path proving parity mismatch returns non-zero and `parity_ok=false`.
- Keep invariant catalog and unified gate assertions aligned for parity requirements.

### DevOps team checklist
- Ensure required check path executes migration smoke and blocks merge on non-zero exit.
- Persist migration smoke JSON output as an artifact for failed and successful runs with artifact name `migration_smoke_vnext.json`.
- Preserve migration smoke command exit status even when output is piped (for example through `tee`).
- CI logs must print exactly one deterministic summary line:
  - `parity_ok=<bool> total_checks=<int> required_artifact_count=<int>`

### Runtime team involvement
- No backend runtime ownership is required for this work.
- Consult runtime/backend only if wording is reused in user-facing runtime API error payloads.

## 61.7 Verification Commands
Primary:
```bash
python3 scripts/migration_smoke_vnext.py
python3 -m pytest -q tests/test_schema_guard_service.py
python3 -m pytest -q tests/test_vnext_gate.py
```

Intentional parity failure drill:
Preferred non-destructive drill:
1. Run migration smoke with a test-only simulation flag:
```bash
python3 scripts/migration_smoke_vnext.py --simulate-parity-mismatch 1
```
2. Confirm:
- non-zero exit
- `ok=false`
- `parity_ok=false`
- `total_checks != required_artifact_count`
- `parity_message` starts with `Schema verifier parity mismatch:`

Fallback drill (if simulation flag is not yet implemented):
1. Remove one SQL verifier check row from `scripts/verify_schema_capabilities.sql`.
2. Run:
```bash
python3 scripts/migration_smoke_vnext.py
```
3. Confirm:
- non-zero exit
- `ok=false`
- `parity_ok=false`
- `total_checks != required_artifact_count`
- `parity_message` starts with `Schema verifier parity mismatch:`

## 61.8 PR Description Snippet (Schema Changes)
Use this exact block in PR descriptions that change schema capability requirements or verifier checks:

```md
## Schema Verifier Parity Evidence
- [ ] I ran `python3 scripts/migration_smoke_vnext.py`.
- [ ] I confirmed `total_checks == required_artifact_count`.
- [ ] I confirmed `parity_ok=true`.
```

## 61.9 Required Failure Message
When parity fails, include this exact message prefix:
- `Schema verifier parity mismatch:`

Required message payload details:
- `total_checks=<int>`
- `required_artifact_count=<int>`
- `delta=<int>`
