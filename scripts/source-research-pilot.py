#!/usr/bin/env python3
"""Exercise the explicit source research API; not an editor or running service."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from agda_evidence.catalog import create_catalog
from agda_evidence.core import (
    build_declaration_index, build_snapshot, canonical_json_bytes, capture_bundle,
    load_verified_bundle, write_declaration_index,
)
from agda_evidence.source_research import SourceResearchWorkspace
from agda_evidence.sources import load_source_observation, source_summary

ROOT = Path(__file__).resolve().parents[1]
AUTO = object()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--agda-bin", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output, supplied_dependency = args.output.resolve(), args.dependency_root.resolve()
    require(not output.exists() and not args.output.is_symlink()
            and not output.is_relative_to(ROOT) and not output.is_relative_to(supplied_dependency),
            "output must be a new external directory outside supplied sources")
    executable = shutil.which(args.agda_bin)
    require(executable is not None, "native compiler is not available")
    binary = str(Path(executable).resolve())
    example, catalog_source = ROOT / "examples/source-query", ROOT / "examples/client-query/library"
    before = [build_snapshot(p)[0]["sourceId"] for p in (supplied_dependency, example, catalog_source)]
    output.mkdir(parents=True)
    client, dependency = output / "client", output / "dependency-source"
    shutil.copytree(example, client)
    shutil.copytree(supplied_dependency, dependency,
                    ignore=shutil.ignore_patterns(".git", "*.agdai", "_build"))
    bundle, active = output / "dependency.evidence", output / "active-dependency.evidence"
    gate = [binary, "--no-libraries", "--ignore-interfaces", "--safe", "-i", "src",
            "src/Relation/Binary/PropositionalEquality/Core.agda"]
    capture_bundle(dependency, bundle, gate, agda_binary=binary,
                   scope="Explicit safe equality Core dependency-module check; not whole stdlib gate",
                   timeout_seconds=180, max_output_bytes=1_048_576)
    manifest, components = load_verified_bundle(bundle)
    require(components["attestation.json"]["outcome"]["status"] == "passed", "native dependency gate failed")
    shutil.copytree(bundle, active)
    # The independent catalog library is discoverable, but not mounted by this profile.
    index_path, catalog_bundle = output / "catalog.index.json", output / "catalog.evidence"
    write_declaration_index(index_path, build_declaration_index(catalog_source))
    capture_bundle(catalog_source, catalog_bundle,
                   [binary, "--no-libraries", "--ignore-interfaces", "--safe", "-i", "src", "src/Example.agda"],
                   agda_binary=binary, scope="safe independent Example catalog module check", index_reference=index_path)
    create_catalog(output / "catalog.json", [("example", catalog_bundle)])
    configuration = dict(dependency_root=dependency, dependency_bundle=active, dependency_includes=["src"],
                         agda_binary=binary, safe=True, catalog=output / "catalog.json", timeout_seconds=120,
                         max_records=32, max_stored_bytes=67_108_864)
    host = SourceResearchWorkspace(client, {"main": "Main.agda"}, **configuration)
    exchanges, records = [], {}
    revision = None

    def call(op: str, *, expected: str = "ok", request_revision=AUTO, **params) -> dict:
        requested = (None if op in {"workspace.status", "record.get"} else revision) if request_revision is AUTO else request_revision
        request = {"apiVersion": 2, "requestId": f"source-ui-{len(exchanges)+1}",
                   "op": op, "revision": requested, "args": params}
        response = host.handle(request)
        exchanges.append({"request": request, "response": response})
        (output / "exchanges.json").write_bytes(canonical_json_bytes(exchanges) + b"\n")
        require(response["apiVersion"] == 2 and response["status"] == expected,
                f"unexpected {op} status: {response}")
        print(op, response["status"], flush=True)
        return response

    def archive(response: dict, name: str, expected: str) -> dict:
        fetched = call("record.get", recordId=response["recordId"])
        require(fetched["result"]["freshness"] == "current", "fresh native record was not current")
        path = output / f"{name}.source.json"
        path.write_bytes(canonical_json_bytes(fetched["result"]["artifact"]) + b"\n")
        value = load_source_observation(path)
        require(value["observation"]["result"]["status"] == expected, f"unexpected {name} native outcome")
        require(response["result"]["sourceObservationId"] == value["sourceObservationId"], "API lost outer evidence identity")
        records[name] = source_summary(value)
        return value

    initial = call("workspace.status")
    require(initial["result"]["dependencyMatchesPin"] is True, "initial dependency must match frozen pins")
    revision = initial["currentRevision"]
    listed = call("goals.list", documentId="main")
    listing = archive(listed, "listing", "listed")
    points = listing["observation"]["result"]["goals"]
    require(len(points) == 1, "expected exactly one source-dependent goal")
    goal = points[0]["id"]
    context = call("goals.inspect", listingId=listed["recordId"], goalId=goal)
    archive(context, "context", "inspected")
    own = call("library.search", listingId=listed["recordId"], goalId=goal,
               prefix="Main", scope="project", limit=2)
    require(own["result"]["entries"], "project lexical discovery returned nothing")
    discovered = call("library.search", listingId=listed["recordId"], goalId=goal,
                      exact="Relation.Binary.PropositionalEquality.Core.sym", scope="dependency")
    dependency_hits = discovered["result"]["entries"]
    require(len(dependency_hits) == 1 and dependency_hits[0]["origin"] == "dependency"
            and dependency_hits[0]["scopeStatus"] == "not-established"
            and dependency_hits[0]["candidateUsability"] == "not-tested", "dependency lexical scope/usability was overstated")
    catalog = call("library.search", listingId=listed["recordId"], goalId=goal,
                   exact="Example.identity", scope="catalog", libraries=["example"])
    require(len(catalog["result"]["entries"]) == 1, "independent catalog example not discoverable")
    good = call("candidate.check", listingId=listed["recordId"], goalId=goal, expression="sym p")
    accepted = archive(good, "symmetry", "elaborated")
    require(accepted["observation"]["result"]["assurance"] == "contextual-elaboration-only"
            and accepted["observation"]["result"]["postflightUnchanged"] is True, "native assurance changed")
    bad = call("candidate.check", listingId=listed["recordId"], goalId=goal, expression="refl")
    archive(bad, "wrong-type", "query-error")
    unmounted = call("candidate.check", listingId=listed["recordId"], goalId=goal, expression="Example.identity n")
    archive(unmounted, "catalog-not-mounted", "query-error")
    old_revision = revision
    host.notify_buffers(dirty=True)
    call("goals.inspect", expected="stale", listingId=listed["recordId"], goalId=goal)
    host.notify_buffers(dirty=False)
    revision = call("workspace.status")["currentRevision"]
    call("goals.inspect", expected="stale", listingId=listed["recordId"], goalId=goal)
    dirty_history = call("record.get", recordId=good["recordId"])
    require(dirty_history["result"]["freshness"] == "stale", "dirty/edit-and-revert generation promoted old history")
    marker = dependency / "unrelated-host-dependency-edit.txt"
    marker.write_text("private pilot dependency edit\n", encoding="utf-8")
    host.notify_buffers(dirty=False)
    changed = call("workspace.status")
    revision = changed["currentRevision"]
    require(changed["result"]["dependencyMatchesPin"] is False
            and changed["workspace"]["dependencySourceId"] != initial["workspace"]["dependencySourceId"],
            "observable dependency edit must be a known pin mismatch")
    refused = call("goals.list", expected="error", documentId="main")
    require(refused["error"]["code"] == "dependency-changed", "refresh must not repin a changed dependency")
    changed_history = call("record.get", recordId=good["recordId"])
    require(changed_history["result"]["freshness"] == "stale"
            and changed_history["result"]["dependencyMatchesPin"] is False
            and canonical_json_bytes(changed_history["result"]["artifact"]) == canonical_json_bytes(accepted),
            "changed dependency must retain exact stale history")
    call("record.get", expected="stale", request_revision=old_revision, recordId=good["recordId"])
    marker.unlink()
    host.notify_buffers(dirty=False)
    restored = call("workspace.status")
    revision = restored["currentRevision"]
    require(restored["result"]["dependencyMatchesPin"] is True, "restored explicit source pins must be observable")
    # Missing required evidence is unknown, not a guess based on cached pins.
    absent_path = output / "temporarily-absent.evidence"
    active.rename(absent_path)
    unknown = call("record.get", recordId=good["recordId"])
    require(unknown["result"]["freshness"] == "unknown" and unknown["workspace"] is None,
            "unobservable required input must report unknown history")
    pinned_unknown = call("record.get", expected="error", request_revision=revision, recordId=good["recordId"])
    require(pinned_unknown["error"]["code"] == "freshness-unavailable", "pinned read cannot succeed from cached state")
    absent_path.rename(active)
    revision = call("workspace.status")["currentRevision"]
    # An independently recaptured, otherwise identical bundle changes exact provenance.
    replacement = output / "replacement.evidence"
    capture_bundle(dependency, replacement, gate, agda_binary=binary,
                   scope="Explicit safe equality Core dependency-module check; not whole stdlib gate",
                   timeout_seconds=180, max_output_bytes=1_048_576)
    replacement_manifest, replacement_components = load_verified_bundle(replacement)
    require(replacement_manifest["bundleId"] != manifest["bundleId"], "recapture fixture needs distinct bundle identity")
    require(replacement_components["snapshot.json"]["sourceId"] == components["snapshot.json"]["sourceId"]
            and replacement_components["resolution.json"]["resolutionId"] == components["resolution.json"]["resolutionId"],
            "recapture test must preserve source/environment subjects")
    shutil.rmtree(active)
    shutil.copytree(replacement, active)
    host.notify_buffers(dirty=False)
    recaptured = call("workspace.status")
    revision = recaptured["currentRevision"]
    require(recaptured["result"]["dependencyMatchesPin"] is False
            and recaptured["workspace"]["dependencyBundleId"] != initial["workspace"]["dependencyBundleId"],
            "same-subject recapture must not automatically refresh frozen bundle provenance")
    refused_again = call("goals.list", expected="error", documentId="main")
    require(refused_again["error"]["code"] == "dependency-changed", "recaptured bundle was silently admitted")
    rebound = SourceResearchWorkspace(client, {"main": "Main.agda"}, **configuration)
    rebound_request = {"apiVersion": 2, "requestId": "explicit-new-host-binding",
                       "op": "workspace.status", "revision": None, "args": {}}
    rebound_state = rebound.handle(rebound_request)
    exchanges.append({"request": rebound_request, "response": rebound_state})
    require(rebound_state["status"] == "ok" and rebound_state["result"]["dependencyMatchesPin"] is True,
            "explicit new host binding did not admit separately captured provenance")
    foreign_request = {"apiVersion": 2, "requestId": "cross-session-record",
                       "op": "record.get", "revision": None, "args": {"recordId": good["recordId"]}}
    foreign = rebound.handle(foreign_request)
    exchanges.append({"request": foreign_request, "response": foreign})
    require(foreign["status"] == "error" and foreign["error"]["code"] == "record-unavailable",
            "new session accepted an old opaque evidence handle")
    require(before == [build_snapshot(p)[0]["sourceId"] for p in (supplied_dependency, example, catalog_source)],
            "original supplied/example/catalog source changed")
    require(build_snapshot(client)[0]["sourceId"] == before[1]
            and build_snapshot(dependency)[0]["sourceId"] == before[0], "private source bytes were not restored unchanged")
    summary = {
        "format": "agda-evidence/source-research-pilot-summary-v2", "initialWorkspace": initial["workspace"],
        "dependencyPins": initial["result"]["dependencyPins"], "records": records,
        "dependencyHit": dependency_hits[0], "catalogHit": catalog["result"]["entries"][0],
        "dependencyEditHistory": changed_history["result"]["freshness"],
        "missingBundleHistory": unknown["result"]["freshness"], "sameSubjectRecaptureRefused": True,
        "explicitRebindAccepted": True, "crossSessionRejected": True,
        "originalSourcesUnchanged": True, "liveEditorIntegrated": False,
    }
    (output / "exchanges.json").write_bytes(canonical_json_bytes(exchanges) + b"\n")
    (output / "summary.json").write_bytes(canonical_json_bytes(summary) + b"\n")
    print("SOURCE RESEARCH API PILOT PASSED: native evidence, lexical provenance, stale/unknown history; no editor deployment", flush=True)


if __name__ == "__main__":
    main()
