# Shipment product coherence — backend review

Timestamp: 2026-10-07T22:20:00+03:00. Run: `2026-10-07_shipment-product-coherence`.

Review focused on bounded queries, state truth, filter parity, and misleading map evidence.
The shared summary prevents map/list/graph filter drift; successful recommendations do not
change Shipment.status. Outcome.success null remains an attention case. No lost label or
unsupported coordinate/time/delivery inference is introduced. Critical is justified by
recorded SLA/retry/open-escalation evidence and is labelled as operationally derived.

Every query is fixed and parameters are bound. All graph calls target SHIPMENT_DATABASE
with READ routing. Curated branches keep Courier and Policy terminal; no graph-driven
execution or complaint writes occur. Embedding properties are omitted. Node caps prioritize
shipments and relationship caps preserve endpoint closure.

Unknown shipment IDs produce an empty selected graph. Invalid filters and out-of-range
limits are rejected by FastAPI. Empty filters return empty graphs. Missing/non-finite or
invalid coordinates are omitted. Address city remains available even if its coordinates
cannot be mapped. The response distinguishes result truncation from census-scope truncation.

Limitations: warehouse pins remain approximate; lines between endpoints are not actual route
history. The dataset has historical event times, so SLA elapsed time uses its first/latest
event interval rather than wall-clock ageing. Counts above 1000 shipments are explicitly
bounded. Legacy governance catalog/helper files remain for inactive legacy paths.
