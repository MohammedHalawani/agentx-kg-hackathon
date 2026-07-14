# Knowledge-Graph Chat - frontend

A React UI for the Neo4j knowledge-graph assistant, behind an app shell with three views
(**Chat**, **Dashboard**, **Explore**) switched from a left nav rail (`AppNav`).

- **Chat** - a split-pane layout: a fixed-width conversation column plus a wide artifact panel
  with **Graph / Map / Table** tabs in one consolidated control bar. A **Chat/Graph** toggle
  (always visible) switches which one shows full width - both stay visible side by side once the
  viewport is wide enough. Conversations persist in Neo4j (see
  [chat/README.md](../chat/README.md#conversation-memory)): every visit starts a fresh thread,
  and past ones - including their full graph/map/table artifact, not just the text - are one
  click away in the **History** popover. A **Stop** button aborts an in-flight answer. An answer
  that mapped incidents gets an inline **Map** button woven into the prose, opening a focused map
  modal. The agent's internals (Cypher, tool trace, timing, confidence) sit one click away behind
  **Inspect**.
- **Dashboard** - a live read across the graph: KPI tiles and interactive charts (hover an
  `AreaChart` point or a `Donut` segment for its exact value).
- **Explore** - three read-only lenses on the whole graph, independent of any chat question:
  **Graph** (a fresh connected slice of the domain graph - random seed nodes plus their
  neighbourhood - with a "Show another part of the graph" button to redraw), **Map** (every
  incident, no cap), **Schema** (the data
  model itself).

Stack: React + TypeScript + Vite + Tailwind v4 + Radix Dialog + `@neo4j-nvl/react` (graph)
+ react-leaflet (map). Talks to the FastAPI backend over plain SSE.

## Run

Production is the only mode: the FastAPI backend serves the built UI and the API from one origin.

```bash
# from visual-pollution-dedup/ — builds the frontend, then serves everything on :8000
./serve.sh
```

Then open http://localhost:8000. Needs the `momah` Neo4j on bolt://127.0.0.1:7687.

To iterate on the frontend: edit, `npm run build`, refresh - the backend serves `dist/`.
(There is no Vite dev server: NVL's layout web-workers only load from the built chunks, so a
single production build is also what fixes the graph layout.)

## How it's wired

- **`types/contract.ts`** - the artifact contract the backend emits, mirrored 1:1. The one
  source of truth for the data shape.
- **`lib/sse.ts` + `hooks/useChatStream.ts`** - the SSE reader and streamed message state (thread
  id, send/stop/newThread/loadThread). All data/IO lives here; components stay presentational
  and prop-driven.
- **`components/artifacts/ArtifactRenderer.tsx`** - builds the Graph/Map/Table tab list from
  whatever the artifact actually carries (a viz = one more `tabs.push(...)`), and renders the
  active one. The subgraph tab appears for any answer that produced one.
- **`hooks/useFetch.ts`** - the minimal GET hook behind Dashboard/Explore's read-only views;
  `refetch()` re-runs the same request (Explore's "show another part of the graph" button).

## Changing the look (re-skin)

Every visual decision is a token in **`src/index.css`** (`@theme` block) - colors, fonts,
the graph palette. A reskin = edit those values (or drop in a new block). No component edits;
components reference token-backed utility classes only, never raw hex. A `.dark` block is wired
for dark mode (light-first; flip by adding `class="dark"` to `<html>`).

## Adding a feature (extensibility)

- **New visualization / agent tool**: write one prop-driven component + add one `tabs.push(...)`
  entry in `ArtifactRenderer.tsx`. No conditionals to hunt down.
- **New dataset/domain**: it's data, not code - add an ontology file on the backend; the samples,
  schema grounding, and the artifact all derive from it.

## Deferred (additive, not rewrites)

Genuine token streaming + live tool-step pills (backend chunks the finished answer today),
recurrence before/after photos, regenerate, a dark-mode toggle (the tokens are wired, no UI
control ships), and typed entity mentions inside answer prose (color-coded by node label).
