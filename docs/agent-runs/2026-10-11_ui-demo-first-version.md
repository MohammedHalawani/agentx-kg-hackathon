# Redesigned UI: first version for the demo milestone (11 October 2026)

One shipment exception was investigated by the real GPT-OSS 120B investigator from the redesigned
interface, and the interface showed what it did from the backend's own run record. The simulated
execution and the independent verification are not shown yet: the scratch database has no
execution simulator, so the authorized action was not carried out. That part needs the backend
track's Stage 4 and its demo database.

## URL

`http://127.0.0.1:8010/app/` while the scratch backend runs. Start it from the UI branch checkout
(`C:\Projects\demo\.ui-integration`) after `npm run build` in `frontend-next`:

```powershell
# real investigator (every "Investigate now" makes real GPT-OSS calls, capped at 12 per case)
$env:SUHAIL_UI_AGENTS = "on"; C:\Projects\demo\chat\.venv\Scripts\python.exe scripts\ui_scratch_backend.py
# without the model (rules only, no model calls)
C:\Projects\demo\chat\.venv\Scripts\python.exe scripts\ui_scratch_backend.py
```

It uses the database `shipments-v2-demo-ui` (set `SUHAIL_UI_DATABASE` to point it at the demo
database once that is named). It is stopped between runs to keep load off the shared Neo4j.

The case investigated: `http://127.0.0.1:8010/app/cases/SYN-OPS-CASE-d40c08ea417e4b44a29aed26`
(shipment `SYN-SHP-000567`, Jubail to Jeddah).

## What happened in the real run

Started with "Investigate now" in the interface. 6 model calls of a cap of 12.

1. The monitor had opened the case from one symptom: a barcode read that differed.
2. The investigator chose two evidence queries: the shipment overview, then the package's scans
   (24 records). While it ran, the pipeline rail showed each query as it was recorded
   (`screenshots/model-investigating.png`).
3. It concluded a scanner misread at the sorting facility (primary cause barcode mismatch), with 11
   of 11 citations valid.
4. The independent model reviewer accepted it.
5. The authority policy classed the recommended rescan as automatic (`AUTH-10-auto-allowlist`).
6. The action was dispatched, but this database has no execution adapter, so it was recorded as
   not acknowledged. Nothing was carried out, nothing was verified, and the backend sent the case
   to a person. The interface shows exactly that and does not show it as executed or resolved.

Screens: `frontend-next/screenshots/model-investigated.png`, `model-assessment.png`,
`model-steps.png`.

## What is new in the interface

- **How Suhail investigated.** The case assessment lists every evidence query the investigator
  chose, in order, with its stated purpose, how many records it returned, a cross-shipment tag when
  the records come from beyond this shipment, and a failed query shown as a failure rather than as
  absence of evidence. It also shows model calls used against the cap and how many citations are
  valid.
- **Live tool calls.** During an investigation the rail's Diagnose stage shows the investigator's
  current query as the backend records it.
- **Reviewer, round by round.** The independent reviewer's verdict and feedback per round, its
  unsupported claims and unaddressed contradictions, and any deterministic check that did not pass.
- **Authority policy.** The policy's class, rule and reason for the recommended action, stated as
  decided by the backend.
- **Record a person's finding.** For a case waiting for a person, a dialog sends the finding, its
  type and the evidence it refers to, to the existing human-outcome endpoint. The backend records
  it as human-verified and decides the state; "parcel not found" does not resolve the case.
- **An action nobody carried out is not shown as carried out.** A not-acknowledged execution is
  shown as such.
- **Long assessments scroll.** With real content the side sheets were clipped below the fold; they
  now scroll.

Everything listed comes from fields documented in `docs/api/investigation-run.md` and
`docs/api/case-detail.md` on `fhd`. Nothing is composed in the browser.

## Lifecycle states: where each stands

| State | In the interface | Checked against |
| --- | --- | --- |
| Queued | Shown; "Investigate now" offered | Real backend |
| Investigating, live stages and queries | Shown live from the event stream | Real backend, real model |
| Diagnosis, hypotheses, citations | Shown when the reviewer accepted; labelled when not | Real backend, real model |
| Recommendation with authority level | Shown with the policy's rule and reason | Real backend, real model |
| Awaiting approval, approve | Shown; approval sent with version and idempotency key | Scripted stand-in only |
| Reject, escalate | Shown and sent | Real backend |
| Executing, execution receipt | Shown; a receipt is never an outcome | Stand-in; real backend only for the not-acknowledged case |
| Verifying, "ask the verifier to check" | Shown and sent | Scripted stand-in only |
| Verified, or verification failed | Shown; only a verified, current, cleared outcome counts | Scripted stand-in only |
| Human investigation, a person's finding | Shown; dialog sends the finding | Unit test and stand-in only |
| Resolved queue | Lists only verified resolutions | Real backend (empty there), stand-in |

## Gaps

| Gap | Needs |
| --- | --- |
| Simulated execution and independent verification on an agent-investigated case | Stage 4 and the demo database with an execution simulator |
| Approval of an agent recommendation, then execution, shown live | A case whose policy class is approval-required, on the demo database |
| A person's finding, sent to the real backend | A live run; the endpoint exists today |
| Request evidence, reopen | No control in the redesigned UI yet; the endpoints exist |
| Cited records of other shipments are counted and tagged but not drawn in the graph | A decision on showing `cited_external_records`; the data is served |
| Decision reasons | Not stored by the backend |
| A list of allowed decisions per case | Not served; the UI mirrors the lifecycle table |
| Canopus | No conversation backend, by decision |
| The demo cases themselves | The 3 to 5 cases and their database, from the backend track |

## Checks

| Check | Result |
| --- | --- |
| TypeScript (app and tests), lint | Clean |
| Unit tests | 52 passed |
| Connected browser tests (scripted stand-in) | 9 passed |
| Real investigation through the interface (real model, scratch database) | 1 passed, 6 model calls |
| Original lab browser tests, unmodified | 20 of 20 passed |

Not rerun for this version: the rest of the live suite (read-only check, walkthrough, agent-path
specs) and the backend route tests.

## Branch

`claude/project-thread-unq829`. It now contains `fhd` up to `82f19ac` (Stages 2 and 3). The UI
scratch database's allowlist entry lives in `chat/operations/datasets.py` on this branch only.
