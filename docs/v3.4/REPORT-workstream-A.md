# Suhail V3.4 Workstream A: anomaly detection quality, final report

Date 2026-10-16. No model calls were made in this workstream (detection is deterministic). Audit: `docs/v3.4/anomaly-audit.md`.

## Branch and SHAs

- Worktree `C:\Projects\suhail-v34-anomaly`, branch `v3/v34-anomaly-detection` (local only, not pushed or merged).
- Base `1ff6518e081c99647a9ed8e1d5eb787ca501c1a4` (tree `b4ead6d8`). Head `d62604993c682bf156fdf80ca3cf5ab7871e4a49` (tree `058fae94`).
- Commits: `1c224cd` monitor detection record, alert state, watch and overview API; `68a634d` Operations overview line; `721c8b4` brief states the detection evidence; `d626049` brief wording. 15 files, +1,119 / -13.
- Not touched: v3/integration, fhd, main, the Workstream B worktree, the combined preview (8023 and 5190 answered 200 at the end), the demo/frozen/CI/race/lanes databases.

## Detector changes

The 15 detection rules and their thresholds are **unchanged**. The audit found detection already deterministic, evidence-driven and time-aware, so the changes record and explain what it finds:

1. **Why a case was detected** (`operations/detection.py`, `OpsCase.detection_json`). Each case stores the rules that fired, with their reasons and evidence ids. It also stores the milestone compared: step, expected facility, deadline including grace, the observed time when late, and whether that milestone is the delivery promise. Differing barcode or weight reads are kept, as is the last corroborated custody holder. GPS is never parcel position. This is computed from visible evidence at the monitor clock, with no cause and no truth. It is served as `detection` in the case detail and written into the CASE_OPENED and SYMPTOMS_UPDATED audit text.
2. **Whether the alert still stands** (`monitor_alert_state` ACTIVE / PARTLY_CLEARED / CLEARED, with an audit entry for each change). The workflow never moves, the case is never closed, no outcome is written and `is_resolution` is false. The investigation, reviewer, authority and verifier are untouched.
3. **Per-shipment watch state** (`OpsMonitorWatch`) and **`GET /operations/monitor/overview`**. It returns shipments booked and monitored, with and without an active exception, cases by stage, alerts cleared or partly cleared, and verified resolved, with definitions in the response.
4. **UI**:
   - One line under the Operations title, in English and Arabic: monitored, no active exception, awaiting investigation, investigating, action pending, with a person, verified resolved, and alerts cleared by later evidence (labelled not resolved and not verified).
   - The case brief's Problem and What happened lines now state the monitor's evidence in plain words. For example: "the promised delivery was due by 2026-09-17 17:00 UTC and has no confirmed record; the last confirmed custody is with a delivery depot SYN-DEPOT-JED-01".

## Measured positive/negative results

The ground truth is the generator's external truth rows. They are read only after detection, by the evaluation script, and never by runtime code.

| Run | Healthy opened | Abnormal opened | Cases | Notes |
|---|---|---|---|---|
| Offline replay (`scripts/v34_detection_eval.py`, 17 clocks, 12 h apart) | 0 / 60 | 40 / 42 | 40 | median 0.8 h from cause knowable to opening |
| Real Neo4j, real gateway and monitor, hour by hour 09-13 21:00 to 09-21 21:00 (`artifacts/v34-anomaly/anomaly_db.py replay`) | 0 / 60 | 40 / 42 | 40 | the same 40 shipments; 4 opened 1 to 3 h later (tick boundaries); 2,078 checks, 22 min |

At the horizon on real Neo4j, all 102 live shipments were monitored:
- 62 had no active exception and 37 had an active exception.
- On 3 cases the alert cleared on later evidence: 133 and 134, where the offline device's buffered custody uploads arrived, and 207. On 12 cases it partly cleared, mostly an overdue delivery that later arrived late.
- There were 0 runs, 0 outcomes and 0 verified resolutions.

The panels cover Fahad's A3 list:

| Panel | Result |
|---|---|
| Delivered with valid proof | 69; the 12 opened all carry another visible discrepancy |
| Failed attempt then return to depot | 26; 21 opened (overdue delivery or recipient unavailable); no rule asserts loss |
| Late device upload | 19 shipments with 34 buffered records; judged on event time once ingested; alerts cleared |
| Bulky | 2; no weight case |
| Recipient dispute | 4/4 opened as human-review disputes |
| Tracking says delivered, no corroboration | 5/5 opened |
| No scan yet, nothing due | 0 findings |
| GPS missing | cannot affect detection (never read) |

Misses, documented and not "fixed":
- **000239 (backlog):** met every milestone, so there was no observable deviation.
- **000131 (wrong address):** one address-not-found attempt, then redelivered within the promise. A rule for it would also open the 4 healthy shipments that have similar failed attempts.

## Dataset

Unchanged. The generator, randomness, distributions, size and schema were not altered. The delivery promise already equals each package's DELIVERED milestone deadline (135 of 135), so no new contract was needed. The only new graph records are ledger records in disposable databases.

## Tests

| Suite | Result |
|---|---|
| New `tests.test_v34_detection` (pure rules, a live in-memory monitor over the V3 test world, brief wording) | 10/10 |
| Monitor-adjacent modules (store, reinvestigation, leakage boundary, world simulation, demo session, narration, reset, approval recheck, reviewer doubt, rescan target, brief, canopus, showcase) | all pass (149 + 50 reruns) |
| Full offline backend suite | 949 run, 871 pass, 28 skipped, 50 fail or error. All 50 are in the provider and inference modules (provider gate, transport, model-call timeout, LLM safety, GPT-OSS evaluator, AFL, evidence integrity), and they fail identically on the unchanged 1ff6518 in the same environment. They need the inference budget settings or a fresh ledger that this runner did not set. Not caused by this branch. |
| Frontend | 101/101 unit tests (2 new); typecheck, lint, build pass |
| Real-Neo4j race and action gate (committed V3 race and V3.2 action modules, run on new disposable `shipments-v2-world-v34-anomaly-race-20261016`; the only change was the harness TARGET constant, in an artifacts copy) | **14/14 OK** (37 min; target empty before the run) |
| Browser | backend on 8026 against the disposable DB serving this branch's build: the overview line shows the counts above; the case page Problem line shows the deadline and last custody |

## API and frontend compatibility

Additive only:
- New optional case-detail fields: `detection`, `monitor_alert`.
- New endpoint: `/operations/monitor/overview`.
- New ledger kind: `OpsMonitorWatch`, cleared by the development reset like every other `OpsEntity`.
- No existing field, state or endpoint changed.

On a database whose cases predate this branch, a case reads as alert ACTIVE with `detection: null` until the monitor re-checks its shipment. The brief text then gains the evidence sentence.

## Untested

- The full end-to-end flow with GPT-OSS investigations after these changes (no paid calls in this workstream). The investigator prompt is unchanged.
- Playwright end-to-end suites.
- A merge with Workstream B. Both edit `store.py` in different regions, so a textual conflict is unlikely, but it is not checked.

## Expected demo impact

Operations can now say "102 monitored · 62 no active exception · 40 awaiting investigation …", so a healthy shipment visibly passes monitoring without a case. A case opened for a missed deadline states which step, where, by when and who last held the parcel. An offline-device case visibly records that its alert cleared, without claiming a resolution.

READY FOR INDEPENDENT REVIEW: YES
