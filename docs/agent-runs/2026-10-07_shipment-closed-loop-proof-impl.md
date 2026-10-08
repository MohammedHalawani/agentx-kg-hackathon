# Shipment closed-loop proof — implementation

Timestamp: 2026-10-07T22:46:55+03:00. Implementation and one canonical live proof complete.

write_resolution now requires an accepted review with a finite score at the review threshold,
a nonempty final-only action, and agreement between extraction, local shipment, local live
failure, and context live_failure_id. Tracking-only complaints are supported when retrieved
tracking identity matches. The fixed write query validates the actual bound
Shipment→Event→FailureReason chain and rejects a failure shared with another shipment.

Stable UUID5 identifiers include the shipment, failure, and accepted action. A temporary
FailureReason lock property is set/removed within the transaction before checking existing
chains. A new chain is allowed only when none exists; replay returns only the identical
compatible agent chain. Seeded history, a different pending recommendation, and incomplete
existing chains are never changed or attributed to the new action. The ephemeral lock is
not persisted and no unrelated nodes are updated. This follows Neo4j's documented
[temporary-property write-lock pattern](https://neo4j.com/docs/operations-manual/current/database-internals/concurrent-data-access/).

New Resolution/Outcome nodes have UTC timestamps, agent_pipeline source, shipment/failure
provenance; Resolution records agent_review approval type and accepted review score.
Outcome remains pending/success null, with notes explicitly saying execution is unconfirmed.
Marked private reasoning is removed from persisted final notes. No physical execution or
human approval is claimed, and no pending recommendation becomes observed precedent.

Escalations validate a real shipment and any supplied failure link, use stable replay IDs and
an ephemeral shipment lock, retain existing compatible handoffs, and add UTC/source fields.
DB exception logging records only the exception type.

Added six write-boundary unit tests and scripts/prove_closed_loop.py. The script defaults to
read-only preview, rechecks synthetic target immediately before mutation, captures exact
new objects/final application DTO, and repeats only the frozen accepted state for sequential
and concurrent replay. It has no reset/delete/backfill/outcome-confirmation path.

After the evidence-integrity reviewer gate passed, one authorized SHP-0004 pipeline run
created a pending reviewed recommendation. Sequential and two concurrent frozen-state
replays produced no additional objects. Evidence artifacts are preserved under
docs/agent-runs/evidence/2026-10-07-shipment-closed-loop-proof/.

## Overall Batch 2 corrections

Updated: 2026-10-07T22:49:13+03:00.

The coordinator made vector/graph retrieval require actual boolean Outcome.success values,
with Python checks as a second boundary. Failed observed outcomes remain useful negative
history. Second-pass recommendation citations and success-rate calculations reject null or
non-boolean outcomes. Backfill selection/write both recheck observed eligibility; its forced
dry-run identified exactly 165 observations. No embedding or outcome-confirmation write ran.

The safety agent supplied deterministic real compiled-graph AFL fixtures, a natural live
read-only rejection/revision proof, and an evidence-integrity correction. Classifier prompts
now state authoritative recorded attempt/event counts, policy values, and timeline scope.
The reviewer hard-rejects clear classifier attempt-count contradictions with correction
feedback before using the model. English retry checks now handle case/hyphen forms; retry
policies were not changed. A second live read-only trace demonstrated truthful two-attempt
counts, real exhausted-budget rejection, feedback, and acceptance of the revised action.

Operator-facing English/Arabic now say recommendation recorded and operational outcome
pending rather than implying execution or immediate precedent. Decisions describes recorded
resolution coverage neutrally and shows unavailable historical rates for an empty observation
denominator. StageCard renders null outcome as pending verification, not failure. The legacy
wire disposition execute remains for compatibility; it is never asserted as completed
authorized physical execution or successful delivery by the revised operator text.
