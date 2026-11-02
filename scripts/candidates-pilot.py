#!/usr/bin/env python3
"""Finite non-filling candidate trials; elaboration is not proof completion."""

import argparse
import json
from pathlib import Path

from agda_evidence.candidates import (
    ASSURANCE, check_candidate, load_candidate_observation, write_candidate_observation,
)
from agda_evidence.core import build_snapshot
from agda_evidence.goals import observe_goals, load_goal_observation, write_goal_observation

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agda-bin", default="agda")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or args.output.is_symlink() or output.is_relative_to(ROOT):
        parser.error("pilot output must be a new directory outside the repository")
    output.mkdir(parents=True)
    project = ROOT / "examples/goal-query"
    before = build_snapshot(project)[0]["sourceId"]
    listing = observe_goals(project, "Main.agda", agda_binary=args.agda_bin, safe=True)
    write_goal_observation(output / "listing.json", listing)
    listing = load_goal_observation(output / "listing.json")
    if listing["result"]["status"] != "listed" or len(listing["result"]["goals"]) != 3:
        raise SystemExit("expected three selectable example goals")
    # Select from source-associated points rather than assume dense IDs.
    points = {goal["range"][0]["start"]["line"]: goal["id"] for goal in listing["result"]["goals"]}
    summaries = {}
    for label, line, expression, expected in (
        ("nat-local", 8, "n", "elaborated"),
        ("unicode-local", 11, "λ₁", "elaborated"),
        ("reflexivity", 14, "refl", "elaborated"),
        ("wrong-type", 8, "λ x → x", "query-error"),
        ("out-of-scope", 8, "notInScope", "query-error"),
        ("bare-underscore", 8, "_", None),
        ("unused-meta", 14, "let x = _ in refl", "elaborated"),
    ):
        value = check_candidate(project, listing, points[line], expression, agda_binary=args.agda_bin)
        path = output / f"{label}.candidate.json"
        write_candidate_observation(path, value)
        checked = load_candidate_observation(path)
        result = checked["result"]
        if expected is not None and result["status"] != expected:
            raise SystemExit(f"unexpected {label} result: {result}")
        if expected is None and result["status"] not in {"elaborated", "query-error"}:
            raise SystemExit(f"unexpected incomplete-expression protocol result: {result}")
        if checked["listing"] != listing or result["assurance"] != ASSURANCE:
            raise SystemExit("trial lost the exact listing or elaboration-only assurance")
        if result["status"] == "elaborated" and result["postflightUnchanged"] is not True:
            raise SystemExit("positive trial did not preserve the original goal summary")
        summaries[label] = {"observationId": checked["observationId"], "goalId": points[line],
                            "expression": expression, "result": result}
        print(f"{label}: {result['status']} ; assurance={result['assurance']}", flush=True)
    if before != build_snapshot(project)[0]["sourceId"] or list(project.rglob("*.agdai")):
        raise SystemExit("candidate pilot changed original source or generated interfaces there")
    summary = {"sourceId": before, "resolutionId": listing["resolution"]["resolutionId"],
               "compiler": listing["resolution"]["agda"], "listingId": listing["observationId"], "trials": summaries}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Native non-filling pilot passed; listing and seven candidate records independently verified.", flush=True)


if __name__ == "__main__":
    main()
