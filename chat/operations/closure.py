"""When an exception is genuinely cleared: one check shared by the outcome verifier and a person's recorded finding.

An action receipt is never an outcome, and a verified action is not a resolved case. A case closes only when, on the
evidence visible now, no standing symptom remains, no open dispute stands that the verified evidence does not itself
settle, and no other case of the shipment is open. Nothing here reads truth or the simulator's private state: the
inputs are the case's recorded symptoms and a fresh assessment of the shipment's visible evidence.
"""
from dataset_v2.contracts import instant
from dataset_v2.derive import custody_corroborated, proof_assessment
from operations.authority import OPEN_DISPUTE_SYMPTOMS

# Symptoms describing a condition that is still true at the clock (an observation still missing, custody
# still unreconciled, a manifest still omitting a loaded package), as opposed to a past event that stays in
# the record (a misread, a late scan). A case resolves only when none of these remain.
STANDING_SYMPTOMS = frozenset(("MILESTONE_OVERDUE", "SESSION_END_UNRECONCILED", "MANIFEST_CUSTODY_CONFLICT",
                               "CUSTODY_TRANSFER_UNCONFIRMED", "DELIVERY_PROOF_INCOMPLETE", "EVIDENCE_MISSING"))
# Verified outcomes that say something true about the shipment without delivering it. They never close a case unless
# corroborated delivery evidence for every package is visible: a confirmed address is not a delivery.
NOT_A_DELIVERY = frozenset(("address_confirmed",))
FACILITIES = ("Branch", "Hub", "SortingCenter", "DeliveryDepot", "FulfillmentWarehouse", "OrganizationWarehouse")


def delivered(assessment):
    """Corroborated delivery evidence for every package of the shipment."""
    rows = assessment.get("delivery_assessment") or []
    return bool(rows) and all(row.get("assessment") == "CORROBORATED_DELIVERY" for row in rows)


def remaining_symptoms(recorded, fresh, *, is_delivered, settled=frozenset(), answered=frozenset(), other_cases=(), outcome_type=None):
    """What still stands. recorded: the case's symptoms; fresh: the symptoms of a re-assessment at the clock;
    settled: disputes the verified evidence itself settles (dropped only while no longer visible);
    answered: past-event disputes that later evidence from the same party answers (a recipient's own later
    confirmation of receipt), dropped although the earlier record stays in view;
    other_cases: the shipment's other open cases."""
    recorded, fresh = set(recorded or []), set(fresh or [])
    remaining = fresh & STANDING_SYMPTOMS
    disputes = (recorded | fresh) & OPEN_DISPUTE_SYMPTOMS
    if is_delivered:
        disputes -= {"DELIVERY_ATTEMPT_FAILED"}   # Corroborated delivery since the failed attempt.
    disputes -= (set(settled) - fresh) | set(answered)
    remaining |= disputes
    remaining |= {s for case in other_cases for s in case.get("symptom_codes") or []} & (STANDING_SYMPTOMS | OPEN_DISPUTE_SYMPTOMS)
    if outcome_type in NOT_A_DELIVERY and not is_delivered:
        remaining.add("DELIVERY_NOT_VERIFIED")
    if other_cases and not remaining:
        remaining = {"OTHER_OPEN_CASE"}
    return sorted(remaining)


# ---------------------------------------------------------------------- a person's finding
def _after(node, start, cutoff):
    recorded = node.properties.get("recorded_at")
    return bool(recorded) and start < instant(recorded) <= cutoff


def finding_evidence(world, sid, outcome_type, evidence_ids, start, cutoff):
    """The cited records that are relevant to this kind of finding AND were recorded after `start` (the case's last
    execution, or its opening when no action ran). Returns (relevant ids, disputes this evidence settles while they
    are no longer visible, past-event disputes it answers).

    A finding needs evidence of the thing found: a located parcel needs a readable facility scan of its own label or
    corroborated custody at a facility; a return needs corroborated custody at a depot; a delivery needs corroborated
    proof or the recipient's own confirmation; a data correction needs the corrected record."""
    nodes = world.nodes
    packages = {n.id: n for n in nodes.values() if n.kind == "Package"}
    cited = [nodes[k] for k in evidence_ids if k in nodes and nodes[k].properties.get("shipment_id") == sid and _after(nodes[k], start, cutoff)]

    def at_facility(n, kinds=FACILITIES):
        holder = nodes.get(n.properties.get("to_id"))
        return n.kind == "CustodyEvent" and holder is not None and holder.kind in kinds and custody_corroborated(world, n, cutoff)

    def own_label(n):
        package = packages.get(n.properties.get("package_id"))
        return (n.kind == "ScanEvent" and n.properties.get("readable") is True and bool(n.properties.get("facility_id"))
                and package is not None and n.properties.get("observed_barcode") == package.properties.get("manifest_barcode"))

    relevant, settles, answered = [], set(), set()
    if outcome_type in ("parcel_located", "returned_to_depot"):
        kinds = ("DeliveryDepot",) if outcome_type == "returned_to_depot" else FACILITIES
        custody = [n for n in cited if at_facility(n, kinds)]
        relevant = custody + ([n for n in cited if own_label(n)] if outcome_type == "parcel_located" else [])
        if packages and set(packages) <= {n.properties.get("package_id") for n in custody}:
            settles.add("SESSION_END_UNRECONCILED")
    elif outcome_type == "delivered_confirmed_by_person":
        proofs = [n for n in cited if n.kind == "DeliveryProof" and proof_assessment(world, n, cutoff)["corroborated"]]
        confirmations = [n for n in cited if n.kind == "RecipientReport" and n.properties.get("report_code") == "RECEIVED_CONFIRMATION"]
        relevant = proofs + confirmations
        if confirmations:
            # The recipient's own later confirmation settles their earlier non-receipt report and a failed attempt.
            denials = [instant(n.properties["recorded_at"]) for n in nodes.values()
                       if n.kind == "RecipientReport" and n.properties.get("report_code") == "NOT_RECEIVED"]
            if all(max(instant(c.properties["recorded_at"]) for c in confirmations) > t for t in denials):
                answered |= {"RECIPIENT_REPORTED_NOT_RECEIVED", "DELIVERY_ATTEMPT_FAILED"}
    elif outcome_type == "data_corrected":
        relevant = [n for n in cited if n.kind in ("Manifest", "DepotReconciliation") or own_label(n)
                    or (n.kind == "AddressVersion" and n.properties.get("verification_status") == "VERIFIED")
                    or (n.kind == "ScanEvent" and n.properties.get("calibrated") is True)]
        settles |= {"MANIFEST_CUSTODY_CONFLICT", "CUSTODY_REPORTS_CONFLICT"} if relevant else set()
    elif outcome_type == "parcel_not_found":
        relevant = cited   # A negative finding cites whatever the search produced; it never resolves anything.
    return sorted(n.id for n in relevant), settles, answered
