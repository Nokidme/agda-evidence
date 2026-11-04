#!/usr/bin/env python3
"""Finite native conformance, not a service, proof certificate or performance SLA.

Use the installed agda_evidence package; no checkout imports or interpreter
re-execution. Each interaction has the requested native timeout, while host
preflight/copy/validation time may exceed it. Gate checks use an explicit 180s
budget. The source facade alone gets 64 records / 128 MiB for full envelopes;
package defaults are unchanged. No downloads, retries or warning suppression.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

from agda_evidence.candidates import load_candidate_observation
from agda_evidence.catalog import create_catalog
from agda_evidence.core import (
    EvidenceError, build_declaration_index, build_snapshot, canonical_json_bytes,
    capture_bundle, load_verified_bundle, write_declaration_index,
)
from agda_evidence.goals import load_goal_observation
from agda_evidence.research import ResearchWorkspace
from agda_evidence.source_research import SourceResearchWorkspace
from agda_evidence.sources import load_source_observation

ROOT = Path(__file__).resolve().parents[1]
MAX_OUTPUT_BYTES = 4_194_304
GATE_TIMEOUT_SECONDS = 180
REQUIRED_CASES = (
    "compiler-version", "dependency-gate", "native-v1", "source-list",
    "source-context", "source-elaborated", "source-wrong-type",
    "source-missing-name", "source-no-import", "source-multiple-goals",
    "source-empty-goals", "source-warning-blocked", "source-fatal-load",
    "lexical-scopes", "catalog-not-mounted", "dirty-generation",
    "dependency-changed", "missing-bundle", "cross-session",
    "offline-verification", "source-integrity",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def recorded_inner_seconds(artifact: dict) -> float:
    """Elapsed recorded execution (includes inner prep), never compiler CPU time.

    Accept a native goal/candidate artifact or its complete source envelope.
    Missing, naive, non-finite or reversed timestamps are errors, not zeroes.
    """
    try:
        execution = artifact.get("observation", artifact)["execution"]
        start, finish = (datetime.fromisoformat(execution[key].replace("Z", "+00:00"))
                         for key in ("startedAt", "finishedAt"))
        require(start.utcoffset() is not None and finish.utcoffset() is not None,
                "execution timestamps must include time zones")
        seconds = (finish - start).total_seconds()
        require(math.isfinite(seconds) and seconds >= 0, "invalid execution interval")
        return seconds
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
        raise EvidenceError("invalid recorded execution timestamps") from error


def _preflight(agda_binary, expected_version, output, profile, dependency_root, timeout_seconds):
    require(profile in ("builtin", "stdlib-function"), "unsupported profile")
    require(isinstance(expected_version, str) and len(expected_version) <= 64 and
            re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,7}", expected_version) is not None,
            "expected_version must be a bounded exact numeric Agda version")
    require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 300,
            "timeout_seconds must be an integer from 1 to 300")
    require(isinstance(agda_binary, str) and 0 < len(agda_binary) <= 4096 and
            not any(ord(c) < 32 for c in agda_binary), "explicit executable required")
    require(isinstance(output, Path), "output must be a Path")
    require((profile == "builtin" and dependency_root is None) or
            (profile == "stdlib-function" and isinstance(dependency_root, Path)),
            "dependency_root is required for stdlib-function and forbidden for builtin")
    dependency = dependency_root.resolve() if dependency_root is not None else None
    if dependency is not None:
        require(not dependency_root.is_symlink() and dependency.is_dir() and
                (dependency / "src/Function/Base.agda").is_file(),
                "stdlib-function requires a regular source root with src/Function/Base.agda")
    destination = output.resolve()
    require(not output.is_symlink() and not destination.exists(), "output must be a new directory")
    for protected in (ROOT, dependency):
        if protected is not None:
            require(not destination.is_relative_to(protected) and
                    not output.absolute().is_relative_to(protected) and
                    not protected.is_relative_to(destination), "output overlaps protected sources")
    return agda_binary, destination, dependency


def run_conformance(*, agda_binary: str, expected_version: str, output: Path,
                    profile: str = "builtin", dependency_root: Path | None = None,
                    timeout_seconds: int = 20) -> dict:
    """Return a persisted report; config errors before creation raise EvidenceError.

    All required cases must actually pass. After creation, any failure retains
    exchanges, saved native envelopes and a failed summary with not-run cases.
    This process-local AGDA_DIR override is restored even on failure.
    """
    binary, output, supplied = _preflight(agda_binary, expected_version, output,
                                         profile, dependency_root, timeout_seconds)
    output.mkdir(parents=True)
    report = {"format": "agda-evidence/native-conformance-report-v1", "status": "failed",
              "profile": profile, "expectedVersion": expected_version, "actualVersion": None,
              "nativeTimeoutSeconds": timeout_seconds,
              "cases": [{"id": name, "name": name, "status": "not-run"} for name in REQUIRED_CASES],
              "timings": [], "records": {}, "bundles": {}, "originalSourcesUnchanged": False,
              "isolation": {"agdaDir": "registry", "explicitExecutable": binary,
                            "noLibraries": True, "ignoreInterfaces": True, "safe": True,
                            "maxOutputBytes": MAX_OUTPUT_BYTES, "gateTimeoutSeconds": GATE_TIMEOUT_SECONDS,
                            "sourceStore": {"maxRecords": 64, "maxStoredBytes": 134_217_728},
                            "composition": "one explicit source-copy dependency; not dependency closure",
                            "timingMeaning": "host monotonic elapsed; inner recorded execution includes preparation, not compiler CPU"}}
    exchanges, saved, call_timings = [], {}, {}
    current_case = None

    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(value) + b"\n")

    def measure(role, label, fn, *args, native_timeout=None, **kwargs):
        started = time.monotonic()
        timing = {"caseId": current_case, "role": role, "label": label}
        if native_timeout is not None:
            timing["nativeTimeoutSeconds"] = native_timeout
        try:
            return fn(*args, **kwargs)
        finally:
            timing["elapsedSeconds"] = time.monotonic() - started
            report["timings"].append(timing)

    @contextmanager
    def case(name):
        nonlocal current_case
        current_case = name
        item = next(item for item in report["cases"] if item["id"] == name)
        require(item["status"] == "not-run", "case executed more than once")
        started = time.monotonic()
        try:
            yield
            item["status"] = "passed"
        except Exception as error:
            item.update(status="failed", reason=str(error), error=type(error).__name__)
            raise
        finally:
            report["timings"].append({"caseId": name, "role": "case", "label": name,
                                      "elapsedSeconds": time.monotonic() - started})
            save(output / "summary.json", report)

    def call(host, op, *, revision=None, expected="ok", api=2, **params):
        request = {"requestId": f"conformance-{len(exchanges)+1}", "op": op,
                   "revision": revision, "args": params}
        if api == 2:
            request["apiVersion"] = 2
        work = expected == "ok" and op in {"goals.list", "goals.inspect", "candidate.check"}
        response = measure("host-call", f"v{api}:{op}", host.handle, request,
                           native_timeout=timeout_seconds if work else None)
        timing = report["timings"][-1]
        exchanges.append({"request": request, "response": response})
        save(output / "exchanges.json", exchanges)
        if response.get("recordId") and work:
            call_timings[response["recordId"]] = timing
        require(type(response.get("apiVersion")) is int and response["apiVersion"] == api and
                response["status"] == expected, f"unexpected v{api} {op} response: {response}")
        return response

    def archive(host, response, name, expected, *, api=2):
        fetched = call(host, "record.get", api=api, recordId=response["recordId"])
        value = fetched["result"]["artifact"]
        inner = value["observation"] if api == 2 else value
        kind = fetched["result"]["kind"]
        suffix = "source.json" if api == 2 else "candidate.json" if kind == "candidate" else "goal.json"
        filename = f"{'source' if api == 2 else 'native'}/{name}.{suffix}"
        measure("export", filename, save, output / filename, value)
        identity = value["sourceObservationId"] if api == 2 else value["observationId"]
        report["records"][f"{'source' if api == 2 else 'native'}/{name}"] = {
            "path": filename, "id": identity, "kind": kind, "nativeStatus": inner["result"]["status"]}
        saved[filename] = value
        # Attach inner duration only after the exact full received envelope is saved.
        call_timings[response["recordId"]]["innerExecutionSeconds"] = recorded_inner_seconds(value)
        require(fetched["result"]["freshness"] == "current", "fresh capture is not current")
        require(inner["result"]["status"] == expected,
                f"{filename}: expected native {expected}, got {inner['result']['status']}")
        require(response["result"]["sourceObservationId" if api == 2 else "observationId"] == identity,
                "API evidence identity differs from saved envelope")
        return value

    def fixture(root, module, body):
        path = root / f"{module}.agda"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{{-# OPTIONS --safe #-}}\nmodule {module} where\n"
                        "open import Agda.Builtin.Nat using (Nat; zero; suc)\n" + body,
                        encoding="utf-8")

    def snapshot(root):
        return measure("snapshot", root.name, build_snapshot, root)[0]

    def gate(root, bundle, module, scope, index=None):
        command = [binary, "--no-libraries", "--ignore-interfaces", "--safe", "-i", "src", f"src/{module}.agda"]
        measure("gate", scope, capture_bundle, root, bundle, command, agda_binary=binary,
                scope=scope, index_reference=index, timeout_seconds=GATE_TIMEOUT_SECONDS,
                max_output_bytes=MAX_OUTPUT_BYTES, native_timeout=GATE_TIMEOUT_SECONDS)
        manifest, components = measure("verification", bundle.name, load_verified_bundle, bundle)
        report["bundles"][bundle.name] = {"path": f"{bundle.name}/bundle.json", "id": manifest["bundleId"], "kind": "bundle",
                                         "nativeStatus": components["attestation.json"]["outcome"]["status"]}
        require(components["attestation.json"]["outcome"]["status"] == "passed", f"{scope}: native gate failed")
        return manifest, components

    try:
        registry = output / "registry"
        registry.mkdir()
        with patch.dict(os.environ, {"AGDA_DIR": str(registry)}):
            with case("compiler-version"):
                executable = shutil.which(binary)
                if executable is None:
                    save(output / "compiler-probe.json", {"available": False, "reason": "not-found", "requested": binary})
                require(executable is not None, "explicit native compiler is missing or not executable")
                binary = str(Path(executable).resolve())
                report["isolation"]["explicitExecutable"] = binary
                process = measure("compiler-probe", "explicit compiler --version", subprocess.run,
                                  [binary, "--version"], capture_output=True, text=True,
                                  check=False, timeout=timeout_seconds, native_timeout=timeout_seconds)
                version = {"available": process.returncode == 0, "exitCode": process.returncode,
                           "stdout": process.stdout.strip(), "stderr": process.stderr.strip()}
                save(output / "compiler-probe.json", {"requested": binary, "version": version})
                require(len(process.stdout.encode("utf-8")) + len(process.stderr.encode("utf-8")) <= MAX_OUTPUT_BYTES,
                        "version probe exceeded fixed output limit")
                match = re.fullmatch(r"Agda version ([0-9]+(?:\.[0-9]+){2,7})", version["stdout"])
                report["actualVersion"] = match.group(1) if match else None
                require(version["available"] is True and report["actualVersion"] == expected_version,
                        f"exact compiler version mismatch: expected {expected_version}, probe {version}")
            with case("dependency-gate"):
                original = snapshot(supplied) if supplied is not None else None
                dependency, client, catalog_source = (output / name for name in ("dependency", "client", "catalog-source"))
                if supplied is None:
                    fixture(dependency / "src", "Mini", "identity : Nat → Nat\nidentity n = n\n")
                else:
                    measure("copy", "private dependency", shutil.copytree, supplied, dependency,
                            ignore=shutil.ignore_patterns(".git", "_build", "*.agdai"))
                module, declaration, short = (("Mini", "Mini.identity", "identity") if profile == "builtin"
                                              else ("Function/Base", "Function.Base.id", "id"))
                namespace = module.replace("/", ".")
                bundle, active = output / "dependency.evidence", output / "active-dependency.evidence"
                manifest, components = gate(dependency, bundle, module,
                    f"Explicit safe {namespace} module check; not a whole-library gate")
                require("index-ref.json" not in components, "dependency gate must not carry a catalog index")
                measure("copy", "active dependency bundle", shutil.copytree, bundle, active)
                fixture(catalog_source / "src", "Example", "identity : Nat → Nat\nidentity n = n\n")
                index = output / "catalog.index.json"
                write_declaration_index(index, build_declaration_index(catalog_source))
                gate(catalog_source, output / "catalog.evidence", "Example", "Independent safe Example catalog check", index)
                create_catalog(output / "catalog.json", [("example", output / "catalog.evidence")])
                fixture(client, "Main", f"open import {namespace} using ({short})\nidentityGoal : Nat → Nat\nidentityGoal n = {{! !}}\n")
                fixture(client, "NoImport", "identityGoal : Nat → Nat\nidentityGoal n = {! !}\n")
                fixture(client, "Complete", "identityGoal : Nat → Nat\nidentityGoal n = n\n")
                fixture(client, "Multiple", "first : Nat → Nat\nfirst n₂ = {! !}\nsecond : Nat → Nat\nsecond n₂ = {! !}\n")
                fixture(client, "Warning", "duplicate : Nat → Nat\nduplicate zero = zero\nduplicate zero = zero\nduplicate (suc n) = n\nidentityGoal : Nat → Nat\nidentityGoal n = {! !}\n")
                fixture(client, "Fatal", "fatal : Set\nfatal = zero\n")
                bare = output / "plain-client"
                fixture(bare, "Plain", "identityGoal : Nat → Nat\nidentityGoal n = {! !}\n")
                originals = {root: snapshot(root) for root in (dependency, client, catalog_source, bare)}
                if original is not None:
                    require(original["sourceId"] == originals[dependency]["sourceId"], "private dependency copy is not exact")
            options = dict(agda_binary=binary, safe=True, timeout_seconds=timeout_seconds, max_output_bytes=MAX_OUTPUT_BYTES)
            with case("native-v1"):
                plain = measure("constructor", "ResearchWorkspace", ResearchWorkspace, bare, {"main": "Plain.agda"}, **options)
                rev1 = call(plain, "workspace.status", api=1)["currentRevision"]
                listing1 = call(plain, "goals.list", api=1, revision=rev1, documentId="main")
                value1 = archive(plain, listing1, "listing", "listed", api=1)
                require(len(value1["result"]["goals"]) == 1, "v1 must list exactly one goal")
                goal1 = value1["result"]["goals"][0]["id"]
                inspected1 = call(plain, "goals.inspect", api=1, revision=rev1, listingId=listing1["recordId"], goalId=goal1)
                context1 = archive(plain, inspected1, "context", "inspected", api=1)
                require(any(e["originalName"] == "n" and e["binding"] == "Nat" for e in context1["result"]["selected"]["entries"]), "v1 local context absent")
                accepted1 = call(plain, "candidate.check", api=1, revision=rev1, listingId=listing1["recordId"], goalId=goal1, expression="n")
                archive(plain, accepted1, "elaborated", "elaborated", api=1)
            configuration = dict(**options, dependency_root=dependency, dependency_bundle=active,
                                 dependency_includes=["src"], catalog=output / "catalog.json",
                                 max_records=64, max_stored_bytes=134_217_728)
            documents = {name.lower(): f"{name}.agda" for name in ("Main", "NoImport", "Complete", "Multiple", "Warning", "Fatal")}
            with case("source-list"):
                host = measure("constructor", "SourceResearchWorkspace", SourceResearchWorkspace, client, documents, **configuration)
                initial = call(host, "workspace.status")
                revision = initial["currentRevision"]
                require(initial["result"]["dependencyMatchesPin"] is True, "initial dependency pins do not match")
                report["initialWorkspace"] = initial["workspace"]
                report["dependencyPins"] = initial["result"]["dependencyPins"]
                listed = call(host, "goals.list", revision=revision, documentId="main")
                listing = archive(host, listed, "listing", "listed")
                require(len(listing["observation"]["result"]["goals"]) == 1, "expected exactly one source goal")
                require(listing["clientSnapshot"]["sourceId"] == originals[client]["sourceId"] and
                        listing["dependency"]["evidence"]["components"]["snapshot.json"]["sourceId"] == originals[dependency]["sourceId"], "envelope lost original source identities")
                goal = listing["observation"]["result"]["goals"][0]["id"]
                selection = dict(listingId=listed["recordId"], goalId=goal)
            with case("source-context"):
                context = archive(host, call(host, "goals.inspect", revision=revision, **selection), "context", "inspected")
                require(any(e["originalName"] == "n" and e["binding"] == "Nat" for e in context["observation"]["result"]["selected"]["entries"]), "local n : Nat is absent")
            with case("source-elaborated"):
                good = call(host, "candidate.check", revision=revision, expression=f"{short} n", **selection)
                accepted = archive(host, good, "elaborated", "elaborated")
                outcome = accepted["observation"]["result"]
                require(outcome["assurance"] == "contextual-elaboration-only" and outcome["postflightUnchanged"] is True,
                        "candidate assurance or postflight unchanged check failed")
            for name, expression in (("source-wrong-type", "Nat"), ("source-missing-name", "unavailableCandidate")):
                with case(name):
                    archive(host, call(host, "candidate.check", revision=revision, expression=expression, **selection), name, "query-error")
            with case("source-no-import"):
                unimported = call(host, "goals.list", revision=revision, documentId="noimport")
                unimported_value = archive(host, unimported, "no-import-listing", "listed")
                unimported_goal = unimported_value["observation"]["result"]["goals"][0]["id"]
                archive(host, call(host, "candidate.check", revision=revision, listingId=unimported["recordId"],
                                  goalId=unimported_goal, expression=f"{declaration} n"), "no-import", "query-error")
            for name, document, count in (("source-multiple-goals", "multiple", 2), ("source-empty-goals", "complete", 0)):
                with case(name):
                    value = archive(host, call(host, "goals.list", revision=revision, documentId=document), document, "listed")
                    require(len(value["observation"]["result"]["goals"]) == count, f"{document}: wrong goal count")
            for name, document, status in (("source-warning-blocked", "warning", "load-blocked"), ("source-fatal-load", "fatal", "load-error")):
                with case(name):
                    response = call(host, "goals.list", revision=revision, documentId=document)
                    value = archive(host, response, document, status)
                    messages = value["observation"]["transcript"][1]["responses"]
                    infos = [m["info"] for m in messages if m.get("kind") == "DisplayInfo" and isinstance(m.get("info"), dict)]
                    if document == "warning":
                        require(any(i.get("kind") == "AllGoalsWarnings" and len(i.get("warnings", [])) > 0 for i in infos), "no actual warning diagnostic")
                        require(any("Unreachable clause" in w.get("message", "") for i in infos for w in i.get("warnings", [])), "missing unreachable-clause diagnostic")
                    else:
                        require(any(i.get("kind") == "Error" for i in infos), "no actual fatal Error record")
                    blocked = call(host, "goals.inspect", revision=revision, expected="error", listingId=response["recordId"], goalId=0)
                    require(blocked["error"]["code"] == "invalid-request", "diagnostic-bearing listing allowed selection")
            with case("lexical-scopes"):
                queries = (("project", "Main.identityGoal"), ("dependency", declaration), ("catalog", "Example.identity"))
                for scope, exact in queries:
                    extra = {"libraries": ["example"]} if scope == "catalog" else {}
                    found = call(host, "library.search", revision=revision, scope=scope, exact=exact, **extra, **selection)
                    hits = found["result"]["entries"]
                    require(len(hits) == 1 and hits[0]["origin"] == scope and hits[0]["evidence"] and
                            hits[0]["scopeStatus"] == "not-established" and hits[0]["candidateUsability"] == "not-tested", f"{scope} lexical provenance overstated")
                    all_hits = call(host, "library.search", revision=revision, scope="all", exact=exact, libraries=["example"], **selection)
                    require(all_hits["result"]["entries"] == hits, f"all-scope changed {scope} lexical provenance")
                filtered = call(host, "library.search", revision=revision, scope="catalog", exact=declaration, libraries=["example"], **selection)
                require(filtered["result"]["entries"] == [], "catalog-only filter leaked dependency declarations")
                rejected_filter = call(host, "library.search", revision=revision, expected="error", scope="dependency", exact=declaration, libraries=["example"], **selection)
                require(rejected_filter["error"]["code"] == "invalid-request", "catalog filter allowed on dependency-only search")
            with case("catalog-not-mounted"):
                archive(host, call(host, "candidate.check", revision=revision, expression="Example.identity n", **selection), "catalog-not-mounted", "query-error")
            with case("dirty-generation"):
                old_revision = revision
                measure("notification", "dirty", host.notify_buffers, dirty=True)
                call(host, "goals.inspect", revision=revision, expected="stale", **selection)
                measure("notification", "clean unchanged bytes", host.notify_buffers, dirty=False)
                revision = call(host, "workspace.status")["currentRevision"]
                call(host, "goals.inspect", revision=revision, expected="stale", **selection)
                history = call(host, "record.get", recordId=good["recordId"])
                require(history["result"]["freshness"] == "stale" and history["result"]["artifact"] == accepted, "dirty generation promoted or changed history")
            with case("dependency-changed"):
                marker = dependency / "unrelated-conformance-edit.txt"
                require(not marker.exists(), "private edit marker already exists")
                try:
                    marker.write_text("private unrelated dependency edit\n", encoding="utf-8")
                    measure("notification", "dependency edit", host.notify_buffers, dirty=False)
                    changed = call(host, "workspace.status")
                    revision = changed["currentRevision"]
                    require(changed["result"]["dependencyMatchesPin"] is False and changed["workspace"]["dependencySourceId"] != initial["workspace"]["dependencySourceId"], "dependency mismatch was not observable")
                    refused = call(host, "goals.list", revision=revision, expected="error", documentId="main")
                    require(refused["error"]["code"] == "dependency-changed", "changed dependency silently repinned")
                    history = call(host, "record.get", recordId=good["recordId"])
                    require(history["result"]["freshness"] == "stale" and history["result"]["dependencyMatchesPin"] is False and
                            canonical_json_bytes(history["result"]["artifact"]) == canonical_json_bytes(accepted), "changed dependency lost exact stale history")
                    call(host, "record.get", revision=old_revision, expected="stale", recordId=good["recordId"])
                finally:
                    marker.unlink(missing_ok=True)
                    measure("notification", "dependency restored", host.notify_buffers, dirty=False)
                restored = call(host, "workspace.status")
                revision = restored["currentRevision"]
                require(restored["result"]["dependencyMatchesPin"] is True, "restored source pins do not match")
            with case("missing-bundle"):
                absent = output / "temporarily-absent.evidence"
                active.rename(absent)
                try:
                    unknown = call(host, "record.get", recordId=good["recordId"])
                    require(unknown["result"]["freshness"] == "unknown" and unknown["result"]["dependencyMatchesPin"] is None and unknown["workspace"] is None,
                            "missing required evidence guessed cached freshness")
                    refused = call(host, "record.get", revision=revision, expected="error", recordId=good["recordId"])
                    require(refused["error"]["code"] == "freshness-unavailable", "pinned read admitted missing evidence")
                finally:
                    absent.rename(active)
                revision = call(host, "workspace.status")["currentRevision"]
            with case("cross-session"):
                rebound = measure("constructor", "explicit new source session", SourceResearchWorkspace, client, documents, **configuration)
                rebound_state = call(rebound, "workspace.status")
                require(rebound_state["result"]["dependencyMatchesPin"] is True, "explicit new session rejected current pins")
                foreign = call(rebound, "record.get", expected="error", recordId=good["recordId"])
                require(foreign["error"]["code"] == "record-unavailable", "new session accepted old opaque handle")
                foreign_listing = call(rebound, "goals.inspect", revision=rebound_state["currentRevision"], expected="error", **selection)
                require(foreign_listing["error"]["code"] == "record-unavailable", "new session accepted old selection")
            with case("offline-verification"):
                def blocked_process(*args, **kwargs):
                    raise EvidenceError("offline verification attempted a subprocess")
                with patch.object(subprocess, "run", blocked_process), patch.object(subprocess, "Popen", blocked_process):
                    for filename, original_value in saved.items():
                        loader = load_source_observation if filename.endswith("source.json") else load_candidate_observation if filename.endswith("candidate.json") else load_goal_observation
                        checked = measure("offline-verification", filename, loader, output / filename)
                        require(canonical_json_bytes(checked) == canonical_json_bytes(original_value), "offline validation changed saved payload")
                    for name in ("dependency.evidence", "active-dependency.evidence", "catalog.evidence"):
                        measure("offline-verification", name, load_verified_bundle, output / name)
            with case("source-integrity"):
                if supplied is not None:
                    require(snapshot(supplied)["sourceId"] == original["sourceId"] and not list(supplied.rglob("*.agdai")), "original dependency changed or contains interfaces")
                for root, original_snapshot in originals.items():
                    require(snapshot(root)["sourceId"] == original_snapshot["sourceId"] and not list(root.rglob("*.agdai")), f"{root.name} source changed or contains interfaces")
                report["originalSourcesUnchanged"] = True
        require(all(item["status"] == "passed" for item in report["cases"]), "required cases did not all pass")
        report["status"] = "passed"
    except Exception as error:
        report.update(reason=str(error), error=type(error).__name__, failedCase=current_case)
    finally:
        save(output / "exchanges.json", exchanges)
        save(output / "summary.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agda-bin", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("builtin", "stdlib-function"), default="builtin")
    parser.add_argument("--dependency-root", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    args = parser.parse_args()
    try:
        report = run_conformance(agda_binary=args.agda_bin, expected_version=args.expected_version,
                                 output=args.output, profile=args.profile, dependency_root=args.dependency_root,
                                 timeout_seconds=args.timeout_seconds)
    except (EvidenceError, OSError) as error:
        print(f"native conformance configuration failed: {error}", file=sys.stderr)
        return 1
    print(f"NATIVE CONFORMANCE {report['status'].upper()}: {args.output / 'summary.json'}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
