# Phase C — evidence-first packet inventory (prepared, not certified)

Prepared during Composer Phase B. **Do not treat this as completed Phase C QA.** Final signoff waits for corrected neutral packets, updated hashes and the dataset checkpoint from Sol.

Contract: `suhail-v3-1`. Supplement: `C:\Projects\suhail-v3-plan-2026-10-13\hour4\composer-live-supplement.json`. Handoff hashes: `C:\Projects\suhail-v3-data\world-v3-20261013\composer-phase-b-handoff.json`.

## Curated development shipments (8)

| Role | Shipment (storage) | Shipment (wire) | Case (wire, when present) | Neutral packet SHA (pending refresh) |
|---|---|---|---|---|
| Normal / reference | DEMO-SHP-000051 | SYN-SHP-000051 | *(no monitor case at final horizon — REVIEW)* | `56cca0d0…` |
| Curated 1 | DEMO-SHP-000129 | SYN-SHP-000129 | SYN-OPS-CASE-531db2c7f1a06dc00e3efb2a | `f471ea2f…` |
| Curated 2 | DEMO-SHP-000133 | SYN-SHP-000133 | SYN-OPS-CASE-2f3547b645f8d57dbd8fd322 | `98fa8b47…` |
| Curated 3 | DEMO-SHP-000134 | SYN-SHP-000134 | SYN-OPS-CASE-e8d589f5e15d9edb8f7da1ee | `c495ed28…` |
| Curated 4 | DEMO-SHP-000182 | SYN-SHP-000182 | SYN-OPS-CASE-1300f172fe7e9db69793599e | `8c33b023…` |
| Curated 5 | DEMO-SHP-000194 | SYN-SHP-000194 | SYN-OPS-CASE-cfc4f4cf4502bef108c682d3 | `2e3f4deb…` |
| Curated 6 | DEMO-SHP-000222 | SYN-SHP-000222 | SYN-OPS-CASE-bbb2ddc9945afee11567862c | `2f7e6234…` |
| Curated 7 | DEMO-SHP-000226 | SYN-SHP-000226 | SYN-OPS-CASE-bd0988ae91406616ef925238 | `e9114cf7…` |

Route/GPS deterministic UI fixture (Phase B tests): `SYN-SHP-000051`, wire copy SHA256 `3887e6b06eb8f88d01e094772511cc94a70e256d2498765f8cd5b8fc3f971d26`.

## V2 video references (read-only)

| Shipment (wire) | Notes |
|---|---|
| SYN-SHP-000304 | Original video A reference; evidence-first review only if read-only snapshots exist |
| SYN-SHP-000443 | Original video B reference; same |

## Open backend/data gates before Phase C signoff

1. **Route summary chronology** — do not trust `summary.first_observed_at` / `last_observed_at` for QA; UI timelines use observation extrema; Sol fix pending on `route_evidence.py`.
2. **Neutral packet parity** — live `DEMO-PROV-SPL` omitted from offline packets; await Sol alignment and hash refresh.
3. **DEMO-SHP-000051 case mapping** — confirm normal-control shipment-view QA vs monitor defect.

## Phase C deliverables (when authorized)

- `evidence-first.md` — immutable first-pass notes per shipment
- `case-audit-matrix.csv` — PASS / REVIEW / FAIL with source citations
- `case-audit-report.md` — catalogue comparison appended after packet refresh

Hard budget: four hours. Catalogue withheld until first-pass notes are committed.
