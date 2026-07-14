"""Parse docs/queries.txt — the hand-written, pre-vetted query catalog — into runnable
entries. Nothing here ever generates Cypher; every query the app can run is frozen text
lifted verbatim out of this file, keyed by its question id (Q01, Q02, ...).

Where each query shows up is derived mechanically from whether it takes parameters, not
from the file's own `Surface:` tag (kept only as `raw_surface`, for reference — some of the
file's own tags didn't match what we actually decided, e.g. Q20/Q34 are tagged as dashboard/
conversational there but need a track picker, so they behave as parameterized here):

- **Filter tab** shows every query. Zero params -> a plain "Run" button. One or more params
  -> a picker per param, then "Run".
- **Dashboard** shows every query too. Zero params -> loads real numbers immediately.
  One or more params -> a shortcut tile (title + "go pick one") that deep-links to its
  already-open Filter-tab card, since there's no sensible default entity to show.
- **Chat** only ever calls the small, explicit `IN_CHAT` set below — being param-free is
  necessary but not sufficient (Q01/Q02/Q07/Q11/Q39 are also param-free but were never
  asked to be conversational; only Q32 was).
"""
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from core import schema

QUERIES_PATH = Path(__file__).resolve().parents[2] / "docs" / "queries.txt"

# Q64's only non-registry, non-code param - a value derived in Cypher (CASE WHEN ... THEN
# 'Closed'/'Overdue'/'Open'), not a stored property, so no registry lookup can back it.
STATUS_OPTIONS = ["Open", "Overdue", "Closed"]

# The only query id reachable from chat (see module docstring for why this isn't automatic).
IN_CHAT = {"Q32"}

_HEADER_RE = re.compile(r"^# (Q\d+) — (.+)$", re.MULTILINE)
_QUESTION_RE = re.compile(r"^> \*\*(.+?)\*\*\s*$", re.MULTILINE)
_QUESTION_AR_RE = re.compile(r"^> ([^\*].+)$", re.MULTILINE)
_META_RE = re.compile(
    r"\*\*Persona:\*\*\s*(?P<persona>.+?)\s*·\s*\*\*Surface:\*\*\s*(?P<surface>.+?)\s*·"
)
_CYPHER_BLOCK_RE = re.compile(r"```cypher\s*\n(.*?)```", re.DOTALL)
_PARAM_RE = re.compile(r"\$(\w+)")


@dataclass
class QueryDef:
    id: str
    title: str
    question_en: str
    question_ar: str
    persona: str
    raw_surface: str  # the file's own tag - reference only, see module docstring
    cypher: str  # the primary (first) query block - what actually runs
    variants: list[str] = field(default_factory=list)  # any further cypher blocks in the entry
    params: list[str] = field(default_factory=list)

    @property
    def needs_params(self) -> bool:
        return bool(self.params)

    @property
    def in_chat(self) -> bool:
        return self.id in IN_CHAT


def _parse_block(qid: str, title: str, body: str) -> QueryDef:
    q_match = _QUESTION_RE.search(body)
    question_en = q_match.group(1).strip() if q_match else ""
    ar_match = _QUESTION_AR_RE.search(body, q_match.end() if q_match else 0)
    question_ar = ar_match.group(1).strip() if ar_match else ""
    meta = _META_RE.search(body)
    persona = meta.group("persona").strip() if meta else ""
    raw_surface = meta.group("surface").strip() if meta else ""
    blocks = [b.strip() for b in _CYPHER_BLOCK_RE.findall(body)]
    cypher = blocks[0] if blocks else ""
    params = list(dict.fromkeys(_PARAM_RE.findall(cypher)))  # de-dup, preserve first-seen order
    return QueryDef(
        id=qid,
        title=title.strip(),
        question_en=question_en,
        question_ar=question_ar,
        persona=persona,
        raw_surface=raw_surface,
        cypher=cypher,
        variants=blocks[1:],
        params=params,
    )


@lru_cache(maxsize=1)
def catalog() -> dict[str, QueryDef]:
    """Every parsed query, keyed by id, in file order."""
    text = QUERIES_PATH.read_text(encoding="utf-8")
    headers = list(_HEADER_RE.finditer(text))
    out: dict[str, QueryDef] = {}
    for i, h in enumerate(headers):
        qid, title = h.group(1), h.group(2)
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        out[qid] = _parse_block(qid, title, text[h.end():end])
    return out


def get(qid: str) -> QueryDef:
    try:
        return catalog()[qid]
    except KeyError:
        raise KeyError(f"Unknown query id {qid!r}; available: {list(catalog())}") from None


def dashboard_ids() -> list[str]:
    """Every query, dashboard shows all of them (live tiles for the param-free ones,
    shortcut tiles for the rest) - see module docstring."""
    return list(catalog())


def filter_ids() -> list[str]:
    """Every query, filter tab shows all of them too."""
    return list(catalog())


def chat_ids() -> list[str]:
    return [qid for qid, q in catalog().items() if q.in_chat]


def _registry_label_for(param: str) -> str | None:
    """schema.yaml's own naming convention ('key property ALWAYS <label>Id') lets a param
    name like trackId resolve to the Track registry with no per-param mapping to maintain."""
    if not param.endswith("Id"):
        return None
    label = param[:-2]
    label = label[0].upper() + label[1:]
    return label if schema.is_registry_label(label) else None


def param_meta(param: str) -> dict:
    """How the Filter tab should render one param: a registry dropdown, the fixed status
    enum, or a plain text box. `code` (Q15/Q51's mandate code) isn't a registry: true node
    per schema.yaml, but a free-text box gives the user no way to know a valid value, so
    it's special-cased to the Mandate dropdown registry.py builds by hand."""
    if param == "status":
        return {"name": param, "kind": "enum", "options": STATUS_OPTIONS}
    if param == "code":
        return {"name": param, "kind": "registry", "label": "Mandate"}
    label = _registry_label_for(param)
    if label:
        return {"name": param, "kind": "registry", "label": label}
    return {"name": param, "kind": "text"}
