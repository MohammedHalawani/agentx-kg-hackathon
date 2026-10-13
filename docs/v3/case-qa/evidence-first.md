# Phase C — evidence-first notes (sealed)

**Sealed at:** `2026-10-13T18:05:00+00:00` (Composer Phase C, independent review)  
**Branch / code baseline:** `v3/route-ui` @ `273a21d` (Phase B UI; this document is QA-only)  
**Auditor role:** independent evidence reconstruction from frozen neutral packets only (no authored test catalogue read).

## Input integrity (verified before review)

| Artifact | SHA-256 |
|---|---|
| `composer-phase-b-handoff.r2.json` | `785ad5857729298701d4ca8eaadbaa6f86e170e51ea9bef2464a4a15a7a8b09f` |
| `freeze-record.json` | `f0d428e9e309e46c088f2776106ae6919cd9fe3f3d073c5842a9d4ba468de870` |
| `runtime-fixtures.json` | `159488d736e48f1d46c15241a49792d3254292aac4d8ee425160687530256c4f` |
| Neutral `DEMO-SHP-000051.json` | `56cca0d0acc17cb7f38ccb03ce4b7315e28f614ded32118d3ace824d0b2eab76` |
| Neutral `DEMO-SHP-000129.json` | `0b4783fa93c4ae59d837bddab4ffc7e84c6d44092a94200f7ed51587041336e1` |
| Neutral `DEMO-SHP-000133.json` | `8faf667f98737e3d89e6ced042d2128dc67a38d56267965a95e6651cc8ee9ef9` |
| Neutral `DEMO-SHP-000134.json` | `ee004bd94ce86f9cb72f236e0cae2e4293ab15ea1ab4d445282bf458df83fe78` |
| Neutral `DEMO-SHP-000182.json` | `da5cfc1228a26159d3d977bd54c561dc85074b88f7125c0b59d0bae5bbb17ae1` |
| Neutral `DEMO-SHP-000194.json` | `92f5eee9b332fa4c05e2fb7a395fb21aa826878d421f8c704c7ca3bbcc5543cc` |
| Neutral `DEMO-SHP-000222.json` | `80c0c5c9121592ef0ac37aeb89a6a50405362af977bfb016f2b8423a59644578` |
| Neutral `DEMO-SHP-000226.json` | `77d28a6163c3f62d7047c94fda612593dff9bb63de214d5686a5f1023f10b0a4` |

Freeze record (`corrected-r1`): `frozen: true`, integrity gates `references` / `temporal` **pass**, live parity **24/24**, seven monitor cases plus shipment-level reference for `DEMO-SHP-000051`.

**Method:** three temporal snapshots per packet (`as_of` cutoffs in each file). Reconstruction uses final snapshot `2026-10-01T21:00:00+00:00` unless cutoff visibility is explicitly tested against snapshot 1 vs 3.

**Case IDs** (from `composer-live-supplement.json`, not embedded in neutral packets): seven `DEMO-OPS-CASE-*` rows mapped to shipments 129, 133, 134, 182, 194, 222, 226; all `OPEN` at supplement time. **No case** for `DEMO-SHP-000051`.

---

## DEMO-SHP-000051 — ordinary planned-stop control (no investigation case)

**Wire IDs:** `SYN-SHP-000051`; monitor case **none** (freeze: 0/422 hourly evaluations opened a case).

### Chronology (final horizon)

1. Hub/depot custody and scans from `DEMO-SHP-000051-SCAN-001` (`2026-09-14T08:30:31+00:00`) through network handling.
2. Last-mile progression: `DEMO-SHP-000051-SCAN-006` … `DEMO-SHP-000051-SCAN-009` on `2026-09-15` (depot / route scans).
3. Delivery closure: `DEMO-SHP-000051-SCAN-010` at `2026-09-15T07:07:33+00:00` (occurrence aligns with delivery scan), `DEMO-SHP-000051-PROOF-001` (occ `2026-09-15T07:07:33+00:00`, rec `2026-09-15T07:08:24+00:00`), `DEMO-SHP-000051-AUTH-001` **PASS**, `DEMO-SHP-000051-HANDOFF-001`, photo/signature chain.
4. Custody chain: `DEMO-SHP-000051-CUST-001` … `DEMO-SHP-000051-CUST-008`.

