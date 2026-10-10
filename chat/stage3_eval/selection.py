"""Pre-registered case selection (amendment 2 sizing rule; amendment 1, F and J). Scorer side, before any run.

Reads each evaluation world's truth rows and monitor replay rows, assigns strata (strata.py), allocates N_main over
the (world, stratum) cells by the design's table and shrink order, draws each cell by a seeded procedure, and
writes these files before any case runs:

- selection.json (run side): the cases to run, in order, each with its key, world, shipment and the monitor
  replica's expected opening time, and nothing else. No stratum, no main-test flag, no extras list, no cause code,
  mechanism name, label or canary: all of those are derived from truth, and the run step reads this file (checked on
  write by design.runtime_selection_problem, and again by the run step when it loads the file).
- selection_scorer.json (scorer side): each case's stratum and whether it is in the main test, and the allocation.
  The run step never reads it; the scorer and the report do (scorer_view puts the two back together).
- extras.json (scorer side): the case keys of the two exploratory extras, both derived from truth (the ablation list
  from the explaining mechanisms, the stability list from the main-test cell). The run step opens it only when it is
  named on the command line, and only after every main-test case has been run.
- pairs.json: the seeded, non-overlapping matched pairs (scorer side only; the run step never reads it).
- strata.json: every opened case's stratum and the census that decided it (scorer side only).

All are written once (an existing file is never replaced) with their sha256 beside them, so the hash can be
committed before the first run (amendment 1, F).
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random

from stage3_eval.design import (ALLOCATION_AT_PLANNING, CROSS_SHIPMENT_MECHANISMS, E1_MAIN_FLOOR, MAIN_TEST_CELL, SHRINK_ORDER,
                                STABILITY_MAX, STRATA, WORLDS, EvalConfig, canonical_bytes, n_main, runtime_selection_problem, sealed_hash,
                                selection_seed)
from stage3_eval.strata import assign_strata, opened_cases

SELECTION_SCHEMA = "stage3-selection-2"
SCORER_SCHEMA = "stage3-selection-scorer-1"
EXTRAS_SCHEMA = "stage3-extras-1"
SCORER_FILE, EXTRAS_FILE = "selection_scorer.json", "extras.json"


def allocate(c_cap, r_cap=0, budget=None):
    """Cases per (world, stratum) cell for the given caps, by amendment 2's table and shrink order."""
    total = n_main(c_cap, r_cap) if budget is None else n_main(c_cap, r_cap, budget)
    alloc = dict(ALLOCATION_AT_PLANNING)
    excess = sum(alloc.values()) - total
    for stratum, worlds, floor in SHRINK_ORDER:
        if excess <= 0:
            break
        cells = [(w, stratum) for w in worlds]
        while excess > 0 and sum(alloc[c] for c in cells) > floor:
            biggest = max(cells, key=lambda c: (alloc[c], c[0] == "E1"))   # take from the larger cell first
            if alloc[biggest] == 0:
                break
            alloc[biggest] -= 1
            excess -= 1
    if excess > 0:
        raise ValueError(f"N_main = {total} cannot hold even the floors of the allocation")
    notes = []
    if alloc[MAIN_TEST_CELL] < E1_MAIN_FLOOR:
        notes.append(f"E1 main test has {alloc[MAIN_TEST_CELL]} cases, below the design's target of {E1_MAIN_FLOOR}")
    return {"n_main": total, "cells": alloc, "notes": notes}


def _draw(cases, k, rng, sampling):
    """k cases from one cell, seeded. round_robin_by_mechanism interleaves the explaining mechanism groups so the
    cell covers as many mechanisms as it can; uniform is a plain seeded shuffle."""
    cases = sorted(cases, key=lambda c: c["shipment_id"])
    if sampling == "uniform":
        rng.shuffle(cases)
        return cases[:k]
    if sampling != "round_robin_by_mechanism":
        raise ValueError(f"unknown sampling rule {sampling}")
    groups = defaultdict(list)
    for c in cases:
        groups[" + ".join(c["mechanism_types"])].append(c)
    keys = sorted(groups)
    rng.shuffle(keys)
    for key in keys:
        rng.shuffle(groups[key])
    out = []
    while len(out) < k and any(groups[key] for key in keys):
        for key in keys:
            if groups[key] and len(out) < k:
                out.append(groups[key].pop(0))
    return out


