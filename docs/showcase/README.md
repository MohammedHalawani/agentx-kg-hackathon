# Showcase recordings: what ran for real and what was staged

Two recordings of the Suhail application were prepared on the isolated test backend (port 8022, database
`shipments-v2-world-ux-test`, synthetic world `SYN-SUHAIL-WORLD-1`). Everything in them is synthetic data. Nothing in
them is SPL operational activity, and no message, request or notification left the simulation.

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

In every run the answer in the simulation came from the depot. A notification to the driver is therefore a visual of
a request Suhail recorded against the driver's app device; it is not a delivered message and not a driver's reply.

What the graph does not contain, so the recording does not show it: vehicle GPS observations (they exist in the
world but are not part of a shipment's evidence graph) and other shipments' return scans. The only map point of
this case is the depot.

## Video B: delivery proof arriving late, shipment SYN-SHP-000443

See the section added after the Video B runs.

## Known limits that matter when describing Suhail

- The model's choice varies between runs of the same case. For SYN-SHP-000304: two runs proposed custody
  reconciliation (automatic), one proposed a facility check (needs approval).
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
