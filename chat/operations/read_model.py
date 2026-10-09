"""Bounded Neo4j V2 read views. All Cypher is fixed, parameterized and READ-only.

The caller supplies the verified shadow driver/database and logical simulation clock.
Operational rows use mutable OpsCase/OpsAudit; source V2Entity records stay immutable.
"""
import re
from datetime import datetime, date, timezone

from dataset_v2.contracts import Config, Edge, KINDS, Node, World, instant
from dataset_v2.context import CATALOG, CONTEXT, OBSERVATIONS
from operations.pagination import LIMITS, fingerprint, encode_cursor, decode_cursor
from operations.reasoning import public_evidence, route_layers, triage

CASE_STATES = frozenset(("OPEN", "INVESTIGATING", "NEEDS_EVIDENCE", "RECOMMENDATION_READY", "AWAITING_APPROVAL",
                        "ACTION_INITIATED", "HUMAN_REVIEW", "AWAITING_OUTCOME", "ESCALATED", "REOPENED", "REJECTED", "RESOLVED"))
EXPLORE_FILTERS = frozenset(("all", "needs_attention", "critical", "sla_risk", "stalled", "unreconciled", "delivery_dispute", "delivered"))
OPERATIONAL_STATUSES=frozenset(("ON_TIME","NEEDS_ATTENTION","SLA_RISK","CRITICAL","UNRECONCILED_CUSTODY",
                              "DELIVERY_DISPUTE","ADDRESS_CONFLICT","RECIPIENT_UNAVAILABLE","HUB_DELAY","RESOLVED"))
CAUSES = frozenset(("BARCODE_MISMATCH", "WEIGHT_MISMATCH", "CUSTODY_GAP", "CONFLICTING_CUSTODY", "MISSED_MILESTONE",
                   "JOURNEY_DELAY", "TRAFFIC_DELAY", "ADDRESS_CONFLICT", "WRONG_GATE", "RECIPIENT_UNAVAILABLE",
                   "DELIVERY_DISPUTE", "PROOF_INSUFFICIENT", "UNRECONCILED_CUSTODY", "INSUFFICIENT_EVIDENCE",
                   "SLA_RISK", "HUB_DELAY", "ROUTE_DELAY", "POSSIBLE_MISDELIVERY"))

