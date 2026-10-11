# Redesigned UI on the demo backend: story cases (11 October 2026)

## URL

`http://127.0.0.1:8020/app/` (the Stage 4 backend, database `shipments-v2-world-demo`, serving the
build at `C:\Projects\demo\.ui-integration\frontend-next\dist`). A case opens at
`http://127.0.0.1:8020/app/cases/<case id>`.

## What renders, checked against that backend's own API

Each case was opened in a browser and compared with `GET /cases/{id}`: state label, diagnosis or
its stated absence, map custody points, investigation steps and model calls, reviewer output,
authority rule, execution, verification, and whether it is in the Resolved queue. Read-only.

| Shipment | What the backend recorded | In the interface |
| --- | --- | --- |
| `SYN-SHP-000165` | Barcode mismatch from a systematic sorter misread (a cross-shipment and device finding), accepted, automatic rescan, acknowledged, verified with the exception cleared, **resolved** | Rail complete through Outcome; "Verified · exception cleared" with the verifier's reason; listed in the Resolved queue |
| `SYN-SHP-000359` | Custody gap, accepted, automatic reconciliation, acknowledged, verifier: facility did not find the parcel, with a person | Outcome stage marked failed with the reason; "Checked · not confirmed"; not in Resolved |
| `SYN-SHP-000124` | Approval-required device sync, approved by the operator, **not acknowledged** | "The action was not carried out · with a person"; Route stage marked failed; no outcome shown |
| `SYN-SHP-000104` | Unreconciled custody at medium confidence, routed to a person by the contractor-custody rule | Diagnosis, authority rule and reason shown; human investigation |
| `SYN-SHP-000312`, `SYN-SHP-000600` | Reviewer did not accept, escalated | Findings shown labelled "not accepted by the reviewer"; no diagnosis presented |
| `SYN-SHP-000375`, `SYN-SHP-000397` | The model's reply was invalid, with a person | "The model's reply could not be used · no diagnosis · with a person", the queries it did make are listed, no error page |

Screens: `frontend-next/screenshots/story-*.png`, `story-resolved-queue.png`, and `demo-*.png` for
the first case.

## The case I ran myself through the interface

`SYN-OPS-CASE-1cc8c63001f5cd3aa6962c1f` (shipment `SYN-SHP-000058`, opened on a weight read that
differs). "Investigate now" in the interface, 12 model calls:
weight mismatch accepted, automatic reweigh (`AUTH-10-auto-allowlist`), execution acknowledged.
It is still **awaiting its outcome**: after about ten simulated hours no answer has arrived, and
the interface shows it as executed and waiting for the verifier, with the deadline, and not as an
outcome. So I have not yet taken a case of my own to a verified outcome. One model-call slot of
the three I was allowed was used; the first attempt made no model calls (see below).

## What did not work, and what was fixed

1. **A declined investigation looked like success.** My first "Investigate now" was answered 200
   by the backend but not run, because it was investigating another case. The interface said
   nothing. It now reports that, and the button is disabled while the backend is busy with another
   case.
2. **Opened time showed "Invalid Date"** on a case opened by direct link before the queue loaded.
   Fixed.
3. **Evidence recorded after the investigation** was indistinguishable from what the investigator
   saw (on the first case a delivery record arrived after its snapshot). Such records are now
   marked in the evidence list and the inspector.
4. **Degraded and not-carried-out cases** read as generic "human investigation". They now say what
   happened.

## Still open

| Item | Detail |
| --- | --- |
| Clock control | The redesigned UI has no control for the simulation clock, so a case sits in "Verifying outcome" until someone advances it through the API. For a live demo either the backend runs the clock, or a control is added |
| Clock ticks answered 503 | About half of my hourly `POST /simulation/tick` calls returned 503 while the other session was also driving that backend |
| My own case has no outcome yet | Waiting on the simulator's answer or the 72-hour deadline |
| First queue read is slow | The header shows "Connecting…" for several seconds after a page load on this backend (queue plus Explore read); pages opened by direct link render the case first |
| Approval through the interface on the demo backend | Not exercised by me: no case I was allowed to act on was approvable |
| A person's finding through the interface on the demo backend | Not exercised |
| Cited records from other shipments | Counted and tagged in the steps list, not drawn in the graph |
| Request evidence, reopen, re-analyse | No control in the redesigned UI |

## Checks

TypeScript and lint clean; 53 unit tests; 9 connected browser tests (scripted stand-in); 8 story
cases and the first-case walkthrough on the demo backend (read-only); the 20 original lab browser
tests.

## Update: when an answer is expected, and three distinct end states

While a delivered request waits, the case page says "Request delivered · answer expected by
<time>" from the execution's `deadline_at`, or "an answer is scheduled for <time>" when the backend
serves `expected_response_at`. It never says what the answer will be.

| Backend record | In the interface |
| --- | --- |
| Acknowledged, outcome recorded from evidence | "Answered · verified · exception cleared", or "Answered · not confirmed" with the verifier's reason |
| Acknowledged, outcome `no_confirming_evidence` at the deadline | "Delivered · no answer by the deadline", with a person |
| `NOT_ACKNOWLEDGED` | "The request could not be delivered · nothing carried out", with a person; no outcome shown |

The unanswered state has a unit test; no case on the demo backend has reached it yet, so it has
not been seen in a browser against real data. Wording quoted in the table further up is the
earlier wording.
