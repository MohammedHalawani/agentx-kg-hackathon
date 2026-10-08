"""Live, read-only API coherence gate. Run after building and restarting the app."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
ALLOWED_LABELS = {"Shipment", "Order", "Customer", "Address", "Courier", "Event",
                  "FailureReason", "Resolution", "Outcome", "Policy", "EscalatedCase"}


def get(path):
    with urlopen(BASE + path, timeout=30) as response:
        return json.load(response)


def check_graph(graph, selected):
    nodes = graph["nodes"]
    assert len(nodes) <= 500
    ids = {n["id"] for n in nodes}
    assert len(ids) == len(nodes)
    actual = {n["properties"]["shipment_id"] for n in nodes if "Shipment" in n["labels"]}
    assert actual == selected, (actual, selected)
    assert all(set(n["labels"]) <= ALLOWED_LABELS for n in nodes)
    assert all("embedding" not in n["properties"] for n in nodes)
    assert all(r["from"] in ids and r["to"] in ids for r in graph["relationships"])
    assert len(graph["relationships"]) <= 800
    return {"nodes": len(nodes), "relationships": len(graph["relationships"]), "shipments": len(actual),
            "truncated": graph.get("truncated", False)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/agent-runs/2026-10-07_shipment-product-coherence-api-gate.json")
    args = parser.parse_args()
    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "base": BASE, "filters": {}}
    for name in ("needs_attention", "all", "stalled", "critical", "delivered"):
        data = get("/explore?filter=" + name)
        shipments = data["shipments"]
        assert data["returned"] == len(shipments) <= 25
        assert data["total"] == data["counts"][name]
        if name != "all":
            assert all(s[name] for s in shipments)
        assert all(s.get("destinations") for s in shipments), "Map should have valid shipment points"
        selected = {s["shipment_id"] for s in shipments}
        report["filters"][name] = {"total": data["total"], "returned": data["returned"],
                                    **check_graph(data["graph"], selected)}
    default = get("/explore")
    assert default["filter"] == "needs_attention"
    check_graph(get("/graph"), {s["shipment_id"] for s in default["shipments"]})
    check_graph(get("/graph?shipment_id=SHP-0227"), {"SHP-0227"})
    check_graph(get("/graph?shipment_id=SHP-NONEXISTENT"), set())
    schema = get("/schema")
    # schema graph nodes carry the real domain label in caption and label-list.
    captions = {n["caption"] for n in schema["nodes"]}
    assert "Shipment" in captions and "FailureReason" in captions
    assert captions <= ALLOWED_LABELS, captions
    report["schema"] = {"labels": sorted(captions), "relationships": len(schema["relationships"])}
    for path in ("/explore?filter=lost", "/explore?limit=0", "/explore?limit=51"):
        try:
            get(path)
        except HTTPError as exc:
            assert exc.code == 422
        else:
            raise AssertionError("Invalid Explore query accepted")
    report["intake_cases"] = len(get("/samples")["cases"])
    decisions = get("/cases")
    report["decisions"] = {"coverage": decisions["coverage"], "writebacks": decisions["writebacks"]}
    report["verdict"] = "PASS"
    target = args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
