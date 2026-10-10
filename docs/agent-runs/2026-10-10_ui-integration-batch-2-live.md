# UI integration, batch 2: live run against a real backend (10 October 2026)

The redesigned interface was run in a real browser against the real backend with a loaded
database. Everything on screen came from genuine API responses.

## URLs (while the scratch backend is running on this machine)

| | |
| --- | --- |
| Redesigned interface | `http://127.0.0.1:8010/app/` |
| Operations | `http://127.0.0.1:8010/app/operations` |
| Decisions | `http://127.0.0.1:8010/app/decisions` |
| Explore | `http://127.0.0.1:8010/app/explore` |
| Audit | `http://127.0.0.1:8010/app/audit` |
| Settings | `http://127.0.0.1:8010/app/settings` |
| A case | `http://127.0.0.1:8010/app/cases/<case id>` (open one from Operations) |
| API (unchanged paths) | `http://127.0.0.1:8010/cases/queue`, `/cases/{id}`, `/audit`, `/explore`, `/schema`, `/worker/status` |

Start it again with the Python of `chat/.venv`, from the UI branch checkout
(`C:\Projects\demo\.ui-integration`), after `npm run build` in `frontend-next`:

```powershell
C:\Projects\demo\chat\.venv\Scripts\python.exe scripts\ui_scratch_backend.py
```

The script always uses `shipments-v2-demo-ui`, runs with the agents off and clears every model
key. The backend on `fhd` still serves the old interface on its own port; nothing there changed.

## The scratch database

- `shipments-v2-demo-ui` did not exist before (checked with `SHOW DATABASES`); it was created
  new. No existing database was modified, replaced, deleted or reset.
- Loaded with the same generator the S5 tests use: 600 synthetic shipments (120 in the operator
  split), import state `COMPLETE`, provider feed loaded as pending.
- The allowlist addition is one commit on the UI branch only (`b9b58a3`): the name was added to
  `OPERATIONS_DATABASES` and to the scratch-name checks of the two live test helpers. Keep that
  commit out of `fhd` when merging. No protection was weakened.
- No GPT-OSS calls were made: the server ran with `SUHAIL_V2_AGENTS=off` and no model key.

The whole 20-day timeline was replayed through real ingestion (17,297 events) and the monitor
opened the cases from that evidence. The rules-only worker then processed some of them. State
at the end of the run: 34 cases (11 queued, 10 human investigation, 5 awaiting approval,
4 rejected, 4 escalated), 449 audit records, a live schema of 72 labels and 275 relationship
types.

## Results

| Check | Result |
| --- | --- |
| Live browser walkthrough against the real backend (`npm run test:e2e:live` with `SUHAIL_LIVE_WRITE=1`) | 7 of 7 passed |
| TypeScript (app and tests), lint | Clean |
| Unit tests | 47 passed |
| Connected browser tests (scripted stand-in) | 8 passed |
| Original lab browser tests, unmodified | 20 of 20 passed |
| Backend `/app/` serving and API route tests | 24 passed (unchanged since batch 1) |

What the live walkthrough verified, each against the API's own response:

- **Operations:** the open count and every row's shipment and state match `GET /cases/queue`.
- **Investigation:** the map draws exactly the backend's corroborated custody points and its
  vehicle telemetry (kept separate); the graph draws real nodes and relationships (48 of the
  case's 98 recorded nodes, stated on screen); the rail follows the recorded stage events.
- **Lifecycle:** "Investigate now" on a queued case ran the backend's real (rules-only)
  investigation and the page followed it to the state the backend recorded. Nothing was shown
  as resolved.
- **Decisions:** a rejection and an escalation were sent from the Decisions screen; the backend
  moved the cases to `REJECTED` and `ESCALATED`, recorded both in its audit ledger, executed
  nothing and recorded no outcome. The decision history shows them from the ledger.
- **Audit, Explore, schema:** audit records are the backend's, Explore lists the queue's cases
  on the map and loads the selected case's graph, and the schema view lists the live labels.
- **Auto switch:** started and paused the real worker; the switch showed the state the backend
  then reported.

Screens from this run are in `frontend-next/screenshots/live-*.png`.

## What the live run changed in the app

1. **Rule output is named as rule output.** With the agents off the backend's stages are
   produced by rules and a deterministic guard. The rail now says "Rule check, not a diagnosis",
   "Rule-derived proposal" and "Deterministic evidence guard (no model review)" instead of
   wording that reads like an agent's finding or an independent review.
2. **A rules-only proposal is shown as not executable.** The backend refuses to approve it
   (`AUTH-22`); the page shows no approve control, the label "Rules-only proposal · not
   executable" and the backend's own reason.
3. **Decision listed twice (bug, fixed).** The case detail and the audit ledger both record a
   decision, on different clocks, so the history showed each one twice. The ledger is now the
   history once loaded; a unit test covers it.
4. **Stale read after an operator request (bug, fixed).** A queue read already in flight could
   be taken as the result of a worker start, leaving the switch wrong for a few seconds.
5. Scanner and driver-app devices are drawn in the graph; a delivered custody point placed at
   its delivery proof is labelled as such.

## What could not be exercised, and why

With the agents off every proposal is rules-only, and the backend correctly makes those
non-approvable. So these were **not** run live:

- an accepted agent diagnosis with hypotheses and citations,
- an operator approval that authorises an execution,
- an execution receipt, the independent verifier's check, and a verified resolution.

They are covered by unit tests and by the browser tests against the scripted stand-in, in the
backend's wire format, but not yet against the real backend. They need an agent run, which
belongs to the backend track's evaluation budget, or a database that already holds
agent-investigated cases opened read-only.

## Remaining API gaps

| Gap | Effect today |
| --- | --- |
| Decision reasons are not stored | The reason field is disabled and says so |
| No served list of allowed decisions per case | Reject and escalate follow the lifecycle table; the backend still enforces every request |
| Audit is served oldest-first with no "after this record" cursor | The ledger is re-read in pages; while the dataset clock is paused every refresh re-reads it |
| Queue has no server-side sort or origin filter | Sorted and filtered in the browser over the loaded, bounded queue |
| Request-evidence, reopen and human-outcome actions | The redesigned UI has no control for them yet |
| Shipments without a case | Explore lists cases only; the 86 healthy shipments are not listed |
| Simulation clock controls | Not in the redesigned UI; the clock was advanced through the API for this run |
| Canopus conversation API | Not connected, by decision |
| New Saudi logistics world | Readable by the backend only after its Stage 2 |

## Next

1. As Stages 2 to 4 are pushed on `fhd`: merge (leaving `b9b58a3` on this branch only) and
   connect what each stabilises.
2. Run the approval, execution and verification path live once agent-investigated cases can be
   served to this branch without spending the evaluation budget.
