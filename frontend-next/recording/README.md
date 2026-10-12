# Showcase recordings

Two short recordings of Suhail's own interface, made on the staging backend (port 8022) with
synthetic data. They are staged demonstrations, not live SPL operations.

## Rerun

1. Prepare the world (build clone, 12 to 15 minutes; leaves the clock paused and Auto off):
   `cd C:\Projects\demo\.stage4\chat && uv run python ../scripts/showcase_seed.py --video A`
2. Record: `node recording/director.mjs --video A --map <evidence_map_A_….json>`
3. Encode: `node recording/finish.mjs --video A` → `recording/out/suhail-video-A.mp4`

The same three steps with `B` and the B evidence map make the second video.

## What is genuine and what is staged

Genuine, executed by the backend during the take:
- the monitor opening the case, the GPT-OSS investigation, the independent review, the policy
  decision, the simulated execution of the request, the arrival of later evidence and the
  verifier's outcome. The pipeline rail moves only when the backend reports a step.
- every highlighted record and relationship is a node or edge of the case's own Neo4j graph.
- the Canopus answer is generated during the take from the case's records.

Staged for the recording:
- the shipment is a curated one in a seeded synthetic world; the script opens it and clicks.
- which records light up at each step, the selected record and the Balanced / Map / Graph view
  come from the evidence map, applied after the step is reported.
- the phone (video A) is drawn by the page in recording mode only. Nothing is sent to any
  device; the backend's recorded recipient of the request is the facility.
- simulated time is moved forward backstage ("Skip to next event") so the awaited scan arrives.
- waiting stretches are cut in `finish.mjs`; nothing is reordered or sped up.
- when the policy holds the action for a person, the script presses Approve as the operator.

Recording mode exists only when the page is opened with `?director=1`.
