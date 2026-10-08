# AgentX / Suhail

Suhail investigates shipment exceptions: **why is this shipment abnormal or stalled,
what evidence explains it, and what is the safest next action?** Neo4j connects events,
address versions, policy and observed historical outcomes. A reviewed LangGraph pipeline
proposes an action; authorized logistics systems remain responsible for physical execution.

This repository uses a **synthetic Saudi shipment dataset**, not an SPL production
integration. Facilities, service rules, carrier assignments and generated outcomes are
demo assumptions. No enterprise GPS, live fleet, proof-of-delivery, email sending,
operator authentication or real execution integration is implemented.

## Architecture

- React / TypeScript / Vite: Intake, Decisions and shipment Explore (Map / Graph / Schema).
- FastAPI: shared-origin UI, read-only shipment APIs and complaint SSE pipeline.
- Neo4j `SHIPMENT_DATABASE`: active logistics evidence. `CHAT_DATABASE` is separate
  conversation infrastructure; `NEO4J_DATABASE` remains for unused legacy tools.
- Local Ollama `bge-m3`: 1024-dimensional embeddings and cosine vector retrieval.
- GraphRAG: vector similarity and connected evidence fused with reciprocal rank fusion;
  second retrieval conditions precedent on the proposed cause.
- LangGraph: extraction → retrieval → classification → recommendation → review, with
  bounded rejection/reconsideration (AFL), pending recommendation recording or escalation.
- Ollama Cloud via LiteLLM: recommended default `openai/gpt-oss:120b`, endpoint
  `https://ollama.com/v1`; `20b` remains an explicitly selectable comparison model.

Neo4j connects which shipment had which attempt, address/version, policy, exception and
past action/outcome. Pending recommendations are excluded from historical retrieval,
success statistics and embedding backfill. An accepted recommendation creates a pending
outcome with `success=null`; it does not mark a shipment delivered.

Operator summaries derive counts and cited-action rates from recorded data. Model diagnoses
are hypotheses. Provider thinking and unverified model rationale stay out of the operator
stream. Internal model judgments still have grounding limitations; computed summaries do
not establish that the chosen category or action is correct.

## Local development on Windows

Reuse the existing environment when it is running. For a fresh checkout, copy `.env.example`
to a local ignored `.env` and set the Neo4j password and cloud credential. Key precedence:
`LLM_API_KEY`, then `OPENAI_API_KEY`, then `OLLAMA_API_KEY`. Explicit model/base environment
settings override the recommended defaults.

Neo4j Desktop must expose the synthetic `shipments` database on local Bolt7687. Local Ollama
must already have bge-m3; the app never pulls models itself. Do not load a dataset into an
unknown or production database.

```powershell
Set-Location C:\Projects\demo\frontend
npm.cmd ci
npm.cmd run build
Set-Location C:\Projects\demo\chat
uv sync
uv run uvicorn --app-dir ..\backend main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. The backend serves `frontend/dist`; rebuild after frontend
changes and restart after Python changes. `serve.sh` is a Unix convenience script. The
Python project directory/distribution names remain legacy runtime compatibility details.

```powershell
Set-Location C:\Projects\demo\chat
uv run python -m unittest discover -s tests -v
uv run python ..\scripts\verify_shipment_explore.py
uv run python ..\scripts\secret_scan.py
Set-Location C:\Projects\demo\frontend
npm.cmd test -- --run
npm.cmd run lint
npm.cmd run build
```

## Explore and demo

Explore defaults to Needs attention and caps selection at25 (maximum50). Map and Graph
share membership and selected-case context. Supported filters: Needs attention, Critical,
Stalled, Delivered and All. There is no baseline Lost category. Origin markers are
approximate city centroids; a dashed origin/destination line is an expected connection,
not a traveled route. Graph/Map include text alternatives.

1. Select an address-conflict shipment in Explore and compare address evidence.
2. Open Intake evidence; analysis requires an eligible unresolved sample.
3. Inspect stages, observed precedent, review and any AFL reconsideration.
4. Inspect Decisions: separate recorded recommendation, escalation, pending outcome and
   observed synthetic result. No operator approval or physical execution is implied.

Controlled write proof SHP-0004 is now pending and must not be rerun as unresolved.
SHP-0017 has a preserved read-only AFL rejection/revision trace. Do not reset records merely
to repeat the presentation.

## Evaluation and limitations

[Evaluation V1](docs/evals/2026-10-08_gpt-oss-v1/closure.md) retains30 paired synthetic
cases per model, frozen whole-shipment holdout evidence and dry writeback. Base-cause
agreement was13/30 for20B and16/30 for120B, not production accuracy. 120B averaged8.537s
vs28.648s on this endpoint and won19 blinded editorial preferences against5 (six ties).
Both produced factual/policy defects; only2/30 and5/30 met the strict editorial ready-to-show
threshold. Reviewer acceptance is not correctness. Computed operator summaries are a
post-evaluation fix; the original60 results were not rerun or relabeled as improved performance.

V1 lacks measured barcode/weight/gate/contact/custody observations for several subtypes.
Outcomes were randomly generated, not independently adjudicated. False-acceptance/rejection
and real operational success cannot be measured. This local demo needs authenticated
operator and external-outcome controls before deployment. Existing lint warnings and a
large graph/3D bundle remain.

[Dataset V2 design](docs/design/2026-10-08_dataset-v2/README.md) proposes evidence-derived
exceptions, expected journey, custody, vehicle/GPS context, delivery disputes, explicit
operator decisions and verified outcomes. It is design-only; no V2 graph has been loaded.

Legacy governance `/chat` and `/registry` return410. Their queries/schema/tools, generic
renderers and separate conversation memory remain preserved for traced reuse.

## Geographic data and dependencies

The V1 generator uses city/district files from
[homaily/Saudi-Arabia-Regions-Cities-and-Districts](https://github.com/homaily/Saudi-Arabia-Regions-Cities-and-Districts).
Reference geography does not establish synthetic network authenticity. Leaflet uses
OpenStreetMap tiles with attribution. Dependencies: FastAPI/Uvicorn, LangGraph,
LiteLLM/langchain-litellm, Neo4j driver, React, Tailwind, Leaflet, Neo4j NVL, lucide-react,
Motion and Vitest. See `chat/pyproject.toml` and `frontend/package.json`.
