# GPT-OSS evaluation v1 audit

Timestamp: 2026-10-08T13:25:51+03:00. Batch 2 integrated gate passed before evaluation preparation. No new product feature or production prompt/rule change in this batch.

The old eval_pipeline.py is a small legacy smoke and incorrectly describes seeded random histories as human labels. The new benchmark stands separately. Root's current evidence audit confirms six supported base categories and 165 observed seeded failure histories; some event projections are structurally indistinguishable after own labels are withheld. Escalation shipments can carry sibling failures sharing an action, so holding out only the selected failure ID is insufficient.

Required design: 30 distinct shipments, five per supported cause, 18AR/12EN identical case-language inputs across both models, frozen first evidence and predicted-category second-pass banks, all held-out shipment siblings excluded, independent runtime/gold files, no writeback, real reviewer/AFL rules, full planned denominators and explicit proxy limitations. Protocol reviewed and implementation/readonly prepare authorized; cloud runs await actual harness fairness review.


## Final closure — 2026-10-08T16:28:44.128094+00:00

**Execution and reporting gate: PASS.** All 30 paired cases completed per model (60 total); no benchmark restart/rerun. All 60 model-blind editorial scores were saved before alias-key reveal. Two AI reviewers split cases and each reviewed both aliases; this is not independent human/SPL adjudication.

20B/120B: base synthetic agreement 13/30 vs 16/30; exact seeded action 7/30 vs 8/30; action-history proxy 17/30 vs 18/30; review accept 24 vs 21; escalate 6 vs 9; AFL 10 vs 11; provider exceptions 0/145 vs 0/149 calls; malformed 0 vs 2 calls (one 120B case, failed closed). Mean latency 28.648s vs 8.537s. Numeric usage available on every call; total reported tokens 228448 vs 216611, not monetary cost.

Blinded total 6.233/10 vs 7.000/10; preference wins 5 vs 19, six ties; ready-to-show 2/30 vs 5/30; critical flags 11/30 vs 8/30. Archived scores include blocked/earlier proposals. Recommend 120B for development and a curated human-reviewed demo. Explicit local 20B selection is preserved.

Before/after evaluation and latest stabilization census match in every non-timestamp field: 300 shipments, 3638 nodes, 4210 edges, 165 observed outcomes, two pending recommendations, 73 unresolved failures and ONLINE 1024-dimension cosine index. Evaluation writers were disabled; no evaluation graph mutation.

See [complete closure](../evals/2026-10-08_gpt-oss-v1/closure.md) and quality-review summary. Failures are categorized there into A model reasoning, B business-rule/prompt, C insufficient graph evidence and D harness/evaluation limits. Synthetic agreement is not production accuracy. Reviewer acceptance is not correctness.

Post-evaluation operator/persistence and prompt fixes are separately tested baseline changes. They do not alter archived scores or establish new model quality. Production readiness and independent false acceptance/rejection remain unestablished. Historical IN PROGRESS statements above are superseded by this closure.
