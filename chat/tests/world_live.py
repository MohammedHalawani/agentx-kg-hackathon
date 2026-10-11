"""A mechanism world running live in memory, for the Stage 4 tests: no database, no model.

  LiveWorld      the development export of tests.world_fixture.small_world() as Suhail holds it at a clock: the import,
                 plus every provider message delivered so far, ingested with the real gateway's time rule
  MemoryGateway  the provider feed and the gateway operations the store and the execution adapter use
  physical()     the export's private physical state, as the generator writes it for the simulator (JSON round trip)
  ledger_store() the real OperationsStore over the in-memory transactional ledger of tests.test_operations_store

The simulator under test reads physical() only. Tests may read truth rows to choose a scenario; nothing under
operations does.
"""
import json
from collections import defaultdict
from datetime import timedelta
from functools import lru_cache

from dataset_v2.context import CATALOG, CONTEXT, OBSERVATIONS
from dataset_v2.contracts import Edge, Node, World, canonical, digest, instant, iso
from dataset_v2.feed import Reference, decode
from operations.ingestion import EDGE_RULES, REFERENCED_KIND, Gateway
from operations.reasoning import public_evidence
from tests.world_fixture import small_world

DATABASE = "shipments-v2-demo-test"   # A scratch database name a world dataset may be operated in.


@lru_cache(maxsize=1)
def physical():
    from world.export import _jsonable, private_physical
    return json.loads(canonical(_jsonable(private_physical(small_world().build, "development"))))


class MemoryGateway:
    def __init__(self, live, items):
        self.live = live
        self.items = {item["feed_id"]: {**item, "status": "PENDING"} for item in items}
        self.ref = Reference.from_world(live.world)
        self.splits = {n.id: n.properties["split"] for n in live.world.nodes.values() if n.kind == "Shipment"}
        self.dataset_id = live.world.config.dataset_id

    def reference(self):
        return self.ref

    def _decoded(self, item):
        return decode(item["channel"], item["message_type"], json.loads(item["payload_json"]), self.ref)

    def ingest_due(self, clock, limit=500, not_before=None):
        clock_at = instant(clock) if isinstance(clock, str) else clock
        floor = instant(not_before) if isinstance(not_before, str) else not_before
        due = sorted((i for i in self.items.values() if i["status"] == "PENDING" and instant(i["deliver_at"]) <= clock_at),
                     key=lambda i: (instant(i["deliver_at"]), i["feed_id"]))[:limit]
        ingested, counts = [], {"duplicate": 0, "conflicting_duplicate": 0, "rejected": 0}
        for item in due:
            kind, entity_id, sid, occurred_at, props = self._decoded(item)
            if entity_id in self.live.world.nodes:
                item["status"] = "DUPLICATE"
                counts["duplicate"] += 1
                continue
            if instant(occurred_at) > clock_at or (sid and sid not in self.splits):
                item["status"] = "REJECTED"
                counts["rejected"] += 1
                continue
            recorded = Gateway.recorded_time(instant(item["deliver_at"]), instant(occurred_at), clock_at, floor)
            self.live.add(kind, entity_id, sid, self.splits[sid] if sid else "shared", occurred_at, iso(recorded), props)
            item["status"] = "INGESTED"
            ingested.append((sid, kind, entity_id))
        return {"ingested": len(ingested), **counts, "messages": len(due), "items": ingested,
                "shipments": sorted({s for s, _, _ in ingested if s}), "max_lag_seconds": 0}

    def enqueue(self, items):
        for item in items:
            self.items.setdefault(item["feed_id"], {**item, "status": "PENDING"})

    def pending_records(self, source_event_ids=None, *, prefix=None):
        wanted = set(source_event_ids) if source_event_ids is not None else None
        out = []
        for item in self.items.values():
            if item["status"] != "PENDING":
                continue
            if (wanted is not None and item["source_event_id"] in wanted) or (prefix is not None and item["source_event_id"].startswith(prefix)):
                kind, entity_id, sid, occurred_at, _ = self._decoded(item)
                out.append({"feed_id": item["feed_id"], "source_event_id": item["source_event_id"], "kind": kind, "shipment_id": sid,
                            "occurred_at": occurred_at, "deliver_at": item["deliver_at"]})
        return sorted(out, key=lambda row: row["feed_id"])

    def pending_feed_ids(self, source_event_ids):
        return [row["feed_id"] for row in self.pending_records(source_event_ids)]

    def reschedule(self, feed_ids, deliver_at):
        moved = 0
        for key in feed_ids:
            item = self.items[key]
            if item["status"] == "PENDING" and instant(item["deliver_at"]) > instant(deliver_at):
                item.setdefault("original_deliver_at", item["deliver_at"])
                item["deliver_at"] = deliver_at
                moved += 1
        return moved

    def withdraw(self, feed_ids, reason):
        for key in feed_ids:
            if self.items[key]["status"] == "PENDING":
                self.items[key].update(status="WITHDRAWN", error=reason)
        return len(feed_ids)

    def pending(self, origin=None):
        return [i for i in self.items.values() if i["status"] == "PENDING" and (origin is None or i["origin"] == origin)]


