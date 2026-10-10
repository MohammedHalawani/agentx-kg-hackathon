"""Run the backend for the redesigned interface against the UI scratch database only.

UI integration branch only. Serves the API and the built frontend-next app on one origin:

    cd frontend-next && npm ci && npm run build && cd ..
    <python of chat/.venv> scripts/ui_scratch_backend.py            # http://127.0.0.1:8010/app/

Operations (cases, ledger, evidence) always use the database shipments-v2-demo-ui. It runs with
the investigation agents off and clears every model key, so it makes no model calls. The legacy
V1 routes of the same app (/v1/..., /threads) still use the configured chat and shipment
databases if they are called; the redesigned interface never calls them.
Neo4j connection settings are read from an env file (default: the repository's .env, else the
main checkout's at C:\\Projects\\demo\\.env); their values are never printed.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_DATABASE = "shipments-v2-demo-ui"
CONNECTION_KEYS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE", "CHAT_DATABASE", "SHIPMENT_DATABASE")


def environment():
    candidates = [os.environ.get("SUHAIL_ENV_FILE"), ROOT / ".env", Path(r"C:\Projects\demo\.env")]
    source = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
    if source is None:
        raise SystemExit("No env file with the Neo4j connection settings was found (set SUHAIL_ENV_FILE).")
    for line in source.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() in CONNECTION_KEYS:
                os.environ[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("LLM_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY"):
        os.environ[key] = ""
    os.environ["SUHAIL_V2_AGENTS"] = "off"
    os.environ["SUHAIL_OPERATIONS_DATABASE"] = UI_DATABASE
    os.environ["SUHAIL_TEST_DATABASE"] = UI_DATABASE


if __name__ == "__main__":
    environment()
    os.chdir(ROOT)
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "chat"), str(ROOT)]
    import uvicorn
    port = int(os.environ.get("SUHAIL_UI_PORT", "8010"))
    print(f"Suhail interface: http://127.0.0.1:{port}/app/  (database {UI_DATABASE}, agents off)")
    uvicorn.run("main:app", app_dir=str(ROOT / "backend"), host="127.0.0.1", port=port, log_level="warning")
