"""Shipments that must never be Stage 3 cases, by dataset. Run side and scorer side both read this; it holds no truth.

A committed exclusion file names a dataset and the shipment ids whose truth labels were exposed (for example committed
to the repository by mistake). The pre-run selection never draws such a shipment from a world whose truth rows carry
that dataset id, and the run wiring refuses a selection that names one for a database holding that dataset. A world
with another dataset id is not affected: the list applies only when the dataset matches.
"""
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Repository-relative paths. Add a file here (never remove one) when another set of labels is exposed.
EXCLUSION_FILES = ("docs/evals/2026-10-10_world1_pilot/excluded_shipments.json",)


def load_exclusions(paths=None, *, root=REPO_ROOT):
    """({dataset_id: frozenset(shipment ids)}, [{file, sha256, dataset_id, shipments}]). A listed file that is missing or
    malformed is an error: an exclusion that cannot be read must stop the selection, not be skipped."""
    by_dataset, sources = {}, []
    for relative in EXCLUSION_FILES if paths is None else paths:
        path = Path(relative) if Path(relative).is_absolute() else Path(root) / relative
        data = path.read_bytes()
        document = json.loads(data)
        dataset_id, ids = document.get("dataset_id"), document.get("shipment_ids")
        if not isinstance(dataset_id, str) or not dataset_id or not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError(f"{path} is not an exclusion list (dataset_id and shipment_ids)")
        by_dataset[dataset_id] = frozenset(by_dataset.get(dataset_id, frozenset()) | set(ids))
        sources.append({"file": str(relative).replace("\\", "/"), "sha256": hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest(),
                        "dataset_id": dataset_id, "shipments": len(set(ids))})
    return by_dataset, sources


def excluded_in(by_dataset, dataset_id, shipment_ids):
    """The given shipment ids that are excluded for this dataset (sorted)."""
    listed = by_dataset.get(dataset_id) or frozenset()
    return sorted(set(shipment_ids) & listed)


def excluded_for(by_dataset, dataset_ids, shipment_ids):
    """The given shipment ids that are excluded for a world whose records carry these dataset ids. A world whose
    dataset id is not known cannot be matched to a list, so every listed shipment is excluded from it (the safe side)."""
    known = [d for d in dataset_ids if d]
    if not known:
        return sorted(set(shipment_ids) & set().union(*by_dataset.values())) if by_dataset else []
    return sorted({sid for dataset_id in known for sid in excluded_in(by_dataset, dataset_id, shipment_ids)})
