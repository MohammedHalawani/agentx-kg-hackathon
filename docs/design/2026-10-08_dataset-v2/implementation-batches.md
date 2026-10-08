# Next-run implementation order

Design 2026-10-08. Each batch uses audit → implementation → independent review/fix → gate
and four dated docs under docs/agent-runs. Do not skip a failed data/state gate to add UI.

| Batch / owner boundary | Concrete work | Exit gate |
|---|---|---|
| V2-01 contracts and narrative pack |Approve synthetic assumptions; versioned evidence/schema/DTOs; 24 scenario narratives; no DB writes|Every cause has positive evidence or explicit uncertainty; flows/places/units/provenance reviewed; neutral language|
| V2-02 offline network generator |Pure deterministic generation for facilities/ownership/inventory, classes/packages, addresses, routes/plans/sessions, compatible vehicles and event histories|Reproducible export; topology/time/capacity/custody validators; gold separated; no network/DB/email calls|
| V2-03 derivation engine |Expected-vs-actual, barcode/weight/gate/address/contact comparisons, custody gaps/traffic/disputes/multi-package rules|Evidence-removal and threshold/equality fixtures; unknown/conflict paths; GPS neither parcel proof nor blame|
| V2-04 isolated import and read adapter |Verified local shadow target/backup strategy; idempotent importer/constraints/indexes; compatible Explore/evidence APIs|Exact target approval, counts/invariants/vector ONLINE, replay adds nothing, rollback leaves V1 intact|
| V2-05 reasoning and evidence contract |Add new supported/unknown/multi-cause outputs; source-backed summaries; citation/condition verification; preserve real AFL|Full fixture pipeline and bounded rejection; no missing-evidence certainty/default cause; no pending precedent; versioned model contract|
| V2-06 operator and outcome authority |Authenticated roles, optimistic state/evidence versions, explicit approval/rejection, execution adapter receipts, verified outcome policy/reopen|Unauthorized/stale/duplicate commands refused; concurrent lifecycle tests; no model self-certification; outcome eligibility proven|
| V2-07 sequential queue and audit |Durable lease/run/checkpoint/outbox, bounded retries, per-transition audit, time filters and metrics|Crash/resume duplicate-safe; failure attempts retained; filter boundaries correct; accepts not counted as successes|
| V2-08 dry notification adapter |Outbox event/template/recipient refs, NOTIFICATION_MODE=dry_run, fake Resend adapter; live adapter kept disabled|Zero provider calls in tests/eval/default mode; durable dedup and safe content; no customer email sent|
| V2-09 controlled Evaluation V2 |Review validation gold and budget;24-input smoke; frozen paired60+12-anchor protocol when authorized|Complete denominator/identity/no-write gates; blind factual/action/language review; honest limitations and chosen model|
| V2-10 UI plan then implementation |Audit workflows/data contracts first; queue/custody timeline/map/case workspace/approval/audit views; AR/EN accessibility|Operator tasks understandable; responsive/RTL/keyboard/text alternatives; reduced motion; true-outcome-only resolution movement|
| V2-11 demo/readiness |Four narrative stories from scenario matrix, at least one actual AFL; tests/API/browser/graph/index/secret checks; logical commits|No SPL infrastructure claims; no hidden reset; known start/end state, approval/execution/outcome boundaries visible|

Initial scope deliberately excludes route optimization, employee scoring/surveillance,
live fleet ingestion and a replacement logistics system. Optional Inventory/POD/Traffic
adapters can be staged after their contracts without inventing unavailable enterprise data.

Decisions needed before their dependent implementation: synthetic policy/network sizing,
shadow DBMS capabilities and target approval, operator roles/outcome verification authority,
cloud-call budget and domain adjudication. Live notifications additionally need recipient
consent/sender verification and explicit send authorization. These are future decisions;
no approval is requested merely to finish or review this design-only run.
