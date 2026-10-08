# Shipment product coherence — frontend audit

Recorded: 2026-10-07 22:26 +03:00 (19:26 UTC).
Owner: Explore UI subagent. Scope: Batch 1 only; no Phase 8 redesign.

ExploreView offered Graph/Schema only, with BrainView reading the generic /graph endpoint. No operational map, shared shipment filters, selected-shipment workflow, text alternative, or transport error state existed. The legacy map artifact described housing/pollution data and was unsuitable for an active shipment overview.

Existing GraphView supports 2D zoom, fit, entity legend and layouts; BrainGraph provides 3D orbit navigation. Reuse these renderers with optional shipment selection callbacks. No new graph library is required.

Intake originally starts a complaint when its queue row is clicked. Navigation from Explore must only inspect shipment evidence: agent execution remains explicit and uses a genuine unresolved worklist complaint. Pending/historical cases must not acquire a new run action from navigation.

Intake final wording incorrectly asserted execution and closed-loop precedent after recommendation write-back. Decisions coverage described Resolution presence as resolved. These labels require evidence-faithful wording independently of later human/outcome lifecycle work.

The backend owner verified statuses FAILED/DELIVERED and safely derived attention/stalled/critical categories. Lost/unaccounted is unsupported and remains absent. Frontend must consume those classification fields rather than independently invent statuses. Warehouse origin is a city centroid and must be explicitly approximate.

No repository AGENTS.md was found in the repository or its checked parent roots. React best-practices skill was read for component quality review.