class LiveWorld:
    """The development export at a clock. evidence() is the read model's evidence loading over what was ingested."""

    def __init__(self, at=None):
        base = small_world()
        self.base, self.truth = base, base.truth
        self.world = World(base.imported.config)
        self.world.nodes = dict(base.imported.nodes)
        self.world.edges = dict(base.imported.edges)
        self.owned = defaultdict(list)
        for node in self.world.nodes.values():
            if node.properties.get("holdout_group"):
                self.owned[node.properties["holdout_group"]].append(node)
        self.gateway = MemoryGateway(self, base.items)
        self.clock = base.live_start if isinstance(base.live_start, str) else iso(base.live_start)
        if at:
            self.advance_to(at)

    def add(self, kind, entity_id, sid, split, occurred_at, recorded_at, props):
        fields = {"entity_id": entity_id, "dataset_id": self.world.config.dataset_id, "synthetic": True, "split": split,
                  "holdout_group": sid, "occurred_at": occurred_at, "recorded_at": recorded_at, "feed_origin": "FEED",
                  **{k: v for k, v in props.items() if v is not None}}
        if sid:
            fields["shipment_id"] = sid
        node = Node(entity_id, kind, fields)
        self.world.nodes[entity_id] = node
        if sid:
            self.owned[sid].append(node)
        # The relationships the gateway creates on ingestion (operations.ingestion.EDGE_RULES), late references included.
        for rule_kind, prop, rel, outward in EDGE_RULES:
            if rule_kind == kind:
                targets = fields.get(prop) if prop != "shipment_id" else sid
                for target in (targets if isinstance(targets, list) else [targets]):
                    if isinstance(target, str) and target.startswith("DEMO-") and target in self.world.nodes:
                        self._link(*((entity_id, rel, target) if outward else (target, rel, entity_id)), sid, recorded_at)
            if REFERENCED_KIND.get(prop) == kind and sid:
                for other in self.owned[sid]:
                    if other.kind == rule_kind and other.properties.get(prop) == entity_id:
                        self._link(*((other.id, rel, entity_id) if outward else (entity_id, rel, other.id)), sid, recorded_at)
        return node

    def _link(self, start, rel, end, sid, recorded_at):
        edge_id = "DEMO-EDGE-" + digest([start, rel, end, "live-ingestion-1"])[:24]
        self.world.edges[edge_id] = Edge(edge_id, rel, start, end, {"edge_id": edge_id, "holdout_group": sid, "recorded_at": recorded_at})

    def advance_to(self, at):
        """Ingest everything delivered by `at` (no store involved)."""
        at = at if isinstance(at, str) else iso(at)
        while self.gateway.ingest_due(at, limit=5000, not_before=self.clock)["messages"]:
            pass
        self.clock = at
        return self

    # ------------------------------------------------------------------ the reader the store and the simulator use
    def evidence(self, sid, as_of):
        owned = [n for n in self.owned[sid] if n.kind in CONTEXT | OBSERVATIONS]
        visible = [n for n in owned if instant(n.properties["recorded_at"]) <= instant(as_of)]
        references = {c for n in visible for v in n.properties.values() for c in (v if isinstance(v, list) else [v])
                      if isinstance(c, str) and c.startswith("DEMO-")}
        world = World(self.world.config)
        for node in owned:
            world.nodes[node.id] = node
        for ref in references:
            node = self.world.nodes.get(ref)
            if node is not None and node.properties.get("split") == "shared" and node.kind in CATALOG \
                    and instant(node.properties["recorded_at"]) <= instant(as_of):
                world.nodes[ref] = node
        for edge in self.world.edges.values():
            if edge.start in world.nodes and edge.end in world.nodes and edge.properties.get("holdout_group") in (None, sid):
                world.edges[edge.id] = edge
        return public_evidence(world, sid, as_of)

    def precedents(self, sid, codes, as_of=None):
        return []

    historical_precedents = precedents

    def records(self, sid, kind=None, tag=None):
        return sorted((n for n in self.owned[sid] if (kind is None or n.kind == kind) and (tag is None or f"-SIM-{tag}" in n.id)),
                      key=lambda n: (n.properties.get("occurred_at") or "", n.id))


