"""Build model-blind paired operator-output packets from completed benchmark cases."""
import argparse
import hashlib
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    runtime = load(args.bundle / "runtime_inputs.json")
    packets, key = [], {}
    for case in runtime["cases"]:
        paths = [args.bundle / "results" / model / (case["case_id"] + ".json")
                 for model in ("20b", "120b")]
        if not all(path.exists() for path in paths):
            continue
        results = [load(path) for path in paths]
        manifest = load(args.bundle / "manifest.json")
        for result in results:
            assert result["case_id"] == case["case_id"]
            assert result["runtime_hash"] == manifest["runtime_hash"]
            assert result["gold_hash"] == manifest["gold_hash"]
            assert result["source_hashes"] == manifest["source_hashes"]
        if hashlib.sha256(("quality-review-v1:" + case["case_id"]).encode()).digest()[0] % 2:
            results.reverse()
        used_categories = {
            event["payload"].get("detail", {}).get("category")
            for result in results for event in result["events"]
            if event["kind"] == "stage" and event["payload"]["stage"] == "classify"
        }
        packet = {"case_id": case["case_id"], "complaint_language": case["language"],
                  "complaint": case["complaint"], "prose_target": None, "prompt_language": "en",
                  "own_evidence": case["context"]["local_subgraph"],
                  "first_precedent": case["context"]["similar_cases"],
                  "used_second_pass_banks": {category: case["second_pass"][category]
                                             for category in sorted(used_categories - {None})
                                             if category in case["second_pass"]},
                  "outputs": {}}
        key[case["case_id"]] = {}
        for alias, result in zip(("A", "B"), results):
            packet["outputs"][alias] = {
                "error_type": result["error_type"], "final": result["final"],
                "dry_disposition": result["dry_disposition"],
                "iterations": [event["payload"] for event in result["events"]
                               if event["kind"] == "stage"
                               and event["payload"]["stage"] in ("classify", "recommend", "review")],
                "execution_confirmed": False,
            }
            key[case["case_id"]][alias] = result["model"]
        packets.append(packet)
    # The reviewer receives only the packets path; the model key is revealed after scoring.
    review = args.bundle / "quality-review"
    review.mkdir(parents=True, exist_ok=True)
    save(review / "blind-pairs.json", packets)
    save(review / "model-key.json", key)
    print(json.dumps({"completed_pairs": len(packets), "planned_pairs": 30}))


if __name__ == "__main__":
    main()
