# Composer Phase B — implementation report

Branch: `v3/route-ui`. Contract: `suhail-v3-1`. Fixture: `tests/fixtures/v3-route-evidence.wire.json` (SHA256 `3887e6b06eb8f88d01e094772511cc94a70e256d2498765f8cd5b8fc3f971d26`).

## Implemented

- V3 wire types: `active_cases`, `route_evidence`, enriched layer points, `investigation_status`.
- Adapters: merge route source graph; GPS requires `evidence_id`; vehicle paths segmented by vehicle/context; chronology from observations (summary mismatch flagged, not used as timeline truth); `shouldApplyPipeline` stale-run fencing.
- Service: `workerConnectionOf`, multi-active detail refresh, passive SSE for active claims, capacity refusal → `investigationQueued` / queued UX (no synthetic failure).
- UI: dual active cards on Operations, evidence chronology + receipt times, map segment polylines, legacy single-worker gate only when `active_cases` absent.

## Backend dependencies (still open — do not UI-compensate)

1. Route summary first/last timestamps wrong in 7 end snapshots (Sol `route_evidence.py`).
2. Neutral packet vs live provider `DEMO-PROV-SPL` parity (19 snapshots).
3. `DEMO-SHP-000051` normal-control case mapping at final horizon.
4. Live Opus `worker.active_cases` contract on production backend (`live_opus_status_contract_verified: false` in supplement).

## Phase C readiness

- Packet inventory prepared: `docs/v3/case-qa/phase-c-packet-inventory.md`.
- **Not started:** evidence-first notes, matrix, catalogue comparison — blocked on corrected neutral packets + updated hashes from Sol.
- V2 references: `SYN-SHP-000304`, `SYN-SHP-000443` (read-only when evidence available).

## Tests (Phase B run)

| Command | Result |
|---|---|
| `npm run typecheck` | Pass |
| Unit (`api-adapters`, `api-service`) | 39/39 pass |
| `npm run build` | Pass |
| `connected.spec.ts` | 17/17 pass |
| `v3-evidence.spec.ts` | 2/2 pass |
| `v3-concurrency.spec.ts` | 1/1 pass |
