# V3 dataset corrections after live database validation — October 13, 2026

Branch `v3/scenarios`, on top of `6a2dd98a17da53c824645cd6ac6e2678b5b09658`. Contract `suhail-v3-1` is unchanged:
no field, name or bound of the route-evidence schema moved. The imported world
`shipments-v2-world-v3-20261013` was used read-only; nothing was reset, reimported or written.

## 1. Route-summary first/last timestamps (seven final snapshots)

**Cause.** `build_route_evidence` sorts observations by `(vehicle_id, route_run_id or trip_id, occurred_at, evidence_id)`,
which is the grouping the stationary-interval pairing needs. The summary then read `first_observed_at` and
`last_observed_at` from list positions `[0]` and `[-1]`, which are the first point of the first *vehicle* and the last
point of the last *vehicle*. With more than one vehicle context that is not time order (for `DEMO-SHP-000133` it produced
a last timestamp before the first).

**Fix.** `chat/operations/route_evidence.py`: first/last are the chronological extremes of the returned observations
(`occurred_at`, ties by `evidence_id`). Observation order, source IDs, receipt cutoffs, bounds and the eligibility
checks are untouched; `input_evidence_ids` still follows the list order.

**Regression test.** `test_v3_route_evidence.py::test_summary_spans_chronological_extremes_across_vehicle_contexts`
(two contexts whose vehicle order opposes time order; fails on the previous code).

## 2. Neutral packet parity (`DEMO-PROV-SPL`)

**Cause.** The live gateway (`operations/ingestion.py`) stamps every ingested record with its delivery envelope,
including `provider_id` of the delivering channel, and the read model loads the shared records a visible evidence
record references. `dataset_v2.feed.reconstitute` decodes payloads only, so the offline packet builder never saw the
delivering provider and did not load `DEMO-PROV-SPL`.

**Legitimacy.** The provider record is the shared catalogue entry for the channel that delivered a record the
investigator can already see. It is loaded under the same cutoff (`recorded_at <= as_of`, shared split) and the same
relationship scope (reachable only through relationships the evidence context already allows).

**Fix.** `world/v3_scenarios.py::_gateway_world` re-attaches the delivering provider to each first-delivered record
(`delivery_providers`). A payload that already names its own `provider_id` keeps it. Nothing else is expanded.
`packets` gains `--output-root` so corrected artifacts can be written beside, not over, the originals.

**Regression test.** `test_v3_scenarios.py::test_delivering_provider_reaches_packet_like_the_live_envelope`
(only provider records that delivered a visible record are added; no node is lost; domain provider is never replaced).

### Resolved at source: the live gateway overwrote the domain provider

`operations/ingestion.py` built the node as `{**props, **envelope}`, so the envelope's `provider_id` replaced a payload
`provider_id`. In the feed this hit 201 of 628 records that carry their own provider: 72 `Manifest`
(`DEMO-PROV-LMC-01` → `DEMO-PROV-SPL`), 49 `RouteRun` (30 `DEMO-PROV-INDEP-01`, 19 `DEMO-PROV-LMC-01`) and 80 `Trip`
(`DEMO-PROV-3PL-01`). For the curated set the only visible effect was `DEMO-SHP-000226` at the final snapshot: the live
view had no `DEMO-PROV-LMC-01` node, so the `OPERATED_BY` and `WORKS_FOR` relationships of that vehicle and driver were
not returned.

Fix (approved Option A): the gateway now keeps a record's own `provider_id` and lets the delivering channel fill it
only when the payload has none (`228e57c`, regression test `test_ingestion_provider_precedence.py`). The 201 stored
nodes were restored by `scripts/repair_provider_overwrite.py` (`0c2fb15`): property-only, one transaction, guarded per
node by channel provider, payload hash and feed id, rolled back unless exactly the planned nodes changed, restricted to
`shipments-v2-world-v3-20261013`. Result: 201 needed repair, 201 written, 201 repaired and every other property
unchanged; a second apply wrote 0. No relationship change was needed (`Trip` `OPERATED_BY` edges are built from the
payload and were already correct). No reimport or replay.

## 3. `DEMO-SHP-000051`

Intended as the innocent counterexample: an ordinary stop inside its planned window. It is outside every planted
mechanism (`test_vehicle_context_and_ordinary_single_stationary_sample` asserts this), the master plan describes it as
"Vehicle stop within expected journey window; no planted fault label, blame or automatic loss inference.", and the authored test catalogue
allows only `NO_EXCEPTION` or `NEEDS_EVIDENCE` for it. A read-only replica of the monitor rule
(`assess_shipment` with the 900 s detection allowance, then `monitor_finding`) over 422 hourly snapshots from its first
record to the final clock never opens a case; the same replica opens cases for the seven investigation shipments.
No scenario defect, no data or monitor change. It is a shipment-level reference, not an investigation case; the private
catalogue now says so (`qa_role`, `expected_monitor_case`). The expected open-case count is seven, not eight.

## Regenerated artifacts

