"""Image files attached to photo evidence records, for demonstration.

The synthetic datasets record a delivery photo's metadata only (who took it, when, where, of what); no image is
generated. When SUHAIL_MEDIA_DIR names a folder that holds a file called after a photo record's public id
(for example SYN-SHP-000443-PHOTO-001.jpg), that file is served for the record and the record's node says so, marked as
an illustration attached for demonstration. Nothing here is read by the investigator, its tools, the reviewer, the
authority policy or the outcome verifier: an image is never evidence of delivery.
"""
import os
import re
from pathlib import Path

from operations.identifiers import public_value

ENVIRONMENT = "SUHAIL_MEDIA_DIR"
KINDS = ("PhotoEvidence",)
TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
IDENTITY = re.compile(r"[A-Z0-9][A-Z0-9-]{0,159}")
NOTE = ("Proof-of-delivery photograph attached to the photo record of this synthetic shipment.",
        "صورة إثبات التسليم المرفقة بسجل الصورة لهذه الشحنة الاصطناعية.")


def media_file(node_id, directory=None):
    """The image file attached to a record id, or None. Only a file directly inside the media folder, named by the id."""
    root = directory or os.environ.get(ENVIRONMENT)
    if not root or not isinstance(node_id, str) or not IDENTITY.fullmatch(node_id):
        return None
    root = Path(root)
    for suffix in TYPES:
        path = root / (node_id + suffix)
        if path.is_file():
            return path
    return None


def attach(nodes, directory=None):
    """Mark each photo record that has an attached image file: node["media"] = {url, content_type, illustration, note}."""
    for node in nodes or []:
        if node.get("kind") not in KINDS:
            continue
        public = public_value(node.get("id"))      # Files are named by the id as the interface shows it.
        path = media_file(public, directory)
        if path is not None:
            node["media"] = {"url": "/media/evidence/" + public, "content_type": TYPES[path.suffix.lower()], "illustration": True,
                             "note_en": NOTE[0], "note_ar": NOTE[1]}
    return nodes