QUEUE_BASE = """
MATCH (c:OpsCase {dataset_id:$dataset_id,split:'development'})
MATCH (s:V2Entity:Shipment {entity_id:c.shipment_id,dataset_id:$dataset_id,split:'development'})
WHERE datetime(c.recorded_at) <= $snapshot AND datetime(c.opened_at) <= $snapshot
  AND ($workflow_state IS NULL OR c.workflow_state=$workflow_state)
  AND ($scope IS NULL OR $scope='all'
       OR ($scope='active' AND NOT (coalesce(c.is_terminal,false) OR c.workflow_state='RESOLVED'))
       OR ($scope='resolved' AND (coalesce(c.is_terminal,false) OR c.workflow_state='RESOLVED')))
  AND ($operational_status IS NULL OR c.operational_status=$operational_status)
  AND ($priority IS NULL OR c.priority=$priority)
  AND ($city IS NULL OR c.city=$city)
  AND ($cause IS NULL OR $cause IN coalesce(c.cause_codes,[]))
  AND ($from_at IS NULL OR datetime(c.opened_at) >= $from_at) AND ($to_at IS NULL OR datetime(c.opened_at) <= $to_at)
  AND ($search IS NULL OR toLower(c.entity_id + ' ' + c.shipment_id) CONTAINS $search)
WITH c,s,c.opened_at AS sort_time,c.entity_id AS sort_id
"""
AUDIT_BASE = """
MATCH (a:OpsAudit {dataset_id:$dataset_id,split:'development'})
MATCH (s:V2Entity:Shipment {entity_id:a.shipment_id,dataset_id:$dataset_id,split:'development'})
WHERE datetime(a.recorded_at) <= $snapshot AND datetime(a.occurred_at) <= $snapshot
  AND coalesce(datetime(a.wall_recorded_at),a.occurred_at) <= $execution_snapshot
  AND ($shipment_id IS NULL OR a.shipment_id=$shipment_id)
  AND ($case_id IS NULL OR a.case_id=$case_id)
  AND ($event_type IS NULL OR a.event_type=$event_type)
  AND ($actor IS NULL OR a.actor_id=$actor)
  AND ($model IS NULL OR a.model=$model)
  AND ($workflow_state IS NULL OR a.to_state=$workflow_state)
  AND ($from_at IS NULL OR datetime(a.occurred_at) >= $from_at) AND ($to_at IS NULL OR datetime(a.occurred_at) <= $to_at)
  AND ($search IS NULL OR toLower(a.entity_id + ' ' + a.shipment_id + ' ' + coalesce(a.case_id,'') + ' ' + coalesce(a.actor_id,'') + ' ' + coalesce(a.model,'')) CONTAINS $search)
WITH a,s,coalesce(datetime(a.wall_recorded_at),a.occurred_at) AS sort_time,a.entity_id AS sort_id
"""
EXPLORE_BASE = """
MATCH (s:V2Entity:Shipment {dataset_id:$dataset_id,split:'development'})
WHERE s.recorded_at <= $snapshot
 AND ($service_type IS NULL OR EXISTS { MATCH (s)-[:HAS_PLAN]->(p:V2Entity:JourneyPlan)
   MATCH (service:V2Entity:ServiceLevel {entity_id:p.service_id,dataset_id:$dataset_id,split:'shared'})
   WHERE (p.service_id=$service_type OR toUpper(service.name)=toUpper($service_type))
     AND p.recorded_at <= $snapshot AND service.recorded_at <= $snapshot })
 AND ($shipment_class IS NULL OR EXISTS { MATCH (s)-[:HAS_PLAN]->(p:V2Entity:JourneyPlan)
   MATCH (class:V2Entity:ShipmentType {entity_id:p.type_id,dataset_id:$dataset_id,split:'shared'})
   WHERE (p.type_id=$shipment_class OR toUpper(class.class_name)=toUpper($shipment_class))
     AND p.recorded_at <= $snapshot AND class.recorded_at <= $snapshot })
OPTIONAL MATCH (c:OpsCase {dataset_id:$dataset_id,split:'development',shipment_id:s.entity_id})
WHERE datetime(c.recorded_at) <= $snapshot AND datetime(c.opened_at) <= $snapshot
WITH s,c,coalesce(c.operational_status,'ON_TIME') AS operational_status,coalesce(c.cause_codes,[]) AS codes,
 CASE WHEN datetime(coalesce(c.as_of,s.as_of))>$snapshot THEN $snapshot ELSE datetime(coalesce(c.as_of,s.as_of)) END AS view_cutoff
WHERE ($city IS NULL OR s.destination_city=$city)
 AND ($cause IS NULL OR $cause IN codes)
 AND ($filter='all'
   OR ($filter='needs_attention' AND c IS NOT NULL AND c.workflow_state <> 'RESOLVED')
   OR ($filter='critical' AND operational_status IN ['CRITICAL','UNRECONCILED_CUSTODY','DELIVERY_DISPUTE'])
   OR ($filter='sla_risk' AND operational_status='SLA_RISK')
   OR ($filter='stalled' AND 'MISSED_MILESTONE' IN codes)
   OR ($filter='unreconciled' AND 'UNRECONCILED_CUSTODY' IN codes)
   OR ($filter='delivery_dispute' AND 'DELIVERY_DISPUTE' IN codes)
   OR ($filter='delivered' AND EXISTS {
     MATCH (s)-[:HAS_STATUS]->(st:V2Entity:StatusEvent)
     WHERE st.shipment_id=s.entity_id AND st.status='DELIVERED'
       AND st.occurred_at <= view_cutoff AND st.recorded_at <= view_cutoff
       AND NOT EXISTS { MATCH (s)-[:HAS_STATUS]->(later:V2Entity:StatusEvent)
         WHERE later.shipment_id=s.entity_id AND later.occurred_at > st.occurred_at
           AND later.occurred_at <= view_cutoff AND later.recorded_at <= view_cutoff }
   }))
WITH s,c,operational_status,codes,view_cutoff,s.recorded_at AS sort_time,s.entity_id AS sort_id
"""
KEYSET = """
WHERE $after_time IS NULL OR datetime(sort_time) > $after_time OR (datetime(sort_time)=$after_time AND sort_id > $after_id)
"""
QUEUE_PROJECTION = """RETURN sort_time,sort_id,{case_id:c.entity_id,shipment_id:c.shipment_id,
 source_case_id:c.source_case_id,issue_summary:coalesce(c.issue_summary,'Evidence-derived shipment exception'),
 city:c.city,category:head(c.cause_codes),cause_codes:coalesce(c.cause_codes,[]),priority:c.priority,
 workflow_state:c.workflow_state,operational_status:c.operational_status,opened_at:c.opened_at,
 as_of:coalesce(c.as_of,s.as_of),state_version:c.state_version,synthetic:true} AS item"""
