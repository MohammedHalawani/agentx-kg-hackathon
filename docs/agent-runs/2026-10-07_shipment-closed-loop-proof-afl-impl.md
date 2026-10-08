# Closed-loop AFL implementation

Timestamp: 2026-10-07T22:37:51+03:00.

Added chat/tests/test_afl_state_machine.py. The fixture executes the real compiled LangGraph, entity extraction, final JSON normalization, classifier, second retrieval/fusion, recommender, business rules, reviewer and graph routing. Only external I/O is mocked: final provider JSON, read retrieval, case-file fetch and writeback. No production business rule or pipeline node was altered.

In-memory SHP-9001 has two attempted deliveries against retry_limit=2 and distinct address versions. The first scripted recipient-unavailable diagnosis proposes a retry citing matching verified history. The real deterministic reviewer rejects it. Its actual rejection feedback enters the second classifier prompt, which revises the diagnosis to address_conflict; a customer-confirmation/redirect recommendation cites matching precedent and the scripted final review accepts. The mocked decision write is explicitly distinguished from any real action or observed success.

Additional scenarios cover persistent retry rejection reaching the cap, missing grounding skipping classification, no citations, category-mismatched citations, and acceptance followed by unavailable writeback escalating.

Saved sanitized machine-readable artifacts:

- 2026-10-07_shipment-closed-loop-proof-afl-fixture.json: corrected acceptance, bounded escalation and missing-grounding traces; proof type explicitly deterministic and I/O mocked.
- 2026-10-07_shipment-closed-loop-proof-afl-live-readonly.json: actual 20B model classification/recommendation/review, feedback and retry; no writeback.
