"""Frontend-independent route, pagination and control authority contracts."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock,patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend import operations_api as api


class OperationsAPITests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI()
        self.app.include_router(api.router)
        self.client=TestClient(self.app,base_url="http://127.0.0.1",client=("127.0.0.1",12345))
        self.reader=Mock()
        self.store=Mock()
        page={"items":[],"filtered_total":0,"next_cursor":None,"previous_cursor":None,"metadata":{"synthetic":True}}
        for name in ("queue","audit","explore"):getattr(self.reader,name).return_value=page
        self.store.status.return_value={"worker":{"state":"PAUSED","concurrency":1},"simulator":{"state":"PAUSED","speed":1},
            "as_of":"2026-09-01T00:00:00+00:00","synthetic":True,"demo":True}
        self.runtime=SimpleNamespace(reader=self.reader,store=self.store,database="shipments-v2-demo",
                                     workers=SimpleNamespace(status=lambda:{}))
        self.patcher=patch.object(api,"get_runtime",return_value=self.runtime)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def headers(self):
        return {"X-Operations-Token":self.client.get("/operations/session").json()["token"]}

    def test_limits_are_validated_before_any_dataset_call(self):
        for route in ("/cases/queue","/audit","/explore"):
            for value in (25,50,100):self.assertEqual(self.client.get(f"{route}?limit={value}").status_code,200)
            for value in (0,24,26,51,101,"NaN"):
                self.assertEqual(self.client.get(f"{route}?limit={value}").status_code,422)
        self.assertEqual(self.reader.queue.call_count,3)

    def test_filter_aliases_and_bounded_explore_match_ui_contract(self):
        response=self.client.get("/cases/queue?from=2026-09-01T00%3A00%3A00%2B00%3A00&to=2026-09-02T00%3A00%3A00%2B00%3A00&operational_status=ADDRESS_CONFLICT")
        self.assertEqual(response.status_code,200)
        kwargs=self.reader.queue.call_args.kwargs
        self.assertEqual(kwargs["from_at"],"2026-09-01T00:00:00+00:00")
        self.assertEqual(kwargs["operational_status"],"ADDRESS_CONFLICT")
        self.client.get("/explore?filter=sla_risk&service_type=EXPRESS&shipment_class=BULKY")
        self.assertEqual(self.reader.explore.call_args.kwargs["shipment_class"],"BULKY")

    def test_status_shape_is_shared_and_read_only(self):
        for path in ("/worker/status","/simulation/status"):
            body=self.client.get(path).json()
            self.assertEqual(body["worker"]["concurrency"],1)
            self.assertIn("simulator",body)
        self.store.control.assert_not_called()

    def test_manual_steps_and_bounded_v2_graph_use_real_runtime(self):
        headers=self.headers()
        self.store.process_one.return_value={"processed":False,"outcome":None}
        self.store.tick.return_value={"events_replayed":0}
        self.assertEqual(self.client.post("/worker/tick",headers=headers).status_code,200)
        self.store.process_one.assert_called_once_with(manual=True)
        self.assertEqual(self.client.post("/simulation/tick",json={"seconds":60.0},headers=headers).status_code,200)
        self.store.tick.assert_called_once_with(seconds=60.0,manual=True)
        self.reader.evidence.return_value={"nodes":[{"id":"DEMO-SHIP","kind":"Shipment","properties":{"status":"IN_TRANSIT"}}],"edges":[]}
        graph=self.client.get("/graph?shipment_id=DEMO-SHIP").json()
        self.assertEqual(graph["nodes"][0]["properties"]["status"],"IN_TRANSIT")
        self.assertTrue(graph["synthetic"])
        self.client.get("/graph")
        self.reader.explore.assert_called_once_with(filter="all",limit=25)

    def test_controls_and_outcomes_require_server_authority(self):
        body={"decision":"approve","expected_version":1,"idempotency_key":"approval_01"}
        self.assertEqual(self.client.post("/cases/DEMO-CASE-01/decision",json=body).status_code,403)
        self.store.decide.assert_not_called()
        self.store.decide.return_value={"workflow_state":"AWAITING_OUTCOME","outcome":None}
        response=self.client.post("/cases/DEMO-CASE-01/decision",json=body,headers=self.headers())
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.store.decide.call_args.kwargs["actor_id"],"DEMO-OPERATOR-LOCAL")
        self.assertEqual(response.json()["workflow_state"],"AWAITING_OUTCOME")
        self.assertEqual(self.client.post("/cases/DEMO-CASE-01/decision",json={**body,"actor_id":"AI"},headers=self.headers()).status_code,422)
        self.assertEqual(self.client.post("/cases/DEMO-CASE-01/decision",json={**body,"expected_version":True},headers=self.headers()).status_code,422)

    def test_new_live_session_requires_server_authority(self):
        self.assertIn(self.client.post("/simulation/reset").status_code,(401,403))
        self.store.reset_session.assert_not_called()
        self.store.reset_session.return_value={"session":{"case_source":"monitor"}}
        self.assertEqual(self.client.post("/simulation/reset",headers=self.headers()).status_code,200)
        self.store.reset_session.assert_called_once_with(actor_id="DEMO-OPERATOR-LOCAL")

    def test_manual_replay_applies_selected_speed_and_mode(self):
        self.store.tick.return_value={"events_replayed":0}
        headers=self.headers()
        self.assertEqual(self.client.post("/simulation/tick",json={"seconds":60,"speed":60,"replay_mode":"compressed"},headers=headers).status_code,200)
        self.store.tick.assert_called_once_with(seconds=60.0,manual=True,speed=60,replay_mode="compressed")
        for speed in (True,1.0,"1",2):
            self.assertEqual(self.client.post("/simulation/tick",json={"speed":speed},headers=headers).status_code,422)

    def test_verified_outcome_routes_bind_case_outcome_and_version(self):
        self.store.verify_outcome.return_value={"resolved":True,"verification_status":"VERIFIED"}
        body={"expected_version":3,"idempotency_key":"verify_01"}
        headers=self.headers()
        for path,data in (("/cases/DEMO-CASE-01/outcomes/DEMO-OUT-01/verify",body),
                          ("/cases/DEMO-CASE-01/outcome/verify",{**body,"outcome_id":"DEMO-OUT-01"})):
            self.assertEqual(self.client.post(path,json=data,headers=headers).status_code,200)
            call=self.store.verify_outcome.call_args.kwargs
            self.assertEqual(call["outcome_id"],"DEMO-OUT-01")
            self.assertEqual(call["authority"],"LOCAL_DEMO_OPERATOR")

    def test_real_failure_returns_error_without_fixture_payload(self):
        self.reader.queue.side_effect=RuntimeError("unavailable")
        response=self.client.get("/cases/queue")
        self.assertEqual(response.status_code,503)
        self.assertNotIn("items",response.json())
        self.reader.case_detail.side_effect=LookupError("heldout")
        self.assertEqual(self.client.get("/cases/DEMO-CASE-HIDDEN").status_code,404)

    def test_reanalysis_authority_alias_and_idempotent_retry_do_not_repeat_run(self):
        body={'expected_version':3,'idempotency_key':'reanalyze_01'}
        # A legacy review_scenario query parameter is ignored: no scripted review path exists.
        route='/cases/SYN-CASE-01/reanalyze?review_scenario=true'
        self.assertEqual(self.client.post(route,json=body).status_code,403)
        self.store.request_reanalysis.assert_not_called()
        self.store.request_reanalysis.side_effect=[{'idempotent':False,'workflow_state':'OPEN'},{'idempotent':True,'workflow_state':'OPEN'}]
        self.store.process_one.return_value={'processed':True,'workflow_state':'HUMAN_REVIEW','outcome':None}
        headers=self.headers()
        first=self.client.post(route,json=body,headers=headers)
        second=self.client.post(route,json=body,headers=headers)
        self.assertEqual(first.status_code,200)
        self.assertFalse(second.json()['analysis']['processed'])
        self.store.process_one.assert_called_once_with(case_id='DEMO-CASE-01')
        self.store.request_reanalysis.assert_called_with(case_id='DEMO-CASE-01',actor_id='DEMO-OPERATOR-LOCAL',**body)

    def test_pipeline_topology_and_invisible_case_are_checked_before_stream(self):
        self.assertEqual(self.client.get('/operations/pipeline').json()['engine'],'langgraph')
        self.store.pipeline_state.side_effect=LookupError('not visible')
        self.assertEqual(self.client.get('/cases/SYN-HIDDEN/events').status_code,404)
        self.store.subscribe_pipeline.assert_not_called()

    def test_reconnected_pipeline_never_regresses_to_queued_older_execution(self):
        latest={'run_id':'RUN-1','state_version':7,'events':[1,2,3],'status':'REVIEWED'}
        self.assertFalse(api.pipeline_follows(latest,{**latest,'events':[1,2]}))
        self.assertFalse(api.pipeline_follows(latest,{**latest,'state_version':6}))
        self.assertFalse(api.pipeline_follows(latest,{**latest,'status':'RUNNING'}))
        self.assertTrue(api.pipeline_follows(latest,{**latest,'run_id':'RUN-2','state_version':8,'events':[1],'status':'RUNNING'}))

    def test_invalid_cursor_length_and_time_values_cannot_start_controls(self):
        self.assertEqual(self.client.get("/cases/queue?cursor="+"x"*2049).status_code,422)
        self.assertEqual(self.client.post("/simulation/start",json={"speed":11},headers=self.headers()).status_code,422)
        for invalid in (True,1.0,"1"):
            self.assertEqual(self.client.post("/simulation/start",json={"speed":invalid},headers=self.headers()).status_code,422)
        self.assertEqual(self.client.post("/simulation/tick",json={"seconds":-1},headers=self.headers()).status_code,422)
        self.store.control.assert_not_called()


if __name__=="__main__":unittest.main()
