"""The seams the backend track wires on Fahad's machine (see WIRING.md). Tests use in-memory fakes behind the same
shapes; nothing here opens a database or calls a model.

Run step (no truth):
  CaseSource.case_ref(world, shipment_id) -> CaseRef | None
      The FIRST case the monitor opened for that shipment in that world's database (case id, opening symptoms and rule
      codes, the evidence ids the opening exception cites, and the snapshot the investigation will use), or None if
      the run's monitor never opened one.
  Capture.capture_case(case_ref, results) -> {surface: [text | json-able, ...]}
      Per case: the tool outputs the agent received (surface "tools"), the case API responses the UI would get
      ("api"), execution receipts ("receipts").
  Capture.capture_run() -> {surface: iterable of text | json-able}
      Once at the end: a property dump of the run database ("graph") and the run's logs ("logs").

Scorer step (reads truth, after the run):
  IngestionLog.ingested(world, t) -> set[str]
      Evidence ids with recorded_at <= t in that world's database after the run (an imported record from its own
      recorded_at, a fed record from its ingestion), as world.truth.labels_at expects.
  EvidenceResolver.recorded_at(world, ids) -> {id: recorded_at ISO string}
      For cited ids; an id absent from the answer does not resolve.
"""
from typing import Iterable, Protocol

from stage3_eval.arms import CaseRef


class CaseSource(Protocol):
    def case_ref(self, world: str, shipment_id: str) -> CaseRef | None: ...


class Capture(Protocol):
    def capture_case(self, case: CaseRef, results: dict) -> dict: ...

    def capture_run(self) -> dict: ...


class IngestionLog(Protocol):
    def ingested(self, world: str, t: str) -> set: ...


class EvidenceResolver(Protocol):
    def recorded_at(self, world: str, ids: Iterable[str]) -> dict: ...
