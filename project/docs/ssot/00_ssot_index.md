# Finance App SSOT Index
_Last updated: 2026-03-11_

## 00.1 Purpose
This directory is the Single Source of Truth (SSOT) for vNext financial correctness.

SSOT exists to keep architecture, contracts, ownership, and gates in one place so Ledger, Import, DB, Reporting, QA, Sec, and PM can work independently without drift.
Section IDs in this file and all SSOT files are stable citation anchors.

## 00.2 Locked Decisions (Do Not Relitigate)
- Canonical ledger source of truth is `JournalEntry` and `JournalLine`.
- Legacy `Transaction` is compatibility/emergency only.
- Ranked reporting is journal-only by default.
- Mixed reporting mode is forbidden.
- CSV ingestion is journal-first and idempotent (file hash + row-level dedupe across files).
- Convergence linking policy is `exact|strong|weak_ambiguous`; weak never auto-links.
- Strong linking requires stable provenance; `row_dedupe_key` is treated as stable with strict 1:1 cardinality.
- Schema guard is capability-based and blocks sensitive operations when required capabilities are missing.
- Schema verifier parity is release-blocking: `total_checks == required_artifact_count` is mandatory.
- Invariant catalog parity is release-blocking: `catalog_ids == asserted_ids` is mandatory.
- Statement export parity is release-blocking: `/accounting/statement/export` must remain parity-consistent with `/accounting/statement/data`.
- Security compliance gate with exception expiry is release-blocking: expired security exceptions fail release.
- Alembic-first schema management is mandatory; `db.create_all()` is forbidden outside isolated test harnesses.
- Startup/migration contract gate is release-blocking: boot/migration changes require gate evidence.
- DB-level journal integrity is mandatory; release is blocked if `journal_integrity` capability or `GATE-DB-INTEGRITY` fails.
- Frontend contract lock is authoritative; changes to frontend-consumed payload keys require SSOT update and QA contract test update.
- Phase 1 UX friction removal contract is authoritative (`SSOT 56`): Quick Add reuses `POST /add_transaction`, and `/upload_csv` remains redirect/flash (no CSV JSON contract change in Phase 1).
- Phase 1.1 filters round-trip contract is authoritative (`SSOT 57`): no new endpoints, no transactions filter JSON endpoint, and no `/upload_csv` JSON behavior change.
- Phase 1.2 transaction edit UX contract is authoritative (`SSOT 58`): edit flow must reuse `PUT /accounting/journal/<entry_id>` and unbalanced finalize failures must map deterministically to `error_code=JOURNAL_NOT_BALANCED`.
- Phase 1.2.1 transaction edit UX hardening contract is authoritative (`SSOT 58_1`): edit preload/render, balance-state gating, and post-save query-param preservation are machine-checkable and endpoint-stable.
- Phase 1.2.2 transaction edit preload/state-drift contract is authoritative (`SSOT 58_2`): preload source, preload-state marker behavior, and state reconciliation are machine-checkable and endpoint-stable.
- Phase 1.2.3 transaction edit refresh-safety contract is authoritative (`SSOT 58_3`): active edit sessions retain local buffer authority, stale warning visibility is mandatory, and refresh params remain preserved.
- Phase 1.2.4 transaction edit usability-polish contract is authoritative (`SSOT 58_4`): additive selector and usability behavior locks are stable while endpoint/registry surfaces remain unchanged.
- Phase 1.3 CSV import UX contract is authoritative (`SSOT 59`): import summary remains session-backed (`last_import_result_v1`), dismiss remains POST-based, and `/upload_csv` remains no-JSON.
- Phase 1.3.1 CSV import details polish contract is authoritative (`SSOT 59_1`): details rendering/toggle semantics are deterministic HTML/session behavior, with no `/upload_csv` JSON change.
- Canonical ledger query API is the reporting contract surface.
- CI vNext gate enforces schema, dedupe, convergence, reporting parity, scope invariants, invariant catalog parity, statement export parity, security compliance, startup/migration contract, and DB integrity.

