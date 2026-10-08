"""Paired, resumable, read-only synthetic-history benchmark with frozen evidence.

--prepare uses local Neo4j READ queries and local embeddings, never generation/writeback.
--run requires reviewed frozen inputs; production stages/rules run with dry external I/O.
Gold is isolated from model inputs; result scoring occurs after each graph run.
No provider reasoning is stored.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import random
import statistics
import sys
from time import perf_counter
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_litellm import ChatLiteLLM
from neo4j import RoutingControl

import config
from core.query_runner import get_driver
from llm.pipeline import _llm, classifier, extract, graph, recommender, retrieve, reviewer, rules, writeback

VERSION = "gpt-oss-v1-frozen-1"
MODELS = ("openai/gpt-oss:20b", "openai/gpt-oss:120b")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "docs" / "evals" / "2026-10-08_gpt-oss-v1"
CATEGORIES = tuple(extract.CATEGORIES)
TIMEOUT_SECONDS = 90
MAX_RETRIES = 0

_CORPUS_QUERY = """
MATCH (s:Shipment)-[:HAS_EVENT]->(:Event)-[:CAUSED_BY]->(f:FailureReason)
MATCH (f)-[:RESOLVES_WITH]->(r:Resolution)-[:HAD_OUTCOME]->(o:Outcome)
WHERE r.source IS NULL AND o.success IN [true,false]
RETURN DISTINCT s.shipment_id AS shipment_id, f.failure_id AS failure_id,
       f.category AS category, f.city AS city, f.district AS district,
       r.resolution_id AS resolution_id, r.action AS action, o.success AS success