def ledger_store(live, adapter=None):
    """(store, driver): the real store on the in-memory ledger, its clock at the live world's clock, the feed in memory."""
    from operations.store import CONTROL_ID, OperationsStore
    from tests.test_operations_store import Driver
    driver = Driver(live.world)
    store = OperationsStore(driver, DATABASE, live.world.config.dataset_id, live.world.config, live)
    store.gateway = live.gateway
    store.initialize()
    control = driver.ledger[CONTROL_ID][1]
    start = instant(live.clock)
    control.update(as_of=start, initial_as_of=start, cursor_time=start, session_id="DEMO-OPS-SESSION-STAGE4", session_started_at=start,
                   end_at=instant(live.world.config.as_of), speed=1)
    store.adapter = adapter
    return store, driver


def advance(store, live, hours):
    """Advance the store's clock (ingestion through the gateway, then monitoring and verification by the caller)."""
    remaining = timedelta(hours=hours)
    while remaining > timedelta(0):
        step = min(remaining, timedelta(hours=6))
        store.tick(seconds=step.total_seconds(), manual=True)
        remaining -= step
    live.clock = store.status()["as_of"]
    return live.clock


def seed_case(store, driver, sid, action, codes, *, auto=True, target=None, symptoms=None):
    """A monitored case with an agent-investigated, reviewer-accepted recommendation, as process_one records it, without a
    model: the case is opened by the real monitor from visible evidence (or with `symptoms` when given), and the
    authorization goes through the store's own policy checks. Returns the case id."""
    from operations.authority import ACTIONS
    from operations.store import identity
    from dataset_v2.contracts import canonical as dump

    def write(tx):
        control = store._control(tx, lock=True)
        when = control["as_of"]
        if symptoms is None:
            raise AssertionError("pass the symptoms the monitor found")
        case_id = store._open_monitored_case(tx, sid, sorted(symptoms), when, control.get("session_id"))
        case = store._case(tx, case_id)
        run_id = identity("run", case_id, "stage4-seed")
        recommendation_id = identity("recommendation", run_id)
        risk = "AUTO" if auto else ACTIONS[action][0]
        store._put(tx, "OpsRun", {"entity_id": run_id, "shipment_id": sid, "case_id": case_id, "recorded_at": when, "mode": "gpt_oss_agents",
                                  "result_json": dump({"mode": "gpt_oss_agents", "trace": [], "pipeline_events": []}), "iteration": 1,
                                  "status": "REVIEWED"})
        store._put(tx, "OpsReview", {"entity_id": identity("review", run_id, 1), "shipment_id": sid, "case_id": case_id, "run_id": run_id,
                                     "recorded_at": when, "verdict": "accept", "feedback": "Supported.", "summary_en": "Supported.",
                                     "model_verdict": "ACCEPT", "degraded": False, "iteration": 1, "mode": "gpt-oss"})
        proposal = {"action_code": codes[0], "action": ACTIONS[action][3], "target": target or {}}
        store._put(tx, "OpsRecommendation", {"entity_id": recommendation_id, "shipment_id": sid, "case_id": case_id, "run_id": run_id,
                                             "recorded_at": when, "action_code": codes[0], "action": ACTIONS[action][3], "evidence_ids": [sid],
                                             "status": "PROPOSED", "requires_approval": True, "action_type": action, "risk_class": risk,
                                             "target_json": dump(target or {}), "agent_mode": "gpt_oss_agents"})
        case.update(last_run_id=run_id, recommendation_id=recommendation_id, state_version=case["state_version"] + 1,
                    workflow_state="AWAITING_OUTCOME" if auto else "AWAITING_APPROVAL", cause_codes=list(codes), diagnosis_available=True)
        execution_id = None
        if auto:
            execution_id = identity("execution", "auto", recommendation_id)
            store._authorize_execution(tx, case, execution_id, recommendation_id, proposal, action, "AUTO_POLICY", when, decision_id=None,
                                       decided_risk="AUTO", recommendation_id=recommendation_id, run_id=run_id)
        store._put(tx, "OpsCase", case, update=True)
        context = {**store._approval_context(tx, case, when), "investigated_by": "agent", "risk_class": risk,
                   "authority_inputs": {"diagnosis_codes": list(codes), "review_verdict": "ACCEPT", "evidence_conflict": False,
                                        "physical_check": False, "contractor_custody": False, "degraded": False}}
        for kind, key in (("OpsRecommendation", recommendation_id), *([("OpsExecution", execution_id)] if auto else [])):
            record = store._get(tx, kind, key)
            record["approval_context_json"] = dump(context)
            store._put(tx, kind, record, update=True)
        return case_id
    return store._execute(write, write=True)


def symptoms_at(live, sid, at):
    from dataset_v2.derive import assess_shipment
    from operations.reasoning import evidence_world
    from operations.store import DETECTION_ALLOWANCE_SECONDS, monitor_finding
    context = live.evidence(sid, at)
    world = evidence_world(context, live.world.config)
    return monitor_finding(assess_shipment(world, sid, context["as_of"], detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS))["symptoms"]
