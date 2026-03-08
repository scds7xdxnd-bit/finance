# Invariant Catalog Parity Playbook
_Last updated: 2026-03-08_

## 81.1 Purpose and Scope
This playbook defines release-blocking parity between the invariant catalog and the unified vNext gate assertions.

Scope is limited to:
- catalog source of invariant IDs
- unified gate assertion coverage
- pass/fail contract and failure drills

## 81.2 Problem Statement
If an invariant ID exists in `project/docs/qa_gate_invariants.md` but is not asserted by unified gate code, release checks can pass while declared correctness rules are untested. This is forbidden.

## 81.3 Formal Definitions
### Invariant catalog
`catalog_ids` is the set of invariant IDs defined in:
- `project/docs/qa_gate_invariants.md`

### Unified gate
Unified gate coverage source is:
- `tests/test_vnext_gate.py`
- plus fixture support from `tests/fixtures/golden/vnext_gate_minimal.json`

### Covered invariant ID
An invariant ID is covered only when unified gate test code asserts it.

Machine rule:
- `asserted_ids` must be extracted from explicit assertion code in `tests/test_vnext_gate.py`.
- Presence in fixture data alone does not count as coverage.

### Parity sets
- `missing_ids := catalog_ids - asserted_ids`
- `extra_asserted_ids := asserted_ids - catalog_ids`

## 81.4 Release Rule
Invariant catalog parity is release-blocking.

Release passes only when:
- `missing_ids` is empty
- `extra_asserted_ids` is empty

If either set is non-empty, `GATE-INVARIANT-PARITY` fails and release is blocked.

## 81.5 Required Output Contract
Parity checker output must include:
- `ok` (boolean)
- `catalog_ids` (sorted unique list)
- `asserted_ids` (sorted unique list)
- `missing_ids` (sorted unique list)
- `extra_asserted_ids` (sorted unique list)
- `catalog_count` (integer)
- `asserted_count` (integer)
- `message` (string; required when `ok=false`)

Pass/fail semantics:
- `ok := (len(missing_ids) == 0) AND (len(extra_asserted_ids) == 0)`
- checker exits `0` when `ok=true`; non-zero when `ok=false`.
- on failure, `message` must start with:
  - `Invariant catalog parity mismatch:`

## 81.6 Team Checklists
### QA checklist (primary owner)
- Implement parity checker logic that computes `catalog_ids`, `asserted_ids`, `missing_ids`, and `extra_asserted_ids`.
- Enforce parity in unified gate (`tests/test_vnext_gate.py`) as release-blocking.
- Add a negative parity drill test path using simulation mode (no manual source edits required).
- Keep checker output fields stable per 81.5.

### DevOps checklist
- Ensure CI executes invariant parity check on every PR and blocks merge on non-zero exit.
- Keep required check names consistent with `SSOT 80.3`.
- If checker emits JSON output, upload artifact as `invariant_catalog_parity.json` on success and failure.
- CI logs must include one summary line:
  - `invariant_parity_ok=<bool> missing_count=<int> extra_count=<int>`

### Backend checklist (consult-only)
- No runtime/API ownership required.
- Consult only if parity mismatch text is reused in operator-visible runtime messaging.

### DB involvement
- Not required for this gate unless invariant catalog parity later depends on schema metadata.

## 81.7 Verification Commands
Primary:
```bash
python3 scripts/check_invariant_catalog_parity.py
python3 -m pytest -q tests/test_vnext_gate.py
```

Required non-destructive failure drill:
```bash
python3 scripts/check_invariant_catalog_parity.py --simulate-missing-id INV-DRIFT-999
```

Drill expected result:
- non-zero exit
- `ok=false`
- `missing_ids` includes `INV-DRIFT-999`
- `message` starts with `Invariant catalog parity mismatch:`

## 81.8 PR Description Snippet (Invariant Changes)
Use this block in PRs that change invariant IDs, invariant assertions, or unified gate coverage:

```md
## Invariant Catalog Parity Evidence
- [ ] I ran `python3 scripts/check_invariant_catalog_parity.py`.
- [ ] I confirmed `missing_ids=[]`.
- [ ] I confirmed `extra_asserted_ids=[]`.
- [ ] I confirmed `ok=true`.
```
