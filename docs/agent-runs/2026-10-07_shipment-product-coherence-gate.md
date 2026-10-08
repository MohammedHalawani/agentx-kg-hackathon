# Shipment product coherence — gate

Timestamp: 2026-10-07 22:31 UTC+3. Verdict: **PASS**. Batch 2 may begin.

| Check | Evidence |
| --- | --- |
| Shipment target | Local Bolt verified; database shipments; all300 SHP identifiers synthetic. Census JSON stored. |
| Active Explore APIs | Live HTTP gate PASS: identical map/graph selection all5 supported filters, edge closure, bounded nodes/edges, schema11 shipment labels, missing ID empty, invalid filters/limits422. |
| Current counts | attention70 shipments, critical28, stalled16, delivered80; unresolved74 FailureReasons (distinct shipment grouping). |
| Provider thinking suppression | 19 focused tests pass; JSON/Arabic live cloud smoke passes; only application final fields emitted. Unmarked provider prose requires provider final-content contract. |
| Python | Combined23 tests passed before final additional safety tests; focused19 LLM tests pass afterward. Standard unittest; no stack reinstallation. |
| Frontend | Full28files105tests PASS after fixing stale execution-wording assertion. |
| Lint | Exit0; 13 pre-existing warnings, no new Explore warnings. |
| Build | TypeScript/Vite PASS; pre-existing large graph/3D bundle warning remains for later UI phase. |
| Diff / secrets | diff --check PASS. Secret scan277text files PASS. .env ignored/untracked. |
| English browser |25 actual map markers,9 loaded tiles, nonzero map dimensions; marker/list selection; compact card; selected shipment graph; open Intake evidence without auto-run. |
| Arabic browser | RTL case card/filter labels, Latin IDs preserved; map marker click, graph selection sync, zoom/fit controls, shipment schema and Decisions render. |
| Mobile |390x844 Arabic Explore shows25 markers and25 keyboard-accessible text entries, no horizontal page overflow. Existing mobile drawer remains open after navigation until Escape; defer routine navigation polish to UI phase. |
| Browser console |Zero errors on rebuilt app. Cache-busting gate query used to avoid old built UI cached by browser. |

Visual evidence: `evidence/2026-10-07-shipment-coherence-map-en.png`, `evidence/2026-10-07-shipment-coherence-graph-ar.png`. API evidence: `2026-10-07_shipment-product-coherence-api-gate.json`.

Intake/Decisions read paths pass and their existing tests remain green. Full model→DB write proof intentionally starts in Batch2 after this gate. No governance graph labels appear in active Explore. Legacy repository identity cleanup remains Batch4. No new product expansion, DB writes, commits or pushes in this batch.
