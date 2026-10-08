# Shipment closed-loop proof — audit

Timestamp: 2026-10-07T22:42:18+03:00. Local synthetic database only.

The old write_resolution path matched FailureReason by ID alone, accepted any review/action,
and generated fresh UUIDs each invocation. MERGE therefore did not make repeated requests
idempotent. Extracted shipment, retrieved local evidence, and live failure identity were not
checked together. Timestamps were naive local strings; Outcome remained correctly pending
with success null. Existing seeded chains could acquire additional recommendations.

SHP-0227 inspection: FR-030af469e0 has existing agent Resolution RES-3f6cb49673 and
Outcome OUT-040d90e150. Its action is customer telephone coordination for an alternative
time. Outcome.status=pending, Outcome.success=null. Both legacy timestamps are the naive
2026-10-07T21:56:54. Those existing nodes and their history are preserved, not retrofitted.

Canonical unresolved address-conflict candidate: SHP-0004 / FR-c6c80b7014. The graph contains
two delivery Address versions, including the customer's تندحة address and a conflicting
ملتقى الصدرين destination. Policy SLA=1 day, retry_limit=1. No resolution exists for its live
failure. A read-only proof preview verified localhost, SHIPMENT_DATABASE=shipments,
300 synthetic SHP IDs, whitelisted shipment-domain labels, and 3636 existing nodes.

The coordinator's separate retrieval audit excludes pending outcomes from historical
precedent. The AFL agent separately reproduced a natural model rationale counting 4/3
attempts against 2 recorded events. The mutating proof is held until that evidence-integrity
guard passes. No DB mutations or model calls were made during this audit/preview.

## Overall Batch 2 findings and ownership

Updated: 2026-10-07T22:49:13+03:00. The held proof subsequently ran after the guard passed.
The coordinator owns the integrated acceptance gate; these primary documents collect the
writeback, observed-precedent, AFL, evidence-integrity, and operator-semantics work.

The success-rate denominator already omitted pending outcomes, but retrieval/backfill did
not. This could promote an unconfirmed decision into precedent without claiming success=true.
The first live read-only AFL trace also exposed incorrect final attempt counts; suppression
of private reasoning alone cannot ensure final assessment fidelity. UI language treated
recorded resolutions as precedent coverage and null retrieved outcomes as unsuccessful.
These concrete baseline defects were corrected before serious evaluation.

Supporting audits: shipment-closed-loop-proof-precedent-integrity.md,
shipment-closed-loop-proof-afl-audit.md, shipment-closed-loop-proof-evidence-integrity.md,
and shipment-closed-loop-proof-semantics-review.md (all prefixed 2026-10-07_ in this directory).
