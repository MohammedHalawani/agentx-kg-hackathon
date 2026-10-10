"""Verified history: how operations handled each history case, so the PRECEDENTS query returns real precedents.

Label-free (addendum B5). Nothing here reads truth labels (mechanisms, causes, resolutions) and nothing writes a
person's finding about a cause. For every imported (history) shipment whose case the monitor opened (derive's
Case at the shipment's history snapshot), the history record is what operations would have done and seen:

  action    the operations policy's default action for the case's most specific rule code
            (operations.authority.default_action); in a minority of cases the operator chose the default
            action of another rule code the case carried.
  outcome   verified from the shipment's own evidence recorded between the action and verification: succeeded
            when re-assessing the shipment (derive's assess_shipment, the monitor's rules) no longer raises any
            rule code that opened the case, or when the evidence shows what the action was for (ACTION_EVIDENCE:
            the buffered records arrived, the parcel was scanned again, a rescan read the manifest barcode, a
            reweigh agreed with the declaration, the parcel was delivered, the recipient confirmed receipt);
            otherwise failed. The outcome cites only that shipment's records recorded before verification.

Cut-off (addendum A2). Every verification happens before the development window starts. A case whose
verification cannot finish before then, or whose shipment a mechanism instance still touched at or after the
cut-off (decided by the generator from its private record and passed in as `excluded`, never written into the
graph), is not imported as a precedent: it keeps its derived Case and Exception but gets no action, resolution
or outcome, so PRECEDENTS never returns it. The simulated world is not changed by these history actions (a
documented limitation): a success means the world's own later evidence cleared the case.
"""
from datetime import timedelta

from dataset_v2.contracts import POLICY_VERSION, Provenance, instant, iso
from operations.authority import ACTIONS, default_action
from world.monitor import by_specificity

EVIDENCE_KINDS = ("CustodyEvent", "ScanEvent", "DeliveryProof", "DepotReconciliation", "RecipientReport", "AddressVersion",
                  "DeliveryAttempt", "Manifest", "CommunicationEvent")
ACTION_EVIDENCE = {
    "REQUEST_DEVICE_SYNC": "records that happened before the case opened arrive after the action",
    "INITIATE_CUSTODY_RECONCILIATION": "a custody or handling record of the parcel after the action",
    "PHYSICAL_CUSTODY_CHECK": "a facility scan of the parcel after the action",
    "CONFLICTING_CUSTODY_REVIEW": "a custody record of the parcel after the action",
    "REQUEST_HUB_CHECK": "a handling record of the parcel at a facility after the action",
    "PRIORITIZE_NEXT_SESSION": "a delivered attempt after the action",
    "REQUEST_ADDRESS_CONFIRMATION": "an address version, recipient report or delivered attempt after the action",
    "REQUEST_RESCAN": "a later read of the label that returns the manifest barcode",
    "REQUEST_REWEIGH": "a later weighing within max(0.5 kg, 10 %) of the declared weight",
    "REQUEST_ADDITIONAL_EVIDENCE": "a delivery proof, authentication or recipient report after the action",
    "DELIVERY_DISPUTE_REVIEW": "the recipient confirming receipt after the action",
    "MANIFEST_RECONCILIATION_REVIEW": "a depot reconciliation of the parcel after the action",
}
VERIFY_AFTER = timedelta(hours=20)          # operations re-check a case about a day after acting
VERIFY_MARGIN = timedelta(minutes=30)       # the last verification before the development window
ALTERNATIVE_ACTION_SHARE = .15


