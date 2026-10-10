# Suhail UI Lab

A complete, interactive frontend design lab for Saudi logistics exception operations. Built with React 19, TypeScript, Vite, Tailwind CSS 4, and the official shadcn/ui **Nova / Radix** preset. All cases, investigations, decisions, chat replies, and outcomes are synthetic browser data.

## Run locally

```powershell
cd C:\Projects\suhail_ui
npm install
npm run dev
```

Open **http://127.0.0.1:5180/**. Vite uses a strict port so it cannot silently open a different address.

```powershell
npm run build
npm run lint
npm test
npm run test:e2e
```

Browser tests use the installed Google Chrome channel. `screenshots/` contains desktop, mobile, and Canopus previews. Open the test report with `npx playwright show-report` after running the browser suite.

## Try the workspace

- **Operations:** search and filter the unresolved table, change sorting or page size, and expand the verified Resolved rail. Enable Auto to watch the oldest eligible case progress. Pausing Auto stops new investigations; the current case and required checks continue.
- **Investigation:** open SHP-10482. The map and knowledge graph stay side by side at desktop and laptop sizes. Select markers or graph nodes, inspect each pipeline stage, switch Force/Tree, resize the panels, and open the assessment.
- **Decisions:** review a proposed action, supply a reason, and authorize, reject, or escalate. Authorization starts simulated execution. Only an independently verified outcome moves a case to Resolved.
- **Explore:** use route filters, select a shipment, follow clustered markers, or inspect its graph and the evidence schema. Canopus applies supported filter requests through the existing page controls and offers Undo.
- **Audit:** filter dates, shipments, event types, actors, routes, and workflows; change the timestamp basis and sort order; page through events; inspect metadata or switch to a shipment timeline.
- **Canopus:** click the purple star on any screen to open a 420px floating conversation. The window overlays the workspace without resizing it; expand for longer reports or minimize back to the launcher. Inline **Ask Suhail** actions open the same conversation with case context. Minimize/reopen retains messages, the selected case, draft, and exact reading position. Try `@investigator explain the highlighted node`, `@reviewer why is approval required?`, or `Explain the selected investigation stage`. Compact expandable notes separate observations, hypotheses, proposed actions, operator decisions, and verified outcomes. Citations focus evidence, stages, assessments, decisions, or timelines, including when reopening the same reference. The working conversation menu provides a simulated response error for exercising Retry.
- **Settings:** switch light/dark mode, English/Arabic, table density, or reduced motion. Add a synthetic scenario or reset the lab.

## Frontend boundaries

This project has no authentication, backend endpoints, LLM calls, cloud inference, database connections, ingestion pipeline, or production execution engine. Browser state is retained in localStorage; case conversations are retained in sessionStorage. Reset lab restores the fixtures and clears conversations and operator decisions.

Map evidence is synthetic. The street basemap uses OpenStreetMap tiles with attribution; an interactive offline schematic is available and activates when tiles cannot load. Vehicle GPS is explicitly distinguished from parcel custody evidence.

The historical dataset and Audit shortcuts are anchored to **9 October 2026**, Saudi time, so examples remain reproducible. Arabic interface controls and Canopus replies are localized; original logistics fixture names and identifiers can remain in English.

See [INTEGRATION.md](INTEGRATION.md) for the small, typed service seams available for a future application integration.

See [VERIFICATION.md](VERIFICATION.md) for browser coverage, responsive screenshots, and the completed build and test checks.
