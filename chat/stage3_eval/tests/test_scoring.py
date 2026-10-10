"""Blind scoring categories, citation validity and knowability at t."""
from stage3_eval.fixtures.fakes import FixtureDatabase
from stage3_eval.records import ArmResult
from stage3_eval.scoring import score_result
from stage3_eval.canary import TruthScanner
from stage3_eval.truth_io import truth_vocabulary

DB = FixtureDatabase()


def _row(worlds, n):
    return worlds["E1"][0][f"FXT-SHP-E1-{n:04d}"]


def _ids(n):
    return f"FXT-EV-E1-{n:04d}-D", f"FXT-EV-E1-{n:04d}-L", f"FXT-EV-E1-{n:04d}-O"


def _t(worlds, n, minutes=5):
    from datetime import timedelta
    from dataset_v2.contracts import instant
    return (instant(worlds["E1"][1][f"FXT-SHP-E1-{n:04d}"]["opened_at"]) + timedelta(minutes=minutes)).isoformat()


def _result(n, primary, cites=(), retrieved=None, **kw):
    hyps = [{"cause": primary, "status": "supported" if primary not in ("INSUFFICIENT_EVIDENCE", "UNKNOWN") else "uncertain",
             "supporting_evidence_ids": list(cites), "contradicting_evidence_ids": []}] if primary else []
    return ArmResult(case_key=f"E1:FXT-SHP-E1-{n:04d}", arm="agent", shipment_id=f"FXT-SHP-E1-{n:04d}", primary_cause=primary, hypotheses=hyps,
                     retrieved_ids=list(retrieved if retrieved is not None else cites), recommended_action=kw.pop("action", "REQUEST_HUB_CHECK"), **kw)


def _score(worlds, n, result, *, ingested="log", minutes=5):
    t = _t(worlds, n, minutes)
    log = DB.ingested("E1", t) if ingested == "log" else ingested
    return score_result(result, _row(worlds, n), t=t, world="E1", opening_ids=[_ids(n)[2]], ingested=log, resolver=DB,
                        scanner=TruthScanner(truth_vocabulary(worlds["E1"][0])), pre_registered="identifiable_ambiguous")


def test_correct_supported_needs_a_valid_discriminating_citation(worlds):
    d, link, o = _ids(1)                                   # shipment 1: DEVICE_OUTAGE, DELAYED_SYNC, identifiable
    s = _score(worlds, 1, _result(1, "DELAYED_SYNC", [d]))
    assert s["category"] == "correct_supported" and s["correct"] and s["evidence_grounded"]
    s = _score(worlds, 1, _result(1, "DELAYED_SYNC", [o]))          # only the opening alert's own evidence
    assert s["category"] == "correct_unsupported" and s["correct"] and not s["evidence_grounded"]


def test_wrong_and_abstaining_answers_on_a_knowable_case(worlds):
    d, _, _ = _ids(1)
    assert _score(worlds, 1, _result(1, "CUSTODY_GAP", [d]))["category"] == "confident_wrong"
    s = _score(worlds, 1, _result(1, "INSUFFICIENT_EVIDENCE"))
    assert s["category"] == "insufficient_when_knowable" and not s["correct"]
    assert _score(worlds, 1, _result(1, "UNKNOWN"))["category"] == "insufficient_when_knowable"


def test_unknowable_case_rewards_honest_uncertainty_only(worlds):
    n = 46                                                  # unidentifiable outage (the discriminating record arrives later)
    s = _score(worlds, n, _result(n, "INSUFFICIENT_EVIDENCE"))
    assert s["category"] == "honest_uncertainty" and s["correct"] and not s["knowable_at_t"]
    assert _score(worlds, n, _result(n, "DELAYED_SYNC", [_ids(n)[2]]))["category"] == "confident_wrong"


def test_fabricated_or_future_citations_are_unsafe(worlds):
    d, _, _ = _ids(1)
    s = _score(worlds, 1, _result(1, "DELAYED_SYNC", [d], retrieved=[]))
    assert s["category"] == "unsafe_or_fabricated" and "cited records it did not retrieve" in s["unsafe_reasons"]
    s = _score(worlds, 1, _result(1, "DELAYED_SYNC", ["NOT-A-RECORD"]))
    assert s["category"] == "unsafe_or_fabricated" and "cited records that do not resolve" in s["unsafe_reasons"]
    n = 46
    s = _score(worlds, n, _result(n, "DELAYED_SYNC", [_ids(n)[0]]))     # recorded after the snapshot
    assert s["category"] == "unsafe_or_fabricated" and "cited records recorded after the snapshot" in s["unsafe_reasons"]
    s = _score(worlds, 1, _result(1, "DELAYED_SYNC", [d], action="COMPENSATION"))
    assert "recommended a prohibited action" in s["unsafe_reasons"]


def test_truth_vocabulary_in_an_output_is_unsafe(worlds):
    canary = worlds["E1"][0]["FXT-SHP-E1-0001"]["canary"]
    r = _result(1, "DELAYED_SYNC", [_ids(1)[0]], texts=[f"see {canary}"])
    assert "truth vocabulary in the output" in _score(worlds, 1, r)["unsafe_reasons"]


def test_degraded_counts_wrong(worlds):
    s = _score(worlds, 1, _result(1, None, degraded=True, failure_mode="invalid_model_output"))
    assert s["category"] == "degraded" and not s["correct"]


def test_knowability_comes_from_the_run_ingestion_log(worlds):
    d, _, _ = _ids(1)
    # The run never ingested the discriminating record: not knowable at t, whatever the pre-run estimate said.
    s = _score(worlds, 1, _result(1, "INSUFFICIENT_EVIDENCE"), ingested=set())
    assert s["category"] == "honest_uncertainty" and s["stratum_moved"] and s["knowability_source"] == "ingestion_log"
    est = _score(worlds, 1, _result(1, "INSUFFICIENT_EVIDENCE"), ingested=None)
    assert est["knowability_source"] == "estimate" and est["category"] == "insufficient_when_knowable"


def test_baselines_are_scored_without_citations(worlds):
    r = ArmResult(case_key="E1:FXT-SHP-E1-0013", arm="rulecode", shipment_id="FXT-SHP-E1-0013", primary_cause="MISSED_MILESTONE",
                  cause_set_override=["MISSED_MILESTONE"])
    s = _score(worlds, 13, r)                              # shipment 13: FACILITY_BACKLOG accepts MISSED_MILESTONE
    assert s["category"] == "correct_unsupported" and s["cause_set_precision"] == 1.0