### Cutoff / receipt

- Early snapshot cutoffs: `2026-09-15T05:17:41+00:00` / `+42s`. `DEMO-SHP-000051-PROOF-001` and late scans **absent** at early cutoff; **present** at final horizon — consistent with `recorded_at` after investigation-style cutoff.
- Example: `DEMO-SHP-000051-SCAN-009` (fixture anchor in `runtime-fixtures.json`) appears only after early cutoff.

### Route / GPS

- 12 vehicle observations at horizon; summary `first_observed_at` / `last_observed_at` match observation extrema (**no summary mismatch** on corrected packet).
- Summary note: *"Vehicle observations only; gaps do not establish continuous stopping or parcel custody."*
- GPS IDs such as `DEMO-GPS-*` carry `evidence_id`; **do not** substitute for delivery proof (delivery established by scan/proof/auth, not GPS alone).

### Alternatives / disposition

- Plausible reading: unremarkable planned stop, delivered with aligned proof and auth.
- **Operational support:** shipment view and route evidence sufficient for a control; no case expected.

### Key source IDs

`DEMO-SHP-000051-SCAN-009`, `DEMO-SHP-000051-SCAN-010`, `DEMO-SHP-000051-PROOF-001`, `DEMO-SHP-000051-AUTH-001`, `DEMO-SHP-000051-CUST-008`, `DEMO-PROV-SPL`.

---

## DEMO-SHP-000129 — linehaul delay (case `DEMO-OPS-CASE-531db2c7f1a06dc00e3efb2a`)

### Chronology

1. Origin handling from `DEMO-SHP-000129-SCAN-001` / `-002` (`2026-09-14T13:09:*`).
2. Load / hub activity: `DEMO-SHP-000129-SCAN-003` … `-010` same day; **overnight gap** before `DEMO-SHP-000129-SCAN-011` (`2026-09-14T23:00:00+00:00`) and continued hub/linehaul scans through `2026-09-15`–`2026-09-16` (`-015` … `-024`).
3. Final delivery: `DEMO-SHP-000129-SCAN-025` / `-026` at `2026-09-17T05:52:*` with `DEMO-SHP-000129-PROOF-001` / `-002` and signatures.
4. Custody: 20 `DEMO-SHP-000129-CUST-*` events; multi-leg journey consistent with extended hub/linehaul timeline.

### Cutoff / receipt

- Investigation cutoffs: `2026-09-14T17:04:20+00:00` / `+21s`.
- `DEMO-SHP-000129-SCAN-003` (occ `2026-09-14T17:01:17+00:00`, rec `2026-09-14T17:04:21+00:00`) **missing** at early cutoff, **visible** at late — receipt-after-occurrence behavior demonstrated.
- Delivery proofs absent at early cutoff; present at horizon.

### Route / GPS

- 54 vehicle observations; summary matches extrema; vehicle-only disclaimer present.
- Providers in graph: `DEMO-PROV-INDEP-01`, `DEMO-PROV-SPL`.

### Alternatives / disposition

- Primary: **linehaul / hub delay** (multi-day scan cadence, late proofs).
- Weaker: mis-sort or failed attempt — less supported than extended network time visible in scan/custody sequence.
- **Support:** further timeline review or hub check; case remains **OPEN** at supplement.

### Key source IDs

`DEMO-SHP-000129-SCAN-003`, `DEMO-SHP-000129-SCAN-011`, `DEMO-SHP-000129-SCAN-015`, `DEMO-SHP-000129-SCAN-025`, `DEMO-SHP-000129-PROOF-001`, `DEMO-SHP-000129-CUST-020`.

---

