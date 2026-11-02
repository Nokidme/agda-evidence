#!/usr/bin/env python3
"""Host API pilot, not a replacement editor, remote server or proof certificate."""

import argparse
import json
from pathlib import Path
import shutil

from agda_evidence.candidates import load_candidate_observation
from agda_evidence.catalog import create_catalog
from agda_evidence.core import (
    build_declaration_index, build_snapshot, canonical_json_bytes, capture_bundle,
    load_verified_bundle, write_declaration_index,
)
from agda_evidence.goals import load_goal_observation
from agda_evidence.research import ResearchWorkspace

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agda-bin", default="agda")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or args.output.is_symlink() or output.is_relative_to(ROOT):
        parser.error("output must be a new external directory")
    output.mkdir(parents=True)
    original = ROOT / "examples/goal-query"
    library = ROOT / "examples/client-query/library"
    before = (build_snapshot(original)[0]["sourceId"], build_snapshot(library)[0]["sourceId"])
    # Only this external disposable workspace is edited in the invalidation case.
    project = output / "workspace"
    shutil.copytree(original, project)
    index_path = output / "library.index.json"
    write_declaration_index(index_path, build_declaration_index(library))
    capture_bundle(library, output / "library.evidence",
        [args.agda_bin, "--no-libraries", "--ignore-interfaces", "--safe", "-i", "src", "src/Example.agda"],
        agda_binary=args.agda_bin, scope="safe example library typecheck", index_reference=index_path)
    _, payloads = load_verified_bundle(output / "library.evidence")
    if payloads["attestation.json"]["outcome"]["status"] != "passed":
        raise SystemExit("example source library gate did not pass")
    create_catalog(output / "catalog.json", [("example", output / "library.evidence")])
    host = ResearchWorkspace(project, {"main": "Main.agda"}, agda_binary=args.agda_bin,
        safe=True, catalog=output / "catalog.json")
    exchanges = []
    records = {}
    revision = None

    def call(op, *, expected="ok", **params):
        request = {"requestId": f"ui-{len(exchanges) + 1}", "op": op,
                   "revision": None if op in {"workspace.status", "record.get"} else revision, "args": params}
        response = host.handle(request)
        exchanges.append({"request": request, "response": response})
        if response["status"] != expected:
            raise SystemExit(f"unexpected {op} status: {response}")
        print(f"{op}: {response['status']}", flush=True)
        return response

    def archive(response, filename):
        fetched = call("record.get", recordId=response["recordId"])
        artifact = fetched["result"]["artifact"]
        path = output / filename
        path.write_bytes(canonical_json_bytes(artifact) + b"\n")
        checked = load_candidate_observation(path) if artifact["query"]["operation"] == "check" else load_goal_observation(path)
        records[filename] = {"observationId": checked["observationId"], "result": checked["result"]}
        return checked

    revision = call("workspace.status")["currentRevision"]
    listed = call("goals.list", documentId="main")
    leaf = archive(listed, "listing.json")
    points = {g["range"][0]["start"]["line"]: g["id"] for g in leaf["result"]["goals"]}
    goal = points[14]
    inspected = call("goals.inspect", listingId=listed["recordId"], goalId=goal)
    archive(inspected, "context.json")
    own = call("library.search", listingId=listed["recordId"], goalId=goal, prefix="Main", scope="project", limit=2)
    if own["result"]["truncated"] is not True or len(own["result"]["entries"]) != 2:
        raise SystemExit("expected bounded project lexical results")
    catalog = call("library.search", listingId=listed["recordId"], goalId=goal,
                   exact="Example.identity", scope="catalog", libraries=["example"])
    hits = catalog["result"]["entries"]
    if len(hits) != 1 or hits[0]["scopeStatus"] != "not-established" or hits[0]["candidateUsability"] != "not-tested":
        raise SystemExit("catalog discovery was confused with current scope/usability")
    good = call("candidate.check", listingId=listed["recordId"], goalId=goal, expression="refl")
    good_artifact = archive(good, "elaborated.candidate.json")
    if good_artifact["result"]["status"] != "elaborated" or good_artifact["result"]["assurance"] != "contextual-elaboration-only":
        raise SystemExit("trial did not preserve elaboration-only assurance")
    failed = call("candidate.check", listingId=listed["recordId"], goalId=goal, expression="n")
    if archive(failed, "rejected.candidate.json")["result"]["status"] != "query-error":
        raise SystemExit("wrong-type expression was not retained as native failure")
    # Finding a library declaration does not mount or import that library.
    unmounted = call("candidate.check", listingId=listed["recordId"], goalId=points[8], expression="Example.identity n")
    if archive(unmounted, "unmounted.candidate.json")["result"]["status"] != "query-error":
        raise SystemExit("catalog was implicitly mounted or imported")
    original_bytes = (project / "Main.agda").read_bytes()
    host.notify_buffers(dirty=True)
    call("candidate.check", expected="stale", listingId=listed["recordId"], goalId=goal, expression="refl")
    (project / "Main.agda").write_bytes(original_bytes + b"\n-- materialized newer editor revision\n")
    host.notify_buffers(dirty=False)
    revision = call("workspace.status")["currentRevision"]
    call("goals.inspect", expected="stale", listingId=listed["recordId"], goalId=goal)
    historical = call("record.get", recordId=good["recordId"])
    if historical["result"]["freshness"] != "stale" or historical["result"]["artifact"] != good_artifact:
        raise SystemExit("historical evidence was lost or promoted as current")
    if before != (build_snapshot(original)[0]["sourceId"], build_snapshot(library)[0]["sourceId"]):
        raise SystemExit("original example source changed")
    if list(original.rglob("*.agdai")) or list(library.rglob("*.agdai")):
        raise SystemExit("original example interface cache was created")
    (output / "exchanges.json").write_bytes(canonical_json_bytes(exchanges) + b"\n")
    summary = {"sourceId": leaf["snapshot"]["sourceId"], "resolutionId": leaf["resolution"]["resolutionId"],
        "compiler": leaf["resolution"]["agda"], "records": records, "catalogHit": hits[0],
        "projectMatches": own["result"]["totalMatches"], "historicalFreshness": historical["result"]["freshness"],
        "liveEditorIntegrated": False}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Research API pilot passed. The actual AgdaLab editor is not changed by this fixture.", flush=True)


if __name__ == "__main__":
    main()