AUDIT_PROJECTION = """RETURN sort_time,sort_id,{id:a.entity_id,timestamp:coalesce(a.wall_recorded_at,a.occurred_at),scenario_time:a.occurred_at,shipment_id:a.shipment_id,
 case_id:a.case_id,event_type:a.event_type,actor:a.actor_id,decision:a.decision,result:a.result,
 from_state:a.from_state,to_state:a.to_state,model:a.model,stage:a.stage,stage_status:a.stage_status,sequence:a.sequence,synthetic:true} AS item"""
EXPLORE_PROJECTION = """
OPTIONAL MATCH (av:V2Entity:AddressVersion {dataset_id:$dataset_id,holdout_group:s.entity_id})
WHERE av.recorded_at <= view_cutoff AND av.valid_from <= view_cutoff
 AND (av.valid_to IS NULL OR av.valid_to > view_cutoff)
OPTIONAL MATCH (seg:V2Entity:RouteSegment {dataset_id:$dataset_id,holdout_group:s.entity_id,sequence:1})
OPTIONAL MATCH (origin:V2Entity {dataset_id:$dataset_id,entity_id:seg.from_id,split:'shared'})
OPTIONAL MATCH (st:V2Entity:StatusEvent {dataset_id:$dataset_id,holdout_group:s.entity_id})
WHERE st.occurred_at <= view_cutoff AND st.recorded_at <= view_cutoff
WITH s,c,operational_status,codes,view_cutoff,sort_time,sort_id,av,origin,st
ORDER BY st.occurred_at DESC,st.entity_id DESC
WITH s,c,operational_status,codes,view_cutoff,sort_time,sort_id,av,origin,head(collect(st)) AS latest_status
RETURN sort_time,sort_id,{shipment_id:s.entity_id,city:s.destination_city,status:coalesce(latest_status.status,'CREATED'),
 origin_city:s.origin_city,destination_city:s.destination_city,flow_type:s.flow_type,
 origin:CASE WHEN origin.lat IS NOT NULL AND origin.lng IS NOT NULL THEN {lat:origin.lat,lng:origin.lng,entity_id:origin.entity_id,source:'synthetic_facility'} ELSE null END,
 destination:CASE WHEN av.lat IS NOT NULL AND av.lng IS NOT NULL THEN {lat:av.lat,lng:av.lng,entity_id:av.entity_id,accuracy_m:av.accuracy_m,source:'effective_address_version'} ELSE null END,
 operational_status:operational_status,cause_codes:codes,priority:coalesce(c.priority,'low'),case_id:c.entity_id,
 workflow_state:c.workflow_state,as_of:view_cutoff,synthetic:true} AS item"""