## DEMO-SHP-000133 — offline-device delayed evidence (case `DEMO-OPS-CASE-2f3547b645f8d57dbd8fd322`)

### Chronology

1. Network scans from `DEMO-SHP-000133-SCAN-001` / `-002` (`2026-09-15T14:20:*`).
2. **Buffered handheld evidence:** `DEMO-SHP-000133-SCAN-003` occurred `2026-09-15T16:15:39+00:00` but **recorded** `2026-09-16T04:09:37+00:00` (~12 h lag).
3. Continued handling scans through `2026-09-18` hub/depot activity (`-011` … `-022`).
4. Delivery `2026-09-19`: `DEMO-SHP-000133-SCAN-025` / `-026`, proofs, **PASS** auth (`DEMO-SHP-000133-AUTH-001`, `-002`), handoff and photo evidence.

### Cutoff / receipt

- Cutoffs aligned to buffered upload: `2026-09-16T04:09:36+00:00` / `+37s`.
- `DEMO-SHP-000133-SCAN-003` **absent** at first snapshot, **present** at second — correct temporal fence for delayed sync.
- Runtime fixture anchor: `DEMO-SHP-000133-SCAN-003`.

### Route / GPS

- 50 observations; summary/extrema aligned; no route observation `recorded_at < observed_at` violations in automated pass.

### Alternatives / disposition

- Primary: **DELAYED_SYNC / device outage** (occurred vs recorded gap on `-SCAN-003`).
- Delivery auth **PASS** at horizon — does not erase earlier sync problem; supports “explain delay, confirm eventual delivery.”
- **Support:** device sync request + custody replay; human review if monitor opened on delay alone.

### Key source IDs

`DEMO-SHP-000133-SCAN-003`, `DEMO-SHP-000133-SCAN-011`, `DEMO-SHP-000133-PROOF-001`, `DEMO-SHP-000133-AUTH-001`, `DEMO-DEV-HH-HUB-DMM-01` (device graph presence).

---

## DEMO-SHP-000134 — related device incident (case `DEMO-OPS-CASE-e8d589f5e15d9edb8f7da1ee`)

### Chronology

1. Multi-parcel style journey: 36 scans, 30 custody events, three delivery proofs (`-PROOF-001` … `-003`) on `2026-09-17T06:06–06:07`.
2. **Same delayed-upload pattern as 133:** `DEMO-SHP-000134-SCAN-004` occ `2026-09-15T16:14:19+00:00`, rec `2026-09-16T04:09:17+00:00`.
3. Early cutoff `2026-09-16T04:09:16+00:00`: `-SCAN-004` hidden; visible at horizon.

### Device / cross-shipment relationship

- Shared facility/device graph nodes with 133 (e.g. `DEMO-DEV-HH-HUB-DMM-01`, `DEMO-DEV-APP-DRV-FM-KHB-005`, sort/handheld IDs) — consistent with **related device incident**, not an independent outage story.

### Route / GPS

- 29 observations; summary aligned; providers `DEMO-PROV-INDEP-01`, `DEMO-PROV-SPL`.

### Alternatives / disposition

- Primary: **shared device buffering** affecting this shipment’s scan visibility timeline.
- Delivered at horizon with triple proof chain — tension is **timeliness of evidence**, not missing delivery records.
- **Support:** cross-shipment device check (134 with 133), not GPS-only closure.

### Key source IDs

`DEMO-SHP-000134-SCAN-004` (runtime fixture anchor), `DEMO-SHP-000134-PROOF-003`, `DEMO-DEV-HH-HUB-DMM-01`, `DEMO-DEV-APP-DRV-FM-KHB-005`.

---

## DEMO-SHP-000182 — disputed delivery (case `DEMO-OPS-CASE-1300f172fe7e9db69793599e`)

### Chronology

