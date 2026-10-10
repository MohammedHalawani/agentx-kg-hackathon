# frontend-next: the redesigned Suhail interface, connected to the backend

`frontend-next` is the redesigned Suhail UI (snapshot of `C:\Projects\suhail_ui`, see
`SOURCE_MANIFEST.sha256`) wired to the real Suhail backend. The backend serves the built app
under **`/app/`**. The previous interface in `frontend/` is untouched and still served at `/`
as the rollback.

## Two builds from one codebase

| Build | Command | Data | Where |
| --- | --- | --- | --- |
| Connected (default) | `npm run build` → `dist/` | The Suhail API only | Served by the backend at `/app/` |
| UI lab | `npm run dev:lab`, `npm run build:lab` → `dist-lab/` | Browser fixtures, local timer, scripted assistant | `http://127.0.0.1:5180/` |

The lab build exists for design work and for regression against the original lab. Lab-only
wording in shared components is behind a build-time constant (`LAB_BUILD`), so it is removed
from the connected bundle rather than merely unreachable. The swap is
made at build time (`src/services/lab-entry.ts` is aliased to `src/services/lab.ts` in lab
mode), so the connected bundle contains no fixture cases, no mock service and no scripted
assistant replies. `npm run build` followed by a search of `dist/` for fixture text is part of
the checks.

## Running the connected app

```powershell
cd frontend-next
npm ci
npm run build          # writes frontend-next/dist
# then start the backend as usual; open http://127.0.0.1:8000/app/
```

`npm run dev` starts Vite on `http://127.0.0.1:5190/app/` and proxies API reads to
`SUHAIL_BACKEND` (default `http://127.0.0.1:8000`). Operator controls need the same-origin
build served by the backend: the backend refuses state changes from another origin.

## What is connected

| Screen | Backend source |
| --- | --- |
| Operations queue, counts, Resolved rail | `GET /cases/queue?scope=all` (cursor pages), `GET /worker/status`, case details for resolved cases |
| Auto switch | `POST /worker/start`, `POST /worker/pause`; shows the worker state the backend then reports |
| Investigation: rail, map, graph, assessment | `GET /cases/{id}` (evidence, `route_layers`, `ledger_graph`, `pipeline`, `diagnosis`, `recommendation`, `review`, executions, outcome) and the live `GET /cases/{id}/events` stream |
| Investigate now | `POST /cases/{id}/investigate` (runs the real investigation) |
| Decisions | Pending cases from the queue; `POST /cases/{id}/decision` with `expected_version` and an idempotency key; history from `OPERATOR_DECISION` audit records |
| Verify | `POST /cases/{id}/outcomes` asks the independent verifier to check; there is no success flag |
| Explore | Queue cases joined with `GET /explore` (origin and destination); schema from `GET /schema` |
| Audit | `GET /audit` (cursor pages, then incremental by `from`) |
| Settings | Connection, dataset, clock, worker and operator session as reported by the backend |

Code: `src/api/contracts.ts` (wire types), `src/api/client.ts` (HTTP, session token),
`src/api/adapters.ts` (pure mappings), `src/services/api-operations.ts` (the service),
`src/domain/case-view.ts` (how a case is presented for either data source).

## Rules the connected app follows

- **The backend is the source of truth.** The browser runs no timer that advances a case and
  never marks anything executed, verified or resolved. After every operator request the case is
  re-read from the backend.
- **Only what the backend allows is offered.** Approval is shown only when the case detail says
  `recommendation.approvable`; otherwise the backend's `approval_reason` is shown. Reject and
  escalate follow the backend lifecycle (`chat/operations/lifecycle.py`) and the backend
  re-checks every request. A refused or stale request reloads the case and shows the refusal.
- **Case and shipment identities stay separate.** Routes and API calls use the case id; screens
  show the shipment id.
