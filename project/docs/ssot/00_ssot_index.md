# Finance App SSOT Index
_Last updated: 2026-03-08_

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
- Canonical ledger query API is the reporting contract surface.
- CI vNext gate enforces schema, dedupe, convergence, reporting parity, scope invariants, invariant catalog parity, and statement export parity.

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

## 00.6 Document Map
| File | Purpose |
| --- | --- |
| `00_ssot_index.md` | SSOT policy, precedence, change control, map. |
| `10_architecture_overview.md` | Runtime architecture, module boundaries, data flow map. |
| `20_domain_model.md` | Canonical entities and ledger invariants. |
| `30_ledger_convergence.md` | Link confidence tiers, backfill rules, reconcile/coverage contracts. |
| `40_import_contracts.md` | CSV normalization/dedupe/provenance contracts and summary schema. |
| `50_reporting_contracts.md` | Canonical query API, ranked endpoint mapping, journal-only totals rule. |
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
