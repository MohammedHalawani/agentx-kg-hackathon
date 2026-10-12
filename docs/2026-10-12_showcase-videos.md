# Suhail showcase videos: what is genuine and what is staged

12 October 2026. Both videos are recordings of Suhail's own interface on a synthetic logistics
world. Nothing in them is SPL operational data, and no message left the simulation.

## Video A: custody discrepancy, resolved (final)

- File: `suhail-video-A.mp4` (same recording as `suhail-video-A-take1.mp4`), 63 s, 1920×1080.
- Shipment: SYN-SHP-000304 (Riyadh to Khobar). Recorded 12 Oct 2026, 02:22 UTC, branch commit `2d8e2ea`.

Genuinely executed by Suhail's backend during the take:
- the monitor opened the case ("a handover of the parcel was not confirmed by the receiving side");
- the GPT-OSS investigation (suspected cause: a gap in the custody chain, high confidence, after
  7 checks), 5 verified precedents, the independent review (accepted);
- the policy released a custody reconciliation request automatically; it was recorded for "the
  facility holding the parcel (the request names no specific recipient)" and executed by the
  simulator;
- later the depot SYN-DEPOT-KHB-01 recorded the parcel in its custody, and the verifier resolved
  the case: "Resolved: warehouse custody confirmed."
- the Canopus answer was generated in the take from the case's records.

Staged for the recording:
- a curated shipment in a seeded world; scripted clicks (Auto on, opening the case, the question);
- the simulated clock was started at 60× and moved forward twice ("Skip to next event") off screen;
- which records light up, the selected record and the Balanced / Map / Graph views were applied by
  the recording script after each step finished, from a map of the case's own graph records;
- **the phone is a picture**, drawn by the page in recording mode. It visualises the recorded
  request to the facility's device ("Custody check required" … "Check scan recorded"). No
  notification was sent to a driver or to anyone, and Suhail has no messaging integration;
- 98.6 s of waiting were removed in 5 cuts (raw take 162.5 s). Nothing was reordered or sped up.

How to describe it accurately:
- Suhail found an unconfirmed custody handover, investigated it with the graph, had the finding
  independently reviewed, issued an authorised request in simulation, and closed the case only
  after later evidence was verified.
- Do not say a driver was notified, or that the phone is a product feature.
- Outcomes vary between runs: in three other runs the same shipment went through an operator's
  approval once, to the driver's app device once, and to a person (unresolved) once on an aged world.
- The investigation in the video took about 25 s of real time; the depot's answer arrives about
  90 simulated minutes later.

## Rerun

See `frontend-next/recording/README.md`: seed, `rehearse.mjs`, `director.mjs`, `finish.mjs`.
