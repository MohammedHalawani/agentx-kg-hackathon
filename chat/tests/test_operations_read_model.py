"""Contract, cursor, query boundary and evidence tests; no DB or provider calls."""
import copy
import unittest

from dataset_v2.contracts import Config
from dataset_v2.contracts import instant
from datetime import datetime, timedelta, timezone
from neo4j.time import DateTime
from operations.pagination import decode_cursor, encode_cursor, fingerprint
from operations.read_model import OperationsReader, ReadModelUnavailable, PRECEDENTS, OWN_NODES, SHARED_NODES, EDGES, normalize_values, SERVICE_CHOICES
from operations.reasoning import public_evidence, route_layers, triage, operational_status
from tests.test_v2_derivation import fixture, add_proof


class Result:
    def __init__(self, rows): self.rows=rows
    def __iter__(self): return iter(self.rows)


class Driver:
    def __init__(self, handler): self.handler=handler; self.calls=[]; self.sessions=[]
    def session(self, **options):
        self.sessions.append(options)
        return self
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute_read(self, callback): return callback(self)
    def run(self, query, **params):
        self.calls.append((query,params))
        return Result(self.handler(query,params))


def make_reader(handler, clock="2026-10-21T00:00:00+00:00"):
    driver=Driver(handler)
    reader=OperationsReader(driver,"shipments-v2-demo","DEMO-SUHAIL-V2-FOUNDATION",clock=lambda:clock)
    return reader,driver


