"""Real V2 operational routes; explicit local operations authority for all controls."""
import json
import logging
import threading
import time
import asyncio
import queue as event_queue
from typing import Annotated,Literal

from fastapi import APIRouter,HTTPException,Query,Request
from fastapi.responses import StreamingResponse
from pydantic import AfterValidator,BeforeValidator,BaseModel,ConfigDict,Field
from neo4j.exceptions import Neo4jError,ServiceUnavailable

import config
from core.query_runner import get_driver
from dataset_v2.contracts import Config,SCHEMA_VERSION,digest
from dataset_v2.load import DEFAULT_DATABASE,target_guard
from backend.local_authority import LocalOperationsAuthority
from operations.identifiers import public_value,storage_value

router=APIRouter()
authority=LocalOperationsAuthority()
log=logging.getLogger("suhail.operations")
_runtime=None
_runtime_lock=threading.Lock()


def _page_limit(value):
    if value not in (25,50,100):raise ValueError("limit must be 25, 50 or 100")
    return value


PageLimit=Annotated[int,AfterValidator(_page_limit)]


class OperationsRuntime:
    def __init__(self):
        from operations.read_model import OperationsReader
        from operations.store import OperationsStore
        target_guard(config.NEO4J_URI,DEFAULT_DATABASE,(config.NEO4J_DATABASE,config.SHIPMENT_DATABASE,config.CHAT_DATABASE))
        driver=get_driver()
        with driver.session(database=DEFAULT_DATABASE,default_access_mode="READ") as session:
            row=session.run("MATCH (m:_V2Import) RETURN m.state AS state,m.manifest_json AS manifest,m.manifest_hash AS manifest_hash").single()
        if not row or row["state"]!="COMPLETE":raise RuntimeError("V2 import must be COMPLETE")
        manifest=json.loads(row["manifest"])
        if manifest.get("synthetic") is not True or manifest.get("schema_version")!=SCHEMA_VERSION or digest(manifest)!=row["manifest_hash"]:
            raise RuntimeError("Invalid frozen V2 manifest")
        dataset_config=Config(**manifest["config"])
        self.reader=OperationsReader(driver,DEFAULT_DATABASE,dataset_config.dataset_id,dataset_config,
                                     lambda:self.store.status()["as_of"])
        self.store=OperationsStore(driver,DEFAULT_DATABASE,dataset_config.dataset_id,dataset_config,reader=self.reader)
        self.reader.store=self.store
        self.store.initialize()
        self._stop=threading.Event()
        self.thread=threading.Thread(target=self._loop,name="suhail-operations",daemon=True)
        self.thread.start()

    def _loop(self):
        last=time.monotonic()
        while not self._stop.wait(1):
            now=time.monotonic()
            elapsed=min(now-last,10)
            last=now
            try:
                status=self.store.status()
                if status["simulator"]["state"]=="running":self.store.tick(seconds=elapsed)
                if status["worker"]["state"]=="running":self.store.process_one()
            except Exception as error:
                # No provider text, evidence contents or credentials in runtime logs.
                log.warning("Operations background checkpoint failed (%s)",type(error).__name__)

    def close(self):self._stop.set()


def get_runtime():
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            try:_runtime=OperationsRuntime()
            except Exception as error:
                log.warning("V2 operations unavailable (%s)",type(error).__name__)
                raise HTTPException(503,"The validated V2 operations database is unavailable") from None
    return _runtime


def invoke(operation,*args,**kwargs):
    try:return public_value(operation(*storage_value(args),**storage_value(kwargs)))
    except LookupError:raise HTTPException(404,"Operational case or shipment not found") from None
    except ValueError as error:
        # Stable validation errors are safe; arbitrary driver exception text is withheld.
        if type(error).__name__=="OperationsConflict":raise HTTPException(409,public_value(str(error))) from None
        raise HTTPException(422,public_value(str(error))) from None
    except (Neo4jError,ServiceUnavailable):raise HTTPException(503,"The V2 graph is unavailable") from None
    except RuntimeError:
        raise HTTPException(503,"V2 operations could not complete this request") from None


@router.get("/operations/session")
def local_session(request: Request):return authority.session(request)


@router.get("/operations/pipeline")
def pipeline_topology():
    from operations.graph import topology
    return topology()


@router.get("/cases/{case_id}/events")
async def case_events(case_id: str,request: Request):
    store=get_runtime().store
    invoke(store.pipeline_state,case_id)
    async def stream():
        previous=None
        last_state=None
        internal_id=storage_value(case_id)
        listener=store.subscribe_pipeline(internal_id)
        try:
            state=await asyncio.to_thread(invoke,store.pipeline_state,case_id)
            while not await request.is_disconnected():
                payload=json.dumps(public_value(state),ensure_ascii=False,separators=(",",":"))
                if payload!=previous and pipeline_follows(last_state,state):
                    yield f'event: pipeline\ndata: {payload}\n\n'
                    previous=payload
                    last_state=state
                try:state=await asyncio.to_thread(listener.get,True,1)
                except event_queue.Empty:
                    try:state=await asyncio.to_thread(invoke,store.pipeline_state,case_id)
                    except HTTPException:
                        yield 'event: unavailable\ndata: {"error":"pipeline_unavailable"}\n\n'
                        return
        finally:store.unsubscribe_pipeline(internal_id,listener)
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


