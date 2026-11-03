#!/usr/bin/env python3
"""Run a bounded one-dependency pilot; the caller provisions all sources/tools."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil

from agda_evidence.core import (
    EvidenceError, build_snapshot, canonical_json_bytes, capture_bundle, verify_bundle,
)
from agda_evidence.goals import observe_goals
from agda_evidence.sources import (
    SourceEvidenceError, check_source_candidate, load_source_observation,
    observe_source_goals, source_summary, write_source_observation,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--agda-bin", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    dependency = args.dependency_root.resolve()
    require(not output.exists() and not output.is_relative_to(dependency),
            "output must be new and outside dependency source")
    executable = shutil.which(args.agda_bin)
    require(executable is not None, "native compiler is not available")
    binary = str(Path(executable).resolve())
    before = build_snapshot(dependency)[0]["sourceId"]
    example = Path(__file__).resolve().parents[1] / "examples" / "source-query"
    original_example = build_snapshot(example)[0]["sourceId"]
    output.mkdir(parents=True)
    client = output / "client"
    shutil.copytree(example, client)
    bundle = output / "dependency.evidence"
    gate = [binary, "--no-libraries", "--ignore-interfaces", "--safe", "-i", "src",
            "src/Relation/Binary/PropositionalEquality/Core.agda"]
    capture_bundle(dependency, bundle, gate, agda_binary=binary,
                   scope="Explicit safe equality Core module check; not a whole-library gate",
                   timeout_seconds=180, max_output_bytes=1_048_576)
    require(not verify_bundle(bundle), "dependency bundle failed internal verification")
    attestation = json.loads((bundle / "attestation.json").read_text(encoding="utf-8"))
    require(attestation["outcome"]["status"] == "passed", "explicit dependency-module gate failed")
    configuration = dict(dependency_bundle=bundle, dependency_root=dependency,
                         dependency_includes=["src"], agda_binary=binary,
                         timeout_seconds=120, max_output_bytes=4_194_304)
    reports = {}

    def retain(name: str, value: dict, expected: str) -> dict:
        path = output / f"{name}.source.json"
        write_source_observation(path, value)
        loaded = load_source_observation(path)
        require(canonical_json_bytes(loaded) == canonical_json_bytes(value), "saved envelope differs")
        reports[name] = source_summary(loaded)
        require(value["observation"]["result"]["status"] == expected,
                f"{name}: expected {expected}, got {value['observation']['result']}")
        print(name, expected, loaded["sourceObservationId"], flush=True)
        return value

    listing = retain("listing", observe_source_goals(client, "Main.agda", safe=True, **configuration), "listed")
    goals = listing["observation"]["result"]["goals"]
    require(len(goals) == 1, "fixture must have exactly one visible goal")
    goal = goals[0]["id"]
    retain("context", observe_source_goals(client, "Main.agda", listing=listing, goal_id=goal,
                                           includes=listing["composition"]["clientIncludes"], safe=True,
                                           **configuration), "inspected")
    accepted = retain("symmetry", check_source_candidate(client, listing, goal, "sym p", **configuration), "elaborated")
    require(accepted["observation"]["result"]["assurance"] == "contextual-elaboration-only"
            and accepted["observation"]["result"]["postflightUnchanged"] is True,
            "candidate must retain non-filling assurance and unchanged postflight")
    retain("wrong-type", check_source_candidate(client, listing, goal, "refl", **configuration), "query-error")
    absent = retain("no-proof-import-listing", observe_source_goals(client, "NoProofImport.agda", safe=True,
                                                                   **configuration), "listed")
    absent_goal = absent["observation"]["result"]["goals"][0]["id"]
    retain("no-proof-import", check_source_candidate(client, absent, absent_goal, "sym p", **configuration), "query-error")
    retain("unsuppressed-warnings", observe_source_goals(client, "Warnings.agda", safe=True,
                                                       **configuration), "load-blocked")
    # A source directory being available does not imply an implicit import.
    unmounted = observe_goals(client, "Main.agda", agda_binary=binary, safe=True,
                              timeout_seconds=60, max_output_bytes=4_194_304)
    require(unmounted["result"]["status"] == "load-error", "unmounted stdlib must not be silently resolved")
    (output / "unmounted.goal.json").write_bytes(canonical_json_bytes(unmounted) + b"\n")
    # Operate on a private copy for the stale unrelated-file probe, not the
    # supplied dependency checkout. The recorded full source pin must reject it.
    stale_root = output / "stale-dependency-copy"
    shutil.copytree(dependency, stale_root, ignore=shutil.ignore_patterns(".git", "*.agdai", "_build"))
    (stale_root / "unrelated-source-pin-change.txt").write_text("stale fixture\n", encoding="utf-8")
    stale_config = {**configuration, "dependency_root": stale_root}
    try:
        check_source_candidate(client, listing, goal, "sym p", **stale_config)
    except SourceEvidenceError:
        stale_rejected = True
    else:
        stale_rejected = False
    require(stale_rejected, "unrelated dependency edit must invalidate the saved listing")
    shutil.rmtree(stale_root)
    require(build_snapshot(dependency)[0]["sourceId"] == before, "original dependency source changed")
    require(build_snapshot(example)[0]["sourceId"] == original_example, "original example source changed")
    require(build_snapshot(client)[0]["sourceId"] == original_example, "client copy source changed")
    summary = {
        "format": "agda-evidence/source-pilot-summary-v1", "dependencySourceId": before,
        "clientSourceId": original_example, "dependencyGate": attestation,
        "observations": reports, "unmountedStatus": unmounted["result"]["status"],
        "staleDependencyRejected": stale_rejected, "originalSourcesUnchanged": True,
    }
    (output / "summary.json").write_bytes(canonical_json_bytes(summary) + b"\n")
    print("SOURCE PILOT PASSED: explicit source availability; no proof completion or closure claim", flush=True)


if __name__ == "__main__":
    main()
