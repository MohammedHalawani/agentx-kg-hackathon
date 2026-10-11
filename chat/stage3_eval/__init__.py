"""Stage 3 blind evaluation harness (docs/plans/2026-10-10_stage3_evaluation_design.md, amendments 1 and 2).

Steps, each its own process on Fahad's machine:
  select  (scorer side, before any run)  truth + monitor replay rows -> selection.json, pairs.json, strata.json (+ sha256)
  run     (runtime, no truth)            selection.json + backend wiring -> results, ledger.jsonl, captured surfaces
  score   (scorer side, after the run)   results + truth + ingestion log -> scores.jsonl, canary.json
  report                                 -> report.json, report.md
  dry-run                                select + run with zero calls + report skeleton (fixture or real selection)

See README.md for the design mapping and WIRING.md for what the backend track plugs in.
"""
