"""Opaque, filter-bound keyset cursors. Cursors convey no access authority."""
import base64
import hashlib
import json
from dataset_v2.contracts import instant

LIMITS = (25, 50, 100)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(route, dataset_id, filters, limit):
    return hashlib.sha256(canonical([route, dataset_id, filters, limit]).encode()).hexdigest()


def encode_cursor(binding, timestamp, entity_id, snapshot):
    if instant(timestamp)>instant(snapshot) or not isinstance(entity_id,str) or not 1<=len(entity_id)<=160:
        raise ValueError("Invalid cursor chronology or identity")
    value = {"v": 1, "binding": binding, "timestamp": timestamp, "id": entity_id, "snapshot": snapshot}
    return base64.urlsafe_b64encode(canonical(value).encode()).decode().rstrip("=")


def decode_cursor(value, binding):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Invalid cursor")
    try:
        decoded = json.loads(base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid cursor") from exc
    if (not isinstance(decoded, dict) or set(decoded) != {"v", "binding", "timestamp", "id", "snapshot"}
            or decoded["v"] != 1 or decoded["binding"] != binding
            or any(not isinstance(decoded[key], str) or not decoded[key] for key in ("timestamp", "id", "snapshot"))):
        raise ValueError("Cursor does not match this request")
    if instant(decoded["timestamp"])>instant(decoded["snapshot"]) or len(decoded["id"])>160:
        raise ValueError("Invalid cursor chronology or identity")
    return decoded
