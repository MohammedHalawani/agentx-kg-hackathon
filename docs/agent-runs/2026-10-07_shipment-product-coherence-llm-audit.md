# Shipment product coherence — LLM safety audit

Timestamp: 2026-10-07T22:24:55+03:00. Scope: Batch 1D and focused Batch 5 provider compatibility tests. No repository AGENTS.md instructions were found. Existing uncommitted config/model normalization changes are preserved and extended. No credentials printed or database mutations performed.

The pipeline's initial message_text helper accepted a text key on any provider block and stringified unsupported or reasoning-only content. Translation separately stringified the entire content array; an Arabic final block therefore caused a serialized thinking block to pass Arabic/literal checks and reach AgentProse. This matches the observed translation instruction prose leak.

ask_json merged arbitrary provider JSON fields into stage state; pipeline stage/final DTOs copied entire model dictionaries. parse_json accepted non-object JSON, which could crash the merge. Invalid model output was logged raw. The legacy chat stream separately emitted reasoning_content and unsanitized token deltas; partial private tags cannot safely be removed after already sending text.

Provider configuration already included LLM_API_KEY -> OPENAI_API_KEY -> OLLAMA_API_KEY fallback. Preserve this order, configured model and base; do not replace Ollama Cloud routing with a different provider.
