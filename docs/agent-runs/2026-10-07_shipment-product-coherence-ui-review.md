# Shipment product coherence — frontend review/fix

Recorded: 2026-10-07 22:26 +03:00 (19:26 UTC).

Review covered React hook order/dependencies, abort handling, user-data rendering, keyboard text alternatives, Arabic/Latin bidirectional text, explicit action boundary and status semantics. No raw HTML contains user-supplied values: Leaflet marker HTML contains static glyphs and trusted stylesheet tokens only; operational fields render through React.

Coordinator review fixes applied: icon/text map legend; schema transport error/retry; neutral historical shipment label; canonical unresolved complaint gating for Intake analysis; recommendation/outcome wording. The Map theme dependency is documented and locally suppressed because stylesheet token reads are external to React. Shared visual constants moved out of the component module to avoid Fast Refresh warnings.

First new component test run failed because filter accessible names had no separating space before counts. Added real whitespace to filter button names and reran successfully. This was a test-discovered accessibility detail, not an API failure.

22:28 +03:00 follow-up: coordinator integrated suite exposed a stale Intake assertion for Executed. Updated its expectation to recorded recommendation, pending operational execution/outcome and absence of an Executed label. Coordinator also removed an unsupported testing-library role-query option during the final TypeScript build.

Known presentation limits: multiple shipments can share an address, so the text list is the unambiguous selection mechanism; markers show addresses, not live tracking. The basemap uses public OpenStreetMap tiles. Existing 3D/bundle size and baseline lint warnings remain for later optimization. This batch deliberately preserves the broader product layout.
