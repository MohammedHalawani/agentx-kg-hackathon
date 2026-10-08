# Shipment product coherence — frontend implementation

Recorded: 2026-10-07 22:26 +03:00 (19:26 UTC).

Explore defaults to Map / Needs attention. Map and Graph share one GET /explore?filter=...&limit=25 result, selection, limit control (10/25/50), filter counts and bounded-result summary. Schema remains an explicit data-model lens, with shipment backend routing owned by the backend agent.

Supported filters: needs_attention, critical, stalled, delivered, all. Backend mapping: attention includes unresolved FailureReason, open escalation or pending recommendation; stalled adds recorded hub delay; critical adds evidence-based SLA breach or exhausted retry budget; delivered uses DELIVERED. No lost filter exists. Priority is explicitly derived, not an enterprise shipment attribute.

Map uses existing danger/warning/good/blue tokens with distinguishable marker glyphs and a text/icon legend. Markers describe destination addresses (or recorded origin when unavailable), not parcel GPS. A selected origin/destination dashed connection is labeled as expected connection, never traveled route; origin is approximate. Overlapping markers remain accessible through the complete shipment text list.

Selected card shows shipment ID, state/raw shipment status, recorded failure reasons, derived priority, origin/destination, last event and Intake action. Selection follows into the Graph lens via bounded GET /graph?shipment_id=...; graph node selection can select the matching shipment. Existing renderer controls are retained, overview reset and optional browser fullscreen added.

Open case in Intake reads connected graph evidence. Analyze exists only for a matching unresolved /samples entry and runs its canonical text. No model call or write-back occurs merely from navigation. Pending/historical views display an evidence-only explanation.

useFetch rejects HTTP errors, exposes an error state, clears old payloads and guards aborted responses. Explore/schema show error + retry, loading and empty states distinctly. Arabic controls, semantic statuses/events, explicit RTL text areas and Latin shipment identifiers are supported.

Legacy Message no longer passes provider reasoning to ReasoningTrace; useChatStream discards reasoning events. Recommendation write-back now says recommendation recorded / operational outcome pending in Arabic and English. Decisions Resolution coverage says recorded resolution, and learning copy requires verified outcomes for success rates.
