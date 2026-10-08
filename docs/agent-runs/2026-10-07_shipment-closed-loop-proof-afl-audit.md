# Closed-loop AFL audit

Timestamp: 2026-10-07T22:37:51+03:00.

Scope: reviewer reconsideration and bounded state-machine routing. Database inspection used read-only queries after confirming local localhost/127.0.0.1 Neo4j and the shipments database. Existing policies contain genuine exhausted-retry cases: SHP-0017 has two attempts/limit two; SHP-0173 and SHP-0269 have two attempts/limit one; SHP-0201 has two attempts/limit two. No synthetic graph was edited to force a rejection.

Production reviewer.py first applies deterministic retry-budget, absent-citation, and category-mismatch hard rejects, then asks the model for remaining judgement. graph.py sends rejection notes and attempted actions back to classification, caps rejected cycles at MAX_LOOPS=2, and escalates when no precedent is present. A failed accepted write also escalates. These guards remain unchanged.

A natural live read-only SHP-0017 attempt was available and actually rejected. A separate deterministic full compiled-graph fixture is still needed to prove routing and repeatable guards; its scripted model answers must not be presented as live model behavior.
