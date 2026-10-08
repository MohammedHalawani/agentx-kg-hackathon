# Shipment product coherence — coordinator review

Timestamp: 2026-10-07 22:29 UTC+3. Review covers backend, LLM safety and React boundaries.

## Findings fixed

1. Translation previously stringified provider block arrays. Final text extraction now ignores private block types/channels and marked analysis, including fragmented tags. JSON stages accept only their declared application fields and compatible scalar/list types. Missing final output fails to stage defaults without logging raw output.
2. Legacy chat forwarded raw provider token deltas and reasoning SSE. It now emits the completed final answer after normalization; frontend ignores reasoning events and does not render stored provider reasoning.
3. Shipment stage/final DTOs copied arbitrary model dicts. They now use application field allowlists, including nested precedent/candidate lists.
4. Opening a historical/delivered/pending case in Intake initially offered a model run. The new navigation now requires a matching unresolved worklist row and uses its canonical complaint; evidence viewing itself never runs an agent.
5. Pending recommendations could have been omitted from attention filters. Backend includes null-outcome recommendations and open escalations.
6. UI labels claimed execution following recommendation write-back. Labels now distinguish recorded recommendations and pending external results in English/Arabic.
7. Schema failure was indistinguishable from empty data; error/retry handling added. Map legend uses glyph/icon plus text, and neutral historical cases are labelled recorded shipments.

## Reviewed limits

- Five evidence-backed filters; no fabricated lost/unaccounted category.
- One API response supplies map/list/overview graph selection. Selected context uses a fixed shipment query. Shipment seed IDs preserved, embeddings omitted, graph capped, edge closure maintained.
- `SHIPMENT_DATABASE` supplies Explore; conversation memory retains `CHAT_DATABASE`; legacy shared catalog is left for Batch 4 classification rather than blindly redirected.
- Origins are approximate city centroids; dashed endpoint connection is explicitly expected connection, not travelled path or live parcel GPS.
- Critical priority is derived from existing policy evidence, not claimed as recorded enterprise dispatch priority. Synthetic historical timelines are evaluated first-to-last event, not against today's clock.
- React changes reuse installed graph/Leaflet components, token colors, stable fetch cancellation, bilingual strings and Latin ID direction. Map text alternatives allow keyboard case selection.

## Validation recorded separately

API gate JSON passes all supported filters, selected/missing graph, shipment schema, invalid query rejection, Intake and Decisions read paths. Python 23 tests passed. Full frontend suite and build are running after final review fixes; browser gate follows their completion. Secret scan passed across 277 project text files, without emitting credential values.

No Batch 2 mutations or new product features have started.