- **A diagnosis is shown only when the backend accepted one.** Without it the queue shows the
  monitor's observed symptoms and the case shows the backend's reason for the absence. Rule
  signals are not presented as a cause.
- **Findings are attributed.** The case assessment lists the investigator's hypotheses with
  their status and cited evidence. Findings the reviewer did not accept are labelled as claims;
  rule checks are labelled "not a diagnosis". Neither replaces an absent diagnosis.
- **Vehicle GPS is never parcel custody.** Custody markers come from `custody_points`
  (corroborated custody); `vehicle_path` is drawn as vehicle telemetry only; a delivery attempt
  is a recorded attempt at an address reference, not proof of delivery.
- **A receipt is not an outcome; a partial effect is not a resolution.** An outcome is shown
  only when it is verified, not invalidated and belongs to the current cycle; `success` with
  `exception_cleared: false` is not shown as successful. The Resolved rail lists only cases the
  backend reports as `RESOLVED` with such an outcome.
- **Failures are shown, never papered over.** If the backend is unreachable nothing is shown
  and the page says so; if it drops out later, the last read stays, marked as possibly out of
  date. There is no fallback to fixtures.
- **Bounded reads are labelled.** The queue loads up to 1,000 cases and the audit ledger up to
  3,000 events; the graph draws up to 48 of a case's recorded nodes (cited evidence first) and
  states the total.
- **Synthetic data is labelled synthetic** and is not presented as SPL operations.

## Known gaps (need backend work, not faked here)

| Gap | Current behaviour |
| --- | --- |
| Decision reasons are not stored | The reason field is disabled and says so; history shows "Not stored by the backend yet" |
| No served list of allowed decisions | Reject and escalate availability mirrors the lifecycle table; the backend still enforces it |
| Queue has no server-side sort or origin filter | Sorting and filtering run in the browser over the loaded (bounded) queue |
| `request_evidence` and `reopen` decisions, human outcomes | Not offered yet; the redesigned UI has no control for them |
| Audit is served oldest-first only | Loaded in bounded pages, then incrementally |
| Rules-only proposals cannot be approved (`AUTH-22`) | Shown as "Rules-only proposal · not executable" with the backend's reason; approval, execution and verification need an agent-investigated case |
| Canopus has no conversation backend | The floating window opens, states that it is not connected and sends nothing |
| Shipments without a case | Explore lists cases; healthy shipments are not listed yet |
| New Saudi logistics world | Not readable by the backend until its Stage 2; the app shows whatever dataset the backend serves |

## Canopus

`CanopusProvider` takes an optional `CanopusService` adapter (`src/domain/canopus.ts`). The
connected build uses `DisconnectedCanopusService`, which never yields text. Supplying a real
adapter is the only change needed when the Canopus API exists; the conversation, citation,
retry and scrolling components are unchanged from the lab.

## Tests

| Check | Command |
| --- | --- |
| TypeScript | `npm run typecheck` |
| Lint | `npm run lint` |
| Unit (adapters, service, original lab units) | `npm test` |
| Connected app in a browser, against a scripted backend stand-in | `npm run test:e2e` |
| Original lab browser suite on this codebase (visual and behavioural regression) | `npm run test:e2e:lab` |
| Backend serves `/app/` and keeps its API routes | `pytest chat/tests/test_frontend_next_mount.py` |
| Read-only check against a running backend | `SUHAIL_LIVE_URL=http://127.0.0.1:8010 npm run test:e2e:live` |
| Full walkthrough with real operator requests (scratch database only) | add `SUHAIL_LIVE_WRITE=1`; backend from `scripts/ui_scratch_backend.py` |

Only the live suite (`test:e2e:live`) exercises the real backend over HTTP. The "connected"
suite is a stand-in: the browser's requests are answered by a route mock in the tests.

The scripted stand-in (`tests/e2e-backend/backend-stub.ts`, `tests/fixtures/backend.ts`) answers
HTTP in the backend's wire format for tests only; the application never imports it.
