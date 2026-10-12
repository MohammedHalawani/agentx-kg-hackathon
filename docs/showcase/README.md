# Showcase recordings: what ran for real and what was staged

Two recordings of the Suhail application were prepared on the isolated test backend (port 8022, database
`shipments-v2-world-ux-test`, synthetic world `SYN-SUHAIL-WORLD-1`). Everything in them is synthetic data. Nothing in
them is SPL operational activity, and no message, request or notification left the simulation.

The recordings: `suhail-video-A.mp4` (63 seconds, driver custody anomaly) and `suhail-video-B.mp4` (65 seconds,
delivery proof arriving late). The last 17 seconds of Video B (the final page, the Canopus answer and the closing
caption) were filmed about fifteen minutes after the take, on the same case, once two corrections to the served text
had been deployed; the case's records were not changed in between.

## What ran for real in both recordings

- The shipments are ordinary shipments of the synthetic world, chosen because their own records tell the story. No
  shipment, record, case, investigation result, action or outcome was written by hand for the recordings.
- The case was opened by Suhail's monitor from the records, when the simulated clock reached the point where the
  anomaly became visible.
- The investigation was run live by the investigator model (GPT-OSS 120B through Ollama Cloud) with its graph tools,
  and reviewed by the independent reviewer. The cause, the proposed action and the review verdict are the model's
  own for that take; they are not scripted and can differ between takes.
- The authority policy decided, by code, whether the proposed action could run automatically or needed a person.
- The request was answered by the world simulator from the physical state of the synthetic world (where the parcel
  really is, what a device really holds), and the answer reached Suhail as ordinary provider records.
- The outcome verifier decided the result from records made after the request. "Resolved" appears only because the
  verifier confirmed it.
- Canopus answers are generated from the case's stored records.

## What was staged for the recordings

- The choice of shipments, using the generator's private labels outside the runtime. The investigator, the reviewer
  and Canopus never see those labels.
- The starting point: `scripts/showcase_seed.py` runs the simulated clock to a few simulated minutes before the
  chosen case opens and leaves it paused with Auto off, so a take starts the same way every time. The backend is
  started with a short list of shipments whose cases the monitor may open (`SUHAIL_DEMO_SHIPMENTS`), so the queue
  is not crowded.
- Waiting time: the simulated clock runs at 60 times real time, and the wait for the field's answer is skipped with
  "Skip to next event" or cut in editing. The answer itself is not altered.
- Camera, focus, highlighting and timing of the interface (the recording director in the UI clone). Highlights use
  the evidence map written by `scripts/showcase_evidence_map.py` from the finished case: every highlighted item is a
  node or relationship of that case's own evidence graph.
- Video A: the phone notification is a recording-only visual. It stands for the custody reconciliation request that
  Suhail recorded; the party that answered in the simulation is the depot, which checked its shelves and scanned the
  parcel. No driver was contacted and there is no driver-facing application.
- Video B: the photograph shown for the proof-of-delivery photo record is an image supplied by Fahad and attached
  for the recording (`SUHAIL_MEDIA_DIR`). The synthetic world records only that a photo was taken, when and where;
  it generates no image. The image plays no part in the verification.

## Video A: driver custody anomaly, shipment SYN-SHP-000304

What the records say. The depot SYN-DEPOT-KHB-01 was the last corroborated holder of the parcel (received on
15 September). On 16 September at 07:25 UTC the depot recorded the parcel coming back off the driver's vehicle
(SYN-VEH-KHB-01-02, route run SYN-RR-KHB-01-0916-2, driver SYN-DRV-KHB-01-02), but there was no record of the parcel
being loaded onto that vehicle and no delivery proof, because the driver's phone was offline and had not uploaded its
records. The monitor opened the case as an unconfirmed custody handover.

