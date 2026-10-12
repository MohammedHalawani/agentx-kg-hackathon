"""Write the per-stage evidence map of one finished case, for the recording choreography. Reads only, over HTTP.

  cd chat && uv run python ../scripts/showcase_evidence_map.py --shipment SYN-SHP-000304 --video A --started-at <UTC wall time of Start>

Everything in the map is taken from the case's own stored records: the ids a stage event recorded, the nodes and
relationships of the case's evidence graph, and the stage facts the backend serves. Nothing is invented: an id that
is not a node of the evidence graph is left out, and a stage with no located record has select = null.

Stages: 0 Opening, then Collect, Graph, Diagnose, Precedent, Recommend, Review, Disposition, Outcome (the pipeline's
extract, retrieve, classify, retrieve_context, recommend, review, writeback or escalate, and the verified outcome).
fires_at_s is the wall-clock seconds after --started-at at which the stage's completing event was recorded in this run.
"""
import argparse
import json
import pathlib
import sys
import urllib.parse
import urllib.request
from datetime import datetime

STAGES = [("Collect", ("extract",)), ("Graph", ("retrieve",)), ("Diagnose", ("classify",)), ("Precedent", ("retrieve_context",)),
          ("Recommend", ("recommend",)), ("Review", ("review",)), ("Disposition", ("writeback", "escalate"))]
LIMIT = 18
RECORDS = ("CustodyEvent", "ScanEvent", "DeliveryAttempt", "DeliveryProof", "PhotoEvidence", "AuthenticationEvidence", "HandoffEvidence", "DepotReconciliation")
# Fahad's wording for the recording-only phone visual of Video A (his message of 2026-10-12 01:02 UTC). The genuine
# request recorded by the backend goes to the depot; the phone is the driver-facing visualization of that request.
PHONE = {"title": "Suhail — Custody confirmation required",
         "body": "Your route has ended, but shipment {shipment} has no delivery confirmation or warehouse return scan. Please confirm its status.",
         "options": ["Scan package into warehouse", "Provide delivery confirmation", "Report package missing"],
         "chosen": "Scan package into warehouse"}


def get(origin, path):
    with urllib.request.urlopen(origin + path, timeout=120) as response:
        return json.loads(response.read())


def when(text):
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


class Graph:
    def __init__(self, detail):
        self.nodes = {n["id"]: n for n in detail["evidence"]["nodes"]}
        self.edges = detail["evidence"]["edges"]

    def props(self, node_id):
        return (self.nodes.get(node_id) or {}).get("properties") or {}

    def known(self, ids, before=False):
        """Ids that are nodes of the graph; before=True keeps only those the investigation could see (not ones that arrived after it)."""
        return [i for i in dict.fromkeys(ids or []) if i in self.nodes and not (before and self.nodes[i].get("after_investigation"))]

    def place(self, node_id):
        """Where a record is, from its own fields: (lat, lng, facility id) or None."""
        p = self.props(node_id)
        if p.get("lat") is not None and p.get("lng") is not None:
            return {"lat": p["lat"], "lng": p["lng"], "facility_id": p.get("facility_id"), "from": "record"}
        for key in ("facility_id", "to_id", "checked_facility_id", "location_id"):
            f = self.props(p.get(key)) if p.get(key) in self.nodes else {}
            if f.get("lat") is not None and f.get("lng") is not None:
                return {"lat": f["lat"], "lng": f["lng"], "facility_id": p[key], "from": key}
        return None

    def around(self, ids, before=False):
        """The records with the things they point at that are in the graph (holder, facility, device, vehicle, package)."""
        out = list(ids)
        for i in ids:
            p = self.props(i)
            for key in ("package_id", "from_id", "to_id", "facility_id", "device_ref", "vehicle_id", "driver_id", "route_run_id", "source_event_id",
                        "attempt_id", "proof_id", "authentication_id", "photo_id", "handoff_id"):
                if p.get(key) in self.nodes:
                    out.append(p[key])
        return self.known(out, before)[:LIMIT]

    def links(self, ids):
        chosen = set(ids)
        return [e["id"] for e in self.edges if e["start"] in chosen and e["end"] in chosen]

    def stage(self, name, ids, fact, fires, *, select=None, mode="Balanced", note=None, before=True):
        ids = self.around(self.known(ids, before), before)
        located = select if select is not None else next((i for i in ids if self.nodes[i]["kind"] in RECORDS and self.place(i)), None)
        selections = located if isinstance(located, list) else ([located] if located else [])
        return {"stage": name, "highlight": ids, "highlight_relationships": self.links(ids),
                "select": located, "select_location": [dict(id=i, **(self.place(i) or {})) for i in selections],
                "mode": mode, "fact": fact, "fires_at_s": fires, **({"note": note} if note else {})}