## 00.3 Source Precedence (Anti-Shadow-Truth Rule)
When sources disagree, precedence is:
1. This SSOT directory (`project/docs/ssot/*`)
2. Enforced code contracts (service/CLI/model constraints)
3. Enforced tests and gate fixtures
4. Supporting docs outside SSOT (`project/docs/*`)

A PR is not mergeable if it introduces contradictory behavior across these layers.

## 00.4 How To Use SSOT
- Start with `10_architecture_overview.md` for runtime boundaries and flow map.
- Use `20`-`70` for domain and interface contracts.
- Use `80_quality_gates.md` for CI/release acceptance criteria.
- Use `90_operator_runbook.md` for operational procedures.
- Use `99_team_boundaries.md` for ownership and change restrictions.

## 00.5 SSOT Change Control Protocol
Any change to locked decisions, contract surfaces, or gate thresholds must satisfy all rules below in one PR:
- Update impacted SSOT file(s).
- Update or add tests and/or gate fixtures proving new behavior.
- Update operator steps if runbook-relevant behavior changed.
- Include section references in PR description (for example `SSOT 40.3`, `SSOT 80.2`).
- Obtain architect signoff for stable interface changes listed in `99_team_boundaries.md`.
- Include the mandatory `SSOT Impact` section from `.github/pull_request_template.md`.
- For schema verifier or capability changes, include parity evidence from `SSOT 61.8`.
- For invariant catalog or invariant assertion changes, include parity evidence from `SSOT 81.8`.
- For statement export or statement data contract changes, include parity evidence from `SSOT 50.7` and gate evidence from `SSOT 80.11`.
- For sensitive endpoint changes, include security gate evidence from `SSOT 80.12` and exception-register updates from `SSOT 70.5` (if applicable).
- For startup, app-factory preflight, migration, or DB URL precedence changes, include gate evidence from `SSOT 80.13` and operator impact notes from `SSOT 90.7`.
- For journal schema, posting finalization semantics, or DB integrity enforcement changes, include gate evidence from `SSOT 80.14` and operator remediation notes from `SSOT 90.8`.
- For frontend-consumed endpoint payloads or endpoint-registry key changes, include SSOT references from `SSOT 55` and QA contract evidence from `tests/test_frontend_contracts.py` once implemented.
- For Phase 1 UX behavior or DOM/query contract changes, include SSOT references from `SSOT 56` and QA contract evidence for key-presence/status handling.
- For Phase 1.1 filter/query round-trip changes, include SSOT references from `SSOT 57` and QA contract evidence for parameter preservation/status handling.
- For Phase 1.2 transaction edit UX contract changes, include SSOT references from `SSOT 58` and QA contract evidence for deterministic error mapping and registry-key usage checks.
- For Phase 1.2.1 transaction edit hardening changes, include SSOT references from `SSOT 58_1` and QA contract evidence for preload/render selectors, error mapping, and query-param preservation checks.
- For Phase 1.2.2 transaction edit preload/state-drift changes, include SSOT references from `SSOT 58_2` and QA contract evidence for preload-state markers, missing-state behavior, and entry-id action-surface checks.
- For Phase 1.2.3 transaction edit refresh-safety changes, include SSOT references from `SSOT 58_3` and QA contract evidence for edit-session marker, stale-warning selector, and buffer-authority semantics.
- For Phase 1.2.4 transaction edit usability-polish changes, include SSOT references from `SSOT 58_4` and QA contract evidence for additive selector surface and registry-stability checks.
- For Phase 1.3 CSV import UX contract changes, include SSOT references from `SSOT 59` and QA contract evidence for panel selectors, dismiss semantics, and filter-param preservation checks.
- For Phase 1.3.1 CSV import details polish changes, include SSOT references from `SSOT 59_1` and QA contract evidence for details-selector surface, collapsed/expanded state behavior, and dismiss redirect-param preservation checks.

