# Composer Phase C — Independent case evidence and storyline QA

Continue the SAME Composer thread and `v3/route-ui` worktree at `C:\Projects\suhail-v3-route-ui`. This follows Phase B and precedes final integration signoff. The user explicitly approved this addition on 13 October 2026. The API contract stays frozen at `suhail-v3-1`; no new branch, dataset manipulation or paid model calls are authorized.

## Scope and hard budget

Review EVERY curated V3 development shipment, approximately 6–10, and original video reference shipments `SYN-SHP-000304` and `SYN-SHP-000443` where actual evidence is available. Do not audit hundreds of shipments. Full-dataset automated structural validation belongs to Sol.

Reserve a hard FOUR HOURS during hours 48–60 of the existing schedule: 15 minutes for packet inventory; up to 12 minutes per case/reference (12 total maximum = 144 minutes); 20 minutes for later catalogue comparison; 35 minutes for matrix/defect handoff; 26 minutes for one affected-case retest/buffer. At the limit, report incomplete coverage as REVIEW and escalate to the integrator; do not silently expand scope or skip a curated case and mark overall PASS. No new features after hour 48.

Use the same worktree/thread; own only your existing UI files plus `docs\v3\case-qa\evidence-first.md`, `case-audit-matrix.csv`, `case-audit-report.md`. These are QA outputs, never runtime evidence. Dataset records, generation, source metadata, test expectations and expected diagnoses are read-only to you.

## Evidence-first protocol

1. Receive Sol's neutral packet manifest: exact shipment/case/source IDs, dataset/hash, actual node/edge records, relevant before/after receipt cutoffs and allowed tool snapshots. It must exclude scenario family, intended diagnosis, desired action, expected outcome and scoring truth. Do not open the isolated test catalogue, historical evaluation gold or private physical state.
2. For each shipment, reconstruct chronology from actual occurred_at/recorded_at/ingested_at and provider source records. Distinguish missing-at-cutoff from never recorded. Check the same earlier snapshot after later ingestion for improper backdating.
3. Trace shipment→package→custody and driver/device/assignment/route/trip/GPS relationships using real edges and source IDs. Plans/manifest membership do not prove loading. Vehicle GPS does not locate/deliver a parcel. Missing edges/coordinates stay missing.
4. Check permitted investigator access using deterministic read-only tool invocations or captured tool results at the stated cutoff; verify source IDs, scope, rendered/citable sample and reviewer-accessible evidence. No live GPT-OSS run is needed. Do not start a backend merely to obtain records without the integrator's exact V3 target check.
5. Compare graph, route map and timeline at the SAME declared source cutoff. If UI follows a later live clock than the saved run, label that difference and verify later records are not presented as earlier investigator evidence. Cross-select exact source IDs; compare vehicle context, custody, planned connection, observed samples and receipt chronology.
6. Record contradictions, missing/implausible/fabricated evidence and alternative explanations BEFORE inspecting authored expectations. Separate what is directly observed from inference and uncertainty. A neutral route stop or strong proof does not eliminate every competing explanation.
7. Write your initial evidence-first conclusion, missing evidence and the operational actions/escalation/verification that the visible facts can support. Then inspect the stored investigator recommendation/review/authority/outcome as an ACTUAL system result, clearly separate from your conclusion. This is not an expected answer.
8. Finalize ALL first-pass notes, with timestamp and input hashes; send the integrator that immutable snapshot or commit SHA. Sol then releases the isolated authored test catalogue for comparison. Never edit the first-pass notes to match the catalogue; add a separate comparison section/delta. Do not read hidden evaluation answers at this step.
9. Classify mismatches: evidence defect, UI defect, tool-access defect, action/verification problem, catalogue expectation defect or legitimate ambiguity. Intended outcomes can be wrong; do not force a preferred diagnosis or a resolved state.
10. Produce the concise matrix and route each defect to its owner. Sol corrects data and supplies a new immutable fixture/hash; you correct UI only. Integrator/Opus handle concurrency/lifecycle defects under frozen ownership. Recheck affected rows only after a reviewed repair; retain original findings.

## V2 reference checks

Use only available read-only source snapshots or explicitly read-only queries of the protected V2 evidence. Do not start/stop/reset the V2 app, replay its feed, invoke its investigator, seed a take, rerun a video or modify recorded files. If querying the V2 database, use a read-only session without operations-runtime initialization. If evidence is unavailable, mark reference coverage `NOT CHECKED — evidence unavailable` in the notes and REVIEW in the three-state matrix; do not reconstruct source facts from the movie or its explanatory diagnosis notes. Keep V2 and V3 dataset IDs distinct. Reference outcomes are not a V3 answer key.

## Required concise matrix

One row per curated shipment and available/unavailable video reference:

```text
CASE / SHIPMENT ID | DATASET / HASH | CUTOFFS | CHRONOLOGY |
RELATIONSHIPS / GPS | TOOL ACCESS | GRAPH / MAP / TIMELINE |
ALTERNATIVES / GAPS | ACTION / VERIFICATION SUPPORT |
SOURCE IDS | FIRST-PASS NOTE / HASH | CATALOGUE DELTA |
PASS / REVIEW / FAIL | DEFECT OWNER / NEXT ACTION
```

PASS: reconstructable and time-correct evidence, source/relationship/tool/view agreement, defensible operational outcome or legitimate human/insufficient-evidence state, no blocking defect. PASS is evidence-integrity QA, not an accuracy claim.

REVIEW: genuine uncertainty, missing source/reference availability, an unresolved noncritical discrepancy, incomplete review at the time limit or a catalogue expectation requiring Sol's assessment. Legitimately ambiguous cases can pass when the system represents their uncertainty safely; REVIEW is not automatically a wrong diagnosis.

FAIL: fabricated/contradictory impossible records, temporal/split leak, invalid cited source, graph/map/timeline materially disagree, tool cannot retrieve required permitted evidence, GPS falsely proves parcel custody/delivery, or operational action/verification unsupported by visible records.

Cite concrete source IDs and cutoffs for every defect; do not fill them with invented examples. A curated-case FAIL blocks signoff until fixed/reviewed; removing the case to conceal a failure is prohibited. A REVIEW needs explicit integrator disposition, not automatic acceptance. If all curated cases cannot be covered in four hours, escalate the coverage gap without rewriting the architecture or broadening testing.

Deliver original evidence-first notes, matrix, catalogue comparison, owners, retest status and exact elapsed time to Fable and Sol through the user's distribution channel. Use the existing checkpoint template. No new thread/branch and no paid inference.
