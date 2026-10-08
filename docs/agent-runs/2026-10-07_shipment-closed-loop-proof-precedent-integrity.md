# Closed loop — observed precedent integrity

Timestamp: 2026-10-07 22:42 UTC+3.

## Architecture finding

Pending agent recommendations were excluded from historical success denominators, but vector/graph retrieval still allowed their Resolution/Outcome chains as citations. The backfill treated non-empty case_summary as sufficient for embedding. This could cause feedback contamination even without success=true.

## Correction

- Both frozen retrieval queries require `Outcome.success IN [true, false]`; Python boundaries independently reject null/non-boolean outcomes. Failed observations remain eligible negative evidence.
- Recommender removes unobserved second-pass rows before deriving candidate success rates and validating citations.
- Success-rate helpers accept actual booleans only, so string/integer values cannot be interpreted as observed wins.
- Backfill selection and embedding-write query recheck observed outcome eligibility. No backfill mutation was run; the live forced dry-run returns exactly165 seeded histories rather than166 recorded recommendations.
- Provider/embedding exceptions log their type without raw response/error text.

## Validation

Five focused unit tests PASS: vector similarity/holdout+eligibility, graph negative history/holdout+eligibility, pending/string/integer exclusion from rates, pending-only citation refusal, and backfill select/write guards. All reads target SHIPMENT_DATABASE. Live backfill dry-run165; no model/DB writes in this correction.

Current seeded observations are synthetic fixture truth, not SPL production observations. Later human outcome loop must add explicit verification/provenance to external outcomes; a non-null synthetic boolean here is the baseline's available observation contract.

## Additional observed limitation

Actual live AFL run on SHP-0017 produced correctable numerical attempt-count claims unsupported by its event history. The raw provider reasoning was suppressed; these were incorrect *final assessment* claims. They are recorded in the AFL report, not asserted as graph facts. Classifier facts + targeted reviewer contradiction guard are being added before the model evaluation. Other model claims remain subject to evidence review and cannot be claimed perfectly grounded from a small smoke.
