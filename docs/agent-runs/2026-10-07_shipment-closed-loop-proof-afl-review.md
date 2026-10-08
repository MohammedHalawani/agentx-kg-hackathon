# Closed-loop AFL review

Timestamp: 2026-10-07T22:37:51+03:00.

Review confirms the fixture's initial rejection comes from the real retry-budget rule, bypassing the reviewer model. Matching citation and category guards remain in place. The second prompt receives the exact first rejection and attempted action; accepted routing calls writeback once. Persistent hard rejects never call the reviewer model, never call resolution writeback, and escalate once after MAX_LOOPS. Missing precedent stops before classification. Artifact output is projected application stage fields only; private provider fixture metadata is absent.

Natural live SHP-0017 proof uses the configured openai/gpt-oss:20b with actual retrieval and model calls. The first proposed warehouse/courier coordination was rejected at score 0.30 because it omitted customer address confirmation. After feedback, the recommendation changed to confirming the correct customer address and redirecting, and review accepted at 0.92. Root cause stayed address_conflict, which is an acceptable reconsideration: the action changed. The live stages were invoked directly without writeback; full compiled routing is separately covered by the fixture.

Material quality limitation: live classifier summaries counted failed attempts as four initially and three on retry; the read-only operational evidence contains two. This is a final evidence-summary hallucination, not private reasoning exposure. The proof therefore establishes real rejection/reconsideration, not fully accurate diagnosis evidence or operational success. Include this fidelity issue in serious model evaluation and demo selection. No claim is made that the accepted action succeeded in the real world.
