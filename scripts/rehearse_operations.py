"""Authorized local synthetic rehearsal through the real HTTP APIs; no provider sends."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
import json
from pathlib import Path
import time
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]


class Demo:
    def __init__(self,url):
        if urlsplit(url).hostname not in {"localhost","127.0.0.1","::1"}:raise ValueError("Loopback demo required")
        self.url=url.rstrip("/")
        self.token=self.request("/operations/session")[1]["token"]

    def request(self,path,body=None,*,authorized=True,expected=200):
        headers={"Content-Type":"application/json"}
        if body is not None and authorized:headers["X-Operations-Token"]=self.token
        request=Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urlopen(request,timeout=60) as response:status,data=response.status,json.load(response)
        except HTTPError as error:status,data=error.code,json.load(error)
        if status!=expected:raise AssertionError(f"{path}: {status} {data.get('detail','')}")
        return status,data

    def get(self,path):return self.request(path)[1]
    def post(self,path,body=None):return self.request(path,body or {})[1]

    def advance(self,target):
        target=datetime.fromisoformat(target)
        for _ in range(1000):
            status=self.get("/simulation/status")
            current=datetime.fromisoformat(status["as_of"])
            if current>=target:return status
            seconds=min(86400.0,(target-current).total_seconds()/status["simulator"]["speed"])
            self.post("/simulation/tick",{"seconds":seconds})
        raise AssertionError("Bounded simulator failed to reach target")

    def case(self,sid):
        page=self.get("/cases/queue?"+urlencode({"search":sid}))
        matches=[row for row in page["items"] if row["shipment_id"]==sid]
        assert len(matches)==1,(sid,matches)
        return self.get("/cases/"+matches[0]["case_id"])

    def analyze(self,sid):
        detail=self.case(sid)
        if detail["workflow_state"] in {"OPEN","REOPENED"}:self.post(f"/cases/{detail['case_id']}/investigate")
        return self.case(sid)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url",default="http://127.0.0.1:8001")
    args=parser.parse_args()
    demo=Demo(args.url)
    gold=[json.loads(line) for line in (ROOT/"artifacts/dataset-v2/main/gold.jsonl").open(encoding="utf-8")]
    def fixture(recipe):
        return min((row for row in gold if row["split"]=="development" and row["recipe_id"]==recipe),key=lambda row:row["assessment"]["as_of"])
    fixtures={name:fixture(recipe) for name,recipe in {
        "late_delivery":"later_hub_departure","address":"obsolete_address","traffic":"traffic_safe_return",
        "custody":"absent_session_receipt","dispute":"report_with_corroboration"}.items()}
    report={"synthetic":True,"status":"RUNNING","provider_calls":0,"stories":{},"checks":{}}
    destination=ROOT/"docs/agent-runs/2026-10-09_demo-rehearsal.json"
    def save():destination.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    demo.post("/worker/pause");demo.post("/simulation/pause")
    heldout=next(row["shipment_id"] for row in gold if row["split"]=="held_out")
    demo.request("/shipments/"+heldout+"/context",expected=404)
    demo.request("/worker/start",{},authorized=False,expected=403)
    demo.request("/cases/queue?limit=26",expected=422)
    report["checks"].update(heldout_withheld=True,unauthorized_control_refused=True,invalid_limit_refused=True)
    late=fixtures["late_delivery"]
    demo.advance(late["assessment"]["as_of"])
    detail=demo.analyze(late["shipment_id"])
    cid=detail["case_id"]
    report["stories"]["afl"]={"shipment_id":detail["shipment_id"],"case_id":cid,
        "trace":detail.get("run",{}).get("result",{}).get("trace",[]),"workflow_state":detail["workflow_state"]}
    assert detail["workflow_state"]!="RESOLVED"
    if detail["workflow_state"] in {"AWAITING_APPROVAL","HUMAN_REVIEW","RECOMMENDATION_READY"}:
        decision={"decision":"approve","expected_version":detail["state_version"],"idempotency_key":"rehearsal_late_approve_v1"}
        approved=demo.post(f"/cases/{cid}/decision",decision)
        replay=demo.post(f"/cases/{cid}/decision",decision)
        assert approved["workflow_state"]=="AWAITING_OUTCOME" and approved["outcome"] is None
        assert replay["idempotent"] and replay["execution_id"]==approved["execution_id"]
    save()
    # This original frozen timeline has real next-day bound proof after its opened case.
    demo.advance("2026-09-04T05:01:00+00:00")
    detail=demo.case(late["shipment_id"])
    if detail["workflow_state"]=="AWAITING_OUTCOME":
        nodes={n["id"]:n for n in detail["evidence"]["nodes"]}
        proofs=[n for n in nodes.values() if n["kind"]=="DeliveryProof"]
        assert proofs
        ids=set()
        for node in proofs:
            ids.add(node["id"])
            ids.update(node["properties"][key] for key in ("attempt_id","authentication_id","signature_id","photo_id","handoff_id") if node["properties"].get(key))
        assert ids<=nodes.keys()
        observed=demo.post(f"/cases/{cid}/outcomes",{"outcome_type":"delivery_verified","evidence_ids":sorted(ids),"success":True,
            "expected_version":detail["state_version"],"idempotency_key":"rehearsal_late_observe_v1"})
        assert observed["workflow_state"]=="AWAITING_OUTCOME" and observed["verification_status"]=="OBSERVED"
        verify={"expected_version":observed["state_version"],"idempotency_key":"rehearsal_late_verify_v1"}
        demo.request(f"/cases/{cid}/outcomes/{observed['outcome_id']}/verify",verify,authorized=False,expected=403)
        verified=demo.post(f"/cases/{cid}/outcomes/{observed['outcome_id']}/verify",verify)
        assert verified["resolved"] and verified["workflow_state"]=="RESOLVED"
        assert demo.post(f"/cases/{cid}/outcomes/{observed['outcome_id']}/verify",verify)["idempotent"]
    detail=demo.case(late["shipment_id"])
    assert detail["workflow_state"]=="RESOLVED" and detail["outcome"]["verification_status"]=="VERIFIED"
    report["stories"]["verified_delivery"]={"shipment_id":detail["shipment_id"],"case_id":cid,"workflow_state":"RESOLVED",
        "outcome_id":detail["outcome"]["outcome_id"],"verification_status":"VERIFIED","proof_after_operator_action":True}
    save()
    for name in sorted(("dispute","custody","traffic","address"),key=lambda n:fixtures[n]["assessment"]["as_of"]):
        item=fixtures[name];demo.advance(item["assessment"]["as_of"]);detail=demo.analyze(item["shipment_id"])
        assessment=detail["reasoning"]["assessment"]
        if name in {"dispute","custody"}:assert detail["workflow_state"]=="HUMAN_REVIEW"
        if name=="traffic":assert assessment["next_session_priority"] and assessment["lost"] is False
        if name=="address":assert "ADDRESS_CONFLICT" in assessment["supported_codes"]
        report["stories"][name]={"shipment_id":item["shipment_id"],"case_id":detail["case_id"],"workflow_state":detail["workflow_state"],
            "codes":assessment["supported_codes"],"next_session_priority":assessment["next_session_priority"],"lost":assessment["lost"],
            "requires_human_review":assessment["requires_human_review"],"custody":assessment["custody"],"delivery_assessment":assessment["delivery_assessment"]}
        save()
    # Genuine automatic processing, followed by a paused, stable pagination snapshot.
    before=demo.get("/worker/status")["worker"]["processed_count"]
    demo.post("/worker/start")
    for _ in range(50):
        if demo.get("/worker/status")["worker"]["processed_count"]>before:break
        time.sleep(.2)
    demo.post("/worker/pause")
    after=demo.get("/worker/status")
    assert after["worker"]["processed_count"]>before and after["worker"]["concurrency"]==1
    report["checks"]["automatic_sequential_worker"]=True
    def claim(_):return demo.post("/worker/tick")
    with ThreadPoolExecutor(max_workers=4) as pool:claims=list(pool.map(claim,range(4)))
    claimed=[r["case_id"] for r in claims if r.get("processed")]
    assert len(claimed)==len(set(claimed))
    report["checks"]["concurrent_requests_distinct_claims"]=True
    first=demo.get("/cases/queue?limit=25")
    for _ in range(15):
        if first["filtered_total"]>25:break
        clock=datetime.fromisoformat(demo.get("/simulation/status")["as_of"])
        demo.advance((clock+timedelta(days=1)).isoformat())
        first=demo.get("/cases/queue?limit=25")
    assert first["next_cursor"],"Actual data must exercise a second server page"
    seen={r["case_id"] for r in first["items"]}
    assert len(first["items"])<=25
    if first["next_cursor"]:
        next_page=demo.get("/cases/queue?"+urlencode({"limit":25,"cursor":first["next_cursor"]}))
        assert not seen.intersection(r["case_id"] for r in next_page["items"])
        demo.request("/cases/queue?"+urlencode({"limit":50,"cursor":first["next_cursor"]}),expected=422)
    report["checks"]["stable_cursor_no_duplicate"]=True
    for limit in (25,50,100):assert len(demo.get("/explore?"+urlencode({"filter":"all","limit":limit}))["items"])<=limit
    audit=demo.get("/audit?"+urlencode({"case_id":cid,"limit":100}))
    assert sum(e["event_type"]=="CASE_RESOLVED" for e in audit["items"])==1
    # No scripted review rehearsal exists; a rejection appears only if the real reviewer rejected.
    assert not any(e["event_type"]=="AFL_RETRY" for e in audit["items"])
    assert all("thinking" not in json.dumps(e) and "chain_of_thought" not in json.dumps(e) for e in audit["items"])
    report["checks"].update(single_resolution_audit=True,no_scripted_review=True,bounded_explore=True,notifications_dry_run=True)
    report["final_status"]=demo.get("/simulation/status")
    assert report["final_status"]["notifications"]["external_calls"]==0
    report["decisions"]=demo.get("/decisions")
    report["status"]="PASS";save()
    print(json.dumps({"status":"PASS","stories":list(report["stories"]),"checks":report["checks"],
                      "case_count":first["filtered_total"],"provider_calls":0}),flush=True)


if __name__=="__main__":main()
