"""Evidence rules and bounded map layers, without hidden labels or model rationale."""
import math

from dataset_v2.contracts import Node, Edge, World, instant
from dataset_v2.context import evidence_context
from dataset_v2.derive import assess_shipment, custody_corroborated


def public_evidence(world, shipment_id, as_of=None):
    shipment = world.nodes.get(shipment_id)
    if shipment is None or shipment.kind != "Shipment" or shipment.properties.get("split") != "development":
        raise LookupError("Operational shipment not found")
    cutoff = instant(as_of or shipment.properties["as_of"])
    if instant(shipment.properties["recorded_at"]) > cutoff:
        raise LookupError("Operational shipment is not visible at this snapshot")
    context = evidence_context(world, shipment_id, as_of)
    selected = {row["id"] for row in context["nodes"]}
    withheld = set(world.nodes) - selected
    private = {"_v2_record_hash", "gold", "expected_cause", "expected_codes", "recipe", "chain_of_thought", "reasoning", "thinking"}
    def clean(props):
        output = {}
        for key, value in props.items():
            if key in private or key.startswith(("gold_", "recipe_")) or isinstance(value, dict):
                continue
            if isinstance(value, str) and value in withheld:
                continue
            if isinstance(value, list):
                value = [item for item in value if not isinstance(item, str) or item not in withheld]
            output[key] = value
        return output
    for row in context["nodes"] + context["edges"]:
        row["properties"] = clean(row["properties"])
    return context


def evidence_world(context, config):
    """Private ownership reattached internally; output contains no split labels."""
    world = World(config)
    sid = context["shipment_id"]
    from dataset_v2.context import CATALOG
    for row in context["nodes"]:
        props = dict(row["properties"])
        if row["kind"] not in CATALOG:
            props.update(shipment_id=sid, holdout_group=sid, split="development")
        world.nodes[row["id"]] = Node(row["id"], row["kind"], props)
    for row in context["edges"]:
        world.edges[row["id"]] = Edge(row["id"], row["kind"], row["start"], row["end"], dict(row["properties"]))
    return world


def operational_status(codes, *, resolved=False, delivered=False):
    if resolved:
        return "RESOLVED"
    codes = set(codes)
    for code, label in (("DELIVERY_DISPUTE", "DELIVERY_DISPUTE"), ("UNRECONCILED_CUSTODY", "UNRECONCILED_CUSTODY"),
                        ("CONFLICTING_CUSTODY", "CRITICAL"), ("ADDRESS_CONFLICT", "ADDRESS_CONFLICT"),
                        ("WRONG_GATE", "ADDRESS_CONFLICT"), ("RECIPIENT_UNAVAILABLE", "RECIPIENT_UNAVAILABLE"),
                        ("HUB_DELAY", "HUB_DELAY"), ("SLA_RISK", "SLA_RISK")):
        if code in codes:
            return label
    return "NEEDS_ATTENTION" if codes else "ON_TIME"


def journey_forecast(world, assessment):
    """A bounded travel-window estimate, never a claim about hidden future events."""
    sid = assessment["shipment_id"]
    shipment = world.nodes[sid]
    plan = world.nodes.get(shipment.properties.get("journey_id"))
    if not plan or not plan.properties.get("promise_at"):
        return {"available": False, "reason": "No visible service promise"}
    if assessment["delivery_assessment"] and all(d["assessment"] == "CORROBORATED_DELIVERY" for d in assessment["delivery_assessment"]):
        return {"available": False, "reason": "Delivery is already corroborated"}
    from datetime import timedelta
    segments = sorted((n for n in world.owned(sid) if n.kind == "RouteSegment"), key=lambda n: n.properties.get("sequence", 0))
    holders = {row["last_corroborated_holder_id"] for row in assessment["custody"]}
    start_indices = [i for i, seg in enumerate(segments) if seg.properties.get("from_id") in holders]
    supporting = [row["last_corroborated_event_id"] for row in assessment["custody"] if row["last_corroborated_event_id"]]
    if not start_indices:
        for row in assessment["custody"]:
            event = world.nodes.get(row["last_corroborated_event_id"])
            if event and event.properties.get("event_type") == "LOADED":
                start_indices += [i for i, seg in enumerate(segments) if seg.properties.get("from_id") == event.properties.get("facility_id")]
    if not start_indices:
        return {"available": False, "reason": "Last corroborated holder cannot be bound to a remaining route segment"}
    remaining = segments[min(start_indices):]
    if not remaining or any(type(seg.properties.get(k)) not in (int,float) or seg.properties[k] < 0
                            for seg in remaining for k in ("minimum_seconds", "maximum_seconds")):
        return {"available": False, "reason": "Remaining route has no valid travel bounds"}
    if any(a.properties.get("to_id") != b.properties.get("from_id") for a,b in zip(remaining,remaining[1:])):
        return {"available": False, "reason": "Remaining route is not connected"}
    cutoff = instant(assessment["as_of"])
    active_traffic = [n for n in world.owned(sid) if n.kind == "TrafficObservation"
                      and n.properties.get("segment_id") in {seg.id for seg in remaining}
                      and n.properties.get("confidence",0) >= .9
                      and n.properties.get("delay_seconds",0) > 0
                      and n.properties.get("start_at") and n.properties.get("end_at")
                      and instant(n.properties["start_at"]) <= cutoff < instant(n.properties["end_at"])]
    delay = sum(n.properties["delay_seconds"] for n in active_traffic)
    earliest = cutoff + timedelta(seconds=sum(n.properties["minimum_seconds"] for n in remaining) + delay)
    latest = cutoff + timedelta(seconds=sum(n.properties["maximum_seconds"] for n in remaining) + delay)
    promise = instant(plan.properties["promise_at"])
    return {"available": True, "earliest_estimate_at": earliest.isoformat(), "latest_estimate_at": latest.isoformat(),
            "promise_at": plan.properties["promise_at"], "sla_risk": latest > promise,
            "minimum_travel_already_exceeds_promise": earliest > promise,
            "evidence_ids": sorted(set([plan.id,*supporting,*[n.id for n in remaining],*[n.id for n in active_traffic]])),
            "certainty": "travel_window_estimate", "assumptions": ["Remaining travel starts at the snapshot clock.",
             "Service, handling and stops may require additional time; this is not a guaranteed arrival prediction."]}


