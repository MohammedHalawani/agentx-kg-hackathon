"""Load shipment_kg/shipment_dataset.cypher into config.SHIPMENT_DATABASE with UTF-8 preserved.

The cypher file is written by shipment_kg/generate_shipment_kg.py as UTF-8. On Windows,
piping that file through cypher-shell or PowerShell with the default code page (cp1252)
replaces non-ASCII characters with literal '?' before they reach Neo4j. This script reads
the file explicitly as UTF-8 and executes statements through the Python driver instead.

Usage (from chat/):
    uv run python scripts/load_shipment_graph.py              # dry run (counts only)
    uv run python scripts/load_shipment_graph.py --yes        # wipe + load
    uv run python scripts/load_shipment_graph.py --yes --file ../shipment_kg/shipment_dataset.cypher
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neo4j import RoutingControl  # noqa: E402

import config  # noqa: E402
from core.query_runner import get_driver  # noqa: E402

DEFAULT_CYPHER = Path(__file__).resolve().parents[2] / "shipment_kg" / "shipment_dataset.cypher"

_WIPE = "MATCH (n) DETACH DELETE n"

_VERIFY = """
MATCH (r:Resolution)
RETURN r.action AS action
LIMIT 1
"""


def _statements(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        out.append(line)
    return out


def _run(cypher: str, write: bool = False) -> list[dict]:
    return get_driver().execute_query(
        cypher,
        routing_=RoutingControl.WRITE if write else RoutingControl.READ,
        database_=config.SHIPMENT_DATABASE,
        result_transformer_=lambda res: [r.data() for r in res],
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", action="store_true", help="wipe the database and load the cypher file")
    ap.add_argument("--file", type=Path, default=DEFAULT_CYPHER, help="path to shipment_dataset.cypher")
    ap.add_argument("--batch", type=int, default=100, help="statements per transaction batch")
    args = ap.parse_args()

    path = args.file.resolve()
    if not path.is_file():
        raise SystemExit(f"Cypher file not found: {path}")

    statements = _statements(path)
    print(f"Database: {config.SHIPMENT_DATABASE}")
    print(f"Source:   {path}")
    print(f"Statements: {len(statements)}")

    sample = next((s for s in statements if "action:" in s and "Resolution" in s), None)
    if sample:
        # Show a snippet so the operator can confirm Arabic survived the read step.
        idx = sample.index("action:")
        snippet = sample[idx : idx + 80]
        safe = snippet.encode("ascii", "backslashreplace").decode("ascii")
        print(f"Sample action field: {safe}...")

    if not args.yes:
        print("\nDry run. Re-run with --yes to wipe the database and import.")
        return

    driver = get_driver()
    print("\nWiping existing graph…")
    _run(_WIPE, write=True)

    print(f"Importing {len(statements)} statements…")
    batch_size = max(1, args.batch)
    for i in range(0, len(statements), batch_size):
        batch = statements[i : i + batch_size]
        with driver.session(database=config.SHIPMENT_DATABASE) as session:
            for stmt in batch:
                session.run(stmt)
        done = min(i + batch_size, len(statements))
        if done % 500 == 0 or done == len(statements):
            print(f"  {done}/{len(statements)}")

    verify = _run(_VERIFY)[0]["action"]
    safe_verify = verify.encode("ascii", "backslashreplace").decode("ascii") if verify else ""
    print(f"\nVerification — first Resolution.action: {safe_verify!r}")
    if verify and all(ch == "?" for ch in verify.replace(" ", "")):
        raise SystemExit("Import finished but Arabic still looks corrupted — check file encoding.")
    print("Import complete.")


if __name__ == "__main__":
    main()
