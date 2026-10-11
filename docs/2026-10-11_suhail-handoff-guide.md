# Suhail: hands-on guide

11 October 2026. All data is synthetic. Actions are executed by a simulator, not by any SPL system.

## Where

| | URL | State |
| --- | --- | --- |
| **Your walkthrough** | **http://127.0.0.1:8021/app/** | Four cases waiting, nothing investigated, Auto OFF, clock PAUSED until you start it |
| Your earlier session | http://127.0.0.1:8020/app/ | Untouched, Auto OFF, the same five cases |

## Steps

1. **Open Operations** at http://127.0.0.1:8021/app/. Four cases wait as "Queued". Beside the
   search are **Clock paused · Start** and the **Auto** switch (off). Leave Auto off: with it on,
   Suhail investigates waiting cases by itself, oldest first.
2. **Select a case** by clicking its row.
3. **Click Investigate now** (top right). One real GPT-OSS 120B investigation runs, 20 to 100
   seconds. Start one at a time: a second click while one is running is not started.
4. **Watch.** The eight pipeline steps move as the backend reports them. Under them, **Canopus
   narration** shows what is happening, each message labelled by who wrote it:
   - **Canopus summary**: Canopus's own summary of recorded events (model text).
   - **Agent's own words**: the investigator's or reviewer's recorded message, quoted.
   - **System record**: written by code from a deterministic record.
   "N evidence checks by the investigator" lists each query; click one to light the records it
   returned in the graph.
5. **Read the result.** Click a pipeline step to read it. **Next best action**, at the bottom of
   the pipeline card, is the backend's statement of what the case needs; **Why, and what is
   missing** opens the reviewer's objection, the missing evidence and what was tried. Click a map
   marker or a graph node to inspect a record. **Case details** has the findings, the reviewer
   round by round and the policy rule.
6. **Start the clock.** On Operations click **Clock paused · Start**; it reads "Clock running ×60
   · Pause". The simulated world then moves one simulated hour per minute: requested actions get
   their answers, the verifier decides, and new cases arrive. Backup if the button does not
   respond: `start-clock.cmd` in `C:\Projects\demo\.stage4\artifacts\demo\walkthrough`.
7. **Approve when offered.** If a case reads "Awaiting your approval", click **Review &
   authorize**, read the proposed action, then **Authorize action**. The backend re-checks the
   evidence first and refuses a stale approval.
8. **Watch the outcome.** After an action the case reads "Verifying outcome" with the time an
   answer is scheduled. The Outcome step then reads "Done" (verified and resolved), "Executed ·
   no answer, not verified", "Executed · exception remains" or "Executed · not verified as
   resolved". Only the first resolves the case.
9. **Ask Canopus.** Click the round button at the bottom right and type a question about the open
   case. It answers from that case's records, quotes the agents' messages as recorded, and
   performs no action.
10. **Replay.** On a finished case, **Replay** beside the narration steps through the stored
    messages again, with no model call.
11. **Pause the clock** when you step away (**Clock running ×60 · Pause**, or `pause-clock.cmd`).

## The cases

Waiting now (clock paused at simulated 15 September, 20:34):

| Shipment | What it is | What happened in today's tests |
| --- | --- | --- |
| SYN-SHP-000375 | Barcode read differs at a sorter | Resolved and verified in 2 of 3 runs (rescan, then the barcode matched), once from a manual click with Auto off. In the third the reviewer asked for a revision and the rescan was still unanswered when the test ended. **Best candidate for a verified resolution** |
| SYN-SHP-000165 | Barcode read differs (opened six simulated hours earlier) | Resolved and verified in 5 of 7 runs. Twice the model's answer was unusable or the reviewer objected |
| SYN-SHP-000058 | Weight read differs | Reweigh executed, verifier found the weight still differs: stays with a person. A complete unsuccessful verification, usually within about three minutes of the clock running |
| SYN-SHP-000104 | Custody unconfirmed, session end unreconciled | Goes to a person every time (escalated, or human review by rule). A legitimate escalation |

Arriving after you start the clock (minutes after Start, at speed 60):

