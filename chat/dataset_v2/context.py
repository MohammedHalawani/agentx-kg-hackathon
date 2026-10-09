"""Evidence-only shipment DTO for future reasoning/RAG adapters.

Uses a caller-supplied snapshot; never reads gold, resolution histories, split labels,
future observations or another shipment sharing a facility, organization or vehicle.
This module is not wired into the active V1 API.
"""
from dataset_v2.contracts import World, instant

OBSERVATIONS=frozenset(("ScanEvent","CustodyEvent","DeliveryAttempt","ContactAttempt",
    "GPSObservation","TrafficObservation","DeliveryProof","AuthenticationEvidence",
    "SignatureEvidence","PhotoEvidence","HandoffEvidence","RecipientReport",
    "DepotReconciliation","StatusEvent","LocationPin","Manifest"))
CONTEXT=frozenset(("Shipment","Package","Customer","Organization","InventoryRecord",
    "Address","AddressVersion","DeliveryInstruction","Route","RouteSegment",
    "RouteMilestone","JourneyPlan","ExpectedMilestone","DeliverySession","VehicleAssignment"))
CATALOG=frozenset(("City","Organization","OrganizationWarehouse","FulfillmentWarehouse",
    "Branch","Hub","SortingCenter","DeliveryDepot","ShipmentType","ServiceLevel",
    "HandlingRequirement","Vehicle","VehicleType","Driver","Policy","Provider","Device"))
PRIVATE=frozenset(("split","holdout_group","recipe_id","intended_healthy","assessment"))


def evidence_context(world: World, shipment_id: str, as_of: str | None=None) -> dict:
    shipment=world.nodes.get(shipment_id)
    if shipment is None or shipment.kind!="Shipment":
        raise ValueError("Unknown shipment")
    cutoff_text=as_of or shipment.properties["as_of"]
    cutoff=instant(cutoff_text)
    selected={}
    for node in world.owned(shipment_id):
        if node.kind not in CONTEXT|OBSERVATIONS:
            continue
        p=node.properties
        if node.kind in OBSERVATIONS and (instant(p["occurred_at"])>cutoff or instant(p["recorded_at"])>cutoff):
            continue
        if instant(p["recorded_at"])>cutoff:
            continue
        if p.get("effective_at") and instant(p["effective_at"])>cutoff:
            continue
        selected[node.id]=node
    # Expand shared reference catalogs only, never shared resources' other journeys.
    allowed_edges=[]
    for edge in world.edges.values():
        p=edge.properties
        if p.get("holdout_group") not in (None,shipment_id):continue
        if p.get("valid_from") and instant(p["valid_from"])>cutoff:continue
        if p.get("recorded_at") and instant(p["recorded_at"])>cutoff:continue
        if p.get("custody_event_id") and p["custody_event_id"] not in selected:continue
        allowed_edges.append(edge)
    changed=True
    while changed:
        changed=False
        for edge in allowed_edges:
            for source,target in ((edge.start,edge.end),(edge.end,edge.start)):
                node=world.nodes[target]
                if source in selected and target not in selected and node.kind in CATALOG and not node.properties.get("holdout_group"):
                    selected[target]=node
                    changed=True
    def public(properties):
        return {key:value for key,value in properties.items() if key not in PRIVATE}
    nodes=[]
    for key,node in sorted(selected.items()):
        props=public(node.properties)
        if node.kind=="Shipment":
            statuses=[n for n in selected.values() if n.kind=="StatusEvent"]
            latest=max(statuses,key=lambda n:n.properties["occurred_at"],default=None)
            props["status"]=latest.properties["status"] if latest else "CREATED"
        # Remove references to future or withheld entities from raw assertions.
        for field,value in list(props.items()):
            if isinstance(value,str) and value in world.nodes and value not in selected:
                del props[field]
        nodes.append({"id":key,"kind":node.kind,"properties":props})
    edges=[]
    for edge in sorted(allowed_edges,key=lambda e:e.id):
        p=edge.properties
        if edge.start not in selected or edge.end not in selected:continue
        if p.get("valid_from") and instant(p["valid_from"])>cutoff:continue
        if p.get("recorded_at") and instant(p["recorded_at"])>cutoff:continue
        if p.get("custody_event_id") and p["custody_event_id"] not in selected:continue
        props=public(p)
        if p.get("valid_to") and instant(p["valid_to"])>cutoff:
            props["valid_to"]=None
            props["interval_status"]="OPEN_AT_SNAPSHOT"
        for field,value in list(props.items()):
            if isinstance(value,str) and value in world.nodes and value not in selected:del props[field]
        edges.append({**edge.record(),"properties":props})
    return {"shipment_id":shipment_id,"as_of":cutoff_text,"synthetic":True,"nodes":nodes,"edges":edges}
