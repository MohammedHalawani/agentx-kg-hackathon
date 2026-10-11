# Suhail: hands-on test guide

11 October 2026. One guide for the interface and the backend behind it.

Everything you will see is synthetic demonstration data. Actions are carried out by the backend's
simulator; no SPL system is contacted.

## 1. Open the interface

Open **http://127.0.0.1:8020/app/** in Chrome or Edge.

The backend serves the interface, so there is no separate frontend to start. The top bar should
show "Connected" and the bottom of the sidebar "Backend connected".

| If you see | Do this |
| --- | --- |
| The page does not load at all | Start Neo4j, then the backend (below) |
| A "not found" page at `/app/` | The interface build is missing. In PowerShell: `cd C:\Projects\demo\.ui-integrationrontend-next`, then `npm ci`, then `npm run build`, then reload |
| "Connecting…" for a few seconds after a reload | Normal on the first read. Wait |
| "Backend offline" in the top bar | The backend stopped. Restart it (below) |

### If something is not running

1. **Neo4j:** open Neo4j Desktop and start the instance "AgentX".
2. **Backend:** in PowerShell:

```powershell
cd C:\Projects\demo\.stage4\chat
$env:LLM_MODEL='openai/gpt-oss:120b'
$env:SUHAIL_OPERATIONS_DATABASE='shipments-v2-world-demo'
$env:SUHAIL_SIM_STATE_ROOT='C:\Projects\suhail-sim-state\world-1-small-r4'
$env:SUHAIL_FRONTEND_NEXT_DIST='C:\Projects\demo\.ui-integrationrontend-next\dist'
$env:SUHAIL_MODEL_CALL_CAP='12'; $env:SUHAIL_TOOL_BATCH='3'; $env:SUHAIL_PREFETCH_OVERVIEW='1'
$env:SUHAIL_INVALID_OUTPUT_REPAIR='1'; $env:SUHAIL_FORCED_CONCLUSION='1'; $env:SUHAIL_DEV_RESET='1'
$env:SUHAIL_DEMO_SHIPMENTS='SYN-SHP-000104,SYN-SHP-000165,SYN-SHP-000359,SYN-SHP-000232,SYN-SHP-000416'
uv run uvicorn --app-dir ../backend main:app --host 127.0.0.1 --port 8020
```

   The session's cases are stored in Neo4j, so a restart keeps them. The model key is read from
   `C:\Projects\demo\.env`.
3. **Frontend:** nothing to start.

### A fresh session with the same five shipments (optional)

```powershell
cd C:\Projects\demo\.stage4\chat
uv run python ../scripts/world_demo_session.py --live-from 2026-09-15T13:30:00+00:00 --preroll-speed 600 --live-speed 600
```

It saves the current session first, resets only the demo ledger and replays: about six minutes of
preparation, then the five cases arrive over roughly fifteen minutes. Each run makes real model
calls, and results differ from run to run because the model's answers differ.

## 2. Shipments to use

The session now on screen was investigated with real GPT-OSS 120B calls. Type the shipment id into
the search box on Operations, or press Ctrl+K.

| What to look at | Shipment | What happened |
| --- | --- | --- |
| A successful, verified resolution | **SYN-SHP-000165** | Barcode mismatch. Reviewer accepted, automatic rescan, the verifier confirmed the barcode now matches. Resolved; it is in the Resolved panel |
| Approval, for you to try | **SYN-SHP-000104** | With a person under the symptom-floor rule. Its evidence request can be approved from the interface. I left it untouched for you. This session's simulated clock has reached the end of its timeline, so the request is sent but its answer will not arrive: to see an approval through to a verified outcome, start a fresh session (section 1) |
| Unresolved after an action | **SYN-SHP-000359** | Device sync approved from the interface and delivered. No confirming evidence arrived by the deadline, so it stays with a person |
| Reviewer did not accept | **SYN-SHP-000232**, **SYN-SHP-000416** | Escalated. Nothing was executed. The investigator's findings are shown labelled as not accepted |

## 3. Operations: the queue

1. Click **Operations** in the sidebar. Cases are listed newest first.
2. Type a shipment id into the search box. The list narrows.
3. Look at the **Automatic investigation** switch. On means the backend investigates the oldest
   waiting case by itself. Please leave it as you found it during a live session.
4. Click **Expand resolved panel** on the right. Only cases the backend resolved from a verified
   outcome appear there.

Check: a case in the Resolved panel must say "verified". A case that was only acted on must not be
there.

