# Redesigned UI: the five-case live rerun (11 October 2026)

URL: `http://127.0.0.1:8020/app/` (session `SYN-OPS-SESSION-51ec40f8d71129ff04691297`, real
`gpt-oss:120b` calls, simulated clock at speed 600). Synthetic data; every execution is the
backend's simulator, not an SPL system.

## How it was checked

A browser watched the session read-only for 16.5 minutes from before the first arrival (Operations
page plus the case under investigation, sampled every 2 seconds; no page error). One approval was
then made from the interface. Finally each case was opened at rest and compared with
`GET /cases/{id}`; all five match.

## Stage by stage

| Stage | Verified in the interface against the backend | Not verified |
| --- | --- | --- |
| Arrival | All five cases appeared on Operations within about 4 s of opening | |
| Investigation | Every run showed its evidence queries, elapsed time, reviewer verdict; "Model reply invalid, retrying" appeared live on `000165` and `000104` | Turn budget exhausted and final-turn conclusion did not occur |
| Recommendation | Shown with its authority class and rule on all five | |
| Routing to a person | `000104` "Routed to a person by policy rule AUTH-14-symptom-floor", `000416` by AUTH-04 before its re-run, each with "the agent's finding is not verified" | |
| Approval | `000359` device sync approved with "Review & authorize"; backend recorded the operator approval | The request was **not acknowledged** (nothing left to sync), so no execution or outcome followed the approval |
| Simulated execution | Automatic actions acknowledged on `000359` (custody reconciliation) and `000232` (hub check), shown with the scheduled answer time | An execution following an operator approval |
| Verified outcome | `000359`: verifier answered, parcel not found. `000232`: "Delivered · no answer by the deadline", seen on real data for the first time | **A successful, resolved outcome: no case resolved in this session** |

## End states

| Shipment | Case | Runs | End state on screen and in the backend |
| --- | --- | --- | --- |
| `SYN-SHP-000165` | `…d2eecc49a809d1333da41694` | 1 | Escalated, reviewer did not accept; nothing executed |
| `SYN-SHP-000104` | `…99abf1259d33890b4f225772` | 3 | With a person under the symptom-floor rule; not approvable |
| `SYN-SHP-000359` | `…5e16b775e5f6eabe0248de43` | 2 | With a person; approved sync not acknowledged; earlier automatic action answered, parcel not found |
| `SYN-SHP-000416` | `…45fe7f37b85e501efaf00629` | 3 | Escalated after a reviewer revision |
| `SYN-SHP-000232` | `…b9274e4d19af6e80d44c74fa` | 1 | With a person; hub check delivered, no answer by the deadline |

### Why runs repeated (the backend's own reasons)

| Shipment | Reason recorded |
| --- | --- |
| `000165` | None: "17 new records arrived; none changes the symptoms or the evidence the conclusion rests on" (run kept) |
| `000104` | A new symptom (milestone overdue); then a cited manifest record got a new version |
| `000359` | Late uploads cleared the custody-gap finding after the outcome failed |
| `000416` | One kept run; then a new symptom (milestone overdue); then a new finding (delivery dispute) |

Every repeat had a material reason. The first run of `000416` was approvable for about ten seconds
before a re-run replaced it, too short for a person to act on.

## What rendered wrongly, and the fixes

1. **The assessment sheet was cut off on the right** on `000359`: a long query argument widened it.
   Long text now wraps.
2. **An earlier cycle's outcome was invisible on the case.** `000359`'s automatic action had been
   answered (parcel not found) before the approval; the sheet showed nothing about it. It now shows
   it as an earlier action's result, apart from the current action.
3. **A blank description** on a case without a diagnosis opened by direct link, until the queue
   loaded. It now says no accepted diagnosis is recorded.

## Checks at this commit

TypeScript and lint clean; 53 unit tests; 9 connected browser tests (scripted stand-in); the live
watch, 1 approval and 5 read-only case checks on the demo backend. Lab browser tests last ran at
`b67f44d` (20 passed).