ACTIONS = {
    "BARCODE_MISMATCH": "Rescan the package and compare the readable barcode with its manifest.",
    "WEIGHT_MISMATCH": "Perform a calibrated remeasurement and compare it with the manifest tolerance.",
    "ADDRESS_CONFLICT": "Confirm the effective address with the recipient before another delivery attempt.",
    "WRONG_GATE": "Confirm the current gate instruction before another delivery attempt.",
    "RECIPIENT_UNAVAILABLE": "Confirm a reachable contact and an eligible delivery session within retry policy.",
    "TRAFFIC_DELAY": "Check route delay and safe return evidence; prioritize the next eligible session if accounted for.",
    "DELIVERY_DISPUTE": "Request a human review of recipient report, address, bound proof and custody evidence.",
    "PROOF_INSUFFICIENT": "Collect bound recipient and location corroboration; do not certify delivery yet.",
    "UNRECONCILED_CUSTODY": "Reconcile package custody from the last corroborated holder and obtain a depot receipt or valid delivery proof.",
    "CONFLICTING_CUSTODY": "Ask a human to reconcile independently attributed incompatible custody reports.",
    "CUSTODY_GAP": "Obtain the missing transfer acknowledgments and a package-bound receipt.",
    "MISSED_MILESTONE": "Investigate the missing expected milestone using its last corroborated custody event.",
    "JOURNEY_DELAY": "Check the observed journey against contextual milestone deadlines.",
    "INSUFFICIENT_EVIDENCE": "Collect the missing package-bound evidence before recommending an operational action.",
    "SLA_RISK": "Check the service promise and remaining travel window; confirm a feasible route or eligible delivery session.",
}