1. Scans from `DEMO-SHP-000182-SCAN-001` through network path to `DEMO-SHP-000182-SCAN-014` (`2026-09-19T07:00:30+00:00` delivery scan time).
2. `DEMO-SHP-000182-PROOF-001` (occ/rec `2026-09-19T07:00:30` / `07:01:47`), `DEMO-SHP-000182-AUTH-001` **PASS** (`SYNTHETIC_PIN`).
3. **Recipient dispute then partial resolution:**
   - `DEMO-SHP-000182-REPORT-001` `NOT_RECEIVED` (`2026-09-20T07:35:33+00:00`) — “marked delivered, not with me.”
   - `DEMO-SHP-000182-REPORT-002` `RECEIVED_CONFIRMATION` (`2026-09-20T18:21:04+00:00`) — recipient retracts.

### Cutoff / receipt

- Investigation cutoffs `2026-09-16T15:53:51+00:00` / `+52s`: proof and late scans absent early, present at horizon.
- Recipient reports occur **before** final packet horizon `2026-10-01T21:00:00+00:00` — visible at horizon (post-delivery dispute window).

### Route / GPS

- 52 observations; vehicle-only summary note; GPS does not override proof/auth.

### Alternatives / disposition

- Tension: **PASS auth + proof vs NOT_RECEIVED report** — legitimate dispute until `REPORT-002`.
- Plausible escalation: contact recipient / driver before closing case despite PASS auth.
- **Support:** human review of dispute thread; do not auto-resolve on auth alone.

### Key source IDs

`DEMO-SHP-000182-SCAN-007`, `DEMO-SHP-000182-PROOF-001`, `DEMO-SHP-000182-AUTH-001`, `DEMO-SHP-000182-REPORT-001`, `DEMO-SHP-000182-REPORT-002`.

---

## DEMO-SHP-000194 — late evidence and disputed handoff (case `DEMO-OPS-CASE-cfc4f4cf4502bef108c682d3`)

### Chronology

1. Scans through `DEMO-SHP-000194-SCAN-014` at delivery occurrence `2026-09-19T07:01:49+00:00`.
2. `DEMO-SHP-000194-PROOF-001` present; `DEMO-SHP-000194-AUTH-001` **FAIL** (`SYNTHETIC_PIN`).
3. `DEMO-SHP-000194-REPORT-001` `NOT_RECEIVED` (`2026-09-20T03:40:58+00:00`) — disputes delivered status.

### Cutoff / receipt

- Cutoffs `2026-09-16T04:09:24+00:00` / `+25s`; proof absent at early snapshot.
- Auth failure recorded **after** occurrence (rec `2026-09-19T07:03:13+00:00`) — investigator at earlier cutoff would not see full delivery/auth bundle.

### Route / GPS

- 58 observations; summary aligned.

### Alternatives / disposition

- Primary: **failed authentication + recipient denial** despite delivery scan/proof — high ambiguity.
- Weaker: GPS proximity as proof — explicitly disclaimed in route summary.
- **Support:** escalation / re-attempt verification; **do not** mark delivered-safe from GPS.

### Key source IDs

`DEMO-SHP-000194-SCAN-002`, `DEMO-SHP-000194-PROOF-001`, `DEMO-SHP-000194-AUTH-001`, `DEMO-SHP-000194-REPORT-001`.

---

## DEMO-SHP-000222 — photograph with failed authentication (case `DEMO-OPS-CASE-bbb2ddc9945afee11567862c`)

### Chronology

1. Scans through `DEMO-SHP-000222-SCAN-013` (`2026-09-19T06:43:46+00:00`).
2. `DEMO-SHP-000222-PHOTO-001` (`media_ref` synthetic, `no_image_generated: true`, `source_ref: driver-app`, `provider_id: DEMO-PROV-INDEP-01`) tied to attempt `DEMO-SHP-000222-ATT-001`.
3. `DEMO-SHP-000222-PROOF-001` + `DEMO-SHP-000222-AUTH-001` **FAIL** (`SYNTHETIC_OTP`).
4. `DEMO-SHP-000222-REPORT-001` `NOT_RECEIVED` (`2026-09-20T12:22:10+00:00`).

