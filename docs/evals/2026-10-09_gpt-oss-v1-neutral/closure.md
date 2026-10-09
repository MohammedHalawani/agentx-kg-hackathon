# V1 evaluation, neutral-complaint recomputation (2026-10-09)

This replaces the 2026-10-08 V1 figures, which are invalid as independent reasoning results:
their complaint texts were authored per gold category and also keyed the complaint-similarity
retrieval. Here every case receives the same neutral complaint (Arabic or English), so the
classifier must work from the shipment's recorded evidence and retrieved precedent only.

Protocol: `chat/scripts/evaluate_gpt_oss_v1.py --prepare --neutral-complaints`, then `--run` and
`--report`. Same 30 frozen cases per model (5 per base category, 18 Arabic / 12 English), the
production V1 pipeline at commit 1063800 (S1 leak fixes), dry writeback, temperature 0.

| Model | Base-cause agreement | Previous (invalid) | Mean seconds |
|---|---:|---:|---:|
| gpt-oss:20b | 6/30 (20.0%) | 13/30 | 23.7 |
| gpt-oss:120b | 14/30 (46.7%) | 16/30 | 7.5 |

Per category (120b): recipient_unavailable 5/5, hub_delay 5/5, address_conflict 3/5,
wrong_gate 1/5, barcode_mismatch 0/5, weight_mismatch 0/5. Full table: [comparison.md](comparison.md).

How to read this:
- These are agreement rates with synthetic seeded labels, not production accuracy.
- The V1 dataset itself still carries a cause-named event: every hub_delay shipment has an event
  of type `HUB_DELAY`, which explains the 5/5. V1 also has no barcode, weight or gate observations,
  so those subtypes cannot be distinguished from evidence at all (0/5). The V1 dataset is therefore
  not a meaningful root-cause benchmark; the live network dataset (S2a onward) replaces it.
- No evaluation result changed any prompt or rule; the run used the committed sources whose hashes
  are recorded in `manifest.json`.
