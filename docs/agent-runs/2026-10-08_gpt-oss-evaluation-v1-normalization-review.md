# Serialized final-content normalization review

Recorded 2026-10-08T13:20:00+03:00. Baseline correction before the paired evaluation is frozen.

Inspection found the existing Harmony branch handled bracket shorthand only. It now
normalizes serialized im_* token spellings and named start/channel/message/end/return aliases,
then selects explicit final assistant messages. Analysis/commentary, user/tool/recipient
messages and recognized incomplete transcripts return no operator text. A later analysis
message cannot become part of an earlier final answer. Plain final strings and supported
provider content blocks continue through the existing application-field sanitizer.

This is conservative transcript filtering, not a general natural-language reasoning detector.
Providers still need to separate unmarked final prose from private content. No model prompt,
business policy or database value changed.

The token/channel distinction was checked against the primary
[OpenAI Harmony documentation](https://developers.openai.com/cookbook/articles/openai-harmony).
Tests exercise original tokens, current named aliases, bracket shorthand, Arabic final
content, final JSON, analysis-only/incomplete messages, other roles, tool recipients and
adjacent later analysis. A test exposed a first-message start-marker parsing error; that
was corrected before verification.

On resume, all 54 Python tests passed from chat with
`uv run python -m unittest discover -s tests -v`; this includes 21 final-content/config/SSE
tests. Git diff whitespace verification and the 315-file secret scan passed. The local
read-only API gate also passed after resume: 300 shipments, 70 needing attention, 28 critical,
16 stalled, 80 delivered; 73 open failures, 165 recorded synthetic observations and two
pending recommendations. Its independent snapshot is
`2026-10-08_shipment-baseline-resume-api.json`. Prior Batch 1/2 proof artifacts are preserved.

The earlier evaluation-agent turns ended at the account usage limit. Their partial evaluator
source is retained; no frozen bundle or cloud benchmark results existed at resume. Harness
tests and independent fairness review are required before the first model call.