def pipeline_follows(previous,current):
    """A reconnect snapshot must not be followed by older queued stage events."""
    if previous is None:return True
    if current['state_version']<previous['state_version']:return False
    if current.get('run_id')==previous.get('run_id'):
        if len(current['events'])<len(previous['events']):return False
        if (len(current['events'])==len(previous['events']) and previous['status'] in {'REVIEWED','ABORTED','FAILED'}
            and current['status']=='RUNNING'):return False
    return True


@router.get("/cases/queue")
def queue(cursor: str|None=Query(None,max_length=2048),limit: PageLimit=25,
          workflow_state: str|None=None,operational_status: str|None=None,priority: str|None=None,
          city: str|None=None,cause: str|None=None,search: str|None=None,
          from_at: str|None=Query(None,alias="from"),to_at: str|None=Query(None,alias="to")):
    return invoke(get_runtime().reader.queue,cursor=cursor,limit=limit,workflow_state=workflow_state,
                  operational_status=operational_status,priority=priority,city=city,cause=cause,search=search,
                  from_at=from_at,to_at=to_at)


@router.get("/audit")
def audit(cursor: str|None=Query(None,max_length=2048),limit: PageLimit=25,
          shipment_id: str|None=None,case_id: str|None=None,event_type: str|None=None,
          actor: str|None=None,model: str|None=None,workflow_state: str|None=None,search: str|None=None,
          from_at: str|None=Query(None,alias="from"),to_at: str|None=Query(None,alias="to")):
    return invoke(get_runtime().reader.audit,cursor=cursor,limit=limit,shipment_id=shipment_id,case_id=case_id,
                  event_type=event_type,actor=actor,model=model,workflow_state=workflow_state,search=search,
                  from_at=from_at,to_at=to_at)


@router.get("/explore")
def explore(cursor: str|None=Query(None,max_length=2048),limit: PageLimit=25,
            filter: Literal["needs_attention","critical","sla_risk","stalled","unreconciled","delivery_dispute","delivered","all"]="needs_attention",
            city: str|None=None,cause: str|None=None,service_type: str|None=None,shipment_class: str|None=None):
    return invoke(get_runtime().reader.explore,cursor=cursor,limit=limit,filter=filter,
                  city=city,cause=cause,service_type=service_type,shipment_class=shipment_class)


@router.get("/cases/{case_id}")
def case_detail(case_id: str):return invoke(get_runtime().reader.case_detail,case_id)


@router.get("/shipments/{shipment_id}/context")
@router.get("/shipments/{shipment_id}",include_in_schema=False)
def shipment_detail(shipment_id: str):return invoke(get_runtime().reader.shipment_detail,shipment_id)


@router.get("/decisions")
def decisions():return invoke(get_runtime().reader.decisions)


@router.get("/schema")
def schema_view():
    """Live label topology from the isolated V2 graph, without shipment properties."""
    from core.query_runner import SCHEMA_CYPHER
    runtime=get_runtime()
    with runtime.store.driver.session(database=DEFAULT_DATABASE,default_access_mode="READ") as session:
        row=session.run(SCHEMA_CYPHER).single()
    if not row:return {"nodes":[],"relationships":[],"synthetic":True}
    nodes=[]
    ids=set()
    for node in row["nodes"]:
        name=dict(node).get("name") or next(iter(node.labels),"?")
        if name in {"V2Entity","OpsEntity","_V2Import"}:continue
        ids.add(node.element_id)
        nodes.append({"id":node.element_id,"labels":[name],"caption":name,"properties":{}})
    relationships=[{"id":edge.element_id,"type":edge.type,"from":edge.start_node.element_id,
                    "to":edge.end_node.element_id} for edge in row["relationships"]
                   if edge.start_node.element_id in ids and edge.end_node.element_id in ids]
    return {"nodes":nodes,"relationships":relationships,"synthetic":True,"database":"isolated_v2"}


@router.get("/graph")
def evidence_graph(shipment_id: str|None=Query(None,min_length=1,max_length=160)):
    reader=get_runtime().reader
    if shipment_id:
        context=invoke(reader.evidence,shipment_id)
        return {"nodes":[{"id":node["id"],"labels":[node["kind"]],"caption":node["id"],
                          "properties":node["properties"]} for node in context["nodes"]],
                "relationships":[{"id":edge["id"],"type":edge["kind"],"from":edge["start"],"to":edge["end"]}
                                 for edge in context["edges"]],"synthetic":True}
    page=invoke(reader.explore,filter="all",limit=25)
    return {"nodes":[{"id":item["shipment_id"],"labels":["Shipment"],"caption":item["shipment_id"],
                      "properties":item} for item in page["items"]],"relationships":[],"synthetic":True}


@router.get("/worker/status")
def worker_status():
    status=invoke(get_runtime().store.status)
    return status


@router.get("/simulation/status")
def simulation_status():
    status=invoke(get_runtime().store.status)
    return status