def action_evidence(action, after, owned, opened):
    """Label-free: does the shipment's evidence recorded after the action show what the action was for?"""
    def kinds(*names, **equal):
        return [n for n in after if n.kind in names and all(n.properties.get(k) == v for k, v in equal.items())]
    packages = {n.id: n.properties for n in owned if n.kind == "Package"}
    if action == "REQUEST_DEVICE_SYNC":
        return any(n.properties.get("occurred_at") and instant(n.properties["occurred_at"]) < opened for n in after)
    if action in ("INITIATE_CUSTODY_RECONCILIATION", "CONFLICTING_CUSTODY_REVIEW"):
        return bool(kinds("CustodyEvent", "ScanEvent"))
    if action == "PHYSICAL_CUSTODY_CHECK":
        return any(n.properties.get("facility_id") for n in kinds("ScanEvent"))
    if action == "REQUEST_HUB_CHECK":
        return any(n.properties.get("facility_id") for n in kinds("ScanEvent", "CustodyEvent"))
    if action == "PRIORITIZE_NEXT_SESSION":
        return bool(kinds("DeliveryAttempt", disposition="DELIVERED"))
    if action == "REQUEST_ADDRESS_CONFIRMATION":
        return bool(kinds("AddressVersion", "RecipientReport") or kinds("DeliveryAttempt", disposition="DELIVERED"))
    if action == "REQUEST_RESCAN":
        return any(n.properties.get("observed_barcode") and n.properties["observed_barcode"] == packages.get(n.properties.get("package_id"), {}).get("manifest_barcode")
                   for n in kinds("ScanEvent"))
    if action == "REQUEST_REWEIGH":
        for n in kinds("ScanEvent", observation_type="SCALE_WEIGH"):
            declared = packages.get(n.properties.get("package_id"), {}).get("weight_kg")
            if declared is not None and abs(n.properties["measured_weight_kg"] - declared) <= max(.5, declared * .1):
                return True
        return False
    if action == "REQUEST_ADDITIONAL_EVIDENCE":
        return bool(kinds("DeliveryProof", "AuthenticationEvidence", "RecipientReport"))
    if action == "DELIVERY_DISPUTE_REVIEW":
        return bool(kinds("RecipientReport", report_code="RECEIVED_CONFIRMATION"))
    if action == "MANIFEST_RECONCILIATION_REVIEW":
        return bool(kinds("DepotReconciliation"))
    return False


