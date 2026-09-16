"""Turn a free-text complaint (Arabic or English) into an ExtractedComplaint - the
structured fields retrieve.py needs to seed both the vector search and the graph traversal.

An LLM call rather than a regex/NER pass: complaints are informal, bilingual, and the fields
worth pulling out (courier name, city/district, a shipment or tracking id if the customer
quoted one) are exactly what a model handles and a parser doesn't. IDs are the exception -
they have a strict, known shape, so they're recovered by regex first and only left to the
model when the pattern doesn't match. That keeps the one field where a hallucination would
silently retrieve the WRONG shipment off the model's critical path.
"""
import logging
import re

from llm.pipeline import _llm
from llm.pipeline.state import ExtractedComplaint

log = logging.getLogger("pipeline.extract")

# Shapes minted by shipment_kg/generate_shipment_kg.py: SHP-0001 / SPL100000001.
_SHIPMENT_RE = re.compile(r"\bSHP-\d{4}\b", re.IGNORECASE)
_TRACKING_RE = re.compile(r"\bSPL\d{9}\b", re.IGNORECASE)

# The FailureReason.category vocabulary in the graph - the model picks a hint from this set
# or returns null, rather than inventing a label retrieval can never match.
CATEGORIES = [
    "address_conflict",
    "recipient_unavailable",
    "failed_attempt_wrong_gate",
    "failed_attempt_barcode_mismatch",
    "failed_attempt_weight_mismatch",
    "hub_delay",
]

_SYSTEM = (
    "You extract structured fields from a shipping complaint. The complaint may be in "
    "Arabic or English; place names and courier names will usually be Arabic and must be "
    "copied EXACTLY as written, with no translation or transliteration - they are matched "
    "literally against a database.\n\n"
    "Return ONLY a JSON object with these keys:\n"
    '  "city": the city name, or null\n'
    '  "district": the neighbourhood/district (حي ...), or null\n'
    '  "courier": the courier/delivery person\'s name, or null\n'
    f'  "category_hint": one of {CATEGORIES}, or null if unclear\n\n'
    "Use null for anything the complaint does not state. Never guess a value that is not "
    "present in the text."
)


def extract_entities(complaint_text: str) -> ExtractedComplaint:
    """Parse one free-text complaint into its structured fields.

    Never raises on a complaint that names nothing recognisable - every field but raw_text
    may come back None, and retrieve.py's vector search still has the raw text to work from.
    """
    shipment = _SHIPMENT_RE.search(complaint_text)
    tracking = _TRACKING_RE.search(complaint_text)

    fields = _llm.ask_json(
        _SYSTEM,
        complaint_text,
        default={"city": None, "district": None, "courier": None, "category_hint": None},
    )

    hint = fields.get("category_hint")
    if hint not in CATEGORIES:  # covers both None and a hallucinated label
        hint = None

    extracted: ExtractedComplaint = {
        "shipment_id": shipment.group(0).upper() if shipment else None,
        "tracking_id": tracking.group(0).upper() if tracking else None,
        "city": fields.get("city") or None,
        "district": fields.get("district") or None,
        "courier": fields.get("courier") or None,
        "category_hint": hint,
        "raw_text": complaint_text,
    }
    log.info("extracted: %s", {k: v for k, v in extracted.items() if k != "raw_text"})
    return extracted