class PaginationTests(unittest.TestCase):
    def test_cursor_bound_to_route_filter_dataset_limit(self):
        bound=fingerprint("queue","DEMO-A",{"city":"Riyadh"},25)
        value=encode_cursor(bound,"2026-09-01T00:00:00+00:00","DEMO-X","2026-10-01T00:00:00+00:00")
        self.assertEqual(decode_cursor(value,bound)["id"],"DEMO-X")
        for binding in (fingerprint("audit","DEMO-A",{"city":"Riyadh"},25),fingerprint("queue","DEMO-B",{"city":"Riyadh"},25),
                        fingerprint("queue","DEMO-A",{"city":"Jeddah"},25),fingerprint("queue","DEMO-A",{"city":"Riyadh"},50)):
            with self.assertRaises(ValueError): decode_cursor(value,binding)
        for bad in ("%%%", "e30", "a"*2049):
            with self.assertRaises(ValueError): decode_cursor(bad,bound)

    def test_keyset_no_duplicate_when_new_row_arrives_and_tied_times(self):
        dataset=[{"sort_time":"2026-09-01T00:00:00+00:00","sort_id":f"DEMO-{i:03}","item":{"id":i}} for i in range(55)]
        def handler(query,p):
            if "AS state,count" in query:return []
            if "count(*) AS total" in query:return [{"total":len(dataset)}]
            if "fetch_limit" not in p:return []
            rows=[r for r in dataset if p["after_time"] is None or (instant(r["sort_time"]),r["sort_id"])>(p["after_time"],p["after_id"])]
            return sorted(rows,key=lambda r:(r["sort_time"],r["sort_id"]))[:p["fetch_limit"]]
        reader,driver=make_reader(handler)
        first=reader.queue(limit=25)
        dataset.append({"sort_time":"2026-09-02T00:00:00+00:00","sort_id":"DEMO-NEW","item":{"id":99}})
        second=reader.queue(limit=25,cursor=first["next_cursor"])
        last=reader.queue(limit=25,cursor=second["next_cursor"])
        ids=[row["id"] for page in (first,second,last) for row in page["items"]]
        self.assertEqual(ids,list(range(55))+[99])
        self.assertEqual(len(ids),len(set(ids)))
        self.assertIsNone(last["next_cursor"])
        self.assertTrue(all(o=={"database":"shipments-v2-demo","default_access_mode":"READ"} for o in driver.sessions))
        self.assertTrue(all("split:'development'" in q for q,p in driver.calls))

    def test_input_filters_parameterized_and_unknown_split_rejected(self):
        reader,driver=make_reader(lambda q,p:[{"total":0}] if "AS total" in q else [])
        reader.queue(city="Riyadh' OR true",cause="ADDRESS_CONFLICT",workflow_state="OPEN")
        self.assertTrue(all("Riyadh' OR true" not in q for q,p in driver.calls))
        self.assertEqual(driver.calls[0][1]["city"],"Riyadh' OR true")
        for kwargs in ({"limit":24},{"limit":True},{"split":"held_out"},{"priority":"urgent"},{"cause":"LOST"},
                       {"from_at":"2026-10-01T00:00:00"},{"from_at":"2026-10-02T00:00:00+00:00","to_at":"2026-10-01T00:00:00+00:00"}):
            with self.assertRaises(ValueError):reader.queue(**kwargs)

    def test_cursor_snapshot_frozen_and_future_cursor_rejected(self):
        reader,_=make_reader(lambda q,p:[{"total":0}] if "AS total" in q else [],clock="2026-10-01T00:00:00+00:00")
        filters=reader._filters({},("workflow_state","operational_status","priority","city","cause","from_at","to_at","search","scope"))
        binding=fingerprint("queue",reader.dataset_id,filters,25)
        cursor=encode_cursor(binding,"2026-09-01T00:00:00+00:00","DEMO-A","2026-10-02T00:00:00+00:00")
        with self.assertRaises(ValueError):reader.queue(cursor=cursor)
        cursor=encode_cursor(binding,"2026-09-01T00:00:00+00:00","DEMO-A","2026-09-30T00:00:00+00:00")
        self.assertEqual(reader.queue(cursor=cursor)["metadata"]["as_of"],"2026-09-30T00:00:00+00:00")

    def test_real_neo4j_temporal_values_normalized_and_parameters_typed(self):
        dt=DateTime.from_native(instant("2026-09-01T00:00:00+00:00"))
        reader,driver=make_reader(lambda q,p:[{"nested":{"at":dt,"list":[dt]}}])
        rows=reader._run("RETURN $snapshot AS nested",snapshot="2026-09-01T00:00:00+00:00")
        self.assertEqual(rows,[{"nested":{"at":"2026-09-01T00:00:00+00:00","list":["2026-09-01T00:00:00+00:00"]}}])
        self.assertIsInstance(driver.calls[0][1]["snapshot"],datetime)
        with self.assertRaises(ReadModelUnavailable):normalize_values(datetime(2026,9,1))

    def test_audit_freezes_source_and_execution_clocks_across_pages(self):
        source="2026-09-11T14:01:00+00:00"
        wall=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        dataset=[{"sort_time":wall,"sort_id":f"DEMO-AUDIT-{i:03}","scenario_time":source,"item":{"id":i}} for i in range(55)]
        def handler(query,p):
            if "execution_snapshot" not in p:return []
            visible=[r for r in dataset if instant(r["sort_time"])<=p["execution_snapshot"] and instant(r["scenario_time"])<=p["snapshot"]]
            if "count(*) AS total" in query:return [{"total":len(visible)}]
            rows=[r for r in visible if p["after_time"] is None or (instant(r["sort_time"]),r["sort_id"])>(p["after_time"],p["after_id"])]
            return sorted(rows,key=lambda r:(r["sort_time"],r["sort_id"]))[:p["fetch_limit"]]
        reader,driver=make_reader(handler,clock=source)
        first=reader.audit()
        self.assertEqual(decode_cursor(first["next_cursor"],fingerprint("audit",reader.dataset_id,first["metadata"]["filters"],25))["v"],2)
        cutoff=first["metadata"]["execution_as_of"]
        dataset.append({"sort_time":(instant(cutoff)+timedelta(seconds=1)).isoformat(),"sort_id":"DEMO-LATE","scenario_time":source,"item":{"id":99}})
        dataset.append({"sort_time":wall,"sort_id":"DEMO-FUTURE-SOURCE","scenario_time":"2026-09-12T00:00:00+00:00","item":{"id":100}})
        second=reader.audit(cursor=first["next_cursor"])
        last=reader.audit(cursor=second["next_cursor"])
        self.assertEqual([r["id"] for page in (first,second,last) for r in page["items"]],list(range(55)))
        self.assertIsNone(last["next_cursor"])
        for page in (first,second,last):
            self.assertEqual(page["filtered_total"],55)
            self.assertEqual(page["metadata"]["as_of"],source)
            self.assertEqual(page["metadata"]["execution_as_of"],cutoff)
        self.assertTrue(all(isinstance(p["execution_snapshot"],datetime) and "<= $execution_snapshot" in q for q,p in driver.calls if "execution_snapshot" in p))

    def test_execution_cursor_cannot_bypass_time_or_route_boundaries(self):
        reader,_=make_reader(lambda q,p:[],clock="2026-09-11T00:00:00+00:00")
        audit_filters=reader._filters({},("shipment_id","case_id","event_type","actor","model","workflow_state","from_at","to_at","search"))
        binding=fingerprint("audit",reader.dataset_id,audit_filters,25)
        future=encode_cursor(binding,"2026-09-01T00:00:00+00:00","DEMO-A","2026-09-10T00:00:00+00:00","2999-01-01T00:00:00+00:00")
        with self.assertRaisesRegex(ValueError,"ahead of execution time"):reader.audit(cursor=future)
        future_source=encode_cursor(binding,"2026-09-01T00:00:00+00:00","DEMO-A","2026-09-12T00:00:00+00:00",datetime.now(timezone.utc).isoformat())
        with self.assertRaisesRegex(ValueError,"ahead of the logical clock"):reader.audit(cursor=future_source)
        queue_filters=reader._filters({},("workflow_state","operational_status","priority","city","cause","from_at","to_at","search","scope"))
        queue_cursor=encode_cursor(fingerprint("queue",reader.dataset_id,queue_filters,25),"2026-09-01T00:00:00+00:00","DEMO-A","2026-09-10T00:00:00+00:00",datetime.now(timezone.utc).isoformat())
        with self.assertRaisesRegex(ValueError,"only supported by Audit"):reader.queue(cursor=queue_cursor)
        valid=encode_cursor(binding,"2026-09-01T00:00:00+00:00","DEMO-A","2026-09-10T00:00:00+00:00",datetime.now(timezone.utc).isoformat())
        with self.assertRaises(ValueError):reader.audit(cursor=valid,limit=50)
        with self.assertRaises(ValueError):reader.audit(cursor=valid,event_type="STAGE_COMPLETED")

    def test_rejected_filter_and_catalog_ids_or_aliases(self):
        def handler(query,params):
            if query==SERVICE_CHOICES:return [{"services":[{"id":"DEMO-SERVICE-STANDARD","label":"STANDARD"}],"classes":[{"id":"DEMO-STYPE-BULKY","label":"BULKY"}]}]
            if "count(*) AS total" in query:return [{"total":0}]
            return []
        reader,driver=make_reader(handler)
        queue=reader.queue(workflow_state="REJECTED")
        self.assertIn("REJECTED",queue["metadata"]["filter_choices"]["workflow_state"])
        result=reader.explore(service_type="standard",shipment_class="DEMO-STYPE-BULKY")
        self.assertEqual(result["metadata"]["filter_choices"]["service_type"],["STANDARD"])
        self.assertEqual(result["metadata"]["filter_choices"]["shipment_class"],["BULKY"])
        self.assertEqual(result["metadata"]["catalog_choices"]["shipment_class"],[{"id":"DEMO-STYPE-BULKY","label":"BULKY"}])
        query,params=next((q,p) for q,p in driver.calls if "service.name" in q)
        self.assertEqual(params["service_type"],"standard")
        self.assertIn("p.service_id=$service_type OR toUpper(service.name)=toUpper($service_type)",query)
        self.assertIn("p.type_id=$shipment_class OR toUpper(class.class_name)=toUpper($shipment_class)",query)