Written to `C:\Projects\suhail-v3-data\world-v3-20261013\corrected-r1`; the originals are untouched.
Rebuild: `uv run python -m world.v3_scenarios packets --output-root <new empty directory>` (from `chat`; reads the
immutable bundle only). The `corrected-r1` set keeps the original bytes for `DEMO-SHP-000051`, the route fixture and the
route schema, because nothing they contain changes an ID, relationship or summary value (a fresh rebuild would add the
envelope `provider_id` property to fed source nodes there).

| Artifact | Old sha256 | New sha256 |
|---|---|---|
| neutral-packets/DEMO-SHP-000129.json | f471ea2f8397ad914527956fb0d644f643d64ad19cba06a1f974fcad6a409311 | 0b4783fa93c4ae59d837bddab4ffc7e84c6d44092a94200f7ed51587041336e1 |
| neutral-packets/DEMO-SHP-000133.json | 98fa8b47c6e4455ce079b2b564d379a44b1372d820e0495ee04089147535ec00 | 8faf667f98737e3d89e6ced042d2128dc67a38d56267965a95e6651cc8ee9ef9 |
| neutral-packets/DEMO-SHP-000134.json | c495ed28a1844a0d2a973d9aadaab0b1023c307c3d4e5e32342d0e2bfcced668 | ee004bd94ce86f9cb72f236e0cae2e4293ab15ea1ab4d445282bf458df83fe78 |
| neutral-packets/DEMO-SHP-000182.json | 8c33b023d8a7d8ee1077f08420313e3a4dc2122f87f3aaec476a0945445aadea | da5cfc1228a26159d3d977bd54c561dc85074b88f7125c0b59d0bae5bbb17ae1 |
| neutral-packets/DEMO-SHP-000194.json | 2e3f4deb4e7a3fc6e88ae4cffdd7c725d000caf2dc72bb34485c6c9a4bae7557 | 92f5eee9b332fa4c05e2fb7a395fb21aa826878d421f8c704c7ca3bbcc5543cc |
| neutral-packets/DEMO-SHP-000222.json | 2f7e6234be4098318e7f25c9f56f5f8436ff6b97c5b20e3bff45d9701a892230 | 80c0c5c9121592ef0ac37aeb89a6a50405362af977bfb016f2b8423a59644578 |
| neutral-packets/DEMO-SHP-000226.json | e9114cf751de919f096a45800e2995d6c46cca3ac82ba4f102243d4fef842ebb | 77d28a6163c3f62d7047c94fda612593dff9bb63de214d5686a5f1023f10b0a4 |
| runtime-fixtures.json | 225fe327dfbed91f03bdeaed2437146c5f4895a7e865185075dfb714c4938df3 | 159488d736e48f1d46c15241a49792d3254292aac4d8ee425160687530256c4f |
| composer-phase-b-handoff.r1.json (new copy of the handoff) | 7 of 8 packet hashes and the directory path superseded | b1838c7b4320a1408f83430df0e9367c26226136e5836902b96adec7c8c14686 |
| correction-manifest.json (new) | | 1d2eea0169c3ea393068b836d826a6ecbe77b0b4b782f9b5468df012286a1d03 |

Unchanged: `neutral-packets/DEMO-SHP-000051.json` `56cca0d0acc17cb7f38ccb03ce4b7315e28f614ded32118d3ace824d0b2eab76`,
`route-evidence.fixture.json` `3887e6b06eb8f88d01e094772511cc94a70e256d2498765f8cd5b8fc3f971d26`,
`route-evidence.schema.json` `ef0b23b61f5d81c9d1661a57b8af21d4c5d57ecaef9b69753de6f9fdb44f6dc3`, bundle manifest
`538d9fffe7c23cb9637be959e7c5ac0f83c76b3fab5c67b8e377e071d687e2b6`.

Composer references to update: the seven packet hashes, `runtime-fixtures.json`, and the handoff
(`composer-phase-b-handoff.r1.json` replaces `composer-phase-b-handoff.json`); the packet directory moves to
`corrected-r1\neutral-packets`. GPS observation IDs and values are identical in every packet.

## Verification (read-only against the imported development database)

All 24 corrected-set snapshots (8 shipments × before/after receipt/final) compared with the live read model:

| Check | Result |
|---|---|
| GPS observation IDs equal | 24/24 |
| Whole route summary equal (first, last, count, intervals) | 24/24 |
| first ≤ last and equal to the observations' chronological extremes | 24/24 |
| Node IDs equal | 24/24 (23/24 before the repair; only `DEMO-SHP-000226` final differed) |
| Relationship IDs equal | 24/24 (23/24 before the repair) |
| All observation and node times at or before the snapshot cutoff | 24/24 |
| Receipt visible only at the "after" cutoff | 24/24 |
| Every cited source ID resolves in the live graph under the cutoff | 24/24 |
| Forbidden private-answer keys in packets | none |

After the repair the 24 live snapshots changed in one place only: `DEMO-SHP-000226` at the final clock gained
`DEMO-PROV-LMC-01` and its two relationships, the intended effect. Reference and temporal integrity gates still pass
(0 unresolved references, 0 temporal violations), counts are unchanged (68,413 nodes, 101,104 relationships, 40,284
ingested records, 40,452 feed items, 7 operations cases). The seven previously wrong summaries were exactly the seven
final snapshots, as reported. The corrected packets (`corrected-r1`) are frozen; see `freeze-record.json` there.
