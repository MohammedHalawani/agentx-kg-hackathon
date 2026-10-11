# Suhail: test guide for the redesigned interface

Draft of 11 October 2026. Two parts are marked **GAP** and are filled in after the fresh demo
session: how to start the backend, and the shipment ids to use.

Everything you will see is synthetic data. Actions are carried out by the backend's simulator, not
by any SPL system.

## 1. Open the interface

Open **http://127.0.0.1:8020/app/** in Chrome or Edge.

The backend serves the interface itself, so there is no separate frontend to start. The top bar
should show "Synthetic data", and the bottom of the left sidebar "Backend connected".

| If you see | Do this |
| --- | --- |
| The page does not load at all | The backend is not running. **GAP: backend and Neo4j start instructions** |
| A "not found" page at `/app/` | The interface build is missing. In PowerShell: `cd C:\Projects\demo\.ui-integration\frontend-next`, then `npm ci`, then `npm run build`, then reload |
| "Connecting…" for a few seconds after a reload | Normal on the first read. Wait |
| A red notice that the backend is unreachable | The backend stopped. Restart it (see the gap above) |

## 2. Shipments to use

**GAP: shipment and case ids from the fresh session**, one of each:

| What to look at | Shipment id | Case link |
| --- | --- | --- |
| A successful, verified resolution | GAP | GAP |
| A case routed to a person | GAP | GAP |
| An unresolved case (action failed, unanswered, or reviewer did not accept) | GAP | GAP |

To open any of them, type the shipment id into "Search exception queue" on Operations and click the
row, or press Ctrl+K and search.

## 3. Operations: the queue

1. Click **Operations** in the sidebar. Cases are listed newest first.
2. Type a shipment id into **Search exception queue**. The list narrows.
3. Look at the **Automatic investigation** switch. On means the backend investigates the oldest
   waiting case by itself. Please leave it as you found it during a live session.
4. Click **Expand resolved panel** on the right. Only cases the backend resolved from a verified
   outcome appear there.

Check: a case in the Resolved panel must say "verified". A case that was only acted on must not be
there.

## 4. An investigation

Open a case. From top to bottom:

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

In **Knowledge graph**:

1. Drag to move, scroll to zoom. **Force** and **Tree** change the layout.
2. Click a node to see the record. **Evidence path** shows the records the finding rests on.
3. The header says how many of the recorded nodes are drawn (for example "48 of 107"). The graph
   is limited so it stays readable.
4. **Explore** in the sidebar shows the wider graph and, under **Schema**, the node and
   relationship types.

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

## 10. Language and theme

**EN / AR** in the top bar switches the interface to Arabic with right-to-left layout. The moon
icon switches dark mode. Findings written by the model stay in the language the model wrote.

## 11. Unfinished or unreliable in the interface

| Item | What you will notice |
| --- | --- |
| No clock control | The simulated clock is run by the backend. A case waiting for an answer waits until the clock reaches it |
| Canopus chat | The floating assistant opens but says it is not connected. It answers nothing |
| Decision reasons | The reason box in the approval dialog is disabled: the backend does not store reasons yet |
| Request evidence, reopen, re-analyse | No buttons for these |
| Elapsed time | Moves in steps with each backend event, not second by second |
| Records from other shipments | Counted and tagged "cross-shipment" in the steps, not drawn in the graph |
| Re-investigation | A case can be investigated again when material new evidence arrives; the page then says "Queued for re-investigation" and an approval offered moments earlier can disappear |
| First load | The queue takes several seconds to appear after a reload |
| Model failures | If the model is unavailable or its reply is invalid, the case goes to a person with no diagnosis. This is intended, but it means some cases show no finding |
| Never seen on real data | "No conclusion within its turn budget" and "concluded on the final allowed turn": built and unit-tested only |
