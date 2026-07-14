"""Environment configuration with fail-fast validation."""
import os
from pathlib import Path

from dotenv import load_dotenv

# the chat lives in chat/, but reads the SAME shared .env at the repo root as the
# backend — so Neo4j creds + database can't drift between the two (parents[1] = repo root)
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env at the repo root and fill in your credentials."
        )
    return value


NEO4J_URI = _require("NEO4J_URI")
NEO4J_USERNAME = _require("NEO4J_USERNAME")
NEO4J_PASSWORD = _require("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
# Conversation memory (chat threads/messages) is persisted in its OWN database, kept separate from
# the domain graph so chat history never shows up in the knowledge-graph census/Explore views.
CHAT_DATABASE = os.getenv("CHAT_DATABASE", "neo4j")

# LLM is routed through LiteLLM, so any provider works: a hosted API
# (openai/gpt-4o-mini, anthropic/claude-..., gemini/...) or a local endpoint
# (ollama/llama3.1, or openai/<model> + LLM_API_BASE for vLLM/LM Studio).
# LLM_API_KEY falls back to OPENAI_API_KEY; local models need no key.
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
LLM_API_BASE = os.getenv("LLM_API_BASE")  # set for a local/self-hosted endpoint

# --- Map data: parsed straight from CSV, never ingested into Neo4j (sensitive, filled in later) --
CATEGORY_CSV = os.getenv("CATEGORY_CSV")        # incident_category, category_id
INCIDENTS_CSV = os.getenv("INCIDENTS_CSV")      # category_id, incident_id, municipality_date, lat, lng, source_id
TRACK_STATUS_CSV = os.getenv("TRACK_STATUS_CSV")  # data_entry_id, track_id, entity_id, entry_action,
                                                   # status, date, Notes, picture_1, picture_2, lat, lng,
                                                   # municipality, source_id, track_location
PHOTOS_DIR = os.getenv("PHOTOS_DIR")            # folder the picture_1/picture_2 paths resolve against