def _pairs(selected, rng):
    """Seeded, non-overlapping matched pairs among identifiable selected cases: same opening symptoms with disjoint
    acceptable causes (discrimination), then same acceptable cause with different opening symptoms (consistency)."""
    pool = [c for c in selected if c["identifiable"]]
    rng.shuffle(pool)
    used, out = set(), []
    for kind in ("same_symptoms_different_cause", "same_cause_different_symptoms"):
        for i, a in enumerate(pool):
            if a["key"] in used:
                continue
            for b in pool[i + 1:]:
                if b["key"] in used or a["world"] != b["world"]:
                    continue
                if kind == "same_symptoms_different_cause":
                    match = a["symptoms"] == b["symptoms"] and not (a["acceptable"] & b["acceptable"])
                else:
                    match = a["symptoms"] != b["symptoms"] and bool(a["acceptable"] & b["acceptable"])
                if match:
                    out.append({"kind": kind, "cases": [a["key"], b["key"]]})
                    used.update((a["key"], b["key"]))
                    break
    return out


FORBIDDEN_IN_SELECTION = ("acceptable", "cause", "mechanism", "label", "canary", "truth", "stratum", "main_test", "extras",
                          "cross_shipment_ablation", "stability_rerun", "allocation", "identifiable")


def _check_runtime_safe(document, vocabulary):
    """The runtime-safety screen of the run-readable file: only the registered names (so no stratum, main-test flag
    or extras list, which are derived from truth), no truth-side field name and no truth vocabulary."""
    problem = runtime_selection_problem(document)
    if problem:
        raise ValueError(f"selection would carry a truth-side field ({problem}); the run step reads this file")
    text = json.dumps(document, sort_keys=True)
    for key in FORBIDDEN_IN_SELECTION:
        if f'"{key}' in text:
            raise ValueError(f"selection would carry a truth-side field ({key}); the run step reads this file")
    for token in [vocabulary["canary"], *vocabulary["mechanism_ids"], *vocabulary["mechanism_names"]]:
        if token in text:
            raise ValueError("selection would carry truth vocabulary")


def _write_once(path: Path, document):
    if path.exists():
        raise FileExistsError(f"{path} exists; a pre-registered selection is never replaced")
    # Bytes, not text: text mode turns "\n" into "\r\n" on Windows, and the file would no longer match the digest
    # taken here. The run step hashes the same canonical bytes (design.canonical_bytes), so a checkout that converts
    # line endings still verifies.
    data = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    path.write_bytes(data)
    digest = hashlib.sha256(canonical_bytes(data)).hexdigest()
    path.with_name(path.name + ".sha256").write_bytes(f"{digest}  {path.name}\n".encode("utf-8"))
    return digest