## 4. An investigation

Open a case. Under each pipeline step there is now one short sentence saying what that step
recorded (for example "Finding: barcode mismatch", "Independent reviewer: accept", "Verifier
confirmed the fix"). On a case that is not resolved, a panel under the pipeline says what you need
to do, why Suhail did not resolve it automatically, what evidence is missing and what was already
attempted, all taken from the backend's records.

From top to bottom:

1. **Header**: shipment id, state (for example "Human investigation", "Verifying outcome",
   "Resolved"), origin and destination.
2. **Investigation pipeline**: eight stages, Collect to Outcome. The sentence beside the title
   says where the case stands. Click any stage to read what the backend recorded for it. A red
   cross marks a stage that did not produce its result.
3. To watch one live, open a case that says "Queued" and click **Investigate now**, or wait for
   the automatic worker. You should see "Investigation in progress" with seconds counting in
   steps, and lines such as "Investigator queried custody chain: …" as each query happens. An
   investigation takes roughly 20 seconds to 2 minutes.

Check: selecting a finished case must not start a new investigation.

## 5. The AI's finding and its evidence

1. On the left of the case, the block headed **Agent's finding · reviewer accepted · not
   verified** is the agent's proposal. If the reviewer did not accept it, or the model failed, the
   block is headed **What the monitor observed** and no cause is shown.
2. Click **Case details** (top right) or **Full assessment**. In the panel:
   - **How Suhail investigated**: every evidence query, how many model calls, how long it took.
   - **Investigator's findings**: the proposed cause, each hypothesis marked supported, refuted or
     uncertain, with the record ids it cites. Click a record id to highlight it on the map and
     graph.
   - **Reviewer, round by round**: the independent reviewer's verdict and its objections.
   - **Authority policy**: which rule decided what may happen, in the backend, not the model.

Check: the confidence shown is the model's own statement, not a guarantee. The finding can be
wrong; in our evaluation it was wrong often enough that nothing closes on it alone.

## 6. The map

In **Route evidence**:

1. Solid line: confirmed custody points, numbered in order. Dashed line: the expected route.
2. Click a numbered marker. The same record is highlighted in the graph and described in the bar
   under the workspace.
3. The layers button (top right of the map) switches custody, expected route and vehicle
   positions on and off.

Check: a vehicle position is labelled as vehicle only. It is never shown as where the parcel is.

## 7. The knowledge graph

In **Knowledge graph** (use **Graph focus** above the workspace for a large view):

1. It opens focused: the shipment in the centre, its packages, the records the finding cites
   (ringed in purple), and the case's own decision records (case, run, review, recommendation,
   execution, outcome). The header says how many are shown, for example "22 of 96".
2. Colours tell record types apart: custody, scans, status and proof, devices, facilities,
   vehicles and trips, people and organisations. The legend lists the ones on screen.
3. Click a record to inspect it; the same record is highlighted on the map. A small **+N** on a
   node, or a double-click, brings in more records connected to it. **All N records** shows the
   whole set; **Focused view** returns.
4. **Evidence path** dims everything except the cited records and what links them to the shipment.
5. **Force** arranges records in rings around the shipment; **Tree** in columns by distance from it.
6. Drag to move, scroll to zoom. **Explore** in the sidebar shows the wider network and, under
   **Schema**, the node and relationship types.

Every node and line is a record or relationship read from Neo4j through the backend. Nothing is
drawn that the backend did not serve.

## 8. Actions and approvals

What you can do depends on what the backend allows for that case:

| Button | When it appears | What it does |
| --- | --- | --- |
| **Review & authorize**, then **Authorize action** | The backend marks the recommendation approvable | Sends your approval. The backend re-checks the evidence first and may refuse if it changed |
| **Reject the action** | A recommendation exists and waits on a person | Records the rejection |
| **Escalate case** | The case is with a person | Escalates it |
| **Record a person's finding** | The case is with a person | Records what a person found. "Parcel not found" never resolves a case |
| **Ask the verifier to check now** | An action was delivered and its answer is awaited | Asks the backend's verifier to look at the evidence now |

1. Open the case routed to a person. If **Review & authorize** is offered, click it, read the
   proposed action, click **Authorize action**.
2. The state should change to "Verifying outcome" and the header to "Request delivered · an answer
   is scheduled for …". If instead it says "The request could not be delivered", the simulator had
   no recipient for it and nothing was carried out.
