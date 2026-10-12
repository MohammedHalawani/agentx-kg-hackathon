# Showcase recordings

Two short recordings of Suhail's own interface, made on the staging backend (port 8022) with
synthetic data. They are staged demonstrations, not live SPL operations.

## Rerun

Needs the staging backend on port 8022 and `npm install` (brings `ffmpeg-static` and Playwright;
the picture is captured from Chrome's own screencast, so Playwright's video binary is not needed).

1. Prepare the world (build clone; unattended, 12 to 20 minutes; leaves the clock paused, Auto off):
   `cd C:\Projects\demo\.stage4\chat && uv run python ../scripts/showcase_seed.py --video A`
2. Check every control without spending the world:
   `node recording/rehearse.mjs --map <evidence-map.json>`
3. Record: `node recording/director.mjs --video A --map <evidence-map.json>`
   - Video A map: `.stage4\artifacts\showcase\evidence_map_A_SYN-SHP-000304.json`
   - Video B map: `recording/maps/evidence_map_B_SYN-SHP-000443.json`
   - `--finding` (B) also records the operator's finding through the dialog; not used in the
     delivered film.
   - `--resume <case id>` (B) continues after an interrupted take whose first investigation
     already ran; `--case <case id> --tail` rehearses B's closing part and writes nothing.
   The script always leaves Auto off and the clock paused, also when it fails.
4. Encode: `node recording/finish.mjs --video A [--cut "from-to,from-to"]` writes
   `recording/out/suhail-video-A.mp4`. It removes the waits the director marked plus the ranges
   given (seconds of the film); nothing is reordered or sped up.

The pointer, the slow scrolling and the paced pipeline rail exist only in recording mode, which
the recording browser switches on; the product itself is unchanged. `ending.mjs` belongs to the
first, rejected versions and is not used for the delivered films.

A take depends on the model: the same shipment can end differently between runs. A wrong ending
means a reseed and another take, not an edit.

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