OWN_NODES = """
MATCH (s:V2Entity:Shipment {entity_id:$shipment_id,dataset_id:$dataset_id,split:'development'})
MATCH (n:V2Entity {dataset_id:$dataset_id,holdout_group:s.entity_id,split:'development'})
WHERE any(k IN labels(n) WHERE k IN $evidence_kinds)
RETURN properties(n) AS props,[k IN labels(n) WHERE k IN $kinds][0] AS kind
ORDER BY n.entity_id LIMIT $node_limit
"""
SHARED_NODES = """
MATCH (ref:V2Entity {dataset_id:$dataset_id,split:'shared'})
WHERE ref.recorded_at <= $cutoff AND any(k IN labels(ref) WHERE k IN $catalog_kinds)
 AND (ref.entity_id IN $reference_ids OR EXISTS {
   MATCH p=(root:V2Entity {dataset_id:$dataset_id,split:'shared'})-[:HAS_TYPE|IN_CITY*1..2]->(ref)
   WHERE root.entity_id IN $reference_ids
    AND all(x IN nodes(p) WHERE x.dataset_id=$dataset_id AND x.split='shared' AND x.recorded_at <= $cutoff)
    AND all(r IN relationships(p) WHERE r.dataset_id=$dataset_id AND r.holdout_group IS NULL
      AND r.recorded_at <= $cutoff AND (r.valid_from IS NULL OR r.valid_from <= $cutoff))
 })
RETURN DISTINCT properties(ref) AS props,[k IN labels(ref) WHERE k IN $kinds][0] AS kind
ORDER BY props.entity_id LIMIT $catalog_limit
"""
EDGES = """
MATCH (a:V2Entity)-[r]->(b:V2Entity)
WHERE a.entity_id IN $ids AND b.entity_id IN $ids AND r.dataset_id=$dataset_id
 AND (r.holdout_group IS NULL OR r.holdout_group=$shipment_id)
RETURN r.edge_id AS id,type(r) AS kind,a.entity_id AS start,b.entity_id AS end,properties(r) AS props
ORDER BY r.edge_id LIMIT $edge_limit
"""
PRECEDENTS = """
MATCH (s:V2Entity:Shipment {dataset_id:$dataset_id,split:'history'})<-[:ABOUT]-(c:V2Entity:Case)
MATCH (c)-[:HAS_EXCEPTION]->(x:V2Entity:Exception)
MATCH (c)-[:RESOLVED_BY]->(r:V2Entity:Resolution)-[:HAS_OUTCOME]->(o:V2Entity:Outcome)
MATCH (o)-[:VERIFIED_BY]->(d:V2Entity:OperatorDecision)
MATCH (d)-[:INITIATES]->(execution:V2Entity:ActionExecution)-[:RESOLVED_BY]->(r)
WHERE x.code IN $codes AND s.entity_id <> $shipment_id
 AND all(n IN [c,x,r,o,d,execution] WHERE n.dataset_id=$dataset_id AND n.split='history' AND n.holdout_group=s.entity_id)
 AND o.verification_status='VERIFIED' AND o.invalidated=false AND o.success IN [true,false]
 AND o.provenance='VERIFIED_OUTCOME' AND d.decision='approve'
 AND execution.receipt_ref IS NOT NULL AND execution.action_type=r.action_type
 AND o.verified_at <= $snapshot AND o.recorded_at <= $snapshot AND r.recorded_at <= $snapshot
 AND all(n IN [c,x,d,execution] WHERE n.recorded_at <= o.verified_at)
 AND ((o.success=true AND o.status='succeeded') OR (o.success=false AND o.status='failed'))
WITH s,c,r,o,collect(DISTINCT x.code) AS matched_codes
ORDER BY o.verified_at DESC,o.entity_id ASC LIMIT $candidate_limit
MATCH (r)-[:SUPPORTED_BY]->(e:V2Entity)
WHERE e.dataset_id=$dataset_id AND e.split='history' AND e.holdout_group=s.entity_id
 AND e.entity_id IN o.evidence_ids AND e.recorded_at <= o.verified_at
 AND (e.occurred_at IS NULL OR e.occurred_at <= o.verified_at)
WITH s,c,r,o,matched_codes,collect(DISTINCT e.entity_id) AS evidence_ids,
 collect(DISTINCT {id:e.entity_id,kind:head([label IN labels(e) WHERE label IN $evidence_kinds]),
   occurred_at:e.occurred_at,source_ref:e.source_ref,event_type:e.event_type,disposition:e.disposition,
   calibrated:e.calibrated,readable:e.readable,measured_weight_kg:e.measured_weight_kg,
   result:e.result,report_code:e.report_code}) AS evidence
WHERE size(evidence_ids)>0
RETURN {shipment_id:s.entity_id,case_id:c.entity_id,exception_code:head(matched_codes),exception_codes:matched_codes,resolution_id:r.entity_id,
 outcome_id:o.entity_id,action_type:r.action_type,action:r.action,success:o.success,verified_at:o.verified_at,
 evidence_ids:evidence_ids[..20],evidence:evidence[..20],verification_policy:o.verification_policy,synthetic:true} AS item
ORDER BY item.verified_at DESC,item.outcome_id ASC LIMIT $precedent_limit
"""

FILTER_CHOICES = """
MATCH (s:V2Entity:Shipment {dataset_id:$dataset_id,split:'development'}) WHERE s.recorded_at <= $snapshot
RETURN collect(DISTINCT s.destination_city) AS cities
"""

SERVICE_CHOICES = """
MATCH (service:V2Entity:ServiceLevel {dataset_id:$dataset_id,split:'shared'}) WHERE service.recorded_at <= $snapshot
WITH collect(DISTINCT {id:service.entity_id,label:service.name}) AS services
MATCH (class:V2Entity:ShipmentType {dataset_id:$dataset_id,split:'shared'}) WHERE class.recorded_at <= $snapshot
RETURN services,collect(DISTINCT {id:class.entity_id,label:class.class_name}) AS classes
"""

