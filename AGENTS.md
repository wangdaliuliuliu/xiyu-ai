# Xiyu repository maintenance rules

For any task involving Xiyu's product direction, persona, agency, proactive contact, enterprise assistance, workbench integration, photos, or production deployment, first read `docs/XIYU-MASTER-HANDOFF-2026-09-14.md`. Record every investigation, decision, code change, test, deployment, rollback, unresolved issue, and user-visible result in `docs/XIYU-SUCCESSOR-WORKLOG.md` before handing the task off. Do not mark an item complete merely because code or a report exists; use the status vocabulary defined in the master handoff.

Before changing proactive contact, enterprise assistance, memory routing, persona expression, or message delivery, read `docs/xiyu-architecture-maintenance-map.md` and trace the existing owner module listed there.

Extend the existing owner unless its contract is demonstrably wrong. Do not add a second scheduler, intention selector, memory store, enterprise router, safety gate, delivery adapter, or receipt ledger beside the canonical one.

The approved v2 implementation and validation specifications are `docs/agency-development-plan-v2-2026-09-08.md` and `docs/agency-validation-plan-v2-2026-09-08.md`. Preserve the original owners, but replace the audited incorrect ordering during implementation with:

`authorized inputs -> proactive.mjs shared cycle -> scoped snapshot/appraisal -> initiative.mjs merge/select -> validated strategy -> existing tools prepare -> ready -> proactive_engine.mjs hard timing gates (proactive only) -> companion.mjs/AI expression -> final factual/safety/dedup checks -> existing ilink/media delivery -> transactional receipts/feedback`

Explicit inbound requests use the same execution/result/feedback contract without an unnecessary background appraisal. Web ownership comes from authenticated account ownership, WeChat ownership from its verified binding. Never infer account_id from companion.user_id.

`initiative.mjs` owns only the selected purpose and its action contract. It must not grow its own timer, LLM client, memory database, enterprise fetcher, or WeChat sender.

`agency_protocol.mjs` owns only structured prompt assembly, schema validation, deterministic boundary normalization, and semantic review protocol. `proactive.mjs` remains the sole scheduler/orchestrator; `db.mjs` is the sole durable agency state store. `XIYU_AGENCY_MODE` defaults to `legacy`; `shadow` records isolated proposals without delivery; `enabled` is the only mode allowed to gate ordinary proactive delivery through the same existing sender.

When a responsibility must move, update the maintenance map in the same change and remove the old route. Do not leave compatibility paths that can both execute unless a documented migration window requires them.

Every proactive behavior change must keep or add an offline deterministic check. Do not trigger a real outbound message solely for validation.
