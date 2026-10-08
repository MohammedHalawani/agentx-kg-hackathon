# GPT-OSS evaluation v1 preparation gate

Timestamp: 2026-10-08T13:25:51+03:00. Status: offline preparation contract passed; actual frozen-bundle fairness review/cloud gate pending.

Command from chat: `.venv/Scripts/python.exe -m unittest discover -s tests -p test_gpt_oss_evaluator.py -v`. Fifteen focused offline harness tests passed, including exact seeded FailureReason/Resolution pair eligibility (an agent resolution cannot inherit eligibility from a seeded failure). No network/model generation or DB writes in these tests. `git diff --check` passes. Root separately confirmed Harmony normalization coverage and the preceding integrated baseline gate.

Preparation readiness and cloud readiness are distinct. The coordinator may prepare the real read-only local bundle now. Before cloud runs, validate that the frozen 30 selected shipments/language/category strata, complete holdout membership, bank evidence and result identity pass independent fairness review. No cloud calls have been made by this evaluator owner. The coordinator owns the eventual paired 60-case run and integrated report, not an assumed model preference.

The controlled benchmark measures synthetic label/action agreement, read-only inference/review/AFL behavior and latency; it cannot claim independent false-acceptance/rejection, real-world success or Arabic explanation quality from canonical action text. Preserve those limitations in final results.

## Actual bundle and execution checkpoint

At 2026-10-08T13:35:00+03:00, independent fairness review and actual immutable bundle
validation passed. All 30 shipment IDs are unique; strata are five per base category and
18 Arabic/12 English inputs. All 1,050 references in 210 banks are observed seeded
failure/resolution pairs, with complete sibling exclusions. Source/provider/input/gold/corpus
identities match. The fresh local graph remains 300 synthetic shipments with an ONLINE
1024-dimension cosine vector index, 165 observed histories and two pending recommendations.

The initial paired case completed on both models with no provider exception, malformed JSON
or declared-shape failure. Both used the actual AFL path and ended in dry escalation; neither
wrote or verified an outcome. These two results are retained as planned benchmark attempts.
The remaining paired execution was started with the same immutable bundle and resumes by
validated result identity. Coordinator integrated Python verification passed all 69 tests.
The 331-file pre-run secret scan passed.

**Overall Batch 3 remains IN PROGRESS.** All 60 planned attempts, independent output-quality
review, before/after graph comparison and the comparison/model-choice report remain required.
Cloud-readiness PASS is not the final evaluation gate. No later product phase is open yet.


## Final closure — 2026-10-08T16:28:44.128094+00:00

**Execution and reporting gate: PASS.** All 30 paired cases completed per model (60 total); no benchmark restart/rerun. All 60 model-blind editorial scores were saved before alias-key reveal. Two AI reviewers split cases and each reviewed both aliases; this is not independent human/SPL adjudication.

20B/120B: base synthetic agreement 13/30 vs 16/30; exact seeded action 7/30 vs 8/30; action-history proxy 17/30 vs 18/30; review accept 24 vs 21; escalate 6 vs 9; AFL 10 vs 11; provider exceptions 0/145 vs 0/149 calls; malformed 0 vs 2 calls (one 120B case, failed closed). Mean latency 28.648s vs 8.537s. Numeric usage available on every call; total reported tokens 228448 vs 216611, not monetary cost.

Blinded total 6.233/10 vs 7.000/10; preference wins 5 vs 19, six ties; ready-to-show 2/30 vs 5/30; critical flags 11/30 vs 8/30. Archived scores include blocked/earlier proposals. Recommend 120B for development and a curated human-reviewed demo. Explicit local 20B selection is preserved.

Before/after evaluation and latest stabilization census match in every non-timestamp field: 300 shipments, 3638 nodes, 4210 edges, 165 observed outcomes, two pending recommendations, 73 unresolved failures and ONLINE 1024-dimension cosine index. Evaluation writers were disabled; no evaluation graph mutation.

See [complete closure](../evals/2026-10-08_gpt-oss-v1/closure.md) and quality-review summary. Failures are categorized there into A model reasoning, B business-rule/prompt, C insufficient graph evidence and D harness/evaluation limits. Synthetic agreement is not production accuracy. Reviewer acceptance is not correctness.

Post-evaluation operator/persistence and prompt fixes are separately tested baseline changes. They do not alter archived scores or establish new model quality. Production readiness and independent false acceptance/rejection remain unestablished. Historical IN PROGRESS statements above are superseded by this closure.