### Cutoff / receipt

- Cutoffs `2026-09-16T14:58:21+00:00` / `+22s`; delivery bundle absent at first snapshot.

### Route / GPS

- 52 observations; same vehicle-only disclaimer.

### Alternatives / disposition

- Primary: **photo present but auth failed** + recipient denial — photo cannot be treated as authenticated delivery.
- UI must not imply OTP success; chronology should show FAIL auth adjacent to photo/proof.
- **Support:** manual review of photo/authentication pipeline; escalation.

### Key source IDs

`DEMO-SHP-000222-SCAN-005`, `DEMO-SHP-000222-PHOTO-001`, `DEMO-SHP-000222-PROOF-001`, `DEMO-SHP-000222-AUTH-001`, `DEMO-SHP-000222-REPORT-001`.

---

## DEMO-SHP-000226 — traffic / route delay context (case `DEMO-OPS-CASE-bd0988ae91406616ef925238`)

### Chronology

1. Scans from `DEMO-SHP-000226-SCAN-001` (`2026-09-16T18:45:19+00:00`) through **`DEMO-SHP-000226-SCAN-017`** (`2026-09-21T18:31:00+00:00`) — **no** `DeliveryProof` at horizon.
2. `latest_status` in permitted overview: **OUT_FOR_DELIVERY** (not delivered).
3. Multiple route runs / drivers / vehicles in graph (5 assignments, 2 route runs) — ongoing attempts.
4. Custody through `DEMO-SHP-000226-CUST-012`; depot reconciliations present; **no** auth/proof/recipient reports.

### Cutoff / receipt

- Cutoffs `2026-09-17T15:09:44+00:00` / `+45s`; many later scans invisible at first snapshot (expected).

### Route / GPS

- 17 vehicle observations; **empty** `timing_comparisons`; **no** `TrafficObservation` nodes in source graph.
- Delay narrative must come from **scan cadence + OFD status + vehicle path gaps**, not traffic feed records.

### Alternatives / disposition

- Primary: **in-flight route delay / unfinished delivery** at dataset horizon.
- Weaker: treat as delivered — **refuted** (no proof, status OFD).
- **Support:** continue monitoring, next-session delivery; case should stay open.

### Key source IDs

`DEMO-SHP-000226-SCAN-005`, `DEMO-SHP-000226-SCAN-013`, `DEMO-SHP-000226-SCAN-017`, `DEMO-SHP-000226-STATUS-006`, `DEMO-SHP-000226-CUST-012`.

---

## V2 video references (read-only; not neutral V3 packets)

| Shipment | Material reviewed | Evidence-first result |
|---|---|---|
| `SYN-SHP-000304` | No frozen neutral packet under `corrected-r1`; no V3 parity hash | **Not checked** (insufficient neutral source packet) |
| `SYN-SHP-000443` | UI recording map `frontend-next/recording/maps/evidence_map_B_SYN-SHP-000443.json` (highlight IDs from prior genuine run; synthetic showcase metadata) | **Not checked** against V3 dataset (not a neutral packet) |

---

## Cross-cutting findings (all development shipments)

1. **Temporal integrity (packets):** zero route-observation cases with `recorded_at < observed_at` in automated pass; freeze gate **temporal: pass**.
2. **Summary vs observations:** all eight final snapshots — `route_evidence.summary.first/last_observed_at` match observation extrema (post r2 correction).
3. **GPS ≠ delivery:** every packet includes explicit vehicle-only summary note; delivery claims require scan/proof/auth/recipient records cited above.
4. **Provider nodes:** `DEMO-PROV-SPL` present in final snapshots (parity concern from Phase B prep **closed** in r2 freeze).
5. **Receipt lag pattern:** scans universally have `recorded_at >= occurred_at`; large gaps (133 `-SCAN-003`, 134 `-SCAN-004`) drive cutoff visibility tests.

---

**End of sealed evidence-first notes.** Catalogue comparison belongs only in `case-audit-report.md` appendix (written after this seal).
