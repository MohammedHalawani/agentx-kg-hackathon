# Baseline stabilization — impl

Timestamp: 2026-10-08T16:30:20.998277+00:00. Branch: fhd.

Implemented shared read-only shipment Explore selection, map/list/graph filters, bounded connected evidence and live shipment schema; selection carries evidence into Intake without automatic analysis. Loading/retry/cancellation and text alternatives are covered. Arabic has root RTL and right-hand navigation while geospatial/graph canvases retain their appropriate direction. Pending recommendations remain distinct from observed success/failure in UI and all precedent paths.

LLM normalization allowlists final application fields, removes private tags/Harmony analysis and rejects reasoning blocks. Legacy streaming buffers completed text, SSE does not forward reasoning and Message does not render it. Authoritative operator/persistence summaries compute attempt budgets, timeline span and cited exact-action outcome fractions; unverified model prose stays in the internal decision loop. A narrow contradictory-attempt guard and bounded AFL remain independently tested.

Writeback verifies shipment/failure identity and acceptable review, uses stable IDs plus transactional locks and preserves existing conflicting recommendations. It records pending outcome with null success and agent-review provenance. Observed-only precedent eligibility is enforced in vector/graph retrieval, recommendation/rules and embedding backfill. The prior controlled SHP-0004 proof and concurrent replay are retained; no new DB writes were made during this closure.

Default code/example model is 120B based on V1 evidence. Existing explicit local 20B configuration and secrets are preserved. Last copy fixes remove false no-shipment/reset implications. No major UI redesign, V2 importer, outcome endpoint or live email was introduced.
