# Pilot: 12 real GPT-OSS 120B investigations on world-1

Run 2026-10-10 18:45 to 19:04 UTC at fhd e0081d3 on `shipments-v2-world-1-small`. Synthetic data. 111 model calls, 985,609 tokens (cap 144). Cases were the first two opened per alert type, chosen without truth; scoring ran afterwards as a separate process against truth kept outside the repository. This is a functional pilot, not an accuracy measurement.

Totals: 8 correct, 4 confident wrong answers, 0 stated uncertainty. All citations valid in 12 of 12. Reviewer accepted 8 (6 correct, 2 wrong) and rejected 4 (2 wrong, 2 correct). No automatic action was authorized. Every run record is served by the case-detail API. Time-correct check inside the feed window: pass (30 queries).

| # | Shipment | Alert at opening | Tools GPT-OSS chose (in order) | Conclusion | Hypotheses | Reviewer | Authority (rule) | Calls | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 000058 | WEIGHT_READ_DIFFERS | shipment_overview, scans, same_device_activity ; (none) | WEIGHT_MISMATCH (high) | WEIGHT_MISMATCH supported, BARCODE_MISMATCH refuted | ACCEPT | HUMAN_REVIEW (AUTH-23-physical-check-requested) | 7 | correct |
| 2 | 000082 | BARCODE_READ_DIFFERS + WEIGHT_READ_DIFFERS | shipment_overview, scans, scans, scans, same_device_activity, same_device_activity | BARCODE_MISMATCH (medium) | BARCODE_MISMATCH supported, WEIGHT_MISMATCH supported, DELAYED_SYNC refuted | ACCEPT | HUMAN_REVIEW (AUTH-23-physical-check-requested) | 9 | correct |
| 3 | 000104 | CUSTODY_TRANSFER_UNCONFIRMED | shipment_overview, custody_chain, same_device_activity, same_device_activity | CUSTODY_GAP (medium) | CUSTODY_GAP supported, DELAYED_SYNC refuted | ACCEPT | HUMAN_REVIEW (AUTH-23-physical-check-requested) | 6 | incorrect |
| 4 | 000395 | CUSTODY_TRANSFER_UNCONFIRMED | shipment_overview, custody_chain, scans, same_device_activity, container_and_trip | CUSTODY_GAP (medium) | CUSTODY_GAP supported, DELAYED_SYNC refuted | ACCEPT | HUMAN_REVIEW (AUTH-23-physical-check-requested) | 7 | correct |
| 5 | 000019 | CUSTODY_TRANSFER_UNCONFIRMED + MILESTONE_OVERDUE | shipment_overview, journey, custody_chain, delivery_attempts, device_status, same_device_activity, address_and_instructions, same_route_run | DELAYED_SYNC (medium) | DELAYED_SYNC supported, RECIPIENT_UNAVAILABLE uncertain | REVISE | HUMAN_REVIEW (AUTH-16-review-rejected) | 11 | incorrect |
| 6 | 000600 | DELIVERY_ATTEMPT_FAILED | shipment_overview, journey, delivery_attempts, address_and_instructions, custody_chain, same_route_run | RECIPIENT_UNAVAILABLE (high) | RECIPIENT_UNAVAILABLE supported, ADDRESS_CONFLICT refuted | ACCEPT | APPROVAL_REQUIRED (AUTH-07-action-mismatch) | 8 | correct |
| 7 | 000130 | BARCODE_READ_DIFFERS | shipment_overview, scans, same_device_activity, custody_chain ; scans, device_status | BARCODE_MISMATCH (medium) | BARCODE_MISMATCH supported, MANIFEST_CONFLICT uncertain | REVISE | HUMAN_REVIEW (AUTH-16-review-rejected) | 11 | correct |
| 8 | 000490 | BARCODE_READ_DIFFERS | shipment_overview, scans, same_device_activity, custody_chain, custody_chain, custody_chain, device_status ; (none) | BARCODE_MISMATCH (medium) | BARCODE_MISMATCH supported, CONFLICTING_CUSTODY refuted | REVISE | HUMAN_REVIEW (AUTH-16-review-rejected) | 11 | correct |
| 9 | 000489 | DELIVERY_ATTEMPT_FAILED | shipment_overview, delivery_attempts, journey, journey, custody_chain, same_route_run, same_route_run ; address_and_instructions | PROOF_INSUFFICIENT (medium) | PROOF_INSUFFICIENT supported, WRONG_GATE supported, RECIPIENT_UNAVAILABLE refuted | REVISE | HUMAN_REVIEW (AUTH-16-review-rejected) | 12 | incorrect |
| 10 | 000374 | WEIGHT_READ_DIFFERS | shipment_overview, scans, scans, scans, same_device_activity, vehicle_and_manifest ; (none) | WEIGHT_MISMATCH (medium) | WEIGHT_MISMATCH supported, DELAYED_SYNC refuted | ACCEPT | HUMAN_REVIEW (AUTH-23-physical-check-requested) | 11 | correct |
| 11 | 000174 | MILESTONE_OVERDUE | shipment_overview, journey, custody_chain, same_route_run, vehicle_and_manifest, delivery_attempts, address_and_instructions, device_status | CUSTODY_GAP (low) | CUSTODY_GAP supported, DELAYED_SYNC refuted | ACCEPT | HUMAN_REVIEW (AUTH-04-contractor-custody) | 10 | incorrect |
| 12 | 000579 | MANIFEST_CUSTODY_CONFLICT | shipment_overview, custody_chain, scans, vehicle_and_manifest, same_route_run, device_status | MANIFEST_CONFLICT (high) | MANIFEST_CONFLICT supported, DELAYED_SYNC refuted | ACCEPT | HUMAN_REVIEW (AUTH-12-human-review-action) | 8 | correct |

