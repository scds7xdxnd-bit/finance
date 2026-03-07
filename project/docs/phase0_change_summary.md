# Phase 0 Change Summary
_Last updated: 2025-12-24_

## What this means
- Added CI guardrails to block new files and new route definitions under legacy `routes/` and `blueprints/`.
- Published a service-to-domain inventory to make ownership explicit.
- Published an endpoint inventory to record current routes, owners, and consumers.
- Recorded Phase 0 decisions for ledger source of truth, money schedule boundary, and ML asset location.

## Why these changes
- Guardrails prevent further routing drift before Phase 1 consolidation.
- Inventories provide the baseline needed for safe refactors and boundary enforcement.
- Decisions remove ambiguity so future work does not diverge across teams.

## Files touched
- `.github/workflows/smoke.yml` (runs Phase 0 guardrails in CI)
- `scripts/phase0_guardrails.py` (guardrail script)
- `project/docs/service_domain_inventory.md` (ownership map)
- `project/docs/endpoint_inventory.md` (route inventory)
- `project/docs/decisions.md` (Phase 0 architecture decisions)
