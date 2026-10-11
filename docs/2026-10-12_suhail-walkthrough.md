# Suhail: walkthrough of the simplified experience

12 October 2026. All data is synthetic. Actions are executed by a simulator, not by any SPL system.

**URL: http://127.0.0.1:8022/app/** (the only backend kept running)

## What you see now

| Where | What it shows |
| --- | --- |
| Case column, left | **Case assessment**: a state line, then Problem, Finding, Review (only when the reviewer challenged it), Action taken, Current status, in plain sentences |
| Pipeline card | Eight steps on one connecting line, each with one short line of what it did; **Next best action** at the bottom |
| "Investigation commentary" | One folded line. Open it only if you want the step-by-step messages and Replay |
| Case details | Seven plain answers (what happened, cause, evidence, review, action, next, resolved). Everything technical is folded under "Technical record" |
| Canopus | A plain chat about the open case. Nothing appears until you ask |

## Steps

1. **Open Operations.** Cases wait as "Queued". Auto is off.
2. **Press "Clock paused · Start"** first. Nothing can arrive while the clock is paused. If you
   forget, a waiting case tells you so and offers **Start the clock** and **Skip to next event**
   right on its page.
3. **Click a Queued case, then "Investigate now."** One real GPT-OSS 120B investigation runs, about
   40 to 100 seconds. The pipeline line fills as the backend reports each step.
4. **Read the Case assessment** on the left and **Next best action** at the bottom of the pipeline.
5. **If an action was sent**, the Action line says who received the request (simulated), what
   Suhail is waiting for and the deadline. When the answer will arrive is not known in advance.
6. **Press "Skip to next event"** on Operations instead of waiting. It runs the clock fast until an
   awaited result arrives or a new case opens, then leaves the clock paused. Press Start to let
   time run again, or Skip again.
7. **Approve when offered**: "Review & authorize", then "Authorize action".
8. **Ask Canopus** (round button, bottom right). Try:
   - "What is Suhail waiting for, and who needs to act next?"
   - "Show me the investigator's original message."
   - "Why can't I approve this?" On a resolved case: "What proved that this is resolved?"
9. **Pause the clock** before stepping away.

## About "Skip to next event"

- It takes about 4 seconds per simulated half hour: one to two and a half minutes for a typical
  rescan wait. The button shows "Skipping…" meanwhile.
- It stops at the first event, so reaching one case's result can take two or three presses when
  other cases open in between.
- Every other shipment ages by the skipped time. Click "Investigate now" on the cases you care
  about before skipping.
- It is refused while an investigation is running. If it fails, press it again; the interface
  already retries once by itself.

## Checked on screen in the final test (real GPT-OSS runs)

| Scenario | Shipment | What happened |
| --- | --- | --- |
| Verified resolution | SYN-SHP-000165 | Clicked right after it opened. Investigated in 58 s, review accepted, rescan sent to the sorter (simulated). Skip brought the result: "Resolved: the verifier confirmed from later evidence that the problem is cleared" |
| Unsuccessful action | SYN-SHP-000058 | Review challenged the finding; a reweigh went out as an evidence request. No confirming evidence arrived: "The verifier did not find evidence that the request fixed the problem." With a person |
| Reviewer rejection | SYN-SHP-000104 | Review did not accept the finding and says why in plain words. Nothing was sent. Escalated to a person, shown as waiting, not as a failure |

On each: the assessment lines matched the backend's record word for word, the seven answers
opened in Case details, no narration cards showed on the page, and Canopus answered three
questions in plain language with the agent's message quoted only when asked.

## What remains imperfect

- **The last two scenarios ran on aged cases.** My test left the clock running by mistake, so
  000058 and 000104 were investigated days after they opened. That is valid for an unsuccessful
  action and a rejection, but they were not fresh.
- **One skip in three failed at once** with a database-driver error and left everything
  unchanged; pressing again worked. The interface now retries once.
- **Outcomes vary between runs.** The same shipment can resolve in one run and go to a person in
  the next, because the model's answers and the reviewer's verdicts differ.
- **Approval with Auto off is still not exercised**: no manually started case became approvable.
- **Canopus is model text.** It was correct in every answer I read, but short ("Suhail is waiting
  for a person, and the operator needs to act next"). When asked why something cannot be done,
  the reason can appear twice: once in the answer and once in the list beneath it.
- **The Problem line can be long** when a case has several symptoms (000104 lists four).
- **Elapsed time moves in steps**, not second by second.
- **Arabic**: system sentences are translated; the investigator's and reviewer's own words are in
  the language the model wrote.
- **The investigator is not more accurate than rules** and rarely says "not enough evidence". Its
  finding is a proposal; nothing closes on it alone.

## If something is not running

Start the Neo4j Desktop instance "AgentX". The backend start commands are in
`suhail-backend-test-guide.md` in the project files.
