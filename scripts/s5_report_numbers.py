"""Recompute every number in the S5 gate report from the committed results files.

Usage: python scripts/s5_report_numbers.py docs/evals/2026-10-09_s5/final
Reads pipeline.json, accounting.json, human.json, checks.json, heldout_detection.json, reviewer_failure.json
and concurrency.json from the directory and prints the figures the report quotes, with each file's provenance.
"""
import json
from pathlib import Path
import sys


def load(directory, name):
    return json.loads((Path(directory) / name).read_text(encoding="utf-8"))


def main(directory):
    p, a, h, c = (load(directory, n) for n in ("pipeline.json", "accounting.json", "human.json", "checks.json"))
    held, rev, conc = (load(directory, n) for n in ("heldout_detection.json", "reviewer_failure.json", "concurrency.json"))
    m, t = p["metrics"], a["scoring_transparency"]
    rows = p["cases"]
    live_healthy = m["live_shipments"] - m["abnormal_live_shipments"]
    cases_abnormal = sum(not r["truth_healthy"] for r in rows)
    out = {
        "provenance": {name: {k: d["provenance"].get(k) for k in ("commit", "dirty_tree", "tree_changed_during_run", "configured_model",
                                                                    "dataset_id", "manifest_hash", "database")}
                       | {"model_calls": d["provenance"].get("model_calls", {}).get("succeeded")}
                       for name, d in (("pipeline", p), ("accounting", a), ("human", h), ("checks", c), ("heldout", held),
                                       ("reviewer", rev), ("concurrency", conc))},
        "1_investigation_accuracy": {
            "all": t["accuracy_all"],
            "by_opening_symptom_rule_codes": {k: v for k, v in t["accuracy_by_opening_symptom_rule_codes"].items() if k != "caveat"},
            "named_vs_not": {"named": t["accuracy_when_an_opening_symptom_names_an_acceptable_cause"],
                             "not_named": t["accuracy_when_no_opening_symptom_names_an_acceptable_cause"]},
            "with_second_cause_credit": t["second_cause_credit"]["accuracy_with"],
            "without_second_cause_credit": t["second_cause_credit"]["accuracy_without"],
            "cases_credited_only_by_second_cause": t["second_cause_credit"]["cases_credited_only_by_it"],
            "delayed_sync_only": t["delayed_sync_only_cases"],
            "diagnosis_equals_symptom_rule_code": t["diagnosis_equals_the_label_of_an_opening_symptom"],
            "degraded_investigations": m["degraded_investigations"]},
        "2_detection": {
            "live": {"shipments": m["live_shipments"], "abnormal": m["abnormal_live_shipments"], "healthy": live_healthy,
                     "cases_opened": m["cases_opened"], "cases_on_healthy": m["cases_on_healthy_shipments"],
                     "cases_on_abnormal": cases_abnormal, "abnormal_without_case": m["abnormal_without_case"],
                     "shipment_precision": None if not m["cases_opened"] else round(
                         len({r["shipment_id"] for r in rows if not r["truth_healthy"]}) / len({r["shipment_id"] for r in rows}), 4),
                     "shipment_recall": round(1 - m["abnormal_without_case"] / m["abnormal_live_shipments"], 4)},
            "held_out": {k: held[k] for k in ("shipments", "healthy", "abnormal", "false_positive_rate", "recall")}
                        | {"false_positives": len(held["false_positive_cases"]), "missed": len(held["missed_abnormal"])}},
        "3_automatic_resolution": {
            "executed": m["automatic_actions_executed"], "on_wrong_cause": m["automatic_actions_with_wrong_cause"],
            "resolved": m["automatic_resolution_success"], "eligible_shipments": m["auto_eligible_shipments_resolved_without_human"],
            "pipeline_false_resolution_metric": m["false_resolution"],
            "resolved_cases": [{k: x[k] for k in ("shipment_id", "truth_recipe", "primary_cause", "standing_symptoms_at_closure",
                                                   "later_cases")} for x in a["resolved_cases"]],
            "resolved_with_standing_symptom_at_closure": a["resolved_with_standing_symptom_at_closure"],
            "false_resolutions_on_a_wrong_cause": a["false_resolutions_on_wrong_cause"],
            "second_cause_credit_effect": {k: t["second_cause_credit"][k] for k in
                                           ("resolved_on_a_wrong_cause_with", "resolved_on_a_wrong_cause_without")}},
        "4_human_escalation": {
            "final_states": m["final_states"], "wrong_diagnosis_end_states": a["wrong_diagnosis_end_states"],
            "human_findings": h["human_findings"], "approval_refusals": h["approval_refusals"], "approvals": h["approvals"]},
        "5_verification": {
            "failed_and_left_unresolved": m["verification_failures_left_unresolved"],
            "verified_but_exception_remained": sum(bool(r["executions"]) and any(o["success"] for o in r["outcomes"]) and r["final_state"] != "RESOLVED"
                                                   for r in rows),
            "answer_key_scan": {k: c["answer_key_scan"][k] for k in ("leak_count", "records_scanned", "terms")},
            "authority_bypass_executions": c["authority_bypass_executions"], "executions_checked": len(c["executions_checked"]),
            "public_id_resolution": c["public_id_resolution"], "evidence_correctness": m["evidence_correctness"]},
        "scenarios": {
            "D_reviewer_failure": {"stored_reviews": rev.get("stored_reviews"), "authority": (rev.get("authority") or {}).get("rule_id"),
                                   "final_state": rev["final_state"], "executions": len(rev["executions"])},
            "F_concurrency": {"paused": conc["investigation_paused_check"], "windows": conc["investigation_windows"]}},
        "triggers": {"opening": c["opening_trigger_symptoms"]},
    }
    print(json.dumps(out, indent=1, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