The recorded take (case SYN-OPS-CASE-368798e1b3f18838c5ad2087) followed the same automatic path as the reference
run below and ended "Resolved: warehouse custody confirmed". Its request was recorded with no named device ("the
facility holding the parcel"), so the phone visual in that take stands for a request to the depot, not to a driver.

What Suhail did, in the reference run (take 2). The investigation concluded a gap in the custody chain and the
review accepted it; it proposed a custody reconciliation request; the policy allowed it automatically; the request
was recorded against the device the investigation cited (the driver's app device); the depot checked, scanned the
parcel and recorded it in its custody about 90 simulated minutes later; the verifier confirmed it and the case
closed: "Resolved: warehouse custody confirmed." The parcel is confirmed in the depot's custody. Nothing is claimed
about delivery to the recipient (the records show it was delivered the next day, outside the recording).

The other honest path. In take 1 the model proposed a facility check instead. The policy holds that action for a
person's approval when the diagnosis is a custody gap, so the case waited; after an operator's Approve the depot's
scan arrived, the verifier confirmed it and the case closed: "Resolved: parcel located at the warehouse." Which
path a take follows is the model's choice in that take.

Which device each run's request was recorded against (the phone visual follows this, and is shown only once the
request has actually been sent):

- Run of 11 October (ten-shipment test): custody reconciliation, automatic, recorded against the depot handheld
  SYN-DEV-HH-DEPOT-KHB-01.
- Take 1: facility check, sent after an operator's approval, recorded with no named device ("the facility holding
  the parcel").
- Take 2 (reference): custody reconciliation, automatic, recorded against the driver's app device
  SYN-DEV-APP-DRV-KHB-01-02.
- Recorded take: custody reconciliation, automatic, recorded with no named device.

In every run the answer in the simulation came from the depot. A notification to the driver is therefore a visual of
a request Suhail recorded against the driver's app device; it is not a delivered message and not a driver's reply.

What the graph does not contain, so the recording does not show it: vehicle GPS observations (they exist in the
world but are not part of a shipment's evidence graph) and other shipments' return scans. The only map point of
this case is the depot.

## Video B: delivery proof arriving late, shipment SYN-SHP-000443

What the records say. The parcel was delivered on 19 September at 05:50 UTC with the recipient's code, a handover
record and a photo record, but the driver's phone (SYN-DEV-APP-DRV-TUU-01-02) was offline, so none of that reached
Suhail. In the system the parcel had not even been loaded for delivery, while the depot's own reconciliation record
already said delivered. Separately, a revision of the dispatch manifest dropped the loaded parcel. The monitor opened
the case when the loading step passed its deadline.

What Suhail did, in the recorded take (session SYN-OPS-SESSION-9535e85dce2441fed0b83ba1, case
SYN-OPS-CASE-1a195686b65702ca2b84b91a). All of it ran for real:

1. First investigation: ended with a person, nothing sent.
2. The simulated clock was skipped to the next morning (two uses of "Skip to next event"). The phone reconnected by
   itself and its records arrived: the delivery attempt, the recipient's passed code, the handover, the proof and the
   photo record. Suhail sent no device sync; no request of any kind went out in this take.
3. Suhail reopened the case by itself on the new evidence. The second investigation (started with "Investigate
   now") first suspected late device records and proposed a device sync; the reviewer asked for a revision; it then
   concluded a conflict with the dispatch manifest, the review accepted it, and it proposed a manifest review by a
   person. The policy sent the case to a person.
4. The operator opened the photograph from the photo record, then recorded a finding through the page: delivery
   confirmed, citing the delivery proof. The system accepted the finding because the cited proof passed its
   corroboration check (bound to a delivered attempt at the address in force, with the recipient's passed code and
   the handover). The finding is stored as a person's finding that does not close the case
   (SYN-OPS-OUTCOME-54d385b4d0b785aca61485ad): the manifest disagreement and the unreconciled delivery session still
   stand, so the case stays with a person.

The closing caption, "Delivery evidence verified. Manifest discrepancy remains. Human review required.", is an
overlay added for the recording, above the served status line. What each part rests on: "verified" means confirmed
by a person against a proof that passed the system's corroboration check; it was not verified automatically by the
outcome verifier, and the photograph played no part in the check. "Manifest discrepancy remains" is one of the two
problems the served line names (the other is the delivery session ending unreconciled). "Human review required" is
the case's state. The served status line reads: "A person recorded a finding: the delivery is confirmed from the
recorded proof. The case is not resolved and stays with a person, because this still stands: the dispatch manifest
and the custody records disagree and the delivery session ended with this parcel unaccounted for."

What did not happen, so it must not be claimed: Suhail did not issue a device sync, did not resolve the case, and
in two earlier genuine takes of the same shipment the first investigation was rejected twice by the reviewer (a
custody gap was suspected, not late device records). No operator action exists to send a device sync on a case that
is with a person in this state. This shipment was chosen before its manifest problem was noticed; it is the only
shipment in this world whose delivery proof and photo are held on an offline phone.

## Known limits that matter when describing Suhail

- The model's choice varies between runs of the same case. For SYN-SHP-000304: three runs proposed custody
  reconciliation (automatic, resolved; the recorded take is one of them) and one proposed a facility check (held
  for an operator's approval, then resolved).
- The investigator has not yet diagnosed late device records at a case's opening and sent a device sync by itself
  in any run; it reached that diagnosis for SYN-SHP-000443 only after the records had arrived.
- A parcel whose last corroborated holder is a contractor or independent driver is never acted on automatically
  (rule AUTH-04): the first candidate for Video A, SYN-SHP-000174, was investigated and went to a person for that
  reason. A delivery session that ends with a parcel unaccounted for is also reserved for a person.
- "Sent" always means recorded and answered inside the simulation. There is no integration with a driver app,
  SMS, email or any SPL system.
- One case is investigated at a time.

## Rerunning

```
powershell -File scripts\showcase_backend.ps1 -Video A        # or B: starts the 8022 backend with that video's shipment list
cd chat
uv run python ../scripts/showcase_seed.py --video A           # archives the current session, leaves the clock paused before the case opens, Auto off
# start the clock at speed 60 and switch Auto on (the recording director does this), let the take finish, then:
uv run python ../scripts/showcase_evidence_map.py --shipment SYN-SHP-000304 --video A --started-at <UTC time of Start>
```

Every seed archives the previous session under `artifacts/demo/ux-test-ledger/` before resetting it. Evidence maps,
reference cases and take logs are under `artifacts/showcase/` (not in git).
