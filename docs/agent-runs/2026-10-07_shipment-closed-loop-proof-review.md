# Shipment closed-loop proof — review

Timestamp: 2026-10-07T22:46:55+03:00. Review: **PASS**.

The write boundary now checks review acceptance/score, nonempty final action, consistent
extraction/local/context IDs, and the actual database Shipment→Event→FailureReason link.
Unresolved-only creation plus compatible-only replay prevents seeded or pending chains from
being replaced, appended to, or credited to a different recommendation. Stable IDs alone
would not prevent concurrent first writes without a constraint; the temporary node lock
precedes the existing-chain check and was exercised by concurrent frozen-state replays.
Both lock properties are removed within their transactions and no unrelated nodes are updated.

UTC timestamps and source/shipment/failure provenance distinguish this accepted decision from
seeded history. Agent review is explicitly labelled agent_review, not operator approval.
Outcome.success remains logically null (Neo4j omits null-valued properties), status remains
pending, and notes state that execution is unconfirmed. No delivery state, route, or actual
outcome is inferred. The legacy pipeline disposition string execute means recording the
reviewed recommendation here; final proof explicitly sets execution_confirmed=false.

Canonical final fields were checked against captured evidence: address_conflict is the live
failure category; retry budget is exhausted; the selected address-confirmation/redirection
action has two same-category observed citations, both success=true, so its stated 2/2
historical success rate is supported. Review accepted at 0.92. There is no fabricated delivery
attempt count in this final rationale. The separate AFL proof preserves the earlier model
counting issue and its deterministic rejection guard; it is not hidden by this successful run.

Before/after comparison found exactly two new nodes and two new edges, no removals, and only
the selected existing FailureReason gained derived case_summary. SHP-0227's legacy pending
chain is byte-for-field unchanged in the captured snapshots. Shipment.status is still FAILED.
Pending recommendations stay visible as attention cases and observed precedent remains 165.

Six write-boundary fixtures and the then-current full 42-test suite passed. Both fixed write
queries passed live EXPLAIN without execution. The live replay reused the same frozen state;
it did not rerun model stages or create another recommendation. No seeded data reset,
embedding backfill, outcome confirmation, dependency change, commit, or push occurred.

## Overall Batch 2 review

Updated: 2026-10-07T22:49:13+03:00. The independent semantics review and coordinator's
observed-precedent correction agree: recorded recommendation, observed result, and successful
delivery are separate facts. Pending recommendations remain operational attention cases,
never enter the historical rate numerator/denominator, and now cannot ground new citations
or become embedding-backed observations. Existing failed observations remain eligible.

Six deterministic AFL fixtures exercise actual LangGraph routing, reviewer hard rules,
feedback entering the second classifier prompt, revised diagnosis/action, retry cap,
missing grounding, and accepted-but-unavailable write escalation. They stub models and writes
and do not claim natural model behavior. The first separate natural live SHP-0017 proof
(53.76s) demonstrated model reject→feedback→accept but exposed 4/3 versus 2 attempt counts.
Its original artifact remains preserved and annotated. The corrected live read-only proof
(49.32s) showed authoritative two-attempt counts and an actual retry-budget rejection before
revision/acceptance. Neither read-only run wrote or confirmed an outcome.

Limits remain explicit: count matching is targeted to clear classifier rationale claims,
not a universal natural-language evidence checker. The corrected live trace still used an
imprecise exceeds-versus-equals comparison and SLA wording. Recommendation/reviewer prose,
contradictions, temporal fidelity, and external observation provenance require serious
evaluation. This small proof is not a model benchmark or SPL performance measurement.

The UI review passed 13 StageCard/Decisions tests plus TypeScript/Vite build and lint; baseline
warnings remain. The operator text does not substitute for a future human approval/execution
handoff/outcome-confirmation feature. Those later capabilities were not added in Batch 2.
