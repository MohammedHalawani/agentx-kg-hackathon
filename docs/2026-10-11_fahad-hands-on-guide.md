# Suhail: hands-on guide (manual investigation with Auto off)

11 October 2026. Everything on screen is synthetic demonstration data. Actions are carried out by
the backend's simulator; no SPL system is contacted.

## Where

| | URL | State |
| --- | --- | --- |
| Your hands-on queue | **http://127.0.0.1:8021/app/** | Clock paused, Auto off, cases waiting; fresh cases arrive once you start the clock |
| Your earlier session | http://127.0.0.1:8020/app/ | Untouched, Auto off. Its clock has reached the end of its timeline, so nothing new arrives there |

## The walk, step by step

1. **Open Operations.** You see the waiting exceptions. Beside the search there are two controls:
   **Clock paused · Start** and the **Auto** switch (off).
2. **Start the clock.** Click **Clock paused · Start**. It reads "Clock running ×60 · Pause": one
   simulated hour passes per minute. New exceptions appear in the list as the monitor opens them.
   Leave **Auto** off; with it off nothing is investigated until you click. If the button does
   not respond, `start-clock.cmd` and `pause-clock.cmd` beside this guide do the same thing.
3. **Select a shipment.** Click a row whose workflow reads "Queued". Prefer one that has just
   arrived: a request sent soon after a case opens can still be answered.
4. **Click Investigate now** (top right of the case). One real GPT-OSS 120B investigation runs,
   usually 30 to 100 seconds. The button waits while another case is being investigated.
5. **Watch.** The eight pipeline steps move as the backend reports them. Under the pipeline,
   **Canopus narration** shows what is happening, each message labelled by who wrote it:
   - **Canopus summary**: Canopus's own summary of recorded events.
   - **Agent's own words**: the investigator's or reviewer's recorded message, quoted.
   - **System record**: written by code from a deterministic record.
   The investigator's evidence queries are listed as "N evidence checks"; click one to light the
   records it returned in the graph.
6. **Inspect.** Click a pipeline step to read it. Click a map marker or graph node to inspect a
   record. **Case details** has the findings, the reviewer round by round and the policy rule.
7. **Read "Next best action"** at the bottom of the pipeline card. It is the backend's statement
   of what the case needs. **Why, and what is missing** opens the reviewer's objection, the
   missing evidence and what was already tried.
8. **Approve when offered.** If the case reads "Awaiting your approval", click
   **Review & authorize**, read the proposed action, then **Authorize action**. The backend
   re-checks the evidence first and refuses a stale approval. (In the automatic ten-case test I
   did exactly this on a rescan request: the case moved to "Verifying outcome" and the request
   was delivered. It has not been exercised with Auto off, because no approvable case appeared.)
9. **Watch the outcome.** After an action the case reads "Verifying outcome" with the time an
   answer is scheduled. Keep the clock running. The Outcome step then shows one of:
   "Done" (verified, resolved), "Executed · no answer, not verified", "Executed · exception
   remains", or "Executed · not verified as resolved". Only the first resolves the case.
10. **Ask Canopus.** Click the round button at the bottom right, or **Ask Suhail**, and type a
    question about the open case. Canopus answers from that case's records, quotes the agents'
    messages as they were recorded, and performs no action.
11. **Replay.** On a finished case, **Replay** beside the narration steps through the stored
    messages again. It makes no model call.
12. **Pause the clock** when you step away, so nothing goes stale.

## Three questions to ask Canopus (each answered correctly in testing)

1. "What did the reviewer say?"
2. "Show me the investigator's original message."
3. "What evidence is missing, and can you request it?"

## What the Disposition step means

It is the case's disposition (who acts next), not a vehicle route.

| Label | Meaning |
| --- | --- |
| Done | An automatic, policy-allowed action was authorized and delivered |
| Awaiting your approval | The backend marks the request approvable by an operator |
| Routed to a person | A policy rule requires a person; nothing runs automatically |
| Escalated to a person | The reviewer did not accept the finding; this is the workflow working, not a failure |
| Request not delivered / No result recorded | A genuine failure of the step |

## What to expect, honestly

| Topic | What you will see |
| --- | --- |
| Results differ per run | The same shipment can be accepted in one run and doubted in the next; the reviewer is inconsistent |
| A case can return to "Queued" | When material new evidence arrives, the earlier run is superseded. The case then reads "Waiting for the investigation of the current evidence to finish", but with Auto off nothing runs until you click **Investigate now** again |
| Resolution is timing-sensitive | An answer can take several minutes at this clock speed, and is not promised on a single click |
| Model failures | An invalid or missing model reply sends the case to a person with no diagnosis |
| Accuracy | In the evaluation the investigator was not more accurate than a rule lookup. Its finding is a proposal; nothing closes on it alone |

## Not verified in manual mode

| Path | Status |
| --- | --- |
| Approval through Review & authorize with Auto off | Not exercised: no approvable case appeared in the manual sessions. It worked in the automatic ten-case session |
| Opening Review & authorize from a Canopus offer | Verified against a stand-in backend only |
| Clock control on a real backend | Tested against a stand-in; confirmed on the real backend in the final check (see the handoff note) |
| Two investigations at the same time | Not supported: the worker runs one at a time |

## If something is not running

Neo4j Desktop: start the instance "AgentX". Backend start commands are in the backend guide
(`suhail-backend-test-guide.md` in the project files).