HISTORY_COUNTS = """
MATCH (s:V2Entity:Shipment {dataset_id:$dataset_id,split:'history'})<-[:ABOUT]-(c:V2Entity:Case)
MATCH (c)-[:RESOLVED_BY]->(r:V2Entity:Resolution)-[:HAS_OUTCOME]->(o:V2Entity:Outcome)
MATCH (o)-[:VERIFIED_BY]->(d:V2Entity:OperatorDecision)-[:INITIATES]->(e:V2Entity:ActionExecution)-[:RESOLVED_BY]->(r)
WHERE all(n IN [c,r,o,d,e] WHERE n.dataset_id=$dataset_id AND n.split='history' AND n.holdout_group=s.entity_id)
 AND o.verification_status='VERIFIED' AND o.invalidated=false AND o.success IN [true,false]
 AND o.provenance='VERIFIED_OUTCOME' AND d.decision='approve' AND e.receipt_ref IS NOT NULL
 AND e.action_type=r.action_type AND o.verified_at <= $snapshot AND o.recorded_at <= $snapshot
 AND ((o.success=true AND o.status='succeeded') OR (o.success=false AND o.status='failed'))
 AND EXISTS {MATCH (r)-[:SUPPORTED_BY]->(proof:V2Entity) WHERE proof.entity_id IN o.evidence_ids
   AND proof.holdout_group=s.entity_id AND proof.split='history' AND proof.recorded_at <= o.verified_at}
RETURN count(DISTINCT o) AS verified_outcome_count,count(DISTINCT CASE WHEN o.success=true THEN o END) AS succeeded,
 count(DISTINCT CASE WHEN o.success=false THEN o END) AS failed
"""


class ReadModelUnavailable(RuntimeError):
    pass


