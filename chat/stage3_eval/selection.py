"""Pre-registered case selection (amendment 2 sizing rule; amendment 1, F and J). Scorer side, before any run.

Reads each evaluation world's truth rows and monitor replay rows, assigns strata (strata.py), allocates N_main over
the (world, stratum) cells by the design's table and shrink order, draws each cell by a seeded procedure, and
writes two files before any case runs:

- selection.json: the cases to run, in order, with world, shipment and stratum, plus the extras lists. No cause
  code, mechanism name, label or canary is written into it (checked on write), because the run step reads it.
- pairs.json: the seeded, non-overlapping matched pairs (scorer side only; the run step never reads it).

Both are written once (an existing file is never replaced) with their sha256 beside them, so the hash can be
committed before the first run (amendment 1, F).
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random

from stage3_eval.design import (ALLOCATION_AT_PLANNING, CROSS_SHIPMENT_MECHANISMS, E1_MAIN_FLOOR, MAIN_TEST_CELL, SHRINK_ORDER,
                                STABILITY_MAX, STRATA, WORLDS, EvalConfig, n_main, sealed_hash, selection_seed)
from stage3_eval.strata import assign_strata, opened_cases

SELECTION_SCHEMA = "stage3-selection-1"


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


FORBIDDEN_IN_SELECTION = ("acceptable", "cause", "mechanism", "label", "canary", "truth")


def _check_runtime_safe(document, vocabulary):
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
    data = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(data, encoding="utf-8")
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
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
        "schema": SELECTION_SCHEMA, "sealed_config_hash": sealed_hash(config), "config": config.as_dict(),
        "allocation": {f"{w}/{s}": v for (w, s), v in sorted(allocation["cells"].items())}, "n_main": allocation["n_main"],
        "cases": [{"order": i, "key": c["key"], "world": c["world"], "shipment_id": c["shipment_id"], "stratum": c["stratum"],
                   "expected_opened_at": c["opened_at"], "main_test": (c["world"], c["stratum"]) == MAIN_TEST_CELL}
                  for i, c in enumerate(selected)],
        "extras": {"cross_shipment_ablation": ablation, "stability_rerun": stability},
        "unit": "first case per shipment, scored at its first investigation",
    }
    for world in worlds:
        _check_runtime_safe(selection, vocabulary_of(worlds[world][0]))
    pair_rng = random.Random(selection_seed(config.freeze_commit, "pairs"))
    pairs = {"schema": "stage3-pairs-1", "pairs": _pairs(selected, pair_rng)}
    strata_list = {"schema": "stage3-strata-1", "cases": [{"key": c["key"], "stratum": c["stratum"], "rule": c["stratum_rule"]}
                                                          for w in by_world_cases for c in by_world_cases[w]],
                   "census": census, "healthy_opened": healthy}
    hashes = {"selection": _write_once(out_dir / "selection.json", selection),
              "pairs": _write_once(out_dir / "pairs.json", pairs),
              "strata": _write_once(out_dir / "strata.json", strata_list)}
    return {"hashes": hashes, "allocation": {**allocation, "cells": {f"{w}/{st}": v for (w, st), v in sorted(allocation["cells"].items())}},
            "shortfalls": shortfalls, "selected": len(selected),
            "by_cell": {f"{w}/{s}": sum(1 for c in selected if (c["world"], c["stratum"]) == (w, s)) for w in WORLDS for s in STRATA},
            "pairs": len(pairs["pairs"]), "census": census}
