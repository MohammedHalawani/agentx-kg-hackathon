# Shipment product coherence — implementation

Timestamp: 2026-10-07 22:31 UTC+3.

- Added shipment Explore query/summary module and `/explore` shared map/list/graph response. Active `/graph` and `/schema` now use SHIPMENT_DATABASE. See `docs/explore-shipment-contract.md` for evidence mapping and explicit limits.
- Added default attention Map lens, matching Graph filters, selected evidence graph/card, text list, status legend, token-based markers, clear approximate origin/expected-connection labels and explicit case navigation.
- Added final-only LLM normalization across JSON stages, translation, legacy chat and pipeline DTOs. Provider reasoning is neither retained for display nor forwarded over SSE.
- Preserved Ollama Cloud compatibility/config fallback edits. Added offline config/provider/content/JSON/Arabic/translation/DTO tests, backend Explore tests, frontend Explore and navigation tests.
- Corrected active recommendation/result wording: write-back is a pending recommendation rather than observed execution or delivery.
- Added read-only census/API verification and secret-scan scripts. All new API checks are read-only; no graph mutations in this batch.

Detailed ownership notes: `2026-10-07_shipment-product-coherence-{backend,llm,ui}-*.md`.
