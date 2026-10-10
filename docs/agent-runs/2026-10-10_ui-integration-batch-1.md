# UI integration, batch 1 (10 October 2026)

The redesigned Suhail interface is in the real project as `frontend-next/`, reads the Suhail
backend, and is served by the backend under `/app/`. The previous interface is untouched at `/`.

## Where it is

| | |
| --- | --- |
| Branch | `claude/project-thread-unq829` (pushed), based on fhd `a71829f` |
| Commits | `a189c67` verbatim snapshot of the UI lab · `e15ff06` backend serves `/app/` · `3ad6360` connected UI |
| Working copy | A separate clone at `C:\Projects\demo\.ui-integration`; the fhd checkout was not edited |
| App URL | `http://127.0.0.1:8000/app/` after `cd frontend-next; npm ci; npm run build` and starting the backend |
| Rollback | The old `frontend/` and its mount at `/` are unchanged; removing `frontend-next/dist` turns `/app/` into a 404 |

`C:\Projects\suhail_ui` was not modified. The snapshot commit is a byte-for-byte copy of its 144
source files with a SHA-256 manifest (`frontend-next/SOURCE_MANIFEST.sha256`) verified against
the original at copy time.

## Checks and results

| Check | Result |
| --- | --- |
| TypeScript (`npm run typecheck`, app and tests) | Passed, no errors |
| Lint (`npm run lint`) | Passed, no warnings |
| Build (`npm run build`, connected) | Passed. The bundle was searched for fixture text and mock code: none present |
| Build (`npm run build:lab`) | Passed |
| Unit tests (`npm test`) | 44 passed: 16 original lab tests, 11 adapter tests, 17 backend-service tests |
| Connected app in Chrome (`npm run test:e2e`) | 8 passed, against a scripted stand-in that answers in the backend's wire format |
| Original lab browser suite on the integrated code (`npm run test:e2e:lab`) | 20 of 20 passed, specs unmodified |
| Backend: `/app/` serving and API routes (`pytest chat/tests/test_frontend_next_mount.py` with the API and authority tests) | 24 passed |
| Backend suite on this branch, without the Neo4j-backed tests | 386 passed, 11 deselected, 0 failed |
| Real backend from this branch on port 8010 (`npm run test:e2e:live`) | Passed: `/app/` and deep links served, API routes kept their paths, and with operations unavailable the app showed its offline state and no cases |

Not yet done: a browser run against a real backend with a loaded database. Starting the
operations runtime writes to its database and starts its workers, so it needs a scratch
database name this track may use. The live check that ran pointed the backend at a dead
database port, touched no database and made no model calls.

## How the screens were confirmed against the original

1. The original lab's 20 browser tests ran unmodified against this codebase built in lab mode
   and all passed: filters, pagination, map and graph linking, approval and rejection flows,
   automatic investigation, Explore, Audit, Canopus, Arabic, dark mode, mobile.
2. That run regenerates the lab's 26 reference screenshots. Compared pixel by pixel with the
   originals (`node scripts/compare-screenshots.mjs`): 12 files are byte-identical, 10 differ
   in under 0.1% of pixels, and 4 differ by 2% to 38%. I looked at the largest (Explore, dark)
   and the investigation one side by side: the differences are OpenStreetMap tiles still loading
   and a list still scrolling at capture time, not layout, components or styling.
3. The connected screens were captured (`frontend-next/screenshots/connected-*.png`) and read
   next to the originals: same shell, typography, spacing, pipeline rail, map and graph panels,
   tables and floating Canopus window. What differs is content and labels only.

## What is connected

Operations queue and Resolved rail, the Auto switch (backend worker), case selection,
investigation rail from recorded stage events with a live stream, evidence map and knowledge
graph from the case's Neo4j evidence and route layers, accepted diagnosis, recommendation and
independent review, operator decisions, verification requests, audit ledger, Explore and the
live graph schema, Settings. Details and the rules the app follows are in
`frontend-next/INTEGRATION.md`.

Behaviour worth knowing:

- Nothing in the browser advances, executes, verifies or resolves a case. After every operator
  request the case is read again from the backend.
- Approval is offered only when the backend says the recommendation is approvable; otherwise its
  reason is shown. A refused or stale request reloads the case and shows the refusal.
- Without an accepted diagnosis the screens show the monitor's observed symptoms and the
  backend's reason for the absence, never a cause.
- Vehicle GPS is drawn as vehicle telemetry only. A delivery attempt is not proof of delivery.
  A receipt is not an outcome. A verified partial effect is not shown as successful.
- If the backend is unreachable nothing is shown and the page says so. There is no fixture
  fallback in the connected build.
- Synthetic data is labelled synthetic. The workspace is named Suhail Operations, not SPL.
- Canopus keeps its floating window, says it is not connected, and sends nothing.

## Needs backend work (not faked in the UI)

| Gap | What the UI does now |
| --- | --- |
| Decision reasons are not stored | Reason field disabled with an explanation; history says "Not stored by the backend yet" |
| No served list of allowed decisions per case | Reject and escalate follow the lifecycle table; the backend still enforces every request |
| No server-side sort or origin filter on the queue; audit is oldest-first only | Sorted and filtered in the browser over bounded loads (1,000 cases, 3,000 audit events), with totals stated |
| Request-evidence, reopen and human-outcome actions | Not offered; the redesigned UI has no control for them yet |
| Shipments without a case | Explore lists cases only |
| Canopus conversation API | Not connected |
| New Saudi logistics world | Shown once the backend can read it (its Stage 2) |

## Added after the first push (same day)

- The case assessment now shows the investigator's hypotheses with their status (supported,
  refuted, uncertain), the evidence each cites (selectable when drawn on the screen), missing
  evidence, and whether evidence arrived after the investigation's snapshot. Findings the
  reviewer did not accept are shown labelled as claims and never become the case's diagnosis.
  Rule checks are shown apart, labelled "not a diagnosis".
- Connected screens checked in Arabic with dark mode and at phone size (390 by 844): layout
  intact, no horizontal overflow (`screenshots/connected-*-arabic-dark.png`, `*-mobile.png`).
- Checks after this change: TypeScript and lint clean, 46 unit tests, 8 connected browser tests.

## Next batch

1. Live browser run against a real backend on a scratch database, monitor and automatic
   investigation off, no model calls.
2. As Stages 2 to 4 finish on fhd: merge, then connect what each stabilised.
3. Backend-side gaps listed above, once the backend track takes them.