## What the wrong answers were

Cases 3, 5, 9 and 11. Each needed either a mechanism-level cause or an honest "insufficient evidence"; all eight correct answers were the observation-level cause that the opening alert maps to. The reviewer rejected two of the four wrong answers (5 and 9) and accepted two (3 and 11). The true causes are not listed here: truth labels stay outside the repository.

## Observations for the next stages

- The investigator never answered insufficient evidence, including the one case where that was right.
- Rescan, reweigh and hub-check proposals all went to a person under AUTH-23 because the investigator marked a physical check as required every time, so nothing was eligible for automatic execution. Stage 4 has to look at that.
- Calls per case: 6 to 12, median 9.5; one case used all 12 allowed calls; none was cut off.

Files: `pilot.json` (public run records, no truth), `pilot.scored.json` (adds the scoring).

## Re-run of six cases after one prompt fix (907be31)

The fix defined what confidence levels mean and what counts as a physical check. Cases 1, 2, 3, 4, 10 and 11 were
re-investigated once at fhd 7a2c1e0 or later (`rerun.json`, `rerun.scored.json`): 62 model calls, 687,366 tokens. The snapshot is the
clock the pilot ended on, later than the first investigations, so more evidence was available.

- 5 of 6 correct against the causes knowable at that later time; 0 confident wrong answers.
- Case 4 was classified AUTO by policy (custody reconciliation, rule AUTH-10): the physical-check definition works. With no
  simulator attached the action got no field response and the case went to a person, as designed.
- Cases 1 and 10 (weight mismatch, correct) were rejected by the reviewer after using all 12 calls.
- Case 11 ran out of calls before a valid conclusion and went to a person as a degraded run. One of six cut off is
  above the 5% rule, so the 12-call cap has to be raised in a dated amendment before the investigator is frozen.
- No case concluded insufficient evidence in the re-run; at the later snapshot every case was identifiable.

Pilot spend in total: 111 + 62 = 173 model calls, 29 more than the 144 planned for the pilot. All 173 count against the
4,000-call budget.

## Shipments excluded from Stage 3

The 12 pilot shipments' labels were committed by mistake in 721406f and 5802528 (removed from the files here, still in history), so they are excluded from any Stage 3 case set: see `excluded_shipments.json`.
