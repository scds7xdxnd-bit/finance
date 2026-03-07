## Summary
- What changed:
- Why:

## Merge Train
- Train position: `PR-LEDGER` / `PR-QA-VNEXT-GATES` / `PR-SEC-HARDENING` / `PR-CLEANUP-DOCS` / `other`
- Depends on:
- Blocks:

## SSOT Impact (Required)
- [ ] I reviewed `project/docs/ssot/00_ssot_index.md` (precedence + change-control protocol).
- [ ] This PR changes SSOT contract surfaces: `yes` / `no`.
- [ ] If `yes`: I updated SSOT sections in `project/docs/ssot/*`.
- [ ] If `yes`: I updated tests/gates proving behavior.
- [ ] If `no`: I confirm behavior remains consistent with current SSOT.
- [ ] I confirmed no forbidden changes from `project/docs/ssot/99_team_boundaries.md`.

### Required SSOT Section References
List all applicable references (examples: `SSOT 30.x`, `SSOT 40.x`, `SSOT 50.x`, `SSOT 60.x`, `SSOT 70.x`, `SSOT 80.x`, `SSOT 90.x`):

- SSOT refs:
- Rationale for each ref:

## Gate Evidence (Required)
Paste exact commands run and outcomes:

```bash
python3 scripts/migration_smoke_vnext.py
python3 -m pytest -q tests/test_vnext_gate.py
```

If this PR changes gate-critical behavior, include:

```bash
pytest -q tests/test_transaction_import_idempotency.py
pytest -q tests/test_ledger_convergence.py
pytest -q tests/test_ranked_reporting_cutover.py
python3 -m flask --app finance_app schema-status
python3 -m flask --app finance_app ledger-reconcile
```

## Rollback Plan (Required)
- Revert strategy:
- Data/schema rollback impact:
- Operator steps/doc updates required:
