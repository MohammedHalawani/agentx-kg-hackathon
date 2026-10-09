# Suhail — Batch 1: Fresh Case Runtime (2026-10-09)

Branch `fhd`. No LLM and no automatic actions in this batch.

## What already existed (reused)

- A scenario clock (`OpsControl.as_of`) and an event replay cursor over development-split V2 events.
- A visibility gate: `OperationsReader.evidence(sid, as_of)` keeps only nodes recorded and observed at or before the
  cutoff, and refuses any cutoff ahead of the clock.
- Partitions: history 1,200 (precedent only), development 400 (the live world), held-out 400 (never read).

## What changed

- **Case source mode** on the control node: `dataset` (the previous behaviour, kept for the existing ledger and tests)
  or `monitor` (a live session).
- **New live session** (`POST /simulation/reset`, operator authority required, UI confirmation dialog):
  - Clears only the derived `OpsEntity` ledger for the development split; V2 evidence and precedent are untouched.
  - Rewinds the clock to 1 s before the first development event and pauses the world and the worker.
- **In a live session:**
  - Dataset `Case` nodes are treated as scenario truth and are never seeded.
  - Each replayed observation queues its shipment for a monitor check.
  - Shipments whose `ExpectedMilestone.latest_at + grace` passes during a tick are also queued, so a *missing* scan
    still triggers a check.
- **Monitor** (`monitor_step`, five shipments per runtime-loop second):
  - Builds visible evidence at the clock and runs the existing deterministic `assess_shipment`.
  - Opens a case (`opened_by: MONITOR`, actor `SUHAIL-MONITOR`) only when exceptions exist and the shipment has no case.
  - Healthy shipments progress with no case.
- The scripted GPS review rehearsal never runs implicitly in a live session.
- World speeds 600× and 3600× were added. The Intake "Start world" button uses 600×, i.e. 10 scenario minutes
  per real second. Investigation stages are never paced.
- **UI:**
  - The Live session bar shows the mode, scenario clock and monitor counts, with Start/Pause world and New live session.
  - The pipeline header shows **Live investigation** (queued or running) or **Recorded investigation**.

## Acceptance run (real browser, real Neo4j)

1. A ledger backup was written to `artifacts/ops-ledger-backups/2026-10-09-before-live-session.json`
   (5,489 nodes; not committed).
2. New live session: 0 cases, clock at 2026-09-01 04:59:59.
3. Start world and auto-triage: healthy shipments were checked and no case opened (14 checks, 0 cases in the first hour).
4. The monitor opened cases from visible evidence, for example `BARCODE_MISMATCH` at 07:05 on day 1. That is earlier
   than the dataset's pre-labelled case time.
5. Opening the fresh case SYN-SHP-001241 before triage showed **Live investigation**, with all eight stages Queued.
6. Resuming auto-triage showed Collect ✓ → Graph ✓ → Diagnose ✓ → Precedent ✓ → Recommend ✓ → Review ✓ → Route,
   one at a time from recorded events. Auto focus followed the stages. The label then switched to Recorded, Outcome
   showed Waiting, and the case was routed to HUMAN_REVIEW (delivery dispute).

Tests: Python 193 (new: reset, monitor-only opening, no future leakage, healthy shipments without cases,
no implicit rehearsal, reset authority). Frontend 153. Lint 0 errors. Build OK. `operations_final_audit.py` PASS.

## State left behind

Live session at about 3 Sep 07:50, world and worker paused. Cases: 7 AWAITING_APPROVAL, 2 HUMAN_REVIEW, 1 OPEN.

## Next (Batch 2+)

- Every route still ends at a human gate, because V2 policy requires approval for every recommendation.
- Batch 3: the action-risk policy for automatic low-risk actions.
- Batch 4: outcomes driven by future events.
- Batch 2: the GPT-OSS investigator over these visible-evidence facts.