def author_history(world, as_of, draws, live_start, excluded):
    """Author precedents for history cases. excluded: {shipment id: reason} that must not become precedents.
    Returns {"authored": n, "not_imported": {shipment id: reason}}."""
    from dataset_v2.derive import assess_shipment
    nodes = world.nodes
    by_owner = {}
    for node in nodes.values():
        owner = node.properties.get("holdout_group")
        if owner:
            by_owner.setdefault(owner, []).append(node)
    authored, skipped = 0, {}
    latest_verification = live_start - VERIFY_MARGIN
    for case in sorted((n for n in nodes.values() if n.kind == "Case" and n.properties["split"] == "history"), key=lambda n: n.id):
        sid = case.properties["holdout_group"]
        if sid in excluded:
            skipped[sid] = excluded[sid]
            continue
        opened = instant(case.properties["opened_at"])
        codes = by_specificity(case.properties.get("codes") or [])
        if not codes:
            skipped[sid] = "NO_RULE_CODE"
            continue
        action = default_action(codes[0])
        if draws.chance(ALTERNATIVE_ACTION_SHARE, "history-alternative", sid):
            options = sorted({default_action(c) for c in codes[1:]} - {action, "REQUEST_ADDITIONAL_EVIDENCE"})
            if options:
                action = draws.choice(options, "history-alternative-action", sid)
        if ACTIONS.get(action, ("",))[0] == "PROHIBITED":
            skipped[sid] = "PROHIBITED_ACTION"
            continue
        start = opened + timedelta(minutes=draws.integer(20, 90, "history-start", sid))
        verified = min(start + VERIFY_AFTER, latest_verification)
        if verified < start + timedelta(minutes=45) or verified >= instant(world.config.as_of):
            skipped[sid] = "NOT_VERIFIABLE_BEFORE_CUTOFF"
            continue
        still = {e["code"] for e in assess_shipment(world, sid, iso(verified))["exceptions"]}
        after = [n for n in by_owner[sid] if n.properties.get("recorded_at") and start < instant(n.properties["recorded_at"]) <= verified]
        success = not (still & set(codes)) or action_evidence(action, after, by_owner[sid], opened)
        later = sorted((n for n in by_owner[sid] if n.kind in EVIDENCE_KINDS and n.properties.get("occurred_at")
                        and opened < instant(n.properties["recorded_at"]) <= verified), key=lambda n: (n.properties["recorded_at"], n.id))
        earlier = sorted((n for n in by_owner[sid] if n.kind in EVIDENCE_KINDS and n.properties.get("occurred_at")
                          and instant(n.properties["recorded_at"]) <= opened), key=lambda n: (n.properties["recorded_at"], n.id))
        evidence = later[:6] if (success and later) else (later[:3] + earlier[-3:]) or earlier[-3:]
        if not evidence:
            skipped[sid] = "NO_EVIDENCE"
            continue
        evidence_ids = [n.id for n in evidence]
        initial = sorted({key for x in by_owner[sid] if x.kind == "Exception" for key in x.properties.get("evidence_ids", [])})

        def n(kind, suffix, when, provenance=Provenance.SYNTHETIC_DEMO_ASSUMPTION, **props):
            key = f"{sid}-HISTORY-{suffix}"
            world.node(kind, key, shipment_id=sid, split="history", provenance=provenance, occurred_at=iso(when), recorded_at=iso(when),
                       source_ref="operations-history", **props)
            return key
        run = n("AnalysisRun", "RUN", start, model="none:history_operations_record", actor_type="HISTORY_OPERATIONS", iteration=0)
        recommendation = n("Recommendation", "REC", start, action_code=action, action_type=action, status="ACCEPTED_FIXTURE",
                           proposal_version=1, evidence_ids=initial)
        review = n("Review", "REVIEW", start + timedelta(minutes=1), verdict="accept", reviewer_kind="history_operations_record",
                   score=1., evidence_ids=initial)
        operator = n("OperatorDecision", "DECISION", start + timedelta(minutes=2), provenance=Provenance.OPERATOR_DECISION,
                     actor_id="DEMO-OPERATOR-01", role="history_operator", decision="approve", proposal_version=1, evidence_version=1)
        execution = n("ActionExecution", "EXEC", start + timedelta(minutes=3), command_id=f"{sid}-HISTORY-COMMAND",
                      receipt_ref=f"{sid}-HISTORY-RECEIPT", status="ACKNOWLEDGED_FIXTURE", adapter_kind="history_record", action_type=action)
        resolution = n("Resolution", "RES", verified, provenance=Provenance.VERIFIED_OUTCOME, action_type=action,
                       action=f"{action} (synthetic verified history)", evidence_ids=evidence_ids, verification_policy="world_history_v2",
                       policy_version=POLICY_VERSION, resolved_at=iso(verified), verifier_id="DEMO-OPERATOR-01")
        outcome = n("Outcome", "OUT", verified, provenance=Provenance.VERIFIED_OUTCOME, status="succeeded" if success else "failed",
                    success=success, action_type=action, verification_status="VERIFIED", evidence_ids=evidence_ids,
                    verification_policy="world_history_v2", policy_version=POLICY_VERSION, verified_at=iso(verified),
                    verifier_id="DEMO-OPERATOR-01", invalidated=False)
        for a, kind, b in ((case.id, "HAS_RUN", run), (run, "PROPOSES", recommendation), (recommendation, "REVIEWED_BY", review),
                           (recommendation, "HAS_DECISION", operator), (operator, "INITIATES", execution), (case.id, "RESOLVED_BY", resolution),
                           (execution, "RESOLVED_BY", resolution), (resolution, "HAS_OUTCOME", outcome), (outcome, "VERIFIED_BY", operator)):
            world.edge(a, kind, b)
        for eid in evidence_ids:
            world.edge(resolution, "SUPPORTED_BY", eid)
        if success:
            case.properties.update(state="RESOLVED", operationally_resolved=True, state_version=2, resolved_at=iso(verified),
                                   resolution_id=resolution)
        else:
            case.properties.update(state="ESCALATED", operationally_resolved=False, state_version=2)
        for step, (state, when) in enumerate((("OPEN", start), ("AWAITING_APPROVAL", start + timedelta(minutes=1)),
                                               ("ACTION_INITIATED", start + timedelta(minutes=3)),
                                               ("RESOLVED" if success else "ESCALATED", verified))):
            audit = n("AuditEvent", f"AUDIT-{step}", when, provenance=Provenance.DERIVED, event_type="HISTORY_TRANSITION", to_state=state,
                      actor_id="DEMO-OPERATOR-01", entity_ref=case.id)
            world.edge(case.id, "HAS_AUDIT", audit)
        notification = n("Notification", "NOTIFY", verified + timedelta(minutes=1), mode="dry_run", status="RECORDED_ONLY",
                         provider_calls=0, template_ref="synthetic_case_update_v1", recipient_ref=f"shipment-{sid}@demo.invalid")
        world.edge(case.id, "HAS_NOTIFICATION", notification)
        authored += 1
    return {"authored": authored, "not_imported": dict(sorted(skipped.items()))}
