"""The canary check (amendment 1, B): no hidden truth reaches the graph, the tools or the API during a run.

Every truth row carries the world's canary token (CNRY + 24 hex characters). After a run, everything the runtime
could see and produce, captured by the run step into <run>/captured/<surface>/, is scanned for the canary, for every
mechanism id in the truth rows and for every mechanism name that is not also an operational code. Any hit invalidates
the run. The scanner first proves it can see a planted marker (a positive control built from the real canary and a
real mechanism id) and a clean control; if either fails the scan refuses to report "clean".

The required surfaces are the design's list: the graph, tool outputs, API responses, execution receipts and logs.
A run that captured fewer is reported "incomplete", never "clean". The arms' own outputs are scanned too.

This module holds no truth: the scorer passes the vocabulary in (truth_io.truth_vocabulary).
"""
import json
from pathlib import Path
import re

REQUIRED_SURFACES = ("graph", "tools", "api", "receipts", "logs")
ALSO_SCANNED = ("arm_outputs",)


class TruthScanner:
    def __init__(self, vocabulary):
        self.canary = vocabulary["canary"]
        self.ids = list(vocabulary["mechanism_ids"])
        self.names = list(vocabulary["mechanism_names"])
        strict = [re.escape(self.canary)] + [re.escape(i) for i in self.ids]
        self._strict = re.compile("|".join(strict))
        self._pattern = re.compile("|".join(strict + [rf"\b{re.escape(n)}\b" for n in self.names]))

    def hits_in(self, text, *, include_names=True):
        """Hits of the canary and mechanism ids, and (include_names) of mechanism names. A model's own words can
        coincide with a mechanism name (MISDELIVERY), so the arms' outputs are scanned without names; everything the
        runtime serves (graph, tools, API, receipts, logs) is scanned with them, as world.export check does."""
        if not text:
            return []
        out = []
        for m in (self._pattern if include_names else self._strict).finditer(text):
            token = m.group(0)
            kind = "canary" if token == self.canary else "mechanism_id" if token in self.ids else "mechanism_name"
            out.append({"kind": kind, "token": token})
        return out

    def self_test(self):
        """Positive and negative controls. Raises if the scanner would miss a planted marker or flag clean text."""
        planted = json.dumps({"note": f"planted marker {self.canary}", "ref": self.ids[0] if self.ids else self.canary})
        found = {h["kind"] for h in self.hits_in(planted)}
        if "canary" not in found or (self.ids and "mechanism_id" not in found):
            raise RuntimeError("canary scanner failed its positive control")
        if self.hits_in(json.dumps({"symptoms": ["MILESTONE_OVERDUE"], "cause": "WRONG_GATE", "id": "DEMO-SHP-000001"})):
            raise RuntimeError("canary scanner flagged clean operational text")
        return True

    def scan_run(self, run_dir):
        """Scan <run_dir>/captured/<surface>/* and return the verdict with per-surface counts (tokens are counted,
        never echoed into the report)."""
        self.self_test()
        root = Path(run_dir) / "captured"
        surfaces, hits = {}, []
        for surface_dir in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
            files = sorted(f for f in surface_dir.rglob("*") if f.is_file())
            count = 0
            for f in files:
                text = f.read_text(encoding="utf-8", errors="replace")
                for h in self.hits_in(text, include_names=surface_dir.name not in ALSO_SCANNED):
                    hits.append({"surface": surface_dir.name, "file": str(f.relative_to(root)), "kind": h["kind"]})
                    count += 1
            surfaces[surface_dir.name] = {"files": len(files), "bytes": sum(f.stat().st_size for f in files), "hits": count}
        missing = [s for s in REQUIRED_SURFACES if not surfaces.get(s, {}).get("files")]
        verdict = "invalid" if hits else "incomplete" if missing else "clean"
        by_kind = {}
        for h in hits:
            by_kind[h["kind"]] = by_kind.get(h["kind"], 0) + 1
        return {"verdict": verdict, "surfaces": surfaces, "missing_surfaces": missing, "hits": len(hits), "hits_by_kind": by_kind,
                "hit_locations": sorted({(h["surface"], h["file"]) for h in hits})[:50], "self_test": "passed"}