ORDER BY shipment_id, failure_id, resolution_id
"""
_MEMBERSHIP_QUERY = """
MATCH (s:Shipment)-[:HAS_EVENT]->(:Event)-[:CAUSED_BY]->(f:FailureReason)
RETURN DISTINCT s.shipment_id AS shipment_id, f.failure_id AS failure_id
ORDER BY shipment_id, failure_id
"""

# Symptoms are fixed before either model runs. Barcode/weight deliberately share a symptom
# because the local projection has no measured barcode/weight observations to separate them.
_SYMPTOMS = {
    "address_conflict": {
        "ar": "المندوب اتصل ولم تكتمل الزيارة؛ المكان الذي ذكره لا يطابق المكان الذي أستقبل فيه عادة. أحتاج معرفة ما الذي يجب التحقق منه قبل محاولة أخرى.",
        "en": "The courier called but the visit did not finish; the place mentioned was different from where I usually receive parcels. What needs checking before another attempt?"},
    "recipient_unavailable": {
        "ar": "لم يصلني شيء؛ ظهرت محاولة في السجل وأنا لم أتمكن من الرد وقتها. لا أعرف إن كان التواصل قد اكتمل أو ما الخطوة المناسبة الآن.",
        "en": "Nothing arrived; the record shows an attempt and I could not respond at that time. I do not know whether contact was completed or what should happen next."},
    "hub_delay": {
        "ar": "لا أرى تقدماً واضحاً منذ فترة، وموعد الوصول غير مؤكد. أريد مقارنة الأحداث المسجلة بالمهلة المناسبة قبل تقرير ما إذا كانت محاولة أخرى مفيدة.",
        "en": "I have not seen clear progress for a while and the arrival time is uncertain. Please compare recorded events with the applicable time window before deciding whether another attempt would help."},
    "failed_attempt_wrong_gate": {
        "ar": "قيل لي إن زيارة حصلت لكن لم يتم التسليم؛ لم ألتق بالمندوب ولا أعرف كيف انتهت المحاولة. أحتاج معرفة ما الدليل الناقص والخطوة التالية.",
        "en": "I was told a visit happened but nothing was handed over; I did not meet the courier and do not know how the attempt ended. What evidence is missing and what should happen next?"},
    "failed_attempt_barcode_mismatch": {
        "ar": "وصلني اتصال بأن التسليم لم يكتمل بسبب مشكلة في بيانات الشحنة، لكن لم يوضحوا أي بيانات. أحتاج قراراً مدعوماً بالأحداث، وليس تخمين نوع المشكلة.",
        "en": "I received a call saying delivery could not finish because of a problem with shipment data, but nobody specified which data. Please use the recorded evidence and identify uncertainty."},
    "failed_attempt_weight_mismatch": {
        "ar": "وصلني اتصال بأن التسليم لم يكتمل بسبب مشكلة في بيانات الشحنة، لكن لم يوضحوا أي بيانات. أحتاج قراراً مدعوماً بالأحداث، وليس تخمين نوع المشكلة.",
        "en": "I received a call saying delivery could not finish because of a problem with shipment data, but nobody specified which data. Please use the recorded evidence and identify uncertainty."},
}


def base(category):
    return (category or "").removeprefix("escalation:")


def family(category):
    cause = base(category)
    return "failed_attempt" if cause.startswith("failed_attempt_") else cause


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)


def digest(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encode(value), encoding="utf-8")
    temporary.replace(path)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_hashes():
    names = ("_llm.py", "extract.py", "classifier.py", "recommender.py", "reviewer.py", "rules.py", "graph.py", "retrieve.py", "writeback.py")
    hashes = {name: hashlib.sha256((ROOT / "chat" / "llm" / "pipeline" / name).read_bytes()).hexdigest() for name in names}
    hashes["evaluator.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return hashes


def provider_identity():
    """Nonsecret identity; endpoint changes invalidate resume, credentials never enter it."""
    return {"api_base_sha256": hashlib.sha256((config.LLM_API_BASE or "").encode()).hexdigest(),
            "temperature": 0, "timeout_seconds": TIMEOUT_SECONDS, "max_retries": MAX_RETRIES}


def select_cases(corpus, seed=42):
    """Five seeded histories per supported cause; one escalation where uniquely available."""
    rng = random.Random(seed)
    used = set()
    grouped = {}
    for cause in CATEGORIES:
        rows = [row for row in corpus if base(row["category"]) == cause]
        rng.shuffle(rows)
        escalation = [row for row in rows if row["category"].startswith("escalation:")]
        ordinary = [row for row in rows if not row["category"].startswith("escalation:")]
        # Prefer a modest escalation subset rather than exhausting every escalation first.
        # Selection remains unique across all six category groups.
        rows = escalation[:1] + ordinary
        selected = []
        for row in rows:
            if row["shipment_id"] in used:
                continue
            selected.append(row)
            used.add(row["shipment_id"])
            if len(selected) == 5:
                break
        if len(selected) != 5:
            raise ValueError(f"Insufficient unique shipments for {cause}")
        grouped[cause] = selected
    return [grouped[cause][slot] for slot in range(5) for cause in CATEGORIES]


def complaint_for(row, slot):
    language = "ar" if slot < 3 else "en"
    symptom = _SYMPTOMS[base(row["category"])][language]
    prefix = "الشحنة" if language == "ar" else "Shipment"
    city = f" ({row['city']})" if row.get("city") else ""
    return f"{prefix} {row['shipment_id']}{city}: {symptom}", language


def clean_local(local):
    """Only operational facts, never own retrospective outcome/failure labels."""
    result = {key: deepcopy(local.get(key)) for key in ("courier", "policy", "addresses", "events")}
    shipment = local.get("shipment") or {}
    result["shipment"] = {key: shipment.get(key) for key in ("shipment_id", "tracking_id", "order_id", "carrier")}
    # Status removed to avoid accidentally carrying a retrospective delivered outcome.
    # Recorded events are retained unaltered, including failure/attempt chronology.
    return result


def filter_precedent(rows, forbidden, allowed_seeded=None):
    return [deepcopy(row) for row in rows
            if row.get("failure_id") not in forbidden and type(row.get("success")) is bool
            and (allowed_seeded is None or (row.get("failure_id"), row.get("resolution_id")) in allowed_seeded)]


def clean_precedent(rows):
    keys = ("failure_id", "resolution_id", "category", "description", "city", "district",
            "courier", "action", "success", "outcome_notes", "score", "rrf_score")
    return [{key: row.get(key) for key in keys if key in row} for row in rows]


def validate_runtime(runtime, gold, membership=None):
    cases = runtime["cases"]
    if (len(cases) != 30 or len({row["shipment_id"] for row in cases}) != 30
            or {row["case_id"] for row in cases} != {f"case-{index:02d}" for index in range(1, 31)}):
        raise ValueError("Benchmark requires 30 distinct shipments")
    if Counter(row["language"] for row in cases) != {"ar": 18, "en": 12}:
        raise ValueError("Expected 18 Arabic and 12 English complaints")
    if Counter(base(gold[row["case_id"]]["category"]) for row in cases) != {cat: 5 for cat in CATEGORIES}:
        raise ValueError("Expected five cases per supported base cause")
    for cat in CATEGORIES:
        if Counter(row["language"] for row in cases if base(gold[row["case_id"]]["category"]) == cat) != {"ar": 3, "en": 2}:
            raise ValueError("Expected three Arabic/two English inputs per category")
    for row in cases:
        answer = gold[row["case_id"]]
        own = row["context"]["local_subgraph"]
        if set(own) - {"shipment", "courier", "policy", "addresses", "events"}:
            raise ValueError("Own context contains answer fields")
        if "status" in own.get("shipment", {}):
            raise ValueError("Retrospective shipment status must be withheld")
        forbidden = set(answer["holdout_failure_ids"])
        if membership is not None:
            actual = {item["failure_id"] for item in membership if item["shipment_id"] == row["shipment_id"]}
            if forbidden != actual:
                raise ValueError("Every held-out shipment failure must be excluded")
        banks = [row["context"]["similar_cases"], *row["second_pass"].values()]
        if set(row["second_pass"]) != set(CATEGORIES):
            raise ValueError("All predicted-category branches must be frozen")
        if any(item.get("failure_id") in forbidden for bank in banks for item in bank):
            raise ValueError("Holdout sibling leaked into precedent")
        if any(item["failure_id"] in forbidden for item in answer["plausibility_history"]):
            raise ValueError("Holdout sibling leaked into scoring history")
        if row["context"].get("live_failure_id") is not None:
            raise ValueError("Live gold failure ID withheld")


def prepare(output_dir):
    if (output_dir / "manifest.json").exists():
        raise ValueError("Frozen manifest already exists; use a new directory for a new protocol")
    if urlsplit(config.NEO4J_URI).hostname not in ("localhost", "127.0.0.1") or config.SHIPMENT_DATABASE != "shipments":
        raise ValueError("Preparation requires the verified local synthetic shipments graph")
    def read(query):
        records, _, _ = get_driver().execute_query(query, database_=config.SHIPMENT_DATABASE, routing_=RoutingControl.READ)
        return [dict(row) for row in records]
    corpus, membership = read(_CORPUS_QUERY), read(_MEMBERSHIP_QUERY)
    seeded_ids = {(row["failure_id"], row["resolution_id"]) for row in corpus}
    held_by_ship = {}
    for row in membership:
        held_by_ship.setdefault(row["shipment_id"], set()).add(row["failure_id"])
    selected = select_cases(corpus)
    # Seven fixed vector queries per case are expensive; cache category queries globally,
    # then filter each shipment's complete sibling set BEFORE fusion/selection.
    category_vectors = {cat: retrieve.vector_search(f"{cat} shipment delivery exception historical resolution", k=100)
                        for cat in CATEGORIES}
    cases, gold = [], {}
    for index, row in enumerate(selected):
        case_id = f"case-{index + 1:02d}"
        complaint, language = complaint_for(row, index // len(CATEGORIES))
        forbidden = held_by_ship[row["shipment_id"]]
        factual = {"shipment_id": row["shipment_id"], "tracking_id": None, "city": row.get("city"),
                   "district": None, "courier": None, "category_hint": None, "raw_text": complaint}
        vector = filter_precedent(retrieve.vector_search(complaint, k=100), forbidden, seeded_ids)
        structural = filter_precedent(retrieve.graph_traversal(factual, k=200), forbidden, seeded_ids)
        first = clean_precedent(retrieve.fuse_rrf(vector, structural)[:5])
        local = clean_local(retrieve.local_subgraph(factual))
        second = {cat: clean_precedent(retrieve.fuse_rrf(
            filter_precedent(category_vectors[cat], forbidden, seeded_ids), first)[:5]) for cat in CATEGORIES}
        cases.append({"case_id": case_id, "shipment_id": row["shipment_id"], "language": language,
                      "complaint": complaint, "factual_extraction": factual,
                      "context": {"similar_cases": first, "local_subgraph": local, "live_failure_id": None},
                      "second_pass": second})
        gold[case_id] = {"category": row["category"], "action": row["action"], "success": row["success"],
                         "holdout_failure_ids": sorted(forbidden),
                         "shipment_base_causes": sorted({base(c["category"]) for c in corpus if c["shipment_id"] == row["shipment_id"]}),
                         "plausibility_history": [{key: c[key] for key in ("failure_id", "category", "action", "success")}
                                                  for c in corpus if c["failure_id"] not in forbidden]}
        print(encode({"prepared": index + 1, "total": 30, "case_id": case_id, "precedent": len(first)}), flush=True)
    runtime = {"version": VERSION, "cases": cases}
    validate_runtime(runtime, gold, membership)
    manifest = {"version": VERSION, "prepared_at": datetime.now(timezone.utc).isoformat(),
                "runtime_hash": digest(runtime), "gold_hash": digest(gold), "corpus_hash": digest(corpus),
                "membership_hash": digest(membership), "source_hashes": source_hashes(), "provider_identity": provider_identity(),
                "symptom_templates_hash": digest(_SYMPTOMS), "models": MODELS, "temperature": 0,
                "timeout_seconds": TIMEOUT_SECONDS, "max_retries": MAX_RETRIES,
                "sampling_seed": 42, "planned_cases_per_model": 30,
                "language_counts": {"ar": 18, "en": 12},
                "escalation_seed_cases": sum(row["category"].startswith("escalation:") for row in selected),
                "methodology": "controlled frozen classifier/recommender/reviewer/AFL benchmark; 30 identical case-language inputs across models (18AR/12EN, not same-case bilingual translations); synthetic seeded labels/actions and random outcomes, not independent human SPL gold; extraction measured but not used to alter frozen retrieval; casefile/writeback disabled",
                "limitations": ["Barcode, weight and gate/contact outcome observations absent from local projection; some subtypes are underidentified.",
                                "Only base categories are supported outputs; full escalation-prefix agreement is separately penalized unsupported vocabulary.",
                                "History action plausibility and retrieval category matching are synthetic proxies, not independently adjudicated correctness.",
                                "False acceptance/rejection rates cannot be measured without independent adjudication.",
                                "Arabic complaints do not require Arabic explanations in native English production prompts; Arabic actions and Arabic prose measured separately."]}
    for name, value in (("runtime_inputs.json", runtime), ("gold.json", gold), ("corpus_snapshot.json", corpus),
                        ("membership_snapshot.json", membership), ("manifest.json", manifest)):
        save_json(output_dir / name, value)
    return manifest


def verify_bundle(output_dir):
    manifest = load_json(output_dir / "manifest.json")
    runtime = load_json(output_dir / "runtime_inputs.json")
    gold = load_json(output_dir / "gold.json")
    if manifest["version"] != VERSION or digest(runtime) != manifest["runtime_hash"] or digest(gold) != manifest["gold_hash"]:
        raise ValueError("Frozen input/gold hash mismatch")
    if source_hashes() != manifest["source_hashes"] or digest(_SYMPTOMS) != manifest["symptom_templates_hash"]:
        raise ValueError("Production source/template hash mismatch; paired runs must use unchanged prompts/rules")
    if provider_identity() != manifest["provider_identity"]:
        raise ValueError("Provider endpoint/settings fingerprint mismatch")
    for filename, key in (("corpus_snapshot.json", "corpus_hash"), ("membership_snapshot.json", "membership_hash")):
        if digest(load_json(output_dir / filename)) != manifest[key]:
            raise ValueError("Frozen corpus hash mismatch")
    validate_runtime(runtime, gold, load_json(output_dir / "membership_snapshot.json"))
    return manifest, runtime


class MeasuredModel:
    """Keep only metrics from provider responses; real ask_json remains authoritative."""
    def __init__(self, provider):
        self.provider = provider
        self.calls = []

    def invoke(self, messages):
        system = messages[0].content
        stage = next((name for name, module in (("extract", extract), ("classify", classifier),
                      ("recommend", recommender), ("review", reviewer)) if system == module._SYSTEM), "unknown")
        started = perf_counter()
        metric = {"stage": stage, "error_type": None, "malformed_json": False, "usage": {},
                  "missing_declared_fields": [], "invalid_declared_fields": []}
        try:
            response = self.provider.invoke(messages)
            parsed = _llm.parse_json(_llm.message_text(getattr(response, "content", None)))
            metric["malformed_json"] = parsed is None
            if isinstance(parsed, dict):
                default = ({"city": None, "district": None, "courier": None, "category_hint": None}
                           if stage == "extract" else getattr({"classify": classifier, "recommend": recommender,
                                                               "review": reviewer}.get(stage), "_DEFAULT", {}))
                # candidates/checks are generated by the application, not requested model fields.
                default = {key: value for key, value in default.items() if key not in ("candidates", "checked_against")}
                metric["missing_declared_fields"] = sorted(set(default) - set(parsed))
                for key, expected in default.items():
                    if key not in parsed:
                        continue
                    value = parsed[key]
                    valid = ((isinstance(value, str) or value is None) if expected is None else
                             isinstance(value, str) and bool(_llm.final_text(value)) if isinstance(expected, str) else
                             isinstance(value, list) and all(isinstance(item, str) for item in value) if isinstance(expected, list) else
                             isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value))
                    if not valid:
                        metric["invalid_declared_fields"].append(key)
                constraints = ({"category": CATEGORIES, "priority": ("low", "medium", "high")}
                               if stage == "classify" else {"verdict": ("accept", "reject")} if stage == "review"
                               else {"category_hint": (None, *CATEGORIES)} if stage == "extract" else {})
                for key, allowed in constraints.items():
                    if key in parsed and parsed[key] not in allowed and key not in metric["invalid_declared_fields"]:
                        metric["invalid_declared_fields"].append(key)
                bounded = "confidence" if stage == "classify" else "score" if stage == "review" else None
                if bounded in parsed and isinstance(parsed[bounded], (int, float)) and not 0 <= parsed[bounded] <= 1:
                    if bounded not in metric["invalid_declared_fields"]:
                        metric["invalid_declared_fields"].append(bounded)
            usage = getattr(response, "usage_metadata", None) or {}
            if not isinstance(usage, dict):
                usage = {}
            if not usage:
                metadata = getattr(response, "response_metadata", None) or {}
                usage = metadata.get("token_usage", metadata.get("usage", {})) if isinstance(metadata, dict) else {}
            if not isinstance(usage, dict):
                usage = {}
            for key in ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens"):
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    metric["usage"][key] = value
            return response
        except Exception as exc:
            metric["error_type"] = type(exc).__name__
            raise
        finally:
            metric["latency_seconds"] = round(perf_counter() - started, 4)
            self.calls.append(metric)


def evaluate_case(case, provider):
    """Gold-free execution with real production graph/rules and dry external I/O."""
    measured = MeasuredModel(provider)
    events, stage_times = [], []
    started, previous = perf_counter(), perf_counter()
    result = {"case_id": case["case_id"], "language": case["language"], "error_type": None,
              "writeback_executed": False, "observed_success": None}
    with ExitStack() as stack:
        stack.enter_context(patch.object(_llm, "model", return_value=measured))
        stack.enter_context(patch.object(retrieve, "retrieve_context", return_value=deepcopy(case["context"])))
        stack.enter_context(patch.object(recommender, "second_retrieval", side_effect=lambda state, **kwargs:
                                        deepcopy(case["second_pass"].get((state.get("classification") or {}).get("category"), []))))
        stack.enter_context(patch.object(graph, "_case_file", return_value=None))
        stack.enter_context(patch.object(writeback, "write_resolution", return_value="DRY-RECOMMENDATION-NOT-PERSISTED"))
        stack.enter_context(patch.object(writeback, "write_escalation", return_value={"escalation_id": "DRY-NOT-FILED", "team": "human_review"}))
        # Fail fast if an unexpected stage attempts any query/embedding during evaluation.
        stack.enter_context(patch.object(retrieve, "_read", side_effect=RuntimeError("Unexpected live retrieval during frozen evaluation")))
        stack.enter_context(patch.object(retrieve, "get_driver", side_effect=RuntimeError("Benchmark database access prohibited")))
        stack.enter_context(patch.object(writeback, "get_driver", side_effect=RuntimeError("Benchmark write access prohibited")))
        try:
            for kind, payload in graph.stream_complaint(case["complaint"]):
                now = perf_counter()
                if kind == "stage":
                    stage_times.append({"stage": payload["stage"], "loop": payload["loop"], "latency_seconds": round(now - previous, 4)})
                    previous = now
                events.append({"kind": kind, "payload": payload})
        except Exception as exc:
            result["error_type"] = type(exc).__name__
    final = next((event["payload"] for event in reversed(events) if event["kind"] == "final"), {})
    result.update({"events": events, "final": final, "calls": measured.calls, "stage_latencies": stage_times,
                   "latency_seconds": round(perf_counter() - started, 4),
                   "dry_disposition": "accepted_recommendation" if final.get("disposition") == "execute" else
                                      "escalation_required" if final.get("disposition") == "escalate" else "error"})
    return result


def prose_language(text):
    arabic = sum("\u0600" <= ch <= "\u06ff" for ch in text)
    english = sum(ch.isascii() and ch.isalpha() for ch in text)
    if not arabic and not english:
        return "empty"
    return "ar" if arabic > english else "en"


def score_result(result, case, answer):
    final = result["final"]
    cause = (final.get("classification") or {}).get("category")
    action = (final.get("recommendation") or {}).get("action")
    history = [row for row in answer["plausibility_history"] if base(row["category"]) == base(answer["category"]) and row["action"] == action]
    strengths = rules.action_success_rate(history).get(action)
    first = case["context"]["similar_cases"]
    own = case["context"]["local_subgraph"]
    prose = " ".join(str((final.get(key) or {}).get(field) or "") for key, field in
                     (("classification", "rationale"), ("recommendation", "rationale"), ("review", "reason")))
    extracted = next((e["payload"].get("detail", {}) for e in result["events"] if e["kind"] == "stage" and e["payload"]["stage"] == "extract"), {})
    stages = [e["payload"] for e in result["events"] if e["kind"] == "stage"]
    reviews = [s.get("detail", {}) for s in stages if s["stage"] == "review"]
    first_cause = next((s.get("detail", {}).get("category") for s in stages if s["stage"] == "classify"), None)
    first_correct = bool(first_cause) and base(first_cause) == base(answer["category"])
    final_correct = bool(cause) and base(cause) == base(answer["category"])
    retried = len([s for s in stages if s["stage"] == "classify"]) > 1
    final_classifier_call = next((call for call in reversed(result["calls"]) if call["stage"] == "classify"), None)
    valid_classifier = bool(final_classifier_call and not final_classifier_call["malformed_json"]
                            and not final_classifier_call["missing_declared_fields"]
                            and not final_classifier_call["invalid_declared_fields"] and not final_classifier_call["error_type"])
    any_fallback = any(call["malformed_json"] or call["missing_declared_fields"] or call["invalid_declared_fields"] for call in result["calls"])
    return {
        "expected_seeded_category": answer["category"], "expected_seeded_action": answer["action"],
        "predicted_category": cause, "predicted_action": action,
        "base_cause_agreement": bool(cause) and base(cause) == base(answer["category"]),
        "first_base_cause_agreement": first_correct,
        "first_predicted_category": first_cause,
        "afl_corrected_seeded_cause_miss_proxy": retried and not first_correct and final_correct,
        "afl_changed_seeded_cause_hit_to_miss_proxy": retried and first_correct and not final_correct,
        "base_cause_valid_model_agreement": valid_classifier and bool(cause) and base(cause) == base(answer["category"]),
        "final_classifier_model_output_valid": valid_classifier,
        "application_field_fallback_or_normalization": any_fallback,
        "failed_attempt_family_agreement": bool(cause) and family(cause) == family(answer["category"]),
        "raw_full_category_agreement_unsupported_escalation_prefix": cause == answer["category"],
        "any_recorded_shipment_base_cause_agreement": bool(cause) and base(cause) in answer["shipment_base_causes"],
        "seeded_action_exact_agreement": bool(action) and action == answer["action"],
        "synthetic_history_action_plausibility_proxy": bool(strengths and strengths["rate"] >= 0.5),
        "plausibility_history_counts": strengths,
        "review_accepted": (final.get("review") or {}).get("verdict") == "accept",
        "accepted_seeded_cause_disagreement_proxy": (final.get("review") or {}).get("verdict") == "accept" and base(cause) != base(answer["category"]),
        "afl_retry": retried,
        "reject_reviews": sum(r.get("verdict") == "reject" for r in reviews),
        "escalated": result["dry_disposition"] == "escalation_required",
        "no_grounding": not first,
        "retrieval_category_match_proxy": sum(base(row.get("category")) == base(answer["category"]) for row in first) / len(first) if first else None,
        "extraction_shipment_id_match": extracted.get("shipment_id") == case["shipment_id"],
        "actual_native_prose_language": prose_language(prose), "native_prompt_prose_language": "en",
        "arabic_canonical_action": prose_language(action or "") == "ar",
        "quality_not_independently_scored": True,
        "recorded_delivery_attempts": rules._attempts(own.get("events") or []),
    }


def run(output_dir, models=MODELS, maximum=None):
    manifest, runtime = verify_bundle(output_dir)
    providers = {name: ChatLiteLLM(model=name, api_key=config.LLM_API_KEY, api_base=config.LLM_API_BASE,
                                 temperature=0, request_timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES) for name in models}
    completed_now = 0
    for case in runtime["cases"]:
        for model_name in models:
            suffix = model_name.rsplit(":", 1)[-1]
            path = output_dir / "results" / suffix / f"{case['case_id']}.json"
            if path.exists():
                existing = load_json(path)
                validate_result_identity(existing, manifest, case, model_name)
                continue
            if maximum is not None and completed_now >= maximum:
                return
            result = evaluate_case(case, providers[model_name])
            # Gold was validated before execution; scoring reads it here after the graph
            # finishes. No gold value is ever supplied to graph state or provider prompts.
            answer = load_json(output_dir / "gold.json")[case["case_id"]]
            result["metrics"] = score_result(result, case, answer)
            result.update({"model": model_name, "runtime_hash": manifest["runtime_hash"], "gold_hash": manifest["gold_hash"],
                           "source_hashes": manifest["source_hashes"], "provider_identity": manifest["provider_identity"],
                           "version": VERSION, "timestamp": datetime.now(timezone.utc).isoformat()})
            save_json(path, result)
            completed_now += 1
            print(encode({"model": model_name, "case": case["case_id"], "seconds": result["latency_seconds"],
                          "error_type": result["error_type"], "dry_disposition": result["dry_disposition"]}), flush=True)


def validate_result_identity(result, manifest, case, model):
    expected = {"runtime_hash": manifest["runtime_hash"], "gold_hash": manifest["gold_hash"],
                "source_hashes": manifest["source_hashes"], "provider_identity": manifest["provider_identity"],
                "version": VERSION, "model": model, "case_id": case["case_id"], "language": case["language"]}
    if any(result.get(key) != value for key, value in expected.items()):
        raise ValueError("Resume/report result identity mismatch")


def latency_summary(values):
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p95": None}
    values = sorted(values)
    return {"n": len(values), "mean": round(statistics.mean(values), 3), "p50": round(statistics.median(values), 3),
            "p95": round(values[max(0, math.ceil(0.95 * len(values)) - 1)], 3)}


def wilson_interval(successes, attempts):
    if not attempts:
        return None
    z = 1.96
    proportion = successes / attempts
    denominator = 1 + z * z / attempts
    midpoint = (proportion + z * z / (2 * attempts)) / denominator
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * attempts)) / attempts) / denominator
    return [round(midpoint - margin, 4), round(midpoint + margin, 4)]


def report(output_dir):
    manifest, runtime = verify_bundle(output_dir)
    summaries = {}
    rows = []
    for model in MODELS:
        suffix = model.rsplit(":", 1)[-1]
        results = []
        for case in runtime["cases"]:
            path = output_dir / "results" / suffix / f"{case['case_id']}.json"
            if path.exists():
                result = load_json(path)
                validate_result_identity(result, manifest, case, model)
                results.append(result)
        calls = [call for result in results for call in result["calls"]]
        names = ("base_cause_agreement", "first_base_cause_agreement", "afl_corrected_seeded_cause_miss_proxy", "afl_changed_seeded_cause_hit_to_miss_proxy", "base_cause_valid_model_agreement", "final_classifier_model_output_valid", "application_field_fallback_or_normalization", "failed_attempt_family_agreement", "raw_full_category_agreement_unsupported_escalation_prefix",
                 "any_recorded_shipment_base_cause_agreement", "seeded_action_exact_agreement", "synthetic_history_action_plausibility_proxy",
                 "review_accepted", "accepted_seeded_cause_disagreement_proxy", "afl_retry", "escalated", "no_grounding", "extraction_shipment_id_match")
        metrics = {name: {"count": sum(bool(r["metrics"][name]) for r in results), "planned_denominator": 30,
                          "rate_per_planned_case": sum(bool(r["metrics"][name]) for r in results) / 30} for name in names}
        base_matches = metrics["base_cause_agreement"]["count"]
        by_case = {r["case_id"]: r for r in results}
        gold = load_json(output_dir / "gold.json")
        per_category, confusion = {}, {}
        for category in CATEGORIES:
            planned = [case for case in runtime["cases"] if base(gold[case["case_id"]]["category"]) == category]
            completed = [by_case[case["case_id"]] for case in planned if case["case_id"] in by_case]
            correct = sum(r["metrics"]["base_cause_agreement"] for r in completed)
            per_category[category] = {"correct": correct, "planned": 5, "completed": len(completed), "percentage": 20 * correct}
            confusion[category] = dict(Counter(
                base(by_case[case["case_id"]]["metrics"]["predicted_category"]) or "no_prediction"
                if case["case_id"] in by_case else "unattempted" for case in planned))
        retrieval_matches = [r["metrics"]["retrieval_category_match_proxy"] for r in results
                             if r["metrics"]["retrieval_category_match_proxy"] is not None]
        malformed = sum(call["malformed_json"] for call in calls)
        invalid = sum(bool(call["missing_declared_fields"] or call["invalid_declared_fields"]) for call in calls)
        exceptions = sum(call["error_type"] is not None for call in calls)
        case_malformed = sum(any(c["malformed_json"] for c in r["calls"]) for r in results)
        case_invalid = sum(any(c["missing_declared_fields"] or c["invalid_declared_fields"] for c in r["calls"]) for r in results)
        stage_names = sorted({call["stage"] for call in calls})
        summaries[model] = {"planned_cases": 30, "completed_cases": len(results), "unattempted_cases": 30 - len(results),
                            "case_exceptions": sum(r["error_type"] is not None for r in results),
                            "llm_exception_calls": sum(call["error_type"] is not None for call in calls),
                            "malformed_json_calls": sum(call["malformed_json"] for call in calls),
                            "llm_calls": len(calls), "metrics": metrics,
                            "base_agreement_wilson95_completed_cases": wilson_interval(base_matches, len(results)),
                            "per_category": per_category, "confusion_counts": confusion,
                            "retrieval_category_proxy_mean": statistics.mean(retrieval_matches) if retrieval_matches else None,
                            "retrieval_category_proxy_cases": len(retrieval_matches),
                            "call_diagnostics": {"attempted_calls": len(calls), "malformed_json": malformed,
                                                 "invalid_or_missing_declared_shape": invalid, "exceptions": exceptions,
                                                 "malformed_rate": malformed / len(calls) if calls else None,
                                                 "invalid_shape_rate": invalid / len(calls) if calls else None,
                                                 "exception_rate": exceptions / len(calls) if calls else None},
                            "case_diagnostics": {"planned_cases": 30, "malformed_json_cases": case_malformed,
                                                 "invalid_shape_cases": case_invalid,
                                                 "malformed_rate_per_planned": case_malformed / 30,
                                                 "invalid_shape_rate_per_planned": case_invalid / 30,
                                                 "exception_rate_per_planned": sum(r["error_type"] is not None for r in results) / 30},
                            "case_latency_seconds": latency_summary([r["latency_seconds"] for r in results]),
                            "model_stage_latency_seconds": {stage: latency_summary([c["latency_seconds"] for c in calls if c["stage"] == stage]) for stage in stage_names},
                            "pipeline_stage_latency_seconds": {stage: latency_summary([s["latency_seconds"] for r in results for s in r["stage_latencies"] if s["stage"] == stage])
                                                               for stage in sorted({s["stage"] for r in results for s in r["stage_latencies"]})},
                            "usage_exposed_calls": sum(bool(call["usage"]) for call in calls),
                            "total_tokens_reported": sum(c["usage"].get("total_tokens", 0) for c in calls) if any(c["usage"] for c in calls) else None,
                            "native_prose_language_counts": dict(Counter(r["metrics"]["actual_native_prose_language"] for r in results)),
                            "arabic_action_cases": sum(r["metrics"]["arabic_canonical_action"] for r in results),
                            "native_prose_by_complaint_language": {language: dict(Counter(r["metrics"]["actual_native_prose_language"] for r in results if r["language"] == language)) for language in ("ar", "en")},
                            "false_acceptance_rate": None, "false_rejection_rate": None,
                            "manual_quality_review": "pending independent rubric review"}
        for r in results:
            rows.append({"model": model, "case_id": r["case_id"], "language": r["language"], "latency_seconds": r["latency_seconds"],
                         "error_type": r["error_type"], "review": (r["final"].get("review") or {}).get("verdict"), **r["metrics"]})
    payload = {"manifest": manifest, "models": summaries, "case_rows": rows}
    save_json(output_dir / "comparison.json", payload)
    lines = ["# GPT-OSS v1 paired synthetic-history benchmark", "", manifest["methodology"], "",
             "Rates use all 30 planned cases per model, including exceptions/no-grounding. Partial runs remain partial; missing attempts are visible.", "",
             "| Model | Completed | Pipeline base agreement | Valid model base agreement | Family agreement | Action exact | Action history proxy | Review accept | AFL retry | Escalate | Mean seconds | p95 seconds |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, summary in summaries.items():
        metric = summary["metrics"]
        counts = [f"{metric[key]['count']}/30 ({100 * metric[key]['rate_per_planned_case']:.1f}%)" for key in ("base_cause_agreement", "base_cause_valid_model_agreement", "failed_attempt_family_agreement", "seeded_action_exact_agreement",
                 "synthetic_history_action_plausibility_proxy", "review_accepted", "afl_retry", "escalated")]
        lines.append(f"| {name} | {summary['completed_cases']}/30 | " + " | ".join(counts) + f" | {summary['case_latency_seconds']['mean']} | {summary['case_latency_seconds']['p95']} |")
    lines.extend(["", "False acceptance/rejection: unavailable without independent human gold. Accepted seeded-cause disagreements are descriptive proxies only.", "",
                  "Pipeline agreement includes application defaults after invalid output; valid-model agreement excludes a final classifier call with malformed, missing, invalid or errored declared output.", "",
                  "Raw escalation-prefix agreement is separate from supported-base cause agreement. Canonical Arabic action text is separate from Arabic explanation quality. Manual rubric scoring is pending.", ""])
    lines.extend(["Wilson 95% intervals use completed case agreement counts, including exceptions as disagreements. Balanced synthetic sampling is not random production sampling; intervals are descriptive uncertainty, not evidence of significance.", "",
                  "| Base category | 20B agreement | 120B agreement |", "|---|---:|---:|"])
    for category in CATEGORIES:
        cells = [summaries[model]["per_category"][category] for model in MODELS]
        lines.append(f"| {category} | " + " | ".join(f"{cell['correct']}/5 ({cell['percentage']}%)" for cell in cells) + " |")
    lines.append("")
    lines.extend(f"- {item}" for item in manifest["limitations"])
    lines.extend(["", "Model choice: pending paired completion and quality review; no assumption that the larger model is better."])
    (output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--report", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--max-new-results", type=int)
    args = parser.parse_args()
    # Provider logs can include request/response content. Benchmark records type-only errors.
    logging.disable(logging.CRITICAL)
    try:
        if args.prepare:
            prepared = prepare(args.output_dir)
            print(encode({"prepared": True, "runtime_hash": prepared["runtime_hash"], "cases": 30}))
        elif args.run:
            run(args.output_dir, (args.model,) if args.model else MODELS, args.max_new_results)
        else:
            report(args.output_dir)
            print(encode({"report_written": True}))
    except Exception as exc:
        print(encode({"error_type": type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