def select(worlds, config: EvalConfig, out_dir, *, vocabulary_of=None):
    """worlds: {"E1": (truth, replay_rows), "E2": (...)} (dicts keyed by shipment id). Writes selection.json and
    pairs.json under out_dir and returns a summary (hashes, allocation, shortfalls, census)."""
    from stage3_eval.truth_io import truth_vocabulary
    if len(config.freeze_commit or "") < 40:
        raise ValueError("the selection is seeded from the full freeze commit hash (amendment 1, G); give all 40 characters")
    vocabulary_of = vocabulary_of or truth_vocabulary
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    allocation = allocate(config.c_cap, config.r_cap, config.budget)
    selected, shortfalls, census, by_world_cases, healthy = [], [], {}, {}, {}
    for world in WORLDS:
        if world not in worlds:
            continue
        truth, replay = worlds[world]
        cases, healthy[world] = opened_cases(truth, replay)
        strata, rule, census[world] = assign_strata(cases)
        for c in cases:
            c.update(world=world, key=f"{world}:{c['shipment_id']}", stratum=strata[c["shipment_id"]], stratum_rule=rule[c["shipment_id"]])
        by_world_cases[world] = cases
        rng = random.Random(selection_seed(config.freeze_commit, world))
        for stratum in STRATA:
            k = allocation["cells"].get((world, stratum), 0)
            pool = [c for c in cases if c["stratum"] == stratum]
            drawn = _draw(pool, k, rng, config.sampling)
            if len(drawn) < k:
                shortfalls.append({"world": world, "stratum": stratum, "allocated": k, "available": len(pool)})
            selected.extend(drawn)
    for world in WORLDS:
        if world not in worlds:
            shortfalls.append({"world": world, "stratum": "all", "available": 0,
                               "allocated": sum(v for (w, _), v in allocation["cells"].items() if w == world)})
    # Run order: world by world, by the monitor's expected opening time. The run replays each world's feed with a clock
    # that only moves forward, so a case is investigated when it opens (its snapshot t stays at the opening); a
    # shuffled order would investigate later cases first and push earlier ones' snapshots past their openings.
    selected.sort(key=lambda c: (WORLDS.index(c["world"]), c["opened_at"], c["shipment_id"]))
    main = [c for c in selected if (c["world"], c["stratum"]) == MAIN_TEST_CELL]
    ablation = [c["key"] for c in main if set(c["mechanism_types"]) & set(CROSS_SHIPMENT_MECHANISMS)]
    stability = [c["key"] for c in main][:STABILITY_MAX]
    selection = {
        "schema": SELECTION_SCHEMA, "sealed_config_hash": sealed_hash(config), "config": config.as_dict(), "n_main": allocation["n_main"],
        "cases": [{"order": i, "key": c["key"], "world": c["world"], "shipment_id": c["shipment_id"], "expected_opened_at": c["opened_at"]}
                  for i, c in enumerate(selected)],
        "unit": "first case per shipment, scored at its first investigation",
    }
    for world in worlds:
        _check_runtime_safe(selection, vocabulary_of(worlds[world][0]))
    selection_sha = _write_once(out_dir / "selection.json", selection)
    scorer_side = {"schema": SCORER_SCHEMA, "selection_sha256": selection_sha,
                   "allocation": {f"{w}/{s}": v for (w, s), v in sorted(allocation["cells"].items())},
                   "cases": [{"key": c["key"], "stratum": c["stratum"], "main_test": (c["world"], c["stratum"]) == MAIN_TEST_CELL} for c in selected]}
    extras = {"schema": EXTRAS_SCHEMA, "selection_sha256": selection_sha,
              "extras": {"cross_shipment_ablation": ablation, "stability_rerun": stability}}
    pair_rng = random.Random(selection_seed(config.freeze_commit, "pairs"))
    pairs = {"schema": "stage3-pairs-1", "pairs": _pairs(selected, pair_rng)}
    strata_list = {"schema": "stage3-strata-1", "cases": [{"key": c["key"], "stratum": c["stratum"], "rule": c["stratum_rule"]}
                                                          for w in by_world_cases for c in by_world_cases[w]],
                   "census": census, "healthy_opened": healthy}
    hashes = {"selection": selection_sha,
              "selection_scorer": _write_once(out_dir / SCORER_FILE, scorer_side),
              "extras": _write_once(out_dir / EXTRAS_FILE, extras),
              "pairs": _write_once(out_dir / "pairs.json", pairs),
              "strata": _write_once(out_dir / "strata.json", strata_list)}
    return {"hashes": hashes, "allocation": {**allocation, "cells": {f"{w}/{st}": v for (w, st), v in sorted(allocation["cells"].items())}},
            "shortfalls": shortfalls, "selected": len(selected),
            "by_cell": {f"{w}/{s}": sum(1 for c in selected if (c["world"], c["stratum"]) == (w, s)) for w in WORLDS for s in STRATA},
            "pairs": len(pairs["pairs"]), "census": census}


def _read_sealed(path):
    """A pre-registered file, refused unless it matches the sha256 written beside it. Returns (document, sha256)."""
    path = Path(path)
    data = path.read_bytes()
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.exists():
        raise ValueError(f"{sidecar} is missing; a pre-registered file without its hash is not used")
    actual = hashlib.sha256(canonical_bytes(data)).hexdigest()
    if actual != sidecar.read_text(encoding="utf-8").split()[0]:
        raise ValueError(f"{path.name} does not match its pre-registered sha256")
    return json.loads(data), actual


def scorer_view(selection_path):
    """Scorer side only: the run-readable selection joined with what the scorer and the report need and the run step
    must not read (each case's stratum and main-test flag, the allocation, the extras lists). Every file is checked
    against its pre-registered hash, and the scorer-side files against the selection they were written for."""
    selection_path = Path(selection_path)
    selection, selection_sha = _read_sealed(selection_path)
    scorer_side, _ = _read_sealed(selection_path.with_name(SCORER_FILE))
    extras, _ = _read_sealed(selection_path.with_name(EXTRAS_FILE))
    for name, document in ((SCORER_FILE, scorer_side), (EXTRAS_FILE, extras)):
        if document.get("selection_sha256") != selection_sha:
            raise ValueError(f"{name} was not written for this selection.json")
    by_key = {row["key"]: row for row in scorer_side["cases"]}
    if set(by_key) != {row["key"] for row in selection["cases"]}:
        raise ValueError(f"{SCORER_FILE} does not name the same cases as selection.json")
    return {**selection, "allocation": scorer_side["allocation"], "extras": extras["extras"], "selection_sha256": selection_sha,
            "cases": [{**row, "stratum": by_key[row["key"]]["stratum"], "main_test": by_key[row["key"]]["main_test"]} for row in selection["cases"]]}
