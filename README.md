# agentx-kg-hackathon

A Neo4j knowledge-graph app: a LangGraph chat agent, a frozen-query dashboard, a map over
incident/track-status CSVs, and a shipment-complaint pipeline — served as one FastAPI app
with a React UI (`./serve.sh`, then http://localhost:8000).

This file records **what this project is built on**: the outside repos and data it pulls in,
and the libraries each part depends on. Setup lives in [.env.example](.env.example) and
[frontend/README.md](frontend/README.md).

## External data / repos

| Source | Used for | Where |
| --- | --- | --- |
| [homaily/Saudi-Arabia-Regions-Cities-and-Districts](https://github.com/homaily/Saudi-Arabia-Regions-Cities-and-Districts) | The real regions/cities/districts the synthetic shipment graph is generated on top of. The generator reads `json/regions_lite.json`, `json/cities.json`, `json/districts_lite.json`, and once `json/districts.json` (~58MB) to compute district centroids, cached into [shipment_kg/district_centroids.cache.json](shipment_kg/district_centroids.cache.json). Clone it as `json/` in the repo root before running the generator — it is not vendored here. | [shipment_kg/generate_shipment_kg.py](shipment_kg/generate_shipment_kg.py) |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) raster tiles | Basemap for every Leaflet map in the UI (attribution is rendered in-map). | [frontend/src/components/agent/ShipmentMap.tsx:54](frontend/src/components/agent/ShipmentMap.tsx#L54) |

## Services this expects to be running

- **[Neo4j](https://neo4j.com/)** — the domain graph (`docs/schema.yaml`), chat threads
  (`CHAT_DATABASE`), and the shipment graph (`SHIPMENT_DATABASE`).
- **An LLM endpoint via [LiteLLM](https://github.com/BerriAI/litellm)** — `LLM_MODEL`,
  `LLM_API_KEY`, `LLM_API_BASE`.
- **[Ollama](https://github.com/ollama/ollama)** (default embeddings) — `ollama pull bge-m3`
  for [chat/scripts/embed_backfill.py](chat/scripts/embed_backfill.py).

## Backend libraries ([chat/pyproject.toml](chat/pyproject.toml))

[FastAPI](https://github.com/fastapi/fastapi) + [Uvicorn](https://github.com/encode/uvicorn) ·
[LangGraph](https://github.com/langchain-ai/langgraph) and
[langchain-litellm](https://github.com/akshay-dongare/langchain-litellm) for the agent and the
complaint pipeline · [LiteLLM](https://github.com/BerriAI/litellm) ·
[neo4j Python driver](https://github.com/neo4j/neo4j-python-driver) ·
[python-dotenv](https://github.com/theskumar/python-dotenv) ·
[PyYAML](https://github.com/yaml/pyyaml). Managed with [uv](https://github.com/astral-sh/uv).

## Frontend libraries ([frontend/package.json](frontend/package.json))

[React 19](https://github.com/facebook/react) + [TypeScript](https://github.com/microsoft/TypeScript)
+ [Vite](https://github.com/vitejs/vite) · [Tailwind v4](https://github.com/tailwindlabs/tailwindcss)
· [Radix UI](https://github.com/radix-ui/primitives) (Dialog, Popover) ·
[@neo4j-nvl](https://neo4j.com/docs/nvl/current/) for the graph view ·
[react-force-graph-3d](https://github.com/vasturiano/react-force-graph) +
[three.js](https://github.com/mrdoob/three.js) ·
[Leaflet](https://github.com/Leaflet/Leaflet) + [react-leaflet](https://github.com/PaulLeCam/react-leaflet)
· [react-markdown](https://github.com/remarkjs/react-markdown) +
[remark-gfm](https://github.com/remarkjs/remark-gfm) ·
[Motion](https://github.com/motiondivision/motion) ·
[lucide-react](https://github.com/lucide-icons/lucide) ·
[oxlint](https://github.com/oxc-project/oxc) + [Vitest](https://github.com/vitest-dev/vitest).
