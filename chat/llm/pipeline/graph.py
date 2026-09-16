"""Compiles the pipeline stages into one LangGraph StateGraph:

    extract -> retrieve -> classify -> recommend -> review
                                 ^                     |
                                 |     reject (loop_count < MAX_LOOPS)
                                 +---------------------+
                                          |
                                accept    v
                                     writeback -> END

Mirrors chat/llm/agent.py's shape (a single compiled, memoized graph object;
create_react_agent there, build_pipeline() here) but this graph has real branching - the
reject edge back to classify is the AFL loop the rest of the pipeline is named for - so it's
hand-assembled with StateGraph rather than a prebuilt constructor.

MAX_LOOPS exists so a persistently-rejected recommendation terminates (routed to a
human/escalation path) instead of looping the classify/recommend/review triangle forever.
"""
from functools import lru_cache

from llm.pipeline.state import PipelineState

MAX_LOOPS = 3


def _should_loop(state: PipelineState) -> str:
    """Conditional edge out of review: 'accept' -> writeback, 'reject' (under the loop
    cap) -> classify, 'reject' (cap hit) -> an escalation exit instead of writeback."""
    ...


@lru_cache(maxsize=1)
def build_pipeline():
    """Assemble and compile the StateGraph described above. Memoized the same way
    chat/llm/agent.py._agent() is - expensive to build, safe to reuse across requests."""
    ...


def run_complaint(complaint_text: str) -> PipelineState:
    """Entry point: run one complaint through the compiled pipeline end to end and return
    the final state (classification, recommendation, review verdict, and resolution_id if
    it was accepted and written back)."""
    ...