ARABIC = {
    "BARCODE_MISMATCH": ("تختلف قراءة الباركود الواضحة وعالية الثقة عن سجل الطرد.", "أعد مسح الطرد وقارن الباركود المقروء بسجل الشحنة."),
    "WEIGHT_MISMATCH": ("يختلف قياس الوزن المعاير عن الوزن المسجل بما يتجاوز هامش السماح.", "أعد قياس الوزن بأداة معايرة وقارنه بالوزن المسجل وهامش السماح."),
    "ADDRESS_CONFLICT": ("استُخدمت نسخة عنوان خارج فترة سريانها في محاولة التسليم.", "أكد العنوان الساري مع المستلم قبل محاولة تسليم أخرى."),
    "WRONG_GATE": ("تختلف البوابة المرصودة عن التعليمات السارية وقت المحاولة.", "أكد تعليمات البوابة الحالية قبل محاولة تسليم أخرى."),
    "RECIPIENT_UNAVAILABLE": ("تتوافق محاولة الوصول غير الناجحة مع سجلات اتصال مستقلة دون رد.", "أكد وسيلة اتصال متاحة وموعد تسليم مؤهل ضمن سياسة عدد المحاولات."),
    "TRAFFIC_DELAY": ("تؤيد ملاحظة المرور تأخر الرحلة عن المعالم المتوقعة؛ ولا تثبت موقع الطرد أو مسؤولية شخص.", "راجع تأخر المسار ودليل العودة الآمنة، وأعط الأولوية للدورة المؤهلة التالية إذا كانت الحيازة مؤكدة."),
    "DELIVERY_DISPUTE": ("بلاغ المستلم عن عدم الاستلام يستدعي التحقيق حتى عند وجود دليل تسليم.", "اطلب مراجعة بشرية لبلاغ المستلم والعنوان ودليل التسليم المرتبط بالطرد وسلسلة الحيازة."),
    "PROOF_INSUFFICIENT": ("لا يكفي نوع دليل التسليم وحده لتأكيد التسليم؛ يلزم تحقق مرتبط بالمستلم والطرد.", "اجمع أدلة مرتبطة بالمستلم والموقع، ولا تعتمد تأكيد التسليم بعد."),
    "UNRECONCILED_CUSTODY": ("لا توجد مطابقة صحيحة للتسليم أو العودة إلى المستودع بعد نهاية الدورة وهامش السماح.", "طابق حيازة الطرد بدءًا من آخر حائز تؤيده الأدلة، واحصل على إيصال مستودع أو دليل تسليم صحيح."),
    "CONFLICTING_CUSTODY": ("تسمّي تقارير مستقلة ومتزامنة حائزين غير متوافقين؛ ويستلزم ذلك تحقيقًا بشريًا.", "اطلب من مختص مطابقة تقارير الحيازة المستقلة والمتعارضة."),
    "CUSTODY_GAP": ("توجد فجوة في النقل أو تأكيداته أو الدليل المرتبط بالطرد ضمن سلسلة الحيازة.", "اجمع تأكيدات النقل المفقودة وإيصالًا مرتبطًا بالطرد."),
    "MISSED_MILESTONE": ("لم تُرصد الملاحظة المتوقعة بعد موعدها المحدد وهامش السماح.", "تحقق من المعلم المتوقع المفقود باستخدام آخر حدث حيازة تؤيده الأدلة."),
    "JOURNEY_DELAY": ("رُصد المعلم بعد الموعد المحدد وهامش السماح.", "قارن الرحلة المرصودة بمواعيد المعالم المتوقعة ضمن سياق الخدمة."),
    "INSUFFICIENT_EVIDENCE": ("تنقص بيانات الطرد اللازمة للتحقق من الشحنة.", "اجمع الأدلة المفقودة المرتبطة بالطرد قبل التوصية بإجراء تشغيلي."),
    "SLA_RISK": ("يمتد تقدير وقت السفر المتبقي إلى ما بعد الموعد الموعود؛ وهذا تقدير وليس تأكيدًا لوقت الوصول.", "راجع الموعد الموعود ونطاق وقت السفر المتبقي، وأكد مسارًا ممكنًا أو دورة تسليم مؤهلة."),
}


def triage(context, config, precedents=()):
    world = evidence_world(context, config)
    assessment = assess_shipment(world, context["shipment_id"], context["as_of"])
    forecast = journey_forecast(world, assessment)
    known = set(world.nodes)
    diagnoses = [{"code": item["code"], "summary": " ".join(item["reasons"]),
                  "evidence_ids": [key for key in item["evidence_ids"] if key in known],
                  "certainty": "supported_observation", "requires_human_review": item["requires_human_review"]}
                 for item in assessment["exceptions"]]
    if forecast.get("sla_risk"):
        diagnoses.append({"code":"SLA_RISK","summary":"The remaining travel estimate extends beyond the visible service promise.",
                          "evidence_ids":[key for key in forecast["evidence_ids"] if key in known],
                          "certainty":"travel_window_estimate","requires_human_review":False})
    for diagnosis in diagnoses:
        diagnosis["summary_en"]=diagnosis["summary"]
        diagnosis["summary_ar"]=ARABIC.get(diagnosis["code"],ARABIC["INSUFFICIENT_EVIDENCE"])[0]
    state = "HUMAN_REVIEW" if assessment["requires_human_review"] else "AWAITING_APPROVAL"
    if any(d["code"] == "INSUFFICIENT_EVIDENCE" for d in diagnoses):
        state = "NEEDS_EVIDENCE"
    if not diagnoses:
        state = "NO_EXCEPTION"
    labels = list(assessment["supported_codes"])
    if forecast.get("sla_risk"):
        labels.append("SLA_RISK")
    for comparison in assessment["expected_vs_actual"]:
        location = world.nodes.get(comparison.get("location_id"))
        if comparison.get("missing_due") and location and location.kind in ("Hub", "SortingCenter"):
            labels.append("HUB_DELAY")
    if "TRAFFIC_DELAY" in labels:
        labels.append("ROUTE_DELAY")
    if any(d["assessment"] == "POSSIBLE_MISDELIVERY" for d in assessment["delivery_assessment"]):
        labels.append("POSSIBLE_MISDELIVERY")
    return {"mode": "deterministic_evidence_rules", "synthetic": True, "as_of": context["as_of"],
            "assessment": assessment, "diagnoses": diagnoses, "workflow_state": state,
            "journey_forecast": forecast, "operational_labels": sorted(set(labels)), "operational_status": operational_status(labels),
            "recommendations": [{"code": d["code"], "action": ACTIONS.get(d["code"], ACTIONS["INSUFFICIENT_EVIDENCE"]),
                                 "action_en": ACTIONS.get(d["code"], ACTIONS["INSUFFICIENT_EVIDENCE"]),
                                 "action_ar": ARABIC.get(d["code"],ARABIC["INSUFFICIENT_EVIDENCE"])[1],
                                 "evidence_ids": d["evidence_ids"], "status": "PROPOSED", "requires_approval": True} for d in diagnoses],
            "precedents": list(precedents), "outcome": None,
            "limitations": ["Synthetic evidence; rule support is not independent operational truth.",
                            "Vehicle GPS does not prove parcel location. Recommendations do not verify outcomes."]}


