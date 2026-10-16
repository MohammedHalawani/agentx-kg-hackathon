"""V3.4 time-aware detection evaluation on the frozen V3 world bundle. Offline: no database, no model, no network.

The development split is replayed as the live monitor sees it: every fed record becomes visible at the first hourly
tick at or after its gateway delivery (world.monitor.Replica, the offline replica of operations.store.monitor_step,
with the monitor's own 900 s detection allowance). At each evaluation clock every booked shipment is assessed with
the monitor's decision function on the evidence visible by then.

Detection never reads truth. The external scoring rows (--truth, outside the repository) are opened only after every
detector decision is recorded, and only these fields are read: healthy, recipe, mechanism types and their
knowable_at_estimate, promise_at. Without --truth the report carries coverage and evidence-based panels only.

Usage (from chat/):
  python ../scripts/v34_detection_eval.py --bundle C:/Projects/suhail-v3-data/world-v3-20261013/bundle
      [--truth C:/Projects/suhail-v3-private/world-v3-20261013/DEMO-SUHAIL-WORLD-V3-20261013/development/truth.jsonl]
      [--out report.json]
"""
import argparse
from collections import Counter, defaultdict
from datetime import timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "chat"))

from dataset_v2.contracts import instant, iso  # noqa: E402
from dataset_v2.derive import assess_shipment  # noqa: E402
from dataset_v2.feed import reconstitute  # noqa: E402
from operations.store import DETECTION_ALLOWANCE_SECONDS, monitor_finding  # noqa: E402
from world.export import read_world_bundle  # noqa: E402
from world.monitor import Replica  # noqa: E402

LATE_UPLOAD_SECONDS = 3600   # a record delivered an hour or more after it occurred: buffered/offline upload


def load(bundle_dir):
    bundle, items = read_world_bundle(bundle_dir)
    manifest = json.loads((Path(bundle_dir) / "world_manifest.json").read_text(encoding="utf-8"))
    imported = bundle.world
    full = reconstitute(imported, items)
    live_start = instant(manifest["live_start"])
    fed = {i["source_event_id"] for i in items}
    replica = Replica(full, live_start, evidence_ids=fed, gateway_lag=False)
    live = sorted(sid for sid, n in imported.nodes.items() if n.kind == "Shipment" and n.properties["split"] == "development")
    end = instant(imported.config.as_of) if imported.config.as_of else None
    return imported, items, full, replica, live, live_start, end, manifest


def assess(replica, sid, clock):
    return assess_shipment(replica.world, sid, iso(clock), _index=replica.index, detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS)


def visible_nodes(replica, sid, kind, clock):
    out = []
    for node in replica.index.groups[sid].get(kind, []):
        p = node.properties
        at, recorded = p.get("occurred_at"), p.get("recorded_at")
        if at and recorded and instant(at) <= instant(recorded) <= clock:
            out.append(node)
    return out


