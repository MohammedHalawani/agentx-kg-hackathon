# Phase C — case audit report (Composer / route-ui)

**Completed:** `2026-10-13T18:05:00+00:00` (within approved Phase C budget)  
**Code baseline:** `273a21d` on branch `v3/route-ui`  
**Sealed evidence-first notes:** [evidence-first.md](./evidence-first.md)  
**Matrix:** [case-audit-matrix.csv](./case-audit-matrix.csv)

## Executive summary

Independent reconstruction from frozen **`corrected-r1`** neutral packets (handoff **r2**, SHA verified) supports the dataset owner’s integrity claims for all eight development shipments: temporal fences behave as expected, route summaries match observation extrema after correction, `DEMO-PROV-SPL` is present, and seven OPEN operations cases plus one **non-case** control (`DEMO-SHP-000051`) are consistent with the supplement.

**No dataset or Neo4j edits** were made. **No UI code changes** were required for this audit; Phase B adapters already enforce GPS `evidence_id`, observation-based chronology, and vehicle-only semantics aligned with the packets.

**Blockers to READY TO MERGE:**

1. Isolated **authored test catalogue** was **not released / not found** in workspace — comparison appendix is **pending**.
2. **`DEMO-SHP-000226`** legitimately **REVIEW** (in-flight at horizon; no traffic feed nodes).
3. **V2 video shipments** `SYN-SHP-000304` / `SYN-SHP-000443` — **REVIEW / not checked** (no neutral V3 packets).
4. **Live integrated stack** walkthrough on repaired DB was **out of scope** for this worktree (backend merge owned separately).

---

## Input verification

| Check | Result |
|---|---|
| `composer-phase-b-handoff.r2.json` SHA-256 | **Matches** `785ad5857729298701d4ca8eaadbaa6f86e170e51ea9bef2464a4a15a7a8b09f` |
| Per-packet SHA-256 vs r2 / freeze-record | **8/8 match** |
| `freeze-record.json` frozen + gates | **pass** / live parity **24/24** |
| Private expected-outcome catalogue read before seal | **No** |

---

## Map versus graph evidence consistency

| Topic | Finding |
|---|---|
| Route summary timestamps | Final snapshot on all 8 packets: summary first/last **equals** min/max of `route_evidence.observations` (automated check). UI uses extrema + `summaryMismatch` flag (Phase B) — **consistent with corrected data**. |
| GPS markers | Observations carry stable `evidence_id` (e.g. `DEMO-GPS-FD-*`); adapter drops points without IDs. Vehicle-only disclaimer in summary — **does not assert delivery**. |
| Map segments | Playwright `v3-evidence.spec.ts` validates polylines / receipt display against wire fixture derived from **051** packet — **PASS**. |
| Graph scope | `GRAPH_LIMIT = 96` in adapters; shipments **129** (150 nodes) and **134** (192 nodes) exceed cap — UI shows cited subset with total count (by design). **REVIEW** for operator expectation on largest cases, not a data defect. |
| Traffic / hub layers | No `TrafficObservation` nodes in packets (including 226); hub/traffic wire layers not fully exposed in toggles (Phase A discovery) — **presentation gap**, not evidence fabrication. |

---

## Temporal and receipt findings

- **Cutoff fencing:** Demonstrated on anchor scans — e.g. `DEMO-SHP-000133-SCAN-003` (rec `2026-09-16T04:09:37+00:00`) absent when `as_of=2026-09-16T04:09:36+00:00`; `DEMO-SHP-000129-SCAN-003` absent when `as_of=2026-09-14T17:04:20+00:00`, visible when recorded.
- **Occurred vs recorded:** Scan events show normal feed lag (seconds–minutes) except **device-buffer cases** (133/134) with **~12 h** lag — drives monitor delayed-sync narrative.
- **Post-delivery disputes:** Recipient reports on 182/194/222 have `occurred_at` after delivery scans but **before** final horizon — visible in full packet review; investigators at earlier cutoffs would not see them (correct).
- **Route observations:** No `recorded_at < observed_at` violations detected in automated pass on final snapshots.

---

## Unsupported claims and misleading presentation risks

| Risk | Mitigation in evidence / UI |
|---|---|
| Inferring delivery from GPS stop | Summary note + adapter chronology ranks proof/auth above GPS — **low** if UI copy unchanged. |
| Treating photo as authenticated delivery (222) | `DEMO-SHP-000222-AUTH-001` **FAIL** must remain visible beside `PHOTO-001` — adapter ranks auth with photo; **monitor should not auto-close**. |
| Auto-resolve 182 on PASS auth | `REPORT-001` NOT_RECEIVED before `REPORT-002` confirmation — **human escalation** appropriate. |
| 194 delivered-safe | AUTH **FAIL** + NOT_RECEIVED — **escalation**; GPS insufficient. |
| 226 delivered | Status **OUT_FOR_DELIVERY**, no proof — UI must not show delivered closure (data supports this). |
| Graph truncation on 134 | Operators may miss uncited nodes — **REVIEW** UX expectation; not a source defect. |

---

## UI fixes and tests

| Item | Status |
|---|---|
| Code changes | **None** (audit found no packet/UI mismatch requiring a narrow fix) |
| `npm run typecheck` | **Pass** |
| `npm test` (Vitest) | **55/55 pass** |
| Playwright `v3-evidence.spec.ts` | **2/2 pass** |
| Playwright `v3-concurrency.spec.ts` | **1/1 pass** |

---

## Appendix A — catalogue comparison (post-seal)

**Status:** **Pending.** The isolated authored test catalogue described in `docs/v3/08-interface-reference.md` and Phase C prompt was **not present** in `suhail-v3-data`, `suhail-v3-scenarios`, or this repo at audit time. Sol should release it to the integrator channel; Composer will record deltas in a follow-up commit **without editing** [evidence-first.md](./evidence-first.md).

**Preliminary expectation (from sealed notes only, not catalogue):**

| Shipment | Independent operational reading |
|---|---|
| 051 | Normal delivery control; no case |
| 129 | Linehaul / hub delay; eventual delivery |
| 133 | Delayed device sync; eventual delivery with PASS auth |
| 134 | Related device buffering; delivered |
| 182 | Dispute with recipient correction |
| 194 | Failed auth + dispute — unresolved without escalation |
| 222 | Photo + failed auth + dispute |
| 226 | Open route delay / not delivered at horizon |

Any catalogue mismatch will be classified per Phase C prompt (evidence vs UI vs catalogue defect).

---

## Appendix B — V2 references

- **`SYN-SHP-000443`:** Recording map lists graph highlights (e.g. `SYN-SHP-000443-CUST-008`) for demo video B; **not** re-validated against V3 neutral exports.
- **`SYN-SHP-000304`:** No equivalent neutral packet located — **not checked**.

---

## Sign-off

| Field | Value |
|---|---|
| Phase C deliverables | `evidence-first.md`, `case-audit-matrix.csv`, `case-audit-report.md` |
| UI commit (this phase) | *(see git SHA after QA doc commit)* |
| Data defects filed | **None** blocking packet integrity after r2 |
| UI defects filed | **None** requiring code change in this pass |
| **READY TO MERGE** | **NO** — pending authored catalogue comparison, 226 + V2 REVIEW rows, and integrated live signoff outside this worktree |