def route_layers(context, config, max_points=200):
    world = evidence_world(context, config)
    cutoff = instant(context["as_of"])
    nodes = world.nodes
    # Trace compatible corroborated transitions, not individually credible but
    # mutually incompatible raw custody assertions.
    accepted = set()
    grouped = {}
    for node in nodes.values():
        if node.kind == "CustodyEvent":
            grouped.setdefault(node.properties.get("package_id"), []).append(node)
    for events in grouped.values():
        holder = None
        for event in sorted(events,key=lambda n:(n.properties["occurred_at"],n.id)):
            p=event.properties
            incompatible = any(other.id != event.id and other.properties.get("occurred_at")==p.get("occurred_at")
                and other.properties.get("from_id")==p.get("from_id") and other.properties.get("to_id")!=p.get("to_id")
                and other.properties.get("source_event_id")!=p.get("source_event_id")
                and other.properties.get("source_ref")!=p.get("source_ref") for other in events)
            if not incompatible and custody_corroborated(world,event,cutoff) and (holder is None or p.get("from_id")==holder):
                accepted.add(event.id)
                holder=p.get("to_id")
    layers = {name: [] for name in ("expected_route", "actual_route", "vehicle_path", "custody_points", "hub_stops", "delivery_attempts")}
    def point(node, source, observation=None):
        if node is None:
            return None
        p = node.properties
        lat, lng = p.get("lat"), p.get("lng")
        if (type(lat) not in (int, float) or type(lng) not in (int, float)
                or not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180):
            return None
        return {"lat": lat, "lng": lng, "entity_id": node.id, "source": source,
                "occurred_at": observation.properties.get("occurred_at") if observation else None,
                "evidence_id": observation.id if observation else node.id}
    for node in sorted(nodes.values(), key=lambda n: (n.properties.get("occurred_at", ""), n.properties.get("sequence", 0), n.id)):
        p = node.properties
        if node.kind == "RouteSegment":
            pts = [point(nodes.get(p.get(key)), "expected_facility_or_address") for key in ("from_id", "to_id")]
            layers["expected_route"].append({"segment_id": node.id, "sequence": p.get("sequence"), "points": [pt for pt in pts if pt]})
        if node.kind == "GPSObservation":
            pt = point(node, "vehicle_telemetry_only", node)
            if pt:
                pt["vehicle_id"] = p.get("vehicle_id")
                layers["vehicle_path"].append(pt)
        if node.kind == "CustodyEvent" and node.id in accepted:
            holder = nodes.get(p.get("to_id"))
            # Vehicle coordinate/GPS is deliberately never substituted for parcel custody.
            pt = point(holder, "corroborated_custody", node) if holder and holder.kind != "Vehicle" else None
            if pt is None and p.get("event_type") == "DELIVERED":
                proof = nodes.get(p.get("proof_id") or p.get("source_event_id"))
                if proof and proof.kind == "DeliveryProof":
                    pt=point(proof,"corroborated_delivery_proof_location",node)
            if pt:
                layers["custody_points"].append(pt)
                layers["actual_route"].append(pt)
                if holder and holder.kind in ("Hub", "SortingCenter", "DeliveryDepot"):
                    layers["hub_stops"].append(pt)
        if node.kind == "DeliveryAttempt":
            pt = point(nodes.get(p.get("used_address_version_id")), "attempt_address_reference_not_vehicle_position", node)
            if pt:
                pt["disposition"] = p.get("disposition")
                layers["delivery_attempts"].append(pt)
    truncated = {key: len(value) > max_points for key, value in layers.items()}
    return {"layers": {key: value[:max_points] for key, value in layers.items()}, "truncated": truncated,
            "actual_route_semantics": "Corroborated custody stops, not an interpolated parcel GPS track.", "synthetic": True}
