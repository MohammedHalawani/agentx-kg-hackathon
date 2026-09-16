"""Run one complaint through the GraphRAG pipeline and print each stage as it happens.

The demo entry point: it makes the diagram's flow visible in the terminal - what was
extracted, what retrieval found, how it was classified, what was recommended, whether the
reviewer accepted, and whether the result was executed (written back) or escalated.

Usage (from chat/):
    uv run python scripts/run_complaint.py "الشحنة SHP-0001 لم تصل والعنوان خطأ"
    uv run python scripts/run_complaint.py --verbose "..."   # include retrieved precedent
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.pipeline.graph import run_complaint  # noqa: E402


def _section(title: str) -> None:
    print(f"\n{'─' * 70}\n{title}\n{'─' * 70}")


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("complaint", help="The complaint text (Arabic or English)")
    parser.add_argument("--verbose", action="store_true", help="Also print retrieved precedent")
    parser.add_argument("--debug", action="store_true", help="Show pipeline log output")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.debug else logging.WARNING,
        format="%(name)s: %(message)s",
    )

    final = run_complaint(args.complaint)

    _section("INPUT")
    print(final["complaint_text"])

    _section("EXTRACTED ENTITIES")
    print(_dump({k: v for k, v in (final.get("extracted") or {}).items() if k != "raw_text"}))

    ctx = final.get("context") or {}
    _section("HYBRID RETRIEVAL")
    print(f"similar cases fused : {len(ctx.get('similar_cases') or [])}")
    print(f"live failure matched: {ctx.get('live_failure_id') or '(none)'}")
    if args.verbose:
        print(_dump(ctx.get("similar_cases")))

    _section("CLASSIFICATION  (المصنّف)")
    print(_dump(final.get("classification")))

    _section("RECOMMENDATION  (المُوصي)")
    print(_dump(final.get("recommendation")))

    _section("REVIEW  (المراجع)")
    print(_dump(final.get("review")))
    if final.get("review_notes"):
        print(f"\nAFL loops taken: {final.get('loop_count')}")
        for i, note in enumerate(final["review_notes"], 1):
            print(f"  rejection {i}: {note}")

    _section("OUTPUT")
    disposition = final.get("disposition")
    if disposition == "execute":
        print(f"ACCEPT -> EXECUTE   written back as {final.get('resolution_id') or '(not written)'}")
    elif disposition == "escalate":
        print("REJECT -> ESCALATE  handed to a human after exhausting the feedback loop")
    else:
        print(f"(no disposition: {disposition})")


if __name__ == "__main__":
    main()