def build(detail, video, started_at, audit=None):
    g = Graph(detail)
    sid = detail["shipment_id"]
    events = [e for e in detail["pipeline"]["events"] if e.get("status") not in ("RUNNING", "RETRYING")]
    facts = {}
    for fact in detail["pipeline"]["stage_facts"]:
        facts[fact["stage"]] = fact               # The last round of each stage.
    start = when(started_at) if started_at else None
    seconds = lambda text: round((when(text) - start).total_seconds(), 1) if start and text else None
    last = {}
    for event in events:
        last[event["stage"]] = event
    packages = [i for i, n in g.nodes.items() if n["kind"] == "Package"]
    # The custody chain as the investigation saw it (records that arrived later are left out until Outcome).
    custody = sorted(g.known([i for i, n in g.nodes.items() if n["kind"] == "CustodyEvent"], True), key=lambda i: g.props(i).get("occurred_at") or "")
    latest = next((i for i in reversed(custody) if g.place(i)), None)      # The latest recorded place of the parcel at that time.
    wall = {}
    for entry in audit or []:
        wall.setdefault(entry.get("event_type"), entry.get("timestamp"))
    stages = [g.stage("Opening", [sid, *packages, *((last.get("extract") or {}).get("output") or {}).get("evidence_ids", [])],
                      (detail["brief"]["what_happened"] or {}).get("text_en"), seconds(wall.get("CASE_OPENED")), select=latest)]
    for name, keys in STAGES:
        event = next((last[k] for k in keys if k in last), None)
        out = (event or {}).get("output") or {}
        fact = next((facts[k] for k in keys if k in facts), {})
        ids = list(out.get("evidence_ids") or [])
        select, mode, note = None, "Balanced", None
        if name == "Collect":
            ids, select = [sid, *packages, *ids], latest
        elif name == "Graph":
            # The shipment with the latest part of its custody chain and the people, vehicles and places those records name.
            ids, select = [sid, *packages, *custody[-5:]], latest
        elif name == "Diagnose":
            cited = [i for i in g.known(ids, True) if g.nodes[i]["kind"] in RECORDS]
            cited.sort(key=lambda i: g.props(i).get("occurred_at") or "")
            located = [i for i in cited if g.place(i)]
            first = located[-1] if located else latest
            # Two selections in order: the cited record that places the parcel (for the map), then the custody record
            # before it in the chain (for the graph): the last holder on record before the unconfirmed handover.
            earlier = [i for i in custody if first and (g.props(i).get("occurred_at") or "") < (g.props(first).get("occurred_at") or "")]
            select = [first] + earlier[-1:] if first else None
            ids = ids + (select or [])
            mode = ["Map focus", "Graph focus"] if select and len(select) == 2 else "Balanced"
            note = ("The records the accepted investigation cited, then the custody record before the cited one. This shipment's graph holds no vehicle "
                    "GPS observation and no other shipment's records, so neither is highlighted.")
        elif name == "Precedent":
            precedents = out.get("precedents") or []
            note = (f"{out.get('verified_precedents') or 0} verified precedent(s) were retrieved from the ledger; they are stored cases, not nodes of this "
                    f"shipment's graph: " + ", ".join(str(p.get("case_id")) for p in precedents[:5]))
        elif name == "Disposition":
            executions = detail.get("executions") or []
            asked = [e.get("target_device") for e in executions if e.get("target_device")]
            ids = [sid, *packages, *asked, *([latest] if latest else []), *ids]
            select = latest
            action = (detail["brief"].get("actions") or [{}])[0]
            note = action.get("text_en")
        stages.append(g.stage(name, ids, fact.get("fact_en"), seconds((event or {}).get("recorded_at")), select=select, mode=mode, note=note))
    outcome = detail.get("outcome") or {}
    stages.append(g.stage("Outcome", list(outcome.get("evidence_ids") or []), (facts.get("outcome") or {}).get("fact_en"),
                          seconds(wall.get("OUTCOME_VERIFIED") or wall.get("CASE_RESOLVED")), note=outcome.get("reason"), before=False))
    action = (detail["brief"].get("actions") or [{}])[0]
    recipient = action.get("recipient") or {}
    document = {
        "schema": "suhail-showcase-evidence-map-1", "video": video, "shipment_id": sid, "case_id": detail["case_id"],
        "synthetic": True, "source": "the case's stored records, read from GET /cases/{id}; nothing here is invented",
        "session_started_wall_at": started_at, "workflow_state": detail["workflow_state"],
        "status_line_en": next((l["text_en"] for l in detail["brief"]["lines"] if l["key"] == "status"), None),
        "status_line_ar": next((l["text_ar"] for l in detail["brief"]["lines"] if l["key"] == "status"), None),
        "action": {"type": action.get("action_type"), "label_en": action.get("label_en"), "text_en": action.get("text_en"), "text_ar": action.get("text_ar"),
                   "recipient": recipient, "authorized_by": action.get("authorized_by"), "sent_at_simulated": action.get("sent_at"),
                   "sent_at_s": seconds(wall.get("ACTION_EXECUTED")), "approved_at_s": seconds(wall.get("OPERATOR_DECISION"))},
        "outcome": {k: outcome.get(k) for k in ("verification_status", "success", "outcome_type", "exception_cleared", "reason", "evidence_ids", "verified_at")},
        "stages": stages,
    }
    if video == "A":
        document["phone"] = {**PHONE, "body": PHONE["body"].format(shipment=sid),
                             "confirmation": ("Warehouse scan recorded" if outcome.get("success") and outcome.get("outcome_type") in ("custody_reconciled", "parcel_located")
                                              else None),
                             "staged": True,
                             "what_it_stands_for": "The driver-facing visualization of the custody reconciliation request. The backend's recorded recipient "
                                                   f"is {recipient.get('label_en')}; no message was sent to a driver or to anyone outside the simulation."}
    photos = [i for i, n in g.nodes.items() if n["kind"] == "PhotoEvidence" and n.get("media")]
    if photos:
        document["photo_node"] = photos[-1]
        document["photo_url"] = g.nodes[photos[-1]]["media"]["url"]
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write the per-stage evidence map of one finished case.")
    parser.add_argument("--origin", default="http://127.0.0.1:8022")
    parser.add_argument("--shipment", required=True)
    parser.add_argument("--video", choices=("A", "B"), required=True)
    parser.add_argument("--started-at", help="UTC wall time at which the take's clock was started (ISO); fires_at_s is measured from it")
    parser.add_argument("--out", default="../artifacts/showcase")
    args = parser.parse_args(argv)
    rows = get(args.origin, "/cases/queue?scope=all&limit=100").get("items") or []
    case_id = next((r["case_id"] for r in rows if r["shipment_id"] == args.shipment), None)
    if not case_id:
        print(f"FAILED: no case for {args.shipment} in the current session", file=sys.stderr)
        return 2
    detail = get(args.origin, "/cases/" + urllib.parse.quote(case_id, safe=""))
    audit, cursor = [], None
    while True:
        page = get(args.origin, "/audit?case_id=" + urllib.parse.quote(case_id, safe="") + "&limit=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else ""))
        audit += page.get("items") or []
        cursor = page.get("next_cursor")
        if not cursor:
            break
    audit.sort(key=lambda e: e.get("sequence") or 0)
    document = build(detail, args.video, args.started_at, audit)
    directory = pathlib.Path(args.out)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"evidence_map_{args.video}_{args.shipment}.json"
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (directory / f"reference_case_{args.video}_{args.shipment}.json").write_text(json.dumps(detail, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(path), "stages": [(s["stage"], len(s["highlight"]), s["fires_at_s"]) for s in document["stages"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
