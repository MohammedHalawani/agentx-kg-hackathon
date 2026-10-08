# Shipment product coherence — LLM safety review

Timestamp: 2026-10-07T22:24:55+03:00.

Manual diff review confirms the original Ollama key fallback and configured provider pass-through survive. Structured JSON extra keys cannot enter model stage state; declared string fields cannot contain provider content objects. Nested stage/candidate/precedent dictionaries are projected for SSE, and translation can no longer expose serialized reasoning blocks. Added defensive handling for malformed non-string block types/channels after review.

Changed legacy chat latency behavior is deliberate: progress still streams, completed final answer arrives together so split private tags cannot leak. The active complaint flow keeps its per-stage streaming behavior.

Limits: unmarked prose inside an otherwise valid final answer cannot reliably be classified as hidden reasoning by pattern matching. The contract relies on providers separating private reasoning and on prompts requiring brief final evidence summaries. Existing case-file graph properties come from curated database queries; this normalization does not rewrite unrelated historical database values. Browser Arabic/English regression verification belongs to the combined Batch 1 gate. No serious evaluation accuracy claim is made from this smoke.
