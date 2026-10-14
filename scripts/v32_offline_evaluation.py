"""Run controlled V3.2 probes and export actual verifier/closure decisions; no paid model or database.

Private expectations are joined after role execution only. This script is never imported by runtime code.
"""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/"chat"),str(ROOT/"chat/tests")]
os.environ.update({"NEO4J_URI":"bolt://127.0.0.1:1","NEO4J_USERNAME":"offline","NEO4J_PASSWORD":"offline",
                   "LLM_API_KEY":"offline-placeholder","LLM_API_BASE":"http://127.0.0.1:1/v1",
                   "LITELLM_LOCAL_MODEL_COST_MAP":"True","LITELLM_TELEMETRY":"False",
                   "SUHAIL_NEO4J_TESTS":"0","SUHAIL_V3_RACE_TESTS":"0"})
from tests import test_v32_actions as actions, test_v32_action_store as store, test_v32_case_intelligence as intelligence
from operations.identifiers import public_value


def main():
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in (actions,store,intelligence))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    actual=actions.ActualVerifierTests.results
    traces=store.ActionStoreTests.traces
    metrics=intelligence.CaseIntelligenceTests.metrics
    negative=[r for r in actual if r["expected"]!="success"]
    negative_cases=[r for r in traces if not r["expected_may_resolve"]]
    report={"schema":"suhail-v32-controlled-evaluation-1","synthetic":True,"mode":"offline scripted roles; real production validators/authority/verifier/closure",
            "live_model_quality":"NOT MEASURED: no billable inference. Classification/reviewer scores below measure scripted fixtures only.",
            "tests":{"passed":result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
                     "failed":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped)},
            "scripted_quality":{"probes":len(metrics),"correct_classifications":sum(r["classification_correct"] for r in metrics),
                                "valid_citations":sum(r["citations_valid"] for r in metrics),
                                "alternatives_addressed":sum(r["alternative_addressed"] for r in metrics),
                                "abstentions":sum(r["abstained"] for r in metrics),
                                "unnecessary_human_escalations":sum(r["unnecessary_human_escalation"] for r in metrics)},
            "safety":{"actual_verifier_probes":len(actual),"negative_or_ambiguous_verifier_probes":len(negative),
                      "false_action_successes":sum(r["status"]=="success" for r in negative),
                      "end_to_end_traces":len(traces),"negative_or_unresolved_case_traces":len(negative_cases),
                      "false_case_resolutions":sum(r["workflow_state"]=="RESOLVED" for r in negative_cases),
                      "verified_case_resolutions":sum(r["workflow_state"]=="RESOLVED" for r in traces)},
            "quality_probes":metrics,"verifier_decisions":actual,"case_traces":traces,
            "limitations":["The authorized request in store probes is seeded with a scripted accepted review; no LLM accuracy is inferred.",
                           "Primitive verifier probes measure action evidence, not independent closure of every case.",
                           "Custody stock confirmation does not backfill an unconfirmed original handover.",
                           "Expected answers remain in tests/evaluation artifacts; runtime code imports neither."]}
    output=ROOT/"docs/v3.2/offline-evaluation.json"
    output.write_text(json.dumps(public_value(report),indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"tests":report["tests"],"quality":report["scripted_quality"],"safety":report["safety"]}))
    return 0 if result.wasSuccessful() and report["safety"]["false_case_resolutions"]==0 and report["safety"]["false_action_successes"]==0 else 1


if __name__=="__main__":sys.exit(main())