class StrictBody(BaseModel):model_config=ConfigDict(extra="forbid",strict=True)


def _simulation_speed(value):
    if type(value) is not int:raise ValueError("Simulation speed requires an integer")
    return value


class SimulationStart(StrictBody):
    speed: Annotated[Literal[1,10,60],BeforeValidator(_simulation_speed)]=10
    replay_mode: Literal["timeline","compressed"]="timeline"
class TickBody(StrictBody):
    seconds: float=Field(default=60,gt=0,le=86400,allow_inf_nan=False)
    speed: Annotated[Literal[1,10,60],BeforeValidator(_simulation_speed)]|None=None
    replay_mode: Literal["timeline","compressed"]|None=None


@router.post("/worker/start")
def start_worker(request: Request):
    actor=authority.authorize(request)
    return invoke(get_runtime().store.control,"worker","start",actor_id=actor["actor_id"])


@router.post("/worker/pause")
def pause_worker(request: Request):
    actor=authority.authorize(request)
    return invoke(get_runtime().store.control,"worker","pause",actor_id=actor["actor_id"])


@router.post("/worker/tick")
def step_worker(request: Request):
    authority.authorize(request)
    return invoke(get_runtime().store.process_one,manual=True)


@router.post("/cases/{case_id}/investigate")
def investigate(case_id: str,request: Request, review_scenario: bool=False):
    authority.authorize(request)
    return invoke(get_runtime().store.process_one,case_id=case_id,**({'review_scenario':True} if review_scenario else {}))


@router.post("/simulation/start")
def start_simulation(request: Request,body: SimulationStart):
    actor=authority.authorize(request)
    return invoke(get_runtime().store.control,"simulator","start",speed=body.speed,replay_mode=body.replay_mode,
                  actor_id=actor["actor_id"])


@router.post("/simulation/pause")
def pause_simulation(request: Request):
    actor=authority.authorize(request)
    return invoke(get_runtime().store.control,"simulator","pause",actor_id=actor["actor_id"])


@router.post("/simulation/tick")
def tick_simulation(request: Request,body: TickBody):
    authority.authorize(request)
    settings={key:value for key,value in {"speed":body.speed,"replay_mode":body.replay_mode}.items() if value is not None}
    return invoke(get_runtime().store.tick,seconds=body.seconds,manual=True,**settings)


class DecisionBody(StrictBody):
    decision: Literal["approve","reject","request_evidence","escalate","reopen"]
    expected_version: int=Field(ge=0)
    idempotency_key: str=Field(min_length=8,max_length=128,pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/cases/{case_id}/decision")
def decide(case_id: str,request: Request,body: DecisionBody):
    actor=authority.authorize(request)
    return invoke(get_runtime().store.decide,case_id=case_id,actor_id=actor["actor_id"],**body.model_dump())


class ReanalysisBody(StrictBody):
    expected_version: int=Field(ge=0)
    idempotency_key: str=Field(min_length=8,max_length=128,pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/cases/{case_id}/reanalyze")
def reanalyze(case_id: str,request: Request,body: ReanalysisBody,review_scenario: bool=False):
    actor=authority.authorize(request)
    store=get_runtime().store
    requested=invoke(store.request_reanalysis,case_id=case_id,actor_id=actor['actor_id'],**body.model_dump())
    result=({'processed':False,'reason':'idempotent_replay'} if requested.get('idempotent') else
            invoke(store.process_one,case_id=case_id,**({'review_scenario':True} if review_scenario else {})))
    return {'requested':requested,'analysis':result}


class ObserveBody(StrictBody):
    outcome_type: str=Field(min_length=3,max_length=80)
    evidence_ids: list[str]=Field(min_length=1,max_length=100)
    success: bool
    expected_version: int=Field(ge=0)
    idempotency_key: str=Field(min_length=8,max_length=128,pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/cases/{case_id}/outcomes")
@router.post("/cases/{case_id}/outcome/observe",include_in_schema=False)
def observe_outcome(case_id: str,request: Request,body: ObserveBody):
    actor=authority.authorize(request)
    return invoke(get_runtime().store.observe_outcome,case_id=case_id,actor_id=actor["actor_id"],**body.model_dump())


class VerifyBody(StrictBody):
    expected_version: int=Field(ge=0)
    idempotency_key: str=Field(min_length=8,max_length=128,pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/cases/{case_id}/outcomes/{outcome_id}/verify")
def verify_outcome(case_id: str,outcome_id: str,request: Request,body: VerifyBody):
    actor=authority.authorize(request)
    return invoke(get_runtime().store.verify_outcome,case_id=case_id,outcome_id=outcome_id,
                  actor_id=actor["actor_id"],authority=actor["authority"],**body.model_dump())


class LegacyVerifyBody(VerifyBody):outcome_id: str=Field(min_length=1,max_length=160)


@router.post("/cases/{case_id}/outcome/verify",include_in_schema=False)
def verify_alias(case_id: str,request: Request,body: LegacyVerifyBody):
    data=body.model_dump()
    outcome_id=data.pop("outcome_id")
    return verify_outcome(case_id,outcome_id,request,VerifyBody(**data))
