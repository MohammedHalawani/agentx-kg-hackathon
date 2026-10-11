# Redesigned UI: live arrivals on the demo backend (11 October 2026)

URL: `http://127.0.0.1:8020/app/` (session `SYN-OPS-SESSION-6405a1cb268436c587a28a8c`, five curated
shipments, real GPT-OSS, simulated clock at speed 600). Synthetic data; executions are the
backend's simulator.

## How it was checked

A browser watched the session read-only for 9.4 minutes from before the first case opened: the
Operations page, plus the case under investigation, sampled every 2 seconds. No operator request
was sent. No page error occurred. Afterwards each case was opened at rest and compared with
`GET /cases/{id}`; all five passed.

## What the live session showed

| Shipment | Arrived (watch clock) | Listed on Operations after | Runs seen | State after the watch |
| --- | --- | --- | --- | --- |
| `SYN-SHP-000165` | +4 s | 2.1 s | 2 | Resolved: automatic rescan, verified, exception cleared |
| `SYN-SHP-000104` | +60 s | 2.1 s | 4 | With a person: evidence kept changing during investigation |
| `SYN-SHP-000359` | +146 s | at once | 3 | Escalated: reviewer did not accept |
| `SYN-SHP-000416` | +386 s | at once | 1 during the watch, another after | With a person |
| `SYN-SHP-000232` | +421 s | 2.2 s | 1 | Awaiting outcome: answer scheduled for 18 Sept 06:31 AST |

Arrival order was 000165, 000104, 000359, 000416, 000232 (the last two swapped against the plan).
Every investigation showed "Investigation in progress" with the backend's elapsed time, each
evidence query the investigator chose as it happened, the reviewer's verdict, and its end state.

## What matters for the demo

1. **Cases are re-investigated several times.** At this clock speed new evidence arrives during
   and after a run, the backend reopens the case, and the page shows "Queued for re-investigation ·
   the earlier run is superseded" and starts over. `SYN-SHP-000104` ran four times in about four
   minutes and ended with a person because the evidence kept changing. It is correct behaviour but
   reads as restless, and it spends model calls. This is a backend pacing choice, reported to the
   backend session.
2. **The elapsed time moves in steps.** It is the backend's measurement at the latest event, so it
   jumps (for example 28 s to 53 s) while a slow model call runs. A smoothly ticking clock would
   need the browser to count between events; not done.

## What rendered wrongly, and the fix

`SYN-SHP-000104` ended with an accepted diagnosis and the authority rule "superseded snapshot", but
the header read "The model's reply could not be used · no diagnosis". The backend's note was that
evidence changed during the investigation, which is not a model failure. It now reads "Evidence
changed during the investigation · a person must review the latest evidence", and the diagnosis
stays shown. The start of a re-run also showed "No event is recorded for this stage"; it now shows
"Starting…".

## Not seen on real data

"Model reply invalid, retrying", "no conclusion within its turn budget", a conclusion on the final
allowed turn, and "no answer by the deadline": none occurred in this session. Unit-tested only.

## Checks at this commit

TypeScript and lint clean; 53 unit tests; 9 connected browser tests (scripted stand-in); the live
watch and 5 read-only case checks on the demo backend. The 20 lab browser tests last ran at
`164f2e7`; later changes touch connected-mode code only.
