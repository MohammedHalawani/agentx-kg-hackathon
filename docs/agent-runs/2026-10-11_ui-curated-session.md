# Redesigned UI on the curated demo session (11 October 2026)

URL: `http://127.0.0.1:8020/app/` (Stage 4 backend, session `SYN-OPS-SESSION-a573e17a73e408a3b9d7c57c`,
8 curated shipments, real GPT-OSS). A case opens at `/app/cases/<case id>`. All data is synthetic and
every execution is the backend's simulator, not an SPL system.

## What was checked, and how

Each of the 8 cases was opened in a browser and compared with `GET /cases/{id}` (read-only). Two
operator actions were then taken from the interface.

| Shipment | Backend record | In the interface | Investigation time shown |
| --- | --- | --- | --- |
| `SYN-SHP-000165` | Barcode mismatch, automatic rescan, verified, exception cleared, resolved | "Answered · verified · exception cleared"; in the Resolved queue | 48.7 s, first conclusion 32.0 s |
| `SYN-SHP-000232` | Hub delay, automatic hub check, verified success, milestone still overdue | "Action verified · the exception remains · with a person"; Outcome stage waiting | 76.4 s |
| `SYN-SHP-000359` | Delayed sync, approved by the backend session, not acknowledged | "The request could not be delivered · nothing carried out"; no outcome | 73.5 s |
| `SYN-SHP-000416` | Proof insufficient, dispute for a person, not approvable | No approve control; a person's finding recorded from the interface (below) | 63.9 s |
| `SYN-SHP-000104` | Custody gap, evidence request, approvable | Approved from the interface (below) | 138.1 s |
| `SYN-SHP-000135`, `SYN-SHP-000093` | Reviewer asked for revision, escalated | Findings labelled "not accepted by the reviewer"; no diagnosis presented | 56.7 s, 54.9 s |
| `SYN-SHP-000279` | Model degraded after 14 calls, no conclusion | "The model's reply could not be used · no diagnosis · with a person" | 90.9 s |

Times are the backend's own `run.result.latency`; the rail shows seconds per stage.

### Approval from the interface (`SYN-SHP-000104`)

"Review & authorize", then "Authorize action". The backend moved the case from human review to
awaiting outcome and recorded an execution acknowledged under operator approval. The page then
read "Request delivered · an answer is scheduled for 18 Sept 2026 · 16:23 AST", offered no second
approval, and showed no outcome. Screens: `frontend-next/screenshots/demo-operator-1..3-*.png`.

### A person's finding from the interface (`SYN-SHP-000416`)

"Record a person's finding", type "Parcel not found", one cited record, and a text stating it was
an interface test with no physical check. The backend recorded a human finding with success false
and escalated the case; it did not resolve. The page shows "Finding on record · not resolved".
Screens: `demo-operator-4-finding-dialog.png`, `demo-operator-5-finding-recorded.png`.

## What rendered wrongly, and the fixes

1. **The case description changed after a few seconds.** On `SYN-SHP-000104` the "What happened"
   text switched from the diagnosis summary to the leading hypothesis's assessment, because the
   queue row serves a different one-line summary than the case detail. The loaded diagnosis now
   stays. The backend serving two different summaries is reported to the backend session.
2. **An action that worked was marked failed.** On `SYN-SHP-000232` the Outcome stage showed a red
   "Failed" although the verifier confirmed the action and only the exception remains. It now
   shows as waiting, with the same header sentence.

## Not seen against real data

| State | Why |
| --- | --- |
| "Model reply invalid, retrying" | No repair event was recorded on any of the 8 cases |
| "Delivered · no answer by the deadline" | No case has reached its deadline unanswered |
| Live arrivals in order with running elapsed time | All 8 cases were already investigated when the session was handed over |
| A case of my own reaching a verified outcome | `SYN-SHP-000104`'s answer is scheduled, not yet arrived |

These are covered by unit tests only.

## Still open

Clock control in the interface; request evidence, reopen and re-analyse controls; cited records
from other shipments are counted but not drawn; the first queue read takes several seconds.

## Checks at this commit

TypeScript and lint clean; 53 unit tests; 9 connected browser tests (scripted stand-in); 9
read-only checks and 2 operator actions on the demo backend. The 20 lab browser tests last ran at
`164f2e7`; the changes since touch only connected-mode code.