class EvidenceTests(unittest.TestCase):
    def test_snapshot_gold_future_and_other_shipment_isolation(self):
        world=fixture(); sid="DEMO-SHP-18"
        world.edge(sid,"GOVERNED_BY","DEMO-POL")
        scan=world.nodes["DEMO-SCAN-18"]
        scan.properties.update(observed_barcode="WRONG",thinking="private raw rationale",gold="secret label")
        world.nodes["DEMO-SCAN-19"].properties["observed_barcode"]="UNRELATED"
        world.gold[sid]["recipe"]="DELIVERY_DISPUTE"
        world.node("GPSObservation",sid+"-FUTURE",shipment_id=sid,split="development",occurred_at="2026-09-02T00:00:00+00:00",recorded_at="2026-09-02T00:00:00+00:00",lat=30,lng=50,vehicle_id="DEMO-VAN")
        context=public_evidence(world,sid)
        text=str(context)
        for forbidden in ("private raw rationale","secret label","UNRELATED","-FUTURE","holdout_group","recipe","split"):
            self.assertNotIn(forbidden,text)
        result=triage(context,world.config)
        self.assertEqual(result["assessment"]["supported_codes"],["BARCODE_MISMATCH"])
        self.assertEqual(result["operational_status"],"NEEDS_ATTENTION")
        self.assertIsNone(result["outcome"])
        ids={row["id"] for row in context["nodes"]}
        self.assertTrue(all(set(d["evidence_ids"])<=ids for d in result["diagnoses"]))
        self.assertTrue(all(r["requires_approval"] and r["status"]=="PROPOSED" for r in result["recommendations"]))

    def test_case_refresh_exposes_new_evidence_without_overwriting_prior_investigation(self):
        reader,_=make_reader(lambda q,p:[{"shipment_id":"DEMO-SHP-18","as_of":"2026-09-01T02:00:00+00:00","workflow_state":"AWAITING_OUTCOME","state_version":4}])
        reader.shipment_detail=lambda sid,asof:{"shipment_id":sid,"as_of":asof,"evidence":{"nodes":[{"id":"LATER-PROOF"}],"edges":[]}}
        class Store:
            def case_detail(self,case_id):return {"workflow_state":"AWAITING_OUTCOME","state_version":4,"as_of":"2026-09-01T02:00:00+00:00","run":{"recorded_at":"2026-09-01T01:00:00+00:00"}}
        reader.store=Store()
        result=reader.case_detail("DEMO-OPS-CASE-X")
        self.assertEqual(result["as_of"], reader.clock())
        self.assertEqual(result["investigated_at"], "2026-09-01T01:00:00+00:00")
        self.assertEqual(result["workflow_state"], "AWAITING_OUTCOME")
        self.assertEqual(result["evidence"]["nodes"][0]["id"], "LATER-PROOF")

    def test_generic_discrepancy_and_milestone_delay_do_not_claim_sla_risk(self):
        for code in ("BARCODE_MISMATCH","WEIGHT_MISMATCH","PROOF_INSUFFICIENT","CUSTODY_GAP","JOURNEY_DELAY","MISSED_MILESTONE","TRAFFIC_DELAY"):
            self.assertEqual(operational_status([code]),"NEEDS_ATTENTION")
        self.assertEqual(operational_status(["SLA_RISK"]),"SLA_RISK")
        self.assertEqual(operational_status(["HUB_DELAY"]),"HUB_DELAY")

    def test_actual_route_delivery_endpoint_requires_bound_valid_proof(self):
        world=fixture();sid="DEMO-SHP-18"
        proof=add_proof(world,sid)
        # Production V2 recipients belong to their shipment. A shared customer
        # fixture is deliberately withheld by the context privacy boundary.
        world.nodes["DEMO-CUSTOMER"].properties.update(shipment_id=sid,holdout_group=sid,split="development")
        world.edge("DEMO-CUSTODY-18","FROM_CUSTODIAN","DEMO-ORIGIN")
        world.edge("DEMO-CUSTODY-18","TO_CUSTODIAN","DEMO-DEPOT")
        package=world.nodes[sid].properties["package_ids"][0]
        key=world.node("CustodyEvent",sid+"-DELIVERED",shipment_id=sid,split="development",package_id=package,
                       from_id="DEMO-DEPOT",to_id="DEMO-CUSTOMER",event_type="DELIVERED",source_event_id=proof,
                       proof_id=proof,source_quality="CORROBORATED",required_acknowledgments=2,received_acknowledgments=2,
                       occurred_at="2026-09-01T10:00:00+00:00",recorded_at="2026-09-01T10:00:00+00:00")
        world.edge(key,"TO_CUSTODIAN","DEMO-CUSTOMER")
        world.edge(key,"FROM_CUSTODIAN","DEMO-DEPOT")
        good=route_layers(public_evidence(world,sid),world.config)
        self.assertEqual(good["layers"]["actual_route"][0]["source"],"corroborated_delivery_proof_location")
        auth=world.nodes[world.nodes[proof].properties["authentication_id"]]
        auth.properties["result"]="FAIL"
        bad=route_layers(public_evidence(world,sid),world.config)
        self.assertEqual(bad["layers"]["actual_route"],[])

    def test_gps_vehicle_only_and_no_coordinate_guess(self):
        world=fixture();sid="DEMO-SHP-18"
        world.node("GPSObservation",sid+"-GPS",shipment_id=sid,split="development",occurred_at="2026-09-01T01:00:00+00:00",recorded_at="2026-09-01T01:00:00+00:00",lat=24,lng=46,vehicle_id="DEMO-VAN")
        context=public_evidence(world,sid)
        layers=route_layers(context,world.config)
        self.assertEqual(len(layers["layers"]["vehicle_path"]),1)
        self.assertEqual(layers["layers"]["vehicle_path"][0]["source"],"vehicle_telemetry_only")
        self.assertEqual(layers["layers"]["custody_points"],[])
        self.assertEqual(layers["layers"]["actual_route"],[])

    def test_sla_forecast_uses_visible_connected_route_and_promise(self):
        world=fixture();sid="DEMO-SHP-18"
        world.nodes["DEMO-SEG-18"].properties.update(from_id="DEMO-DEPOT",to_id="DEMO-AV-18",minimum_seconds=600,maximum_seconds=1200)
        world.nodes["DEMO-JOURNEY-18"].properties["promise_at"]="2026-09-01T02:05:00+00:00"
        world.edge("DEMO-SEG-18","FROM","DEMO-DEPOT")
        result=triage(public_evidence(world,sid),world.config)
        self.assertTrue(result["journey_forecast"]["sla_risk"])
        self.assertIn("SLA_RISK",result["operational_labels"])
        self.assertEqual(result["journey_forecast"]["certainty"],"travel_window_estimate")
        self.assertEqual(result["workflow_state"],"AWAITING_APPROVAL")
        self.assertEqual(result["diagnoses"][-1]["code"],"SLA_RISK")
        self.assertEqual(result["diagnoses"][-1]["certainty"],"travel_window_estimate")
        world.nodes["DEMO-JOURNEY-18"].properties["promise_at"]="2026-09-02T02:05:00+00:00"
        self.assertFalse(triage(public_evidence(world,sid),world.config)["journey_forecast"]["sla_risk"])
        world.nodes["DEMO-SEG-18"].properties["from_id"]="DEMO-ORIGIN"
        self.assertFalse(triage(public_evidence(world,sid),world.config)["journey_forecast"]["available"])

    def test_future_history_and_heldout_never_operational_context(self):
        world=fixture();sid="DEMO-SHP-18"
        world.node("Outcome",sid+"-FUTURE-OUT",shipment_id=sid,split="development",success=True,
                   verification_status="VERIFIED",verified_at="2026-09-02T00:00:00+00:00",recorded_at="2026-09-02T00:00:00+00:00")
        result=triage(public_evidence(world,sid),world.config)
        self.assertIsNone(result["outcome"])
        self.assertNotEqual(result["workflow_state"],"RESOLVED")
        for blocked in ("DEMO-SHP-0","DEMO-SHP-29"):
            with self.assertRaises(LookupError):public_evidence(world,blocked)

    def test_ledger_detail_preserves_actual_workflow_and_approval(self):
        reader,_=make_reader(lambda q,p:[{"shipment_id":"DEMO-SHP-18","as_of":"2026-09-01T02:00:00+00:00","workflow_state":"OPEN","state_version":1}])
        reader.shipment_detail=lambda sid,asof:{"shipment_id":sid,"as_of":asof,"rule_signals":{"is_diagnosis":False,"signals":[]}}
        class Store:
            def case_detail(self,case_id):return {"workflow_state":"AWAITING_OUTCOME","state_version":4,"recommendation":{"action":"confirm address"},"outcome":None}
        reader.store=Store()
        result=reader.case_detail("DEMO-OPS-CASE-X")
        self.assertEqual(result["workflow_state"],"AWAITING_OUTCOME")
        self.assertEqual(result["state_version"],4)
        self.assertEqual(result["recommendation"],{"action":"confirm address"})
        self.assertIsNone(result["outcome"])

    def test_real_driver_hydration_bounds_and_heldout_not_found(self):
        world=fixture();sid="DEMO-SHP-18"
        def handler(q,p):
            if q==OWN_NODES:
                if p["shipment_id"]!=sid:return []
                return [{"kind":n.kind,"props":copy.deepcopy(n.properties)} for n in world.owned(sid)]
            if q==SHARED_NODES:return [{"kind":n.kind,"props":copy.deepcopy(n.properties)} for n in world.nodes.values() if not n.properties.get("holdout_group")]
            if q==EDGES:return [{"id":e.id,"kind":e.kind,"start":e.start,"end":e.end,"props":e.properties} for e in world.edges.values() if e.start in p["ids"] and e.end in p["ids"]]
            return []
        reader,driver=make_reader(handler)
        result=reader.shipment_detail(sid)
        self.assertEqual(result["shipment_id"],sid)
        self.assertNotIn("reasoning",result)
        self.assertEqual((result["rule_signals"]["signals"],result["rule_signals"]["is_diagnosis"]),([],False))
        self.assertEqual((result["diagnosis"]["available"],result["diagnosis"]["reason"]),(False,"not_a_case"))
        with self.assertRaises(LookupError):reader.evidence("DEMO-SHP-29")
        self.assertIn("split:'development'",OWN_NODES)
        reader.driver.handler=lambda q,p:[{"kind":"Package","props":{}}]*1001
        with self.assertRaises(ReadModelUnavailable):reader.evidence(sid)

    def test_graph_history_verified_boolean_and_bound_evidence(self):
        reader,driver=make_reader(lambda q,p:[{"item":{"outcome_id":"DEMO-O","success":False}}])
        values=reader.historical_precedents("DEMO-SHP-18",["ADDRESS_CONFLICT"])
        self.assertFalse(values[0]["success"])
        query,params=driver.calls[0]
        for guard in ("split:'history'","o.invalidated=false","o.success IN [true,false]","o.provenance='VERIFIED_OUTCOME'",
                      "e.holdout_group=s.entity_id","e.entity_id IN o.evidence_ids","d.decision='approve'","s.entity_id <> $shipment_id"):
            self.assertIn(guard,query)
        self.assertEqual(params["candidate_limit"],20)
        self.assertEqual(params["precedent_limit"],5)
        reader.historical_precedents("DEMO-SHP-18",["ADDRESS_CONFLICT"],as_of="2026-09-01T02:00:00+00:00")
        self.assertEqual(driver.calls[-1][1]["snapshot"].isoformat(), "2026-09-01T02:00:00+00:00")
        with self.assertRaises(ValueError):reader.historical_precedents("DEMO-X",["GOLD_CAUSE"])

    def test_read_only_fence_and_explicit_target(self):
        reader,driver=make_reader(lambda q,p:[])
        for query in ("MATCH (n) DELETE n","CREATE (n)","CALL db.labels()","MATCH(n) SET n.foo=1"):
            with self.assertRaises(ValueError):reader._run(query)
        self.assertEqual(driver.calls,[])
        for target in ("shipments","neo4j","system", "shipments-v2-demo; DROP DATABASE foo"):
            with self.assertRaises(ValueError):OperationsReader(driver,target,"DEMO-A")


if __name__=="__main__":unittest.main()
