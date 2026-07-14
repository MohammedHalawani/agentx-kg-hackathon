"""Load docs/schema.yaml — the single source of truth for the graph's shape.

This file is reference-only (never edited by app code): it tells us which node labels
exist, their key/display properties, and which ones are `registry: true` (a small,
enumerable set of real-world things — Person, Track, Committee, ... — that a dropdown
makes sense for, versus a fact record like Mandate or Assignment that you filter into,
not pick from a list).
"""
from functools import lru_cache
from pathlib import Path

import yaml

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "schema.yaml"

# every registry node in schema.yaml names its Arabic/English label with this prefix
_DISPLAY_PREFIX = "displayName"


@lru_cache(maxsize=1)
def load() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def nodes() -> dict:
    return load()["nodes"]


def node_spec(label: str) -> dict:
    """Raw schema.yaml entry for one node label."""
    spec = nodes().get(label)
    if spec is None:
        raise KeyError(f"Unknown node label {label!r}; available: {list(nodes())}")
    return spec


def key_of(label: str) -> str:
    """The node's unique key property name (schema.yaml convention: always <label>Id)."""
    return node_spec(label)["key"]


def display_props(label: str) -> list[str]:
    """The human-readable name properties for a node (displayName_ar / displayName_en),
    in the order declared — used to label dropdown options."""
    return [p for p in node_spec(label).get("props", {}) if p.startswith(_DISPLAY_PREFIX)]


@lru_cache(maxsize=1)
def registry_labels() -> list[str]:
    """Every node label flagged `registry: true` — the set a Filter-tab dropdown can be
    built from generically, with no per-label code."""
    return [label for label, spec in nodes().items() if spec.get("registry")]


def is_registry_label(label: str) -> bool:
    """Whitelist check before a label is interpolated into Cypher (labels can't be
    parameterized) — only ever call registry_options() with a label that passes this."""
    return label in registry_labels()


@lru_cache(maxsize=1)
def caption_props() -> dict[str, list[str]]:
    """label -> its displayName_* properties, in order — the Explore graph view's caption
    picker (see view/subgraph.py) tries these first before falling back to the label name."""
    return {label: display_props(label) for label in nodes()}
