# Shipment product coherence — audit

Timestamp: 2026-10-07 22:20 UTC+3. Branch: `fhd`. Starting head: `2b9f7c8`.

The operator workflow is Intake → shipment evidence → diagnosis/recommendation/review → pending write-back or human escalation. Explore must read the same shipment graph and offer a bounded overview; map selection and graph selection must open the same case without running it automatically.

## Verified baseline

- Existing app listener on 127.0.0.1:8000, local Neo4j Bolt on 7687, local Ollama on 11434. No bootstrap repeated.
- Read-only census: `2026-10-07_shipment-product-coherence-census.json`.
- Database `shipments`; 300/300 synthetic SHP identifiers. 240 FailureReasons: 166 linked to Resolution, 74 without Resolution. 165 seeded histories plus one agent pending resolution. One escalation.
- Vector index `failurereason_case_summary`: ONLINE, COSINE, 1024 dimensions.
- Shipment statuses: FAILED (220), DELIVERED (80). No explicit lost status; do not invent one.
- SHP-0227 → FR-030af469e0 → RES-3f6cb49673 → OUT-040d90e150. Source `agent_pipeline`, outcome `pending`, success null.
- Existing uncommitted config/model compatibility edits and earlier notes preserved.

## Findings and ownership

- `/graph` uses generic subgraph functions against NEO4J_DATABASE; `/schema` uses governance schema. Explore backend owner will add shipment-scoped APIs and shared filters.
- Explore map previously calls missing legacy CSV endpoints. UI owner will implement shipment overview, status legend, compact card, graph context and case navigation.
- Translation stringifies provider block arrays and can return thinking to Arabic UI. LLM safety owner will normalize final content only, constrain structured DTOs and protect legacy SSE.
- Existing pending outcome semantics are correct in write-back; resolution existence is still different from verified operational success. Needs-attention overview must retain pending agent outcomes.
- Python runtime works but pytest is not an installed project dependency; use isolated test runner dependency or standard-library unittest rather than reinstalling the stack.

## Gate sequence

Batch 1 implementation → independent review/fix → Python/frontend checks, API/DB and AR/EN browser smoke. No Batch 2 mutation or product expansion before Batch 1 passes. Batches 1–5 must all pass before Expected Journey or other expansion.

No credentials or internal model reasoning are stored in this audit.
