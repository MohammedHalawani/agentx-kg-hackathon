# Suhail Operations UI V2 — UX audit (2026-10-08)

Branch: `ui/suhail-operations-v2` (worktree `demo-ui`)

## Scope

Frontend-only foundation for operational shipment-exception investigation. V1 APIs preserved; V2 fields optional with adapters and fixtures.

## Current-state audit (pre-V2)

| Area | Finding | V2 direction |
|------|---------|--------------|
| **Intake** | Flat open-case list; agent trace reads like a dev pipeline | Operational queue, filters, pagination, case workspace with structured trace |
| **Decisions** | Strong KPIs from `/cases` | Grouped shell: operational status, resolution quality, learning, pending outcomes, escalations |
| **Explore** | Graph/schema only on `main`; no `/explore` | Map/list hierarchy with fixture fallback; layer controls disabled until backend exists |
| **Navigation** | Intake / Decisions / Explore | Add **Audit** primary nav item |
| **Status** | Category labels + chart colors | Operational shipment states with icon + label (never color-only) |
| **Agent trace** | Raw stage cards | Collapsed operational steps: evidence → similar cases → hypothesis → recommendation → review → decision → outcome |
| **Arabic/RTL** | Intake column `dir` fixes | All new strings EN/AR; maps stay LTR; chronological order preserved |
| **Mobile** | Sidebar + scroll | Filter stacks, no horizontal overflow, touch-friendly controls |

## Operational visual language

Shipment-facing states (icon + label + optional border pattern; color is never sole indicator):

| State | Semantics | Visual |
|-------|-----------|--------|
| ON TIME | Within SLA | Package check, green |
| SLA RISK | Approaching breach | Timer, warning, dashed border |
| CRITICAL | Immediate ops attention | Alert triangle, danger |
| UNRECONCILED CUSTODY | Chain-of-custody gap | Shield, orange |
| DELIVERY DISPUTE | Customer dispute | Scale, orange |
| ADDRESS CONFLICT | Conflicting addresses | Map pin off, blue dashed |
| RECIPIENT UNAVAILABLE | Failed contact | User X, warning dashed |
| HUB DELAY | Hub backlog | Truck, warning dashed |
| RESOLVED | Verified closure | Check, green |

Case workflow (distinct from shipment health): OPEN → INVESTIGATING → RECOMMENDATION_READY → AWAITING_APPROVAL → AWAITING_OUTCOME → RESOLVED, plus NEEDS_EVIDENCE, HUMAN_REVIEW, ESCALATED, REOPENED.

**Rule:** Recommendation generation must not visually skip to RESOLVED; only verified outcome may close.

## Mock vs live

| Feature | Live (V1) | Fixture/demo |
|---------|-----------|----------------|
| Open case list | `/samples` | — |
| Pipeline run | `/complaint` SSE | — |
| Queue bucket counters (beyond Open) | — | Simulation + labeled fixture buckets |
| Process queue worker | — | UI shell only; DEMO label |
| Live simulation | — | `useQueueSimulation` |
| Audit history | — | `FIXTURE_AUDIT_EVENTS` |
| Explore map/list at scale | `/explore` when on fhd backend | `EXPLORE_DEMO_FIXTURE` fallback |
| Time-range filters | — | Disabled until `opened_at` |
| Decisions KPIs | `/cases` | Pending-outcome metrics placeholder |

## Accessibility & motion

- Keyboard-focusable filters, tabs, pagination, simulation controls
- `sr-only` / `aria-*` on icons and pagination
- `prefers-reduced-motion` respected in `CaseTransition` (motion layout disabled)

## Backend contracts needed (Dataset V2 / fhd integration)

- Paginated cases: `GET /cases/queue?cursor&limit&filters…` with `total`, workflow state, priority, `opened_at`
- Audit: `GET /audit?cursor&limit&filters…`
- Explore: `GET /explore` (already designed on fhd)
- Outcome authority fields to drive AWAITING_OUTCOME → RESOLVED without UI inference

## Recommended integration after fhd V2 lands

1. Point adapters at V2 queue/audit endpoints; remove fixture providers behind `?source=live` default.
2. Enable time filters when `opened_at` present.
3. Wire process-queue panel to read-only worker status API (no DB writes from UI).
4. Keep simulation behind explicit toggle + persistent DEMO banner.