| Shipment | Arrives | What happened in today's tests |
| --- | --- | --- |
| SYN-SHP-000015 | about 10 min | Not resolved in any run |
| SYN-SHP-000304 | about 12 min | Resolved and verified once (custody reconciliation) |
| SYN-SHP-000232 | about 35 min | Escalated every time: the reviewer does not accept the custody-gap conclusion |
| SYN-SHP-000263 | about 43 min | Reweigh verified as successful, but the reviewer did not accept the re-investigation, so it went to a person (reviewer-doubt rule AUTH-27) |

## How long answers take

The clock must be running for anything to happen after an investigation.

- A reweigh is answered in **1 to 3 minutes**.
- A custody reconciliation in **3 to 5 minutes**.
- A **rescan is answered only when the parcel is next read**: about 32 minutes after Start for
  SYN-SHP-000165 and about 55 minutes after Start for SYN-SHP-000375. Until then the case shows
  "Verifying outcome". `fast-forward-clock.cmd` (same folder as the other two) runs the clock ten
  times faster to bring that moment sooner; go back to the normal Start afterwards, because at
  that speed newly arriving cases age quickly.

## Three questions to ask Canopus

Each was answered correctly in testing, with the agents' messages quoted:

1. "What did the reviewer say?"
2. "Show me the investigator's original message."
3. "What evidence is missing, and can you request it?" On a resolved case: "What proved that
   this is resolved?"

## What the Disposition step means

It is the case's disposition (who acts next), not a vehicle route.

| Label | Meaning |
| --- | --- |
| Done | An automatic, policy-allowed action was authorized and delivered |
| Awaiting your approval | The backend marks the request approvable by an operator |
| Routed to a person | A policy rule requires a person; nothing runs automatically |
| Escalated to a person | The reviewer did not accept the finding. The workflow working, not a failure |
| Request not delivered, or No result recorded | A genuine failure of the step |

## Confirmed in testing

| Check | What was seen |
| --- | --- |
| Investigate now with Auto off | Seven clicks, each ran exactly one real investigation |
| Execution and verification after a manual start | SYN-SHP-000375: rescan delivered, verified, resolved. SYN-SHP-000058: reweigh delivered, verified as not successful |
| Canopus narration and answers | Live narration on seventeen real runs, three labelled sources; about fifteen real answers with quoted agent messages |
| Graph highlights | Only records the backend names for that case were lit |
| Resolved means verified | Only verified, successful, exception-cleared cases read "Resolved" |
| Escalated and unsuccessful cases | Shown as waiting on a person, with the rule and the reviewer's objection |
| Interface and backend states | Matched on every case checked at rest |
| No mixing between shipments | Two cases never showed each other's narration, answers or highlights |
| Clock control | Start and Pause worked on this backend; same session, no case changed |

## Not reliable, or not covered

- **Outcomes vary between runs.** The same shipment can resolve in one run and go to a person in
  the next, because the model's answers and the reviewer's verdicts differ. No single click is
  guaranteed to resolve.
- **A waiting case's next best action reads oddly.** A case that is queued, or sent back by new
  evidence, shows "Waiting for the investigation of the current evidence to finish" although
  nothing runs with Auto off: click **Investigate now**.
- **Approval with Auto off was not exercised.** No manually started case produced an approvable
  request. It was done once in the automatic test: an operator-approved rescan on SYN-SHP-000015
  was delivered; the verifier found nothing. Opening the approval from a Canopus offer was tested
  against a stand-in backend only.
- **One investigation at a time.** Two cases investigating at the same moment is not supported
  and was not tested.
- **Model failures.** An invalid or missing model reply sends the case to a person with no
  diagnosis.
- **Device sync was never chosen by the investigator**, so that recovery type is unproven.
- **The investigator is not more accurate than rules** (81 against 92 of 119 in the evaluation)
  and almost never says "not enough evidence". Its finding is a proposal; nothing closes on it
  alone.
- **Canopus summaries are model text.** They are checked for invented record ids and false
  "resolved" claims and are labelled as Canopus; the agents' own words, shown separately, are the
  source to trust.

## If something is not running

Start the Neo4j Desktop instance "AgentX". The backend start commands are in
`suhail-backend-test-guide.md` in the project files.
