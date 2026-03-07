# Finance App SSOT Index
_Last updated: 2026-03-07_

## Purpose
This directory is the Single Source of Truth (SSOT) for vNext financial correctness.

SSOT exists to keep architecture, contracts, ownership, and gates in one place so Ledger, Import, DB, Reporting, QA, Sec, and PM can work independently without drift.

## Locked Decisions (Do Not Relitigate)
- Canonical ledger source of truth is `JournalEntry` and `JournalLine`.
- Legacy `Transaction` is compatibility/emergency only.
- Ranked reporting is journal-only by default.
- Mixed reporting mode is forbidden.
- CSV ingestion is journal-first and idempotent (file hash + row-level dedupe across files).
- Convergence linking policy is `exact|strong|weak_ambiguous`; weak never auto-links.
- Strong linking requires stable provenance; `row_dedupe_key` is treated as stable with strict 1:1 cardinality.
- Schema guard is capability-based and blocks sensitive operations when required capabilities are missing.
- Canonical ledger query API is the reporting contract surface.
- CI vNext gate enforces schema, dedupe, convergence, reporting parity, and scope invariants.

## Source Precedence (Anti-Shadow-Truth Rule)
When sources disagree, precedence is:
1. This SSOT directory (`project/docs/ssot/*`)
2. Enforced code contracts (service/CLI/model constraints)
3. Enforced tests and gate fixtures
4. Supporting docs outside SSOT (`project/docs/*`)

A PR is not mergeable if it introduces contradictory behavior across these layers.

## How To Use SSOT
- Start with `10_architecture_overview.md` for runtime boundaries and flow map.
- Use `20`-`70` for domain and interface contracts.
- Use `80_quality_gates.md` for CI/release acceptance criteria.
- Use `90_operator_runbook.md` for operational procedures.
- Use `99_team_boundaries.md` for ownership and change restrictions.

## SSOT Change Control Protocol
Any change to locked decisions, contract surfaces, or gate thresholds must satisfy all rules below in one PR:
- Update impacted SSOT file(s).
- Update or add tests and/or gate fixtures proving new behavior.
- Update operator steps if runbook-relevant behavior changed.
- Include section references in PR description (for example `SSOT 40.3`, `SSOT 80.2`).
- Obtain architect signoff for stable interface changes listed in `99_team_boundaries.md`.

## Document Map
| File | Purpose |
| --- | --- |
| `00_ssot_index.md` | SSOT policy, precedence, change control, map. |
| `10_architecture_overview.md` | Runtime architecture, module boundaries, data flow map. |
| `20_domain_model.md` | Canonical entities and ledger invariants. |
| `30_ledger_convergence.md` | Link confidence tiers, backfill rules, reconcile/coverage contracts. |
| `40_import_contracts.md` | CSV normalization/dedupe/provenance contracts and summary schema. |
| `50_reporting_contracts.md` | Canonical query API, ranked endpoint mapping, journal-only totals rule. |
| `60_schema_capabilities.md` | Capability matrix and hard-fail guard behavior. |
| `70_security_model.md` | AuthN/AuthZ, CSRF, admin safety, audit requirements, endpoint sensitivity classes. |
| `80_quality_gates.md` | Gate invariants, CI jobs, thresholds, failure drills. |
| `90_operator_runbook.md` | Backup/restore/migrate/backfill/reconcile/cutover/rollback operations. |
| `99_team_boundaries.md` | Team ownership, stable interfaces, forbidden changes, signoff rules. |

## PR Checklist Snippet
Use this snippet in PR templates/descriptions:

```md
## SSOT Impact
- [ ] I reviewed `project/docs/ssot/00_ssot_index.md` source precedence and change protocol.
- [ ] This PR touches SSOT contract surfaces: `yes` / `no`.
- [ ] If yes, I updated SSOT sections: `<file + section ids>`.
- [ ] I added/updated tests or gates proving contract behavior: `<tests/gates>`.
- [ ] I confirmed no forbidden changes from `project/docs/ssot/99_team_boundaries.md`.
- [ ] If a stable interface changed, architect signoff is attached.
```
