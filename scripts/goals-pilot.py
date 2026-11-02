#!/usr/bin/env python3
"""Finite read-only native goal pilot over the committed unfinished example."""

import argparse
import json
from pathlib import Path

from agda_evidence.core import build_snapshot
from agda_evidence.goals import observe_goals, write_goal_observation, load_goal_observation

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
        raise SystemExit(f"expected three selectable goals: {listing['result']}")
    contexts = []
    for goal in listing["result"]["goals"]:
        value = observe_goals(project, "Main.agda", agda_binary=args.agda_bin, listing=listing, goal_id=goal["id"])
        path = output / f"goal-{goal['id']}.json"
        write_goal_observation(path, value)
        checked = load_goal_observation(path)
        if checked["result"]["status"] != "inspected":
            raise SystemExit(f"goal inspection did not succeed: {checked['result']}")
        selected = checked["result"]["selected"]
        contexts.append({"observationId": checked["observationId"], "selected": selected})
        print(f"Goal {selected['id']}: {selected['type']} ; context {selected['entries']}", flush=True)
    if not any(entry["reifiedName"] == "λ₁" for context in contexts for entry in context["selected"]["entries"]):
        raise SystemExit("Unicode local context binding was not retained")
    if not any("≡" in context["selected"]["type"] for context in contexts):
        raise SystemExit("dependent equality goal was not retained")
    empty = observe_goals(project, "Complete.agda", agda_binary=args.agda_bin, safe=True)
    write_goal_observation(output / "empty.json", empty)
    empty = load_goal_observation(output / "empty.json")
    if empty["result"]["status"] != "listed" or empty["result"]["goals"]:
        raise SystemExit("expected an accepted empty goal listing")
    if before != build_snapshot(project)[0]["sourceId"] or list(project.rglob("*.agdai")):
        raise SystemExit("goal pilot changed original source or generated interfaces there")
    summary = {"sourceId": before, "resolutionId": listing["resolution"]["resolutionId"],
               "compiler": listing["resolution"]["agda"], "listingId": listing["observationId"],
               "emptyListingId": empty["observationId"], "contexts": contexts}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Read-only native goal pilot passed; all five saved observations verified.", flush=True)


if __name__ == "__main__":
    main()
