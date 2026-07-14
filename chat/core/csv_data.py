"""Parse the three map CSVs directly - nothing here is ever ingested into Neo4j.

Column names, as shared:
  category CSV:      incident_category, category_id
  incidents CSV:      category_id, incident_id, municipality_date, lat, lng, source_id
  track-status CSV:   data_entry_id, track_id, entity_id, entry_action, status, date, Notes,
                       picture_1, picture_2, lat, lng, municipality, source_id, track_location

All three paths (config.CATEGORY_CSV / INCIDENTS_CSV / TRACK_STATUS_CSV) and the photo
folder (config.PHOTOS_DIR) are sensitive and filled in later - every reader here degrades
to an empty list rather than raising when a path isn't configured yet or the file is
missing, so the rest of the app can start up before the real data arrives.
"""
import csv
import os
from functools import lru_cache
from pathlib import Path

import config


def _rows(path: str | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_photos(*cells: str) -> list[str]:
    """Each picture_N cell may be blank or a '|'-separated list of paths (a visit can point
    to more than one photo). Concatenate all cells, split, drop blanks, keep order - same
    rule as the old project's dedup/ingest/loader_governance.py:parse_photos, just never
    written to Neo4j here."""
    out = []
    for cell in cells:
        for part in (cell or "").split("|"):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _photo_url(path: str) -> str | None:
    """A picture_N path is resolved against PHOTOS_DIR; expose it as the URL the backend
    serves (/photos/<file>). basename-only, so nothing outside PHOTOS_DIR can be
    referenced - same guard as the old project's _image_url."""
    return f"/photos/{os.path.basename(path)}" if path else None


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def category_labels() -> dict[str, str]:
    """category_id -> incident_category (the Arabic display name)."""
    return {
        r["category_id"]: r.get("incident_category", "")
        for r in _rows(config.CATEGORY_CSV)
        if r.get("category_id")
    }


def incidents() -> list[dict]:
    """Every geolocated row from the incidents CSV, in the shape the frontend's Incident
    type expects. No photos - this dataset never has one, matching the old project's
    Incident nodes (which also carry no real per-incident photo)."""
    labels = category_labels()
    out = []
    for r in _rows(config.INCIDENTS_CSV):
        lat, lon = _to_float(r.get("lat")), _to_float(r.get("lng"))
        if lat is None or lon is None:
            continue
        cat_id = r.get("category_id")
        if not labels.get(cat_id, "").strip():
            continue
        out.append({
            "key": r.get("incident_id"),
            "lat": lat,
            "lon": lon,
            "categories": [labels[cat_id]],
            "date": r.get("municipality_date"),
            "source_id": r.get("source_id"),
        })
    return out


def track_status() -> list[dict]:
    """Every geolocated row from the track-status CSV, with picture_1/picture_2 merged into
    one `images` list of servable URLs - the map's only photo-bearing layer."""
    out = []
    for r in _rows(config.TRACK_STATUS_CSV):
        lat, lon = _to_float(r.get("lat")), _to_float(r.get("lng"))
        if lat is None or lon is None:
            continue
        photos = parse_photos(r.get("picture_1", ""), r.get("picture_2", ""))
        images = [u for u in (_photo_url(p) for p in photos) if u]
        notes = r.get("Notes")
        if not images and not (notes and notes.strip()):
            continue
        out.append({
            "key": r.get("data_entry_id"),
            "lat": lat,
            "lon": lon,
            "track": r.get("track_id"),
            "entity_id": r.get("entity_id"),
            "entry_action": r.get("entry_action"),
            "status": r.get("status"),
            "date": r.get("date"),
            "notes": notes,
            "municipality": r.get("municipality"),
            "source_id": r.get("source_id"),
            "track_location": r.get("track_location"),
            "images": images,
        })
    return out
