# Shipment product coherence — LLM safety implementation

Timestamp: 2026-10-07T22:24:55+03:00.

message_text now extracts supported final strings/text/output_text/OpenAI text.value/message envelopes without stringify fallback. Private block types, analysis channels, unknown blocks and empty/missing content produce no text. Explicit think/thinking/reasoning/analysis tags, labeled analysis/final prose and Harmony analysis/final transcripts are normalized before application parsing; incomplete private segments fail closed.

ask_json accepts JSON objects only, takes declared fields from each stage's default, validates scalar/list shapes, removes marked private prose from final fields, and fills missing/invalid fields from independent defaults. Raw fallback content is no longer logged. Translation uses the same final-only normalization on model content and marked source text, and retains existing Arabic/literal safeguards.

Pipeline live stage/final DTOs use application field allowlists; nested candidate/citation fields are separately constrained. The legacy chat sends tool progress, then one normalized completed assistant message; raw token deltas and reasoning are no longer emitted. Backend SSE accepts only the known complaint events and no legacy reasoning event. Provider exceptions are logged by type without full raw exception text at these request/translation boundaries.

Model, endpoint, temperature and API-key precedence remain unchanged. Frontend removal of the legacy reasoning display is handled by the Explore UI owner. No Explore implementation files edited here.
