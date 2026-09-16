"""Turn a free-text complaint (Arabic or English) into an ExtractedComplaint - the
structured fields retrieve.py needs to seed both the vector search and the graph traversal.

This is an LLM call (via config.LLM_MODEL through LiteLLM, same as chat/llm/agent.py), not
a regex/NER pass - complaints are informal and the fields it should pull out (courier name,
city/district, a shipment or tracking id if the customer gave one) are exactly the kind of
loosely-structured extraction an LLM handles and a parser doesn't.
"""
from llm.pipeline.state import ExtractedComplaint


def extract_entities(complaint_text: str) -> ExtractedComplaint:
    """Parse one free-text complaint into its structured fields. Never raises on a complaint
    that names nothing recognizable - every field but raw_text is allowed to come back None,
    and retrieve.py's vector search still has the raw text to fall back on."""
    ...
