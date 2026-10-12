# Suhail showcase videos: what is genuine and what is staged

12 October 2026. Both videos are recordings of Suhail's own interface on a synthetic logistics
world. Nothing in them is SPL operational data, and no message left the simulation.

**The final files are `suhail-video-A-v2.mp4` and `suhail-video-B-v2.mp4`.** Every other video
file in the folder (`suhail-video-A.mp4`, `suhail-video-A-take1.mp4`, `suhail-video-B.mp4`,
`suhail-video-B-take1.mp4`, `suhail-video-B-take1-60s.mp4`) is an earlier, rejected version.

Neither video has captions, subtitles, narration or any text added to the picture.

## Staged in both videos

- A curated shipment in a seeded synthetic world. The script moves the pointer and clicks.
- The simulated clock is started at 60× and moved forward off screen ("Skip to next event").
- **The eight pipeline steps are shown at reading pace.** In recording mode the rail shows one
  more finished step only when the script allows it, about every two seconds, and never before
  the backend has reported that step. The backend itself finishes some steps faster than that,
  so the rail runs up to a few seconds behind it. In the product the rail follows the backend
  directly.
- Which records light up at each step and the Map focus / Graph focus views come from a list of
  the case's own graph records. Every lit record is a node of that case's graph.
- Waiting is removed, and some still moments are shortened, to stay under 60 seconds. Nothing
  is reordered or sped up.

## Video A: custody discrepancy, verified resolution

- File: `suhail-video-A-v2.mp4`, 59.7 s, 1920×1080. Shipment SYN-SHP-000304 (Riyadh to Khobar),
  case SYN-OPS-CASE-0e2e71c42dc052dccff3392b, recorded 12 Oct 2026 at 09:02 UTC.

Genuinely executed by Suhail's backend during the take:
- the monitor opened the case ("a handover of the parcel was not confirmed by the receiving side");
- the GPT-OSS investigation (a gap in the custody chain), the precedent lookup and the
  independent review, which accepted the finding;
- the policy released a custody reconciliation request automatically. It was recorded for the
  driver's app device SYN-DEV-APP-DRV-KHB-01-02 and executed by the simulator;
- later the depot SYN-DEPOT-KHB-01 recorded the parcel in its custody and the verifier resolved
  the case: warehouse custody confirmed;
- the Canopus answer was generated in the take from the case's records.

Staged, in addition to the list above:
- **the phone is a picture**, drawn by the page in recording mode only. It visualises the
  request recorded for the driver's app device: the notification, the three options and the
  choice "Scan package into warehouse". No notification was sent to a driver or to anyone;
  Suhail has no messaging integration. The driver's choice is not a backend record: what the
  backend recorded is the depot's custody record that arrived afterwards.
- 80 s were removed in 12 cuts (raw take 139.5 s): five waits (the queue, the review, the
  skipped time, the Canopus answer) and seven trims of 0.5 to 1 s inside still moments.

How to describe it accurately:
- Suhail found an unconfirmed custody handover, investigated it with the graph, had the finding
  independently reviewed, issued an authorised request in simulation, and closed the case only
  after later evidence was verified.
- Do not say a driver was notified or replied, or that the phone is a product feature.
- Outcomes vary between runs of the same shipment. Of the runs made for this video, some
  resolved automatically, one needed an operator's approval, and two went to a person unresolved.

## Video B: late delivery proof, responsible escalation

- File: `suhail-video-B-v2.mp4`, 59.7 s, 1920×1080. Shipment SYN-SHP-000443 (Riyadh to Tabuk),
  case SYN-OPS-CASE-1d9d834dc3aaf712e44342aa, recorded 12 Oct 2026 at 09:58 UTC.

Genuinely executed by Suhail's backend during the take:
- the monitor opened the case and Suhail investigated it while the queue was on screen. That
  first investigation ended with a person and nothing was sent;
- simulated time ran to the next morning. The driver's phone uploaded its records: the delivery
  attempt, the recipient's passed code, the handover, the delivery proof and the photograph
  entered the case's graph, and Suhail reopened the case by itself;
- Auto started the second investigation by itself. It concluded a conflict with the dispatch
  manifest, the independent review accepted that, and it proposed a manifest review by a person.
  This second investigation is the one whose eight steps are shown;
- the closing status line is served by the backend from the case's records: "Delivery evidence
  and the recipient's code received. The recorded proof supports delivery. Manifest discrepancy
  remains. A journey step is still overdue. Delivery session not reconciled. Human review required."
- the Canopus answer was generated in the take.

Staged, in addition to the list above:
- the film stays on the queue during the first investigation and opens the case only for the
  second one, so the pipeline is seen once. Auto started that second investigation by itself a
  few seconds after the case page was opened; that wait is removed;
- the photograph is an illustration supplied for this synthetic shipment and served from the
  photo record's stored image. It is not a photograph of a real delivery;
- 243 s of waiting were removed in 7 cuts (raw take 321 s: the first investigation, the skipped
  day, the second investigation's waits, the Canopus answer), then a further 17.9 s in ten trims
  of still moments, including one blank frame while the case page loaded.

How to describe it accurately:
- Suhail flagged an overdue shipment, investigated, received new evidence, re-examined the case
  by itself, and correctly left the remaining manifest conflict to a person. The case is not
  resolved and the video does not say it is.
- No operator finding is recorded in this video, and no request was sent by Suhail. The phone's
  records arrived on their own the next morning.
- "The recorded proof supports delivery" means the proof record passed the system's
  corroboration check (a delivered attempt with the recipient's passed code and a handover). It
  is not Suhail's automatic outcome verification, and the photograph plays no part in that check.

## Rerun

See `frontend-next/recording/README.md`: seed, `rehearse.mjs`, `director.mjs`, `finish.mjs`.
A take depends on the model, so the same shipment can end differently between runs; a wrong
ending means a reseed and another take.

## Cut lists of the delivered files (seconds of the film, removed)

- Video A (raw film 139.5 s): waits 3.65-8.73, 9.53-11.11, 37.34-42.53, 51.82-110.93,
  125.9-130.33; trims 0-0.5, 8.73-9.53, 22.58-23.08, 25.28-25.78, 46.38-46.88, 114.08-114.88,
  138.18-139.18.
- Video B (raw film 321.0 s): waits 3.65-9.24, 10.04-11.12, 13.62-49.24, 56.49-231.98,
  236.56-249.44, 255.69-264.52, 306.73-310.65, giving 77.6 s; then, in seconds of that 77.6 s
  film, trims 0-0.6, 9.5-13.3, 16.6-17.7, 34.3-37.3, 54.3-56.3, 58.6-59.8, 61.3-63.0,
  69.5-71.3, 74.3-76.8, and the last 0.4 s.
