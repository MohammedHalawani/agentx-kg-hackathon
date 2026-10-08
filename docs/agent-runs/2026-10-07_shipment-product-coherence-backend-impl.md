# Shipment product coherence — backend implementation

Timestamp: 2026-10-07T22:20:00+03:00. Run: `2026-10-07_shipment-product-coherence`.

Added chat/core/explore.py with fixed parameterized read queries against SHIPMENT_DATABASE.
The shared shipment summary computes needs_attention/all/stalled/critical/delivered
membership once and provides the same selected IDs to the curated graph. Raw shipment status,
recorded root-cause categories, pending recommendation state, and operational rule flags are
kept separate. Priority is explicitly derived from those rules.

Added `/explore` with validated filter/limit; `/graph` now supports a selected shipment or
the default attention selection. `/schema` introspects SHIPMENT_DATABASE. The legacy query
catalog's run() still targets its existing governance database; no broad database migration
was attempted. Unused active sampler import was removed from backend/main.py.

Map pins validate finite/range-correct Address coordinates. Existing warehouse coordinates
are exposed as approximate city centroids, not precise facilities. Census cap 1000,
result limit 50, graph caps 1201 paths / 500 nodes / 800 edges, and explicit truncation fields
bound the read/response scope. Hub branches are terminal and do not pull in other shipments.

Added docs/explore-shipment-contract.md and six non-mutating unittest checks. All work is
uncommitted; no dependency changes, environment changes, database mutations, or model calls.
