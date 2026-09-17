"""Display-only translation of the agent's free-text reasoning into Arabic.

STRICTLY a presentation concern. The pipeline keeps reasoning, classifying and writing back
in its own language: nothing here touches a system prompt, a confidence score, an evidence
id or anything that reaches the graph. The UI asks for a translated *copy* of a rationale
when the viewer has set the interface to Arabic, and that copy is never fed back into the
pipeline or persisted.

Why not just ask the agent for Arabic in the first place: the classifier and reviewer are
graded on reasoning quality against an English-language graph vocabulary
(FailureReason.category, Resolution.action). Making the model produce its justification in
another language changes the tokens it reasons in, which is a real risk to that quality for
a purely cosmetic gain. Translating afterwards leaves the decision path untouched.

Two safeguards, because a translation that mangles an id is worse than no translation:
  - the prompt forbids summarising or reinterpreting, and pins ids/numbers verbatim;
  - _keeps_literals() verifies that every id, code and percentage in the source survived
    into the output, and discards the translation if any did not. A caller that gets the
    original English back has lost a nicety, not correctness.
"""
import logging
import re
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage

from llm.pipeline._llm import model

log = logging.getLogger("llm.translate")

SYSTEM = (
    "You are a professional technical translator. You translate text into Modern Standard "
    "Arabic for display in a logistics operations dashboard. You never summarise, never "
    "explain, never add or remove information, and never answer the content of the text - "
    "you only translate it. Reply with the translation alone, no preamble, no quotes."
)

USER = (
    "Translate the following technical justification text to Arabic, preserving all "
    "technical terms, IDs, and percentages exactly as-is. Do not summarize or reinterpret, "
    "only translate:\n\n{text}"
)

# What must survive verbatim, and nothing more. Being too eager here is its own bug: a first
# version treated any hyphenated word as an id, so translating the ordinary phrase
# "reweigh-and-reroute" looked like a dropped identifier and threw a good translation away.
#   - ids carry a digit:              SHP-1042, res_88f2, FR-7
#   - graph vocabulary is snake_case: recorded_failure, address_conflict
#   - every number, percentage included
_LITERAL_RE = re.compile(
    r"\b[A-Za-z]+[-_][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*"  # identifier containing a digit
    r"|\b[a-z]+(?:_[a-z]+)+\b"                        # snake_case term
    r"|\d+(?:\.\d+)?"                                 # bare number (a % sign may be written ٪)
)
_ARABIC_RE = re.compile(r"[؀-ۿ]")
# Arabic-Indic and extended Arabic-Indic digits, so a model that writes ٨٧٪ rather than 87%
# still counts as having preserved the value.
_DIGIT_FOLD = {**{0x0660 + i: str(i) for i in range(10)},
               **{0x06f0 + i: str(i) for i in range(10)}}
MAX_CHARS = 2000


def _keeps_literals(source: str, translated: str) -> bool:
    """Did every id, graph term and number in `source` come through unchanged?"""
    folded = translated.translate(_DIGIT_FOLD)
    for literal in set(_LITERAL_RE.findall(source)):
        if literal not in translated and literal not in folded:
            log.warning("translation dropped literal %r; keeping the original text", literal)
            return False
    return True


@lru_cache(maxsize=512)
def to_arabic(text: str) -> str:
    """The Arabic rendering of one piece of agent prose, or the original text unchanged if it
    cannot be translated safely. Memoized on the exact source string: the same rationale is
    translated once per process however many times the UI re-renders or re-opens the case."""
    source = text.strip()
    if not source:
        return text
    if len(source) > MAX_CHARS:
        log.warning("skipping translation of %d chars (over %d)", len(source), MAX_CHARS)
        return text
    # already Arabic (a complaint quoted back, or a model that answered in Arabic anyway)
    if len(_ARABIC_RE.findall(source)) > len(source) / 4:
        return text

    try:
        resp = model().invoke([SystemMessage(SYSTEM), HumanMessage(USER.format(text=source))])
        out = (resp.content if isinstance(resp.content, str) else str(resp.content)).strip()
    except Exception:
        log.exception("translation call failed; keeping the original text")
        return text

    if not out or not _ARABIC_RE.search(out) or not _keeps_literals(source, out):
        return text
    return out