def population(replica, sid, clock, assessment):
    """What the visible evidence (never truth) says about the shipment at the clock."""
    shipment = replica.world.nodes[sid]
    if instant(shipment.properties["recorded_at"]) > clock:
        return "not_booked"
    rows = assessment["delivery_assessment"]
    if any(r["recipient_report_ids"] for r in rows):
        return "recipient_dispute"
    if rows and all(r["assessment"] == "CORROBORATED_DELIVERY" for r in rows):
        return "delivered_corroborated"
    statuses = sorted(visible_nodes(replica, sid, "StatusEvent", clock), key=lambda n: (n.properties["occurred_at"], n.id))
    status = statuses[-1].properties.get("status") if statuses else None
    if status == "RETURNED_TO_DEPOT":
        return "returned_to_depot"
    if status == "DELIVERED":
        return "tracking_delivered_without_corroboration"
    if visible_nodes(replica, sid, "CustodyEvent", clock) or visible_nodes(replica, sid, "ScanEvent", clock):
        return "in_progress"
    return "awaiting_first_scan"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--truth")
    parser.add_argument("--step-hours", type=int, default=12)
    parser.add_argument("--out")
    args = parser.parse_args()
    imported, items, full, replica, live, live_start, end, manifest = load(args.bundle)
    end = end or max(replica.visible.values())
    # Horizon end of the generated world: local (UTC+3) midnight after the last horizon day, as world.config.end_at.
    horizon = instant(manifest["start_date"] + "T00:00:00+00:00") - timedelta(hours=3) + timedelta(days=manifest["days"] + manifest["horizon_days"])
    clocks = []
    t = live_start + timedelta(hours=args.step_hours)
    while t <= horizon:
        clocks.append(t)
        t += timedelta(hours=args.step_hours)
    if not clocks or clocks[-1] != horizon:
        clocks.append(horizon)

    # ---- detector decisions (no truth) ----
    timelines = {sid: replica.timeline(sid, horizon) for sid in live}
    def codes_at(sid, clock):
        current = []
        for tick, codes, _ in timelines[sid]:
            if tick <= clock:
                current = codes
        return current
    def opened_at(sid):
        return next((tick for tick, codes, _ in timelines[sid] if codes), None)
    per_clock, snapshots = [], {}
    for clock in clocks:
        pops, opened, active, symptom_mix = Counter(), Counter(), Counter(), Counter()
        snap = {}
        for sid in live:
            a = assess(replica, sid, clock)
            pop = population(replica, sid, clock, a)
            first = opened_at(sid)
            was_opened = first is not None and first <= clock
            now = codes_at(sid, clock)
            snap[sid] = {"population": pop, "opened": was_opened, "active_codes": now,
                         "symptoms": monitor_finding({"exceptions": [{"code": c} for c in now]})["symptoms"]}
            if pop == "not_booked":
                continue
            pops[pop] += 1
            opened[pop] += was_opened
            active[pop] += bool(now)
            for s in snap[sid]["symptoms"]:
                symptom_mix[s] += 1
        snapshots[iso(clock)] = snap
        per_clock.append({"clock": iso(clock), "booked": sum(pops.values()), "population": dict(pops),
                          "opened_by_clock_by_population": dict(opened), "active_finding_by_population": dict(active),
                          "healthy_now_no_active_finding": sum(1 for s in snap.values() if s["population"] != "not_booked" and not s["active_codes"]),
                          "cases_opened_by_clock": sum(opened.values()), "active_symptoms": dict(symptom_mix)})

    # ---- transitions: openings that later clear on new evidence ----
    cleared_rows = []
    for sid in live:
        rows = timelines[sid]
        for (t0, c0, _), (t1, c1, _) in zip(rows, rows[1:]):
            gone = sorted(set(c0) - set(c1))
            if gone:
                cleared_rows.append({"shipment_id": sid, "from": iso(t0), "at": iso(t1), "cleared_codes": gone, "remaining_codes": c1})
    late = defaultdict(list)
    for item in items:
        if item.get("origin") != "PROVIDER":
            continue
        payload = json.loads(item["payload_json"])
        node = full.nodes.get(item["source_event_id"])
        if node is None or not node.properties.get("occurred_at"):
            continue
        lag = (instant(item["deliver_at"]) - instant(node.properties["occurred_at"])).total_seconds()
        sid = node.properties.get("shipment_id")
        if sid in timelines and lag >= LATE_UPLOAD_SECONDS:
            late[sid].append({"record": node.id, "kind": node.kind, "lag_hours": round(lag / 3600, 2)})
        del payload
    late_cleared = [r for r in cleared_rows if r["shipment_id"] in late]

    # ---- evidence-based panels (A3), detector outcome at the horizon ----
    final = snapshots[iso(horizon)]
    def panel(name, sids, expectation):
        sids = sorted(sids)
        return {"panel": name, "expectation": expectation, "shipments": len(sids),
                "opened": sum(1 for s in sids if opened_at(s)), "active_at_horizon": sum(1 for s in sids if final[s]["active_codes"]),
                "opening_codes": dict(Counter(" + ".join(next(c for _, c, _ in timelines[s] if c)) for s in sids if opened_at(s)))}
    def kind_nodes(sid, kind):
        return visible_nodes(replica, sid, kind, horizon)
    failed_returned = {sid for sid in live
                       if any(n.properties.get("disposition") == "FAILED" for n in kind_nodes(sid, "DeliveryAttempt"))
                       and any(n.properties.get("result") == "RETURNED" for n in kind_nodes(sid, "DepotReconciliation"))}
    delivered_clean = {sid for sid in live if final[sid]["population"] == "delivered_corroborated"
                       and not any(n.properties.get("disposition") == "FAILED" for n in kind_nodes(sid, "DeliveryAttempt"))}
    bulky = {sid for sid in live if replica.world.nodes[sid].properties.get("handling") in ("bulky", "heavy")}
    plans = {n.properties["shipment_id"]: n for n in replica.world.nodes.values() if n.kind == "JourneyPlan" and n.properties.get("shipment_id") in timelines}
    multi_day = {sid for sid, p in plans.items() if instant(p.properties["promise_at"]) - instant(replica.world.nodes[sid].properties["recorded_at"]) > timedelta(hours=24)}
    disputes = {sid for sid in live if final[sid]["population"] == "recipient_dispute"}
    tracking_conflict = {sid for sid in live if any(snapshots[iso(c)][sid]["population"] == "tracking_delivered_without_corroboration" for c in clocks)}
    weight_compared = {sid for sid in live if any(r["predicate"] == "WEIGHT_KG" for r in assess(replica, sid, horizon)["expected_vs_actual"])}
    panels = [
        panel("delivered with corroborated proof, no failed attempt", delivered_clean, "no case unless another discrepancy is visible"),
        panel("failed attempt followed by a recorded return to depot", failed_returned, "may open for the failed attempt or overdue delivery; must never assert loss"),
        panel("multi-day journey (promise more than 24 h after booking)", multi_day, "no case while milestones are within their windows"),
        panel("bulky/heavy handling", bulky, "no weight case inside the calibrated tolerance"),
        panel("calibrated weight observed", weight_compared, "case only when outside max(0.5 kg, 10 %)"),
        panel("recipient reported not received", disputes, "human-review dispute case; never auto-dismissed"),
        panel("tracking says delivered without corroborated delivery at some clock", tracking_conflict, "a case when no corroborating proof arrives"),
        panel("has a buffered upload (delivered >= 1 h after occurrence)", set(late), "reassessed on event time when the upload arrives"),
    ]
    # "No scan yet, milestone not due": shipments booked by a clock with nothing visible and no milestone due.
    not_due_opened = 0
    not_due = 0
    for clock in clocks:
        for sid in live:
            s = snapshots[iso(clock)][sid]
            if s["population"] == "awaiting_first_scan":
                due = [r for r in assess(replica, sid, clock)["expected_vs_actual"] if r.get("due")]
                if not due:
                    not_due += 1
                    not_due_opened += bool(s["active_codes"])
    # Promise contract: does each package's DELIVERED milestone deadline equal the plan's promise?
    promise_rows = Counter()
    for sid, plan in plans.items():
        promise = instant(plan.properties["promise_at"])
        delivered_ms = [n for n in replica.index.groups[sid].get("ExpectedMilestone", []) if n.properties.get("predicate") == "DELIVERED"]
        if not delivered_ms:
            promise_rows["no_delivered_milestone"] += 1
        for m in delivered_ms:
            latest = instant(m.properties["latest_at"]) + timedelta(seconds=m.properties.get("grace_seconds") or 0)
            promise_rows["milestone_deadline_equals_promise" if latest == promise else
                          "milestone_deadline_before_promise" if latest < promise else "milestone_deadline_after_promise"] += 1

    report = {"bundle": str(args.bundle), "dataset_id": imported.config.dataset_id, "live_start": iso(live_start), "horizon_end": iso(horizon),
              "detection_allowance_seconds": DETECTION_ALLOWANCE_SECONDS, "tick_seconds": 3600, "live_shipments": len(live),
              "per_clock": per_clock, "cleared_transitions": {"count": len(cleared_rows), "shipments": len({r["shipment_id"] for r in cleared_rows}),
                                                               "codes": dict(Counter(c for r in cleared_rows for c in r["cleared_codes"])),
                                                               "fully_cleared": sum(1 for r in cleared_rows if not r["remaining_codes"]),
                                                               "rows": cleared_rows},
              "late_uploads": {"shipments": len(late), "records": sum(len(v) for v in late.values()),
                               "kinds": dict(Counter(r["kind"] for v in late.values() for r in v)),
                               "cleared_transitions_on_those_shipments": len(late_cleared)},
              "panels": panels, "no_scan_not_due": {"shipment_clock_pairs": not_due, "with_active_finding": not_due_opened},
              "promise_contract": dict(promise_rows)}

    # ---- scoring against external truth (read last) ----
    if args.truth:
        truth = {}
        for line in Path(args.truth).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["shipment_id"] in timelines:
                truth[row["shipment_id"]] = {"healthy": row["healthy"], "recipe": row["recipe"],
                                             "mechanisms": sorted({m["type"] for m in row["mechanisms"] if m.get("resolution") != "NONE"}),
                                             "knowable_at": row.get("knowable_at_estimate"), "promise_at": row.get("promise_at")}
        scored = []
        for clock in clocks:
            snap = snapshots[iso(clock)]
            booked = [s for s in live if snap[s]["population"] != "not_booked"]
            healthy = [s for s in booked if truth[s]["healthy"]]
            abnormal = [s for s in booked if not truth[s]["healthy"]]
            knowable = [s for s in abnormal if truth[s]["knowable_at"] and instant(truth[s]["knowable_at"]) <= clock]
            scored.append({"clock": iso(clock), "booked": len(booked), "healthy": len(healthy),
                           "healthy_opened": sum(snap[s]["opened"] for s in healthy), "abnormal": len(abnormal),
                           "abnormal_knowable_by_clock": len(knowable), "knowable_opened": sum(snap[s]["opened"] for s in knowable),
                           "abnormal_opened_before_knowable": sum(snap[s]["opened"] for s in abnormal if s not in knowable)})
        healthy = [s for s in live if truth[s]["healthy"]]
        abnormal = [s for s in live if not truth[s]["healthy"]]
        missed = [s for s in abnormal if not opened_at(s)]
        delays = [(opened_at(s) - instant(truth[s]["knowable_at"])).total_seconds() / 3600 for s in abnormal
                  if opened_at(s) and truth[s]["knowable_at"]]
        report["scoring"] = {
            "source": "external generated truth rows (evaluation only; never read by detection)",
            "healthy": len(healthy), "healthy_opened": sum(1 for s in healthy if opened_at(s)),
            "abnormal": len(abnormal), "abnormal_opened": len(abnormal) - len(missed),
            "missed": [{"shipment_id": s, "recipe": truth[s]["recipe"], "mechanisms": truth[s]["mechanisms"]} for s in missed],
            "false_positives": [{"shipment_id": s, "codes": next(c for _, c, _ in timelines[s] if c)} for s in healthy if opened_at(s)],
            "hours_from_knowable_to_opening": {"n": len(delays), "median": sorted(delays)[len(delays) // 2] if delays else None,
                                               "min": min(delays) if delays else None, "max": max(delays) if delays else None},
            "per_clock": scored,
            "per_recipe": {recipe: {"shipments": sum(1 for s in live if truth[s]["recipe"] == recipe),
                                    "opened": sum(1 for s in live if truth[s]["recipe"] == recipe and opened_at(s))}
                           for recipe in sorted({truth[s]["recipe"] for s in live})},
            "cleared_transitions_on_healthy": sum(1 for r in cleared_rows if truth[r["shipment_id"]]["healthy"]),
        }
    text = json.dumps(report, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    summary = {k: v for k, v in report.items() if k not in ("per_clock", "cleared_transitions")}
    summary["cleared_transitions"] = {k: v for k, v in report["cleared_transitions"].items() if k != "rows"}
    summary["per_clock"] = [{k: r[k] for k in ("clock", "booked", "population", "cases_opened_by_clock", "healthy_now_no_active_finding")} for r in per_clock]
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