def normalize_values(value):
    """Neo4j temporal values become UTC strings before cursors or domain logic."""
    if hasattr(value,"to_native"):
        value=value.to_native()
    if isinstance(value,datetime):
        if value.tzinfo is None:
            raise ReadModelUnavailable("Naive database timestamp")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value,date):
        return value.isoformat()
    if isinstance(value,dict):
        return {key:normalize_values(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):
        return [normalize_values(item) for item in value]
    return value


class OperationsReader:
    def __init__(self, driver, database, dataset_id, config=None, clock=None, store=None):
        if not isinstance(database, str) or not re.fullmatch(r"shipments-v2-demo(?:-[a-z0-9-]+)?", database):
            raise ValueError("Operations requires an explicit isolated V2 target")
        if not isinstance(dataset_id, str) or not dataset_id.startswith("DEMO-"):
            raise ValueError("Operations requires the audited synthetic storage namespace")
        self.driver, self.database, self.dataset_id = driver, database, dataset_id
        self.config = config or Config(dataset_id=dataset_id)
        if self.config.dataset_id != dataset_id:
            raise ValueError("Config and read target dataset identities differ")
        self.clock = clock or (lambda: self.config.as_of)
        self.store = store

    def _run(self, query, **params):
        # No injectable query fragments or write-capable driver calls in this module.
        if re.search(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|LOAD|CALL)\b", query, re.I):
            raise ValueError("Read model rejected a non-read query")
        params={key:instant(value) if key in {"snapshot","cutoff","from_at","to_at","after_time","execution_snapshot"} and value is not None else value
                for key,value in params.items()}
        with self.driver.session(database=self.database, default_access_mode="READ") as session:
            return session.execute_read(lambda tx: [normalize_values(dict(row)) for row in tx.run(query, dataset_id=self.dataset_id, **params)])

    def _filters(self, filters, allowed):
        unknown = set(filters) - set(allowed)
        if unknown:
            raise ValueError("Unsupported filters: " + ",".join(sorted(unknown)))
        cleaned = {key: None for key in allowed}
        for key, value in filters.items():
            if value in (None, "", "all"):
                continue
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError("Invalid filter")
            cleaned[key] = value.strip()
        for key in ("from_at", "to_at"):
            if cleaned.get(key):
                instant(cleaned[key])
        if cleaned.get("from_at") and cleaned.get("to_at") and instant(cleaned["from_at"]) > instant(cleaned["to_at"]):
            raise ValueError("Invalid time range")
        if cleaned.get("priority") and cleaned["priority"] not in ("low", "medium", "high", "unknown"):
            raise ValueError("Invalid priority")
        if cleaned.get("workflow_state") and cleaned["workflow_state"] not in CASE_STATES:
            raise ValueError("Invalid workflow state")
        if cleaned.get("cause") and cleaned["cause"] not in CAUSES:
            raise ValueError("Invalid cause")
        if cleaned.get("search"):
            cleaned["search"] = cleaned["search"].lower()
        return cleaned

    def _page(self, route, base, projection, filters, limit, cursor, metadata=None):
        if type(limit) is not int or limit not in LIMITS:
            raise ValueError("limit must be 25, 50 or 100")
        binding = fingerprint(route, self.dataset_id, filters, limit)
        decoded = decode_cursor(cursor, binding) if cursor else None
        snapshot = decoded["snapshot"] if decoded else self.clock()
        instant(snapshot)
        if instant(snapshot) > instant(self.clock()):
            raise ValueError("Cursor is ahead of the logical clock")
        execution_snapshot=None
        if route=='audit':
            execution_snapshot=(decoded.get('sort_snapshot',decoded['snapshot']) if decoded else datetime.now(timezone.utc).isoformat())
            if instant(execution_snapshot)>datetime.now(timezone.utc):raise ValueError('Cursor is ahead of execution time')
        elif decoded and decoded['v']!=1:raise ValueError('Execution cursor is only supported by Audit')
        params = {**filters, "snapshot": snapshot, "after_time": decoded["timestamp"] if decoded else None,
                  "after_id": decoded["id"] if decoded else None, "fetch_limit": limit + 1}
        if execution_snapshot:params['execution_snapshot']=execution_snapshot
        count = self._run(base + "RETURN count(*) AS total", **params)
        rows = self._run(base + KEYSET + projection + " ORDER BY sort_time ASC,sort_id ASC LIMIT $fetch_limit", **params)
        selected = rows[:limit]
        next_cursor = encode_cursor(binding, selected[-1]["sort_time"], selected[-1]["sort_id"], snapshot,execution_snapshot) if len(rows) > limit else None
        return {"items": [row["item"] for row in selected], "filtered_total": count[0]["total"] if count else 0,
                "next_cursor": next_cursor, "previous_cursor": None,
                "metadata": {"as_of": snapshot, **({'execution_as_of':execution_snapshot} if execution_snapshot else {}), "split": "development", "synthetic": True, "limit": limit,
                             "filters": filters, **(metadata or {})}}

    def queue(self, *, cursor=None, limit=25, **filters):
        filters = self._filters(filters, ("workflow_state", "operational_status", "priority", "city", "cause", "from_at", "to_at", "search", "scope"))
        if filters["scope"] not in (None, "active", "resolved", "all"):
            raise ValueError("Invalid scope")
        result = self._page("queue", QUEUE_BASE, QUEUE_PROJECTION, filters, limit, cursor,
                            {"filter_choices": {"workflow_state": sorted(CASE_STATES), "operational_status":sorted(OPERATIONAL_STATUSES), "priority": ["low", "medium", "high", "unknown"], "cause": sorted(CAUSES)}})
        snapshot = result["metadata"]["as_of"]
        buckets = self._run(QUEUE_BASE+"RETURN c.workflow_state AS state,count(*) AS count",**filters,snapshot=snapshot)
        result["metadata"]["buckets"] = {row["state"]: row["count"] for row in buckets}
        choices=self._run(FILTER_CHOICES,snapshot=snapshot)
        result["metadata"]["filter_choices"]["city"]=sorted(choices[0].get("cities",[])) if choices else []
        return result

    def audit(self, *, cursor=None, limit=25, **filters):
        filters = self._filters(filters, ("shipment_id", "case_id", "event_type", "actor", "model", "workflow_state", "from_at", "to_at", "search"))
        result=self._page("audit", AUDIT_BASE, AUDIT_PROJECTION, filters, limit, cursor)
        choices=self._run("MATCH (a:OpsAudit {dataset_id:$dataset_id,split:'development'}) WHERE datetime(a.recorded_at) <= $snapshot AND datetime(a.occurred_at) <= $snapshot RETURN collect(DISTINCT a.event_type) AS event_type,collect(DISTINCT a.actor_id) AS actor,collect(DISTINCT a.model) AS model,collect(DISTINCT a.to_state) AS workflow_state",snapshot=result["metadata"]["as_of"])
        result["metadata"]["filter_choices"]={k:sorted(v) for k,v in choices[0].items()} if choices else {}
        return result

    def explore(self, *, cursor=None, limit=25, filter="needs_attention", **filters):
        if filter not in EXPLORE_FILTERS:
            raise ValueError("Invalid Explore filter")
        filters = self._filters(filters, ("city", "cause", "service_type", "shipment_class"))
        filters["filter"] = filter
        result=self._page("explore", EXPLORE_BASE, EXPLORE_PROJECTION, filters, limit, cursor,
                         {"filter_choices": {"filter": sorted(EXPLORE_FILTERS), "cause": sorted(CAUSES)}})
        choices=self._run(FILTER_CHOICES,snapshot=result["metadata"]["as_of"])
        result["metadata"]["filter_choices"]["city"]=sorted(choices[0].get("cities",[])) if choices else []
        catalogs=self._run(SERVICE_CHOICES,snapshot=result["metadata"]["as_of"])
        for field,key in (("service_type","services"),("shipment_class","classes")):
            options=catalogs[0].get(key,[]) if catalogs else []
            result["metadata"]["filter_choices"][field]=sorted({option["label"] or option["id"] for option in options})
            result["metadata"].setdefault("catalog_choices",{})[field]=sorted(options,key=lambda item:item["id"])
        return result

    def decisions(self):
        snapshot=self.clock()
        states=self._run("MATCH (c:OpsCase {dataset_id:$dataset_id,split:'development'}) WHERE datetime(c.recorded_at) <= $snapshot RETURN c.workflow_state AS state,count(*) AS count",snapshot=snapshot)
        counts=self._run("MATCH (o:OpsOutcome {dataset_id:$dataset_id,split:'development'}) WHERE datetime(o.recorded_at) <= $snapshot RETURN count(o) AS outcome_count,count(CASE WHEN o.verification_status='VERIFIED' AND o.invalidated=false AND o.success IN [true,false] THEN o END) AS verified_outcome_count,count(CASE WHEN o.verification_status='VERIFIED' AND o.invalidated=false AND o.success=true THEN o END) AS succeeded,count(CASE WHEN o.verification_status='VERIFIED' AND o.invalidated=false AND o.success=false THEN o END) AS failed,count(CASE WHEN o.verification_status <> 'VERIFIED' OR o.verification_status IS NULL THEN o END) AS pending_outcome_count",snapshot=snapshot)
        history=self._run(HISTORY_COUNTS,snapshot=snapshot)
        def metrics(rows):
            row=rows[0] if rows else {"verified_outcome_count":0,"succeeded":0,"failed":0}
            denominator=row.get("verified_outcome_count",0)
            return {**row,"verified_success_rate":row.get("succeeded",0)/denominator if denominator else None,
                    "denominator":"verified non-invalidated observed outcomes only"}
        return {"as_of":snapshot,"synthetic":True,"development":{"case_counts":{r["state"]:r["count"] for r in states},**metrics(counts)},
                "history":metrics(history),"limitations":["Synthetic outcomes are not measured model performance.","Healthy shipments without outcome records are excluded from outcome-rate denominators."]}

    def evidence(self, shipment_id, as_of=None):
        if not isinstance(shipment_id, str) or not shipment_id.startswith("DEMO-") or len(shipment_id) > 160:
            raise ValueError("Invalid V2 shipment identity")
        params = {"shipment_id": shipment_id, "kinds": sorted(KINDS), "evidence_kinds": sorted(CONTEXT | OBSERVATIONS), "node_limit": 1001}
        owned = self._run(OWN_NODES, **params)
        if len(owned) > 1000:
            raise ReadModelUnavailable("Shipment context exceeds safe node bound")
        if not any(row["kind"] == "Shipment" for row in owned):
            raise LookupError("Operational shipment not found")
        shipment_row = next(row for row in owned if row["kind"] == "Shipment")
        cutoff = as_of or min(shipment_row["props"]["as_of"], self.clock(), key=instant)
        if instant(cutoff) > instant(self.clock()):
            raise ValueError("Evidence snapshot is ahead of the logical clock")
        visible_rows = [r for r in owned if r["props"]["recorded_at"] <= cutoff
                        and (r["kind"] not in OBSERVATIONS or r["props"].get("occurred_at", "") <= cutoff)]
        reference_ids=set()
        for row in visible_rows:
            for value in row["props"].values():
                for candidate in value if isinstance(value,list) else [value]:
                    if isinstance(candidate,str) and candidate.startswith("DEMO-"):
                        reference_ids.add(candidate)
        shared = self._run(SHARED_NODES, shipment_id=shipment_id, reference_ids=sorted(reference_ids), cutoff=cutoff,
                           catalog_kinds=sorted(CATALOG), kinds=sorted(KINDS), catalog_limit=401)
        if len(shared) > 400:
            raise ReadModelUnavailable("Shipment catalog exceeds safe bound")
        world = World(self.config)
        for row in owned + shared:
            p = row["props"]
            world.nodes[p["entity_id"]] = Node(p["entity_id"], row["kind"], p)
        rows = self._run(EDGES, shipment_id=shipment_id, ids=list(world.nodes), edge_limit=2001)
        if len(rows) > 2000:
            raise ReadModelUnavailable("Shipment context exceeds safe edge bound")
        for row in rows:
            world.edges[row["id"]] = Edge(row["id"], row["kind"], row["start"], row["end"], row["props"])
        return public_evidence(world, shipment_id, cutoff)

    def historical_precedents(self, shipment_id, codes, limit=5, as_of=None):
        if type(limit) is not int or not 1 <= limit <= 10 or set(codes) - CAUSES:
            raise ValueError("Invalid historical retrieval request")
        if not codes:
            return []
        rows = self._run(PRECEDENTS, shipment_id=shipment_id, codes=sorted(set(codes)), snapshot=as_of or self.clock(),
                         candidate_limit=20, precedent_limit=limit, evidence_kinds=sorted(OBSERVATIONS))
        return [row["item"] for row in rows if type(row["item"].get("success")) is bool]

    def shipment_detail(self, shipment_id, as_of=None):
        evidence = self.evidence(shipment_id, as_of)
        reasoning = triage(evidence, self.config)
        reasoning["precedents"] = self.historical_precedents(shipment_id, reasoning["assessment"]["supported_codes"], as_of=evidence["as_of"])
        return {"shipment_id": shipment_id, "as_of": evidence["as_of"], "synthetic": True,
                "evidence": evidence, "reasoning": reasoning, "route_layers": route_layers(evidence, self.config)}

    def case_detail(self, case_id):
        if not isinstance(case_id, str) or len(case_id)>160:
            raise ValueError("Invalid case identity")
        rows = self._run("MATCH (c:OpsCase {entity_id:$case_id,dataset_id:$dataset_id,split:'development'}) WHERE datetime(c.recorded_at) <= $snapshot RETURN c.shipment_id AS shipment_id,c.as_of AS as_of,c.workflow_state AS workflow_state,c.state_version AS state_version,c.priority AS priority,c.operational_status AS operational_status,c.last_run_id AS last_run_id,c.recommendation_id AS recommendation_id", case_id=case_id, snapshot=self.clock())
        if not rows:
            raise LookupError("Operational case not found")
        row=rows[0]
        # Evidence follows the live replay clock so post-action observations can
        # be inspected. The recorded investigation remains separately dated.
        detail={"case_id":case_id,**row,**self.shipment_detail(row["shipment_id"],self.clock())}
        if self.store is not None and hasattr(self.store,"case_detail"):
            ledger=self.store.case_detail(case_id)
            # Stored workflow/approvals/outcomes are authoritative. Fresh triage is
            # a proposal and cannot silently replace an existing human decision.
            for key in ("workflow_state","state_version","priority","operational_status","recommendation_id",
                        "last_run_id","recommendation","review","outcome","decisions","executions","run"):
                if key in ledger:
                    detail[key]=ledger[key]
            detail["investigated_at"]=(ledger.get("run") or {}).get("recorded_at")
        from operations.graph import topology
        saved=((detail.get("run") or {}).get("result") or {})
        detail["pipeline"]={"topology":topology(),"events":saved.get("pipeline_events",[]),
                            "source":"recorded_stage_events" if saved.get("pipeline_events") else "earlier_run",
                            "status":(detail.get("run") or {}).get("status","QUEUED")}
        if self.store is not None and hasattr(self.store,'case_graph'):
            detail['ledger_graph']=self.store.case_graph(case_id,[n['id'] for n in detail['evidence']['nodes']])
        return detail