## 00.6 Document Map
| File | Purpose |
| --- | --- |
| `00_ssot_index.md` | SSOT policy, precedence, change control, map. |
| `10_architecture_overview.md` | Runtime architecture, module boundaries, data flow map. |
| `20_domain_model.md` | Canonical entities and ledger invariants. |
| `30_ledger_convergence.md` | Link confidence tiers, backfill rules, reconcile/coverage contracts. |
| `40_import_contracts.md` | CSV normalization/dedupe/provenance contracts and summary schema. |
| `50_reporting_contracts.md` | Canonical query API, ranked endpoint mapping, journal-only totals rule. |
| `55_frontend_contracts.md` | Frontend-facing endpoint payload lock and endpoint registry contract. |
| `56_phase1_ux_friction_removal.md` | Phase 1 UX behavior, DOM/query contracts, and implementation boundaries. |
| `57_phase1_1_filters_roundtrip.md` | Phase 1.1 filter/query round-trip contract and measurement-first performance posture. |
| `58_phase1_2_transaction_edit_ux.md` | Phase 1.2 transaction edit UX contract, edit DOM surface, error mapping, and registry touchpoints. |
| `58_1_phase1_2_1_transaction_edit_ux_hardening.md` | Phase 1.2.1 transaction edit UX hardening: preload/render determinism, balance-state gating, and round-trip preservation. |
| `58_2_phase1_2_2_transaction_edit_state_drift.md` | Phase 1.2.2 transaction edit state-drift contract: preload source lock, preload-state markers, and state reconciliation behavior. |
| `58_3_phase1_2_3_transaction_edit_refresh_safety.md` | Phase 1.2.3 transaction edit refresh-safety contract: edit-session marker, stale warning visibility, and local-buffer authority under refresh. |
| `58_4_phase1_2_4_transaction_edit_usability_polish.md` | Phase 1.2.4 transaction edit usability polish: additive keyboard/focus/line/delta/error/stale/save-status selector and behavior locks. |
| `59_phase1_3_csv_import_ux_no_json.md` | Phase 1.3 CSV import UX contract: session summary payload, panel selectors, dismiss lifecycle, no JSON upload behavior. |
| `59_1_phase1_3_csv_import_details_polish.md` | Phase 1.3.1 CSV import details polish: deterministic details rendering/toggle semantics, additive selector lock, and no `/upload_csv` JSON behavior. |
| `60_schema_capabilities.md` | Capability matrix and hard-fail guard behavior. |
| `61_schema_verifier_parity_playbook.md` | Formal verifier parity definition, release rule, and implementation checklists. |
| `70_security_model.md` | AuthN/AuthZ, CSRF, admin safety, audit requirements, endpoint sensitivity classes. |
| `80_quality_gates.md` | Gate invariants, CI jobs, thresholds, failure drills. |
| `81_invariant_catalog_parity_playbook.md` | Formal invariant catalog parity definition, release rule, and implementation checklists. |
| `90_operator_runbook.md` | Backup/restore/migrate/backfill/reconcile/cutover/rollback operations. |
| `99_team_boundaries.md` | Team ownership, stable interfaces, forbidden changes, signoff rules. |

## 00.7 PR Checklist Snippet
Use `.github/pull_request_template.md` as the source template. Minimum required SSOT block:

```md
## SSOT Impact (Required)
- [ ] I reviewed `project/docs/ssot/00_ssot_index.md` source precedence and change protocol.
- [ ] This PR changes SSOT contract surfaces: `yes` / `no`.
- [ ] If `yes`: I updated SSOT sections in `project/docs/ssot/*`.
- [ ] If `yes`: I updated tests/gates proving behavior.
- [ ] If `no`: I confirm behavior remains consistent with current SSOT.
- [ ] I confirmed no forbidden changes from `project/docs/ssot/99_team_boundaries.md`.

### Required SSOT Section References
- SSOT refs: `<SSOT 30.x, SSOT 40.x, SSOT 50.x, SSOT 60.x, SSOT 70.x, SSOT 80.x, SSOT 81.x, SSOT 90.x>`
- Rationale for each ref: `<why it applies>`
```