3. **Decisions** in the sidebar lists cases waiting on a person; **Decision history** lists what
   was decided and by whom.

Check: automatic actions are only the safe, reversible ones (a rescan, a reweigh, a device sync, an
evidence request, a hub check). Rerouting or returning a shipment always needs approval.

When the reviewer asks for a revision or more evidence (rule AUTH-27): only those safe
evidence-gathering actions may proceed, and only if every other rule allows them. The reviewer's
doubt stays on the case, shown under **Reviewer, round by round** and **Authority policy**. After
the new evidence arrives the investigator and reviewer reassess. A case resolves only when the
latest review accepts and the independent verifier confirms the problem is corrected; otherwise it
stays open or goes to a person.

## 9. Verification

After an action is delivered, open **Case details** and scroll to **Execution & verification**.
You should see one of these, and only the first resolves the case:

| Text | Meaning |
| --- | --- |
| Answered · verified · exception cleared | New evidence shows the problem is fixed. The case is resolved |
| Verified · exception remains | The action worked but the shipment problem is still there. With a person |
| Answered · not confirmed | The answer came and did not confirm the fix. With a person |
| Delivered · no answer by the deadline | Nothing confirming arrived in 72 simulated hours. With a person |
| The request could not be delivered | Nothing was carried out. With a person |

"A receipt is not an outcome" means the request was received, nothing more. **Audit** in the
sidebar shows the full trail for a case, including the verifier's entry.

## 10. Checklist

| Check | Where | Expected |
| --- | --- | --- |
| Resolved case | SYN-SHP-000165 | "Resolved"; all eight steps done with their sentences; no "what you need to do" panel; listed in the Resolved panel |
| Human investigation | SYN-SHP-000104 | "Human investigation"; panel names rule AUTH-14, the missing evidence, "No corrective action has been carried out"; **Review & authorize** offered |
| After an action | SYN-SHP-000359 | "Human investigation"; panel lists the device sync as approved by an operator, delivered, verified as not successful |
| Escalated | SYN-SHP-000232, SYN-SHP-000416 | "Escalated"; panel gives the reviewer's objection; no approval offered |
| Graph | any case, **Graph focus** | Shipment centred, readable labels, +N expands, click highlights the map |
| Logo | sidebar toggle (top left of the page) | Full logo when open, star alone when collapsed, in light and dark |

## 11. Language and theme

**EN / AR** in the top bar switches the interface to Arabic with right-to-left layout. The moon
icon switches dark mode. Findings written by the model stay in the language the model wrote.

## 12. Unfinished or unreliable in the interface

| Item | What you will notice |
| --- | --- |
| No clock control | The simulated clock is run by the backend. A case waiting for an answer waits until the clock reaches it |
| Canopus chat | The floating assistant opens but says it is not connected. It answers nothing |
| Decision reasons | The reason box in the approval dialog is disabled: the backend does not store reasons yet |
| Request evidence, reopen, re-analyse | No buttons for these |
| Elapsed time | Moves in steps with each backend event, not second by second |
| Records from other shipments | Counted and tagged "cross-shipment" in the steps, not drawn in the graph |
| Scans and their devices | A scan names its device and facility inside the record, not as a relationship, so the graph draws no line between them. Devices and facilities appear through custody records |
| Live narration by Canopus | Not in this build. The step sentences restate recorded fields; the narrated bubbles follow once the backend serves narration |
| Re-investigation | A case can be investigated again when material new evidence arrives; the page then says "Queued for re-investigation" and an approval offered moments earlier can disappear |
| First load | The queue takes several seconds to appear after a reload |
| Model failures | If the model is unavailable or its reply is invalid, the case goes to a person with no diagnosis. This is intended, but it means some cases show no finding |
| Never seen on real data | "No conclusion within its turn budget", "concluded on the final allowed turn", and the reviewer-doubt rule AUTH-27 (it did not fire in this session; covered by tests only) |
| The reviewer is inconsistent | The same case can be accepted in one session and doubted in the next. This is the main reason results differ between runs |
| The investigator is not more accurate than rules | In the evaluation it got 81 of 119 right against 92 for a rule lookup, and never answered "not enough evidence". Do not present it as more accurate than rules |
| Repeated investigation | SYN-SHP-000104 was investigated six times in this session as its symptoms changed |
| Dataset label | The word "synthetic" no longer appears in the interface, as you asked. Settings still says the data is a demonstration dataset and not SPL operational data, and ids keep their SYN- prefix |
