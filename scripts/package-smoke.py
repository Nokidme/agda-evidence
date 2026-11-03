#!/usr/bin/env python3
"""Smoke-test an installed wheel/sdist, never the checkout's src directory.

Run with the Python interpreter into which the artifact was installed, from any
working directory (preferably outside the checkout)::

    /path/to/venv/bin/python /path/to/agda-evidence/scripts/package-smoke.py
    /path/to/venv/bin/python /path/to/agda-evidence/scripts/package-smoke.py \
        --agda-bin /usr/bin/agda

Only the standard library is used. The default workflow does not require Agda:
on POSIX a deliberately non-interactive fake supplies version/app-dir probes;
on Windows an explicitly unavailable executable records no compiler evidence.
Two explicit Python commands attest only their own fixture checks. The
optional native workflow inspects an unfinished --safe module and checks `n`
without filling its hole; elaboration is not proof completion. All generated
files and CLI working directories are temporary and outside the checkout.
"""

from __future__ import annotations

import argparse
import importlib
from importlib import metadata, resources
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit

# Resolve once, before any chdir: neither subprocess cwd nor invocation location
# is allowed to change the identity of this script or its exclusion boundary.
SCRIPT_PATH = Path(__file__).resolve()
CHECKOUT = SCRIPT_PATH.parent.parent
SCHEMA_NAMES = frozenset({
    "candidate-observation-v1.schema.json",
    "client-observation-v1.schema.json",
    "declaration-index-v1.schema.json",
    "evidence-aggregate-v1.schema.json",
    "evidence-bundle-v1.schema.json",
    "goal-observation-v1.schema.json",
    "local-catalog-v1.schema.json",
    "research-request-v1.schema.json",
    "research-response-v1.schema.json",
    "source-observation-v1.schema.json",
    "source-research-request-v2.schema.json",
    "source-research-response-v2.schema.json",
    "type-observation-v1.schema.json",
})
PUBLIC_MODULES = ("checker", "client", "goals", "candidates", "research", "catalog", "sources", "source_research")


class SmokeFailure(Exception):
    """A packaging or workflow assertion failed."""


def require(condition: Any, message: str) -> None:
    # Unlike assert, these checks remain enabled with Python -O.
    if not condition:
        raise SmokeFailure(message)


def status(label: str, detail: str) -> None:
    print(f"{label}: {detail}", flush=True)


def digest(value: Any, label: str) -> None:
    require(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value),
            f"{label}: expected a complete sha256 identifier, got {value!r}")


def parse_json(text: str, label: str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise SmokeFailure(f"{label}: non-JSON numeric constant {value}")

    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, UnicodeError) as error:
        raise SmokeFailure(f"{label}: invalid JSON: {error}") from error


def read_object(path: Path) -> dict[str, Any]:
    value = parse_json(path.read_text(encoding="utf-8"), str(path))
    require(isinstance(value, dict), f"{path}: expected a JSON object")
    return value


def objects(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def check_reference(documents: dict[str, Any], origin: str, reference: Any) -> None:
    require(isinstance(reference, str), f"{origin}: $ref must be a string")
    parts = urlsplit(reference)
    require(not parts.scheme and not parts.netloc and not parts.query,
            f"{origin}: $ref is not a local resource reference: {reference!r}")
    target_name = unquote(parts.path) or origin
    require(target_name in documents,
            f"{origin}: missing local $ref target {target_name!r} ({reference!r})")
    target = documents[target_name]
    fragment = unquote(parts.fragment)
    if not fragment:
        return
    if not fragment.startswith("/"):
        anchors = [node for node in objects(target)
                   if node.get("$anchor") == fragment or node.get("$dynamicAnchor") == fragment
                   or node.get("$id") == f"#{fragment}"]
        require(len(anchors) == 1,
                f"{origin}: unresolved/ambiguous $ref anchor {reference!r}")
        return
    for raw_token in fragment[1:].split("/"):
        require(re.search(r"~(?![01])", raw_token) is None,
                f"{origin}: invalid JSON Pointer escape in {reference!r}")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(target, dict):
            require(token in target, f"{origin}: missing $ref fragment {reference!r}")
            target = target[token]
        elif isinstance(target, list):
            require(re.fullmatch(r"0|[1-9][0-9]*", token) is not None,
                    f"{origin}: invalid $ref array index {reference!r}")
            index = int(token)
            require(index < len(target), f"{origin}: missing $ref array item {reference!r}")
            target = target[index]
        else:
            raise SmokeFailure(f"{origin}: $ref traverses a scalar: {reference!r}")


def inspect_installation() -> tuple[str, int]:
    package = importlib.import_module("agda_evidence")
    installed_version = metadata.version("agda-evidence")
    require(installed_version == package.__version__,
            f"metadata version {installed_version!r} != module version {package.__version__!r}")
    require(not Path(package.__file__).resolve().is_relative_to(CHECKOUT),
            f"package resolves into the checkout ({package.__file__}); install a non-editable artifact")
    for name in PUBLIC_MODULES:
        module = importlib.import_module(f"agda_evidence.{name}")
        require(not Path(module.__file__).resolve().is_relative_to(CHECKOUT),
                f"public module {name} resolves into the checkout")
    status("imports", ", ".join(PUBLIC_MODULES) + " passed (installed package)")

    schema_root = resources.files("agda_evidence.schemas")
    available = {entry.name for entry in schema_root.iterdir()
                 if entry.is_file() and entry.name.endswith(".schema.json")}
    require(available == SCHEMA_NAMES,
            f"installed schema resources differ: missing={sorted(SCHEMA_NAMES - available)}, "
            f"unexpected={sorted(available - SCHEMA_NAMES)}")
    documents = {}
    for name in sorted(SCHEMA_NAMES):
        value = parse_json(schema_root.joinpath(name).read_text(encoding="utf-8"), name)
        require(isinstance(value, dict), f"{name}: schema must be a JSON object")
        documents[name] = value
    ref_count = 0
    for name, document in documents.items():
        for node in objects(document):
            if "$ref" in node:
                check_reference(documents, name, node["$ref"])
                ref_count += 1
    status("resources", f"{len(documents)} schemas parsed; {ref_count} local $refs resolved offline")
    return installed_version, len(documents)


class CLI:
    def __init__(self, cwd: Path, environment: dict[str, str]) -> None:
        self.cwd = cwd
        self.environment = environment

    def run(self, *arguments: Any) -> str:
        command = [sys.executable, "-I", "-m", "agda_evidence", *map(str, arguments)]
        try:
            process = subprocess.run(command, cwd=self.cwd, env=self.environment,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8", errors="replace",
                                     timeout=180, check=False)
        except subprocess.TimeoutExpired as error:
            raise SmokeFailure(f"CLI timed out: {command!r}") from error
        require(process.returncode == 0,
                f"CLI exited {process.returncode}: {command!r}\n"
                f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}")
        return process.stdout

    def json(self, *arguments: Any) -> dict[str, Any]:
        value = parse_json(self.run(*arguments), "CLI " + " ".join(map(str, arguments)))
        require(isinstance(value, dict), f"CLI {arguments!r}: expected a JSON object")
        return value


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def fixture_workflows(cli: CLI, root: Path, app_dir: Path) -> None:
    fake = root / "deliberately-unavailable-agda-package-smoke"
    # Executable Python shebangs are POSIX-only. A path containing spaces also
    # cannot be represented safely by a conventional shebang. In either case,
    # use a nonexistent *absolute* path: never accidentally find a real Agda.
    probe_fixture = os.name == "posix" and not any(char.isspace() for char in sys.executable)
    if probe_fixture:
        fake = root / "fake-agda"
        fake.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            "if sys.argv[1:] == ['--version']:\n"
            "    print('Agda version package-smoke-fixture')\n"
            "elif sys.argv[1:] == ['--print-agda-app-dir']:\n"
            f"    print({str(app_dir)!r})\n"
            "else:\n"
            "    print('fake Agda supports probes only; no interaction', file=sys.stderr)\n"
            "    sys.exit(97)\n", encoding="utf-8")
        fake.chmod(0o700)
    status("fixture compiler", "probe-only fake (not Agda)" if probe_fixture else
           "explicitly unavailable; no Agda evidence claimed")
    project = root / "project"
    project.mkdir()
    (project / "Main.agda").write_text(
        "module Main where\nopen import Agda.Builtin.Nat\n"
        "identity : Nat → Nat\nidentity n = n\n", encoding="utf-8")
    (project / "smoke.agda-lib").write_text("name: package-smoke\ninclude: .\n", encoding="utf-8")
    (project / "check.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "assert 'identity n = n' in Path('Main.agda').read_text(encoding='utf-8')\n"
        "assert sys.argv[1] in ('first', 'second')\n"
        "print('package-smoke lane ' + sys.argv[1])\n", encoding="utf-8")
    before = tree_bytes(project)
    index_path = root / "index.json"
    built = cli.json("index", "build", "--project-root", project, "--output", index_path)
    digest(built["indexId"], "indexId")
    digest(built["sourceId"], "index sourceId")
    require(built["entryCount"] >= 2, f"index lacks module/signature entries: {built!r}")
    require(read_object(index_path)["indexId"] == built["indexId"], "index build report differs from file")
    status("index build", f"passed; {built['entryCount']} lexical entries")

    captures = {}
    bundles = {}
    for lane in ("first", "second"):
        bundle = root / f"bundle-{lane}"
        command = [sys.executable, "-I", "check.py", lane]
        scope = f"package-smoke explicit fixture lane {lane} (not an Agda proof check)"
        captured = cli.json("capture", "--project-root", project, "--output", bundle,
                            "--agda-bin", fake, "--index-reference", index_path,
                            "--scope", scope, "--timeout-seconds", 15, "--", *command)
        for field in ("bundleId", "sourceId", "resolutionId", "attestationId"):
            digest(captured[field], f"{lane} {field}")
        require(captured["sourceId"] == built["sourceId"], f"{lane}: capture changed indexed source")
        require(captured["outcome"]["status"] == "passed"
                and captured["outcome"]["exitCode"] == 0
                and captured["outcome"]["executionError"] is None,
                f"{lane}: explicit check was not successful: {captured!r}")
        attestation = read_object(bundle / "attestation.json")
        require(attestation["command"] == command and attestation["scope"] == scope,
                f"{lane}: command/scope was not preserved")
        require(attestation["attestationId"] == captured["attestationId"]
                and attestation["outcome"] == captured["outcome"], f"{lane}: attestation report mismatch")
        resolution = read_object(bundle / "resolution.json")
        if probe_fixture:
            require(resolution["agda"]["available"] is True
                    and resolution["agda"]["version"]["available"] is True
                    and resolution["agda"]["version"]["stdout"] == "Agda version package-smoke-fixture"
                    and "appDirectoryReference" in resolution["agda"], f"{lane}: fake Agda probes failed")
        else:
            require(resolution["agda"]["available"] is False and resolution["agda"]["reason"] == "not-found",
                    f"{lane}: unavailable fixture compiler was not recorded honestly")
        diagnostics = read_object(bundle / "diagnostics.json")
        require(diagnostics["stdout"]["text"].strip() == f"package-smoke lane {lane}"
                and diagnostics["stderr"]["text"] == "", f"{lane}: command output was not retained")
        require(cli.run("verify", bundle).strip() == "Evidence bundle verification passed.",
                f"{lane}: missing bundle verification success message")
        queried = cli.json("index", "query", bundle, "--exact", "Main.identity", "--kind", "signature")
        require(queried["indexId"] == built["indexId"] and queried["sourceId"] == built["sourceId"],
                f"{lane}: index query lost source/index pins")
        require(len(queried["entries"]) == 1 and queried["entries"][0]["qualifiedName"] == "Main.identity"
                and queried["entries"][0]["path"] == "Main.agda"
                and queried["entries"][0]["kind"] == "signature", f"{lane}: incorrect index query: {queried!r}")
        captures[lane], bundles[lane] = captured, bundle
        status(f"capture/verify/index query {lane}", "passed; explicit command exitCode=0")
    require(captures["first"]["sourceId"] == captures["second"]["sourceId"], "lanes have different source")
    require(captures["first"]["resolutionId"] == captures["second"]["resolutionId"], "fixture resolution drifted")
    for field in ("bundleId", "attestationId"):
        require(captures["first"][field] != captures["second"][field], f"independent lanes duplicate {field}")

    catalog_path = root / "catalog" / "local.json"
    created = cli.json("catalog", "create", "--output", catalog_path,
                       "--entry", f"first={bundles['first']}", "--entry", f"second={bundles['second']}")
    require(created["format"] == "agda-evidence/local-catalog-v1"
            and set(created["entries"]) == set(bundles), "catalog create lost entries/format")
    require(created == read_object(catalog_path), "catalog create report differs from saved config")
    verified = cli.json("catalog", "verify", catalog_path)
    require(verified["format"] == "agda-evidence/catalog-verification-v1"
            and {entry["entry"] for entry in verified["entries"]} == set(bundles), "catalog verification lost entries")
    query = cli.json("catalog", "query", catalog_path, "--exact", "Main.identity", "--kind", "signature")
    require(query["format"] == "agda-evidence/catalog-query-v1"
            and query["checkedEntries"] == ["first", "second"] and len(query["entries"]) == 2,
            f"catalog query lost independent colliding candidates: {query!r}")
    provenance = {entry["entry"]: entry for entry in verified["entries"]}
    for entry in query["entries"]:
        evidence = entry["evidence"]
        lane = evidence["entry"]
        require(entry["qualifiedName"] == "Main.identity" and entry["path"] == "Main.agda",
                "catalog query returned the wrong source candidate")
        require(evidence == provenance[lane], f"catalog query/verify provenance differs for {lane}")
        for field in ("bundleId", "sourceId", "resolutionId", "attestationId", "outcome"):
            require(evidence[field] == captures[lane][field], f"catalog lost {lane} {field}")
        require(evidence["indexId"] == built["indexId"], f"catalog lost {lane} indexId")
        require(created["entries"][lane]["expected"] ==
                {field: captures[lane][field] for field in ("sourceId", "resolutionId")},
                f"catalog did not pin {lane} source/resolution")
    status("catalog create/verify/query", "passed; 2 candidates with distinct bundle provenance")

    aggregate_path = root / "aggregate"
    aggregate = cli.json("aggregate", "create", "--output", aggregate_path,
                         "--lane", f"first={bundles['first']}", "--lane", f"second={bundles['second']}")
    digest(aggregate["aggregateId"], "aggregateId")
    require(aggregate["sourceId"] == built["sourceId"]
            and aggregate["lanes"] == {lane: captures[lane]["bundleId"] for lane in bundles},
            "aggregate lost lane bundle/source identities")
    saved = read_object(aggregate_path / "aggregate.json")
    require(saved["aggregateId"] == aggregate["aggregateId"] and len(saved["lanes"]) == 2,
            "aggregate envelope/report mismatch")
    for lane in bundles:
        record = saved["lanes"][lane]
        require(record["outcome"] == {"status": "passed", "exitCode": 0}, f"aggregate lane {lane} is not green")
        for field in ("bundleId", "sourceId", "resolutionId", "attestationId"):
            require(record[field] == captures[lane][field], f"aggregate lost {lane} {field}")
        require(read_object(aggregate_path / "lanes" / lane / "bundle.json")["bundleId"] == captures[lane]["bundleId"],
                f"aggregate did not materialize lane {lane}")
    # Prove the aggregate is closed, not dependent on external child directories.
    for bundle in bundles.values():
        shutil.rmtree(bundle)
    require(cli.run("aggregate", "verify", aggregate_path).strip() == "Evidence aggregate verification passed.",
            "closed aggregate verification did not report success")
    require(tree_bytes(project) == before, "default workflows changed original project source bytes")
    status("aggregate create/verify", "passed; 2 independent same-source lanes, external children removed")


def native_workflow(cli: CLI, root: Path, agda_binary: str) -> None:
    project = root / "native-project"
    project.mkdir()
    source = project / "Main.agda"
    source.write_text("{-# OPTIONS --safe #-}\nmodule Main where\n"
                      "open import Agda.Builtin.Nat\n"
                      "identity : Nat → Nat\nidentity n = {! !}\n", encoding="utf-8")
    before = tree_bytes(project)
    listing_path, inspection_path, candidate_path = [root / name for name in
                                                   ("goals.json", "inspection.json", "candidate.json")]
    common = ["--project-root", project, "--agda-bin", agda_binary, "--timeout-seconds", 30]
    listing = cli.json("goals", "list", *common, "--file", "Main.agda", "--safe", "--output", listing_path)
    require(listing["result"]["status"] == "listed" and len(listing["result"]["goals"]) == 1,
            f"native Agda did not list one unfinished goal: {listing!r}")
    saved_listing = read_object(listing_path)
    compiler = saved_listing["resolution"]["agda"]
    require(compiler["available"] is True and compiler["version"]["available"] is True,
            "native listing lacks an available recorded compiler version")
    status("native compiler", compiler["version"]["stdout"].strip())
    goal = listing["result"]["goals"][0]
    require(type(goal["id"]) is int and goal["id"] >= 0 and goal["type"] == "Nat" and goal["range"],
            f"unexpected native goal: {goal!r}")
    selection = [*common, "--listing", listing_path, "--goal-id", goal["id"]]
    inspection = cli.json("goals", "inspect", *selection, "--output", inspection_path)
    selected = inspection["result"]["selected"]
    require(inspection["result"]["status"] == "inspected" and selected is not None,
            f"native goal inspection failed: {inspection!r}")
    require(selected["id"] == goal["id"] and selected["range"] == goal["range"] and selected["type"] == "Nat"
            and any(entry["reifiedName"] == "n" and entry["binding"] == "Nat" and entry["inScope"] is True
                    for entry in selected["entries"]), f"native goal context lacks n : Nat: {selected!r}")
    candidate = cli.json("goals", "check", *selection, "--expression", "n", "--output", candidate_path)
    result = candidate["result"]
    require(result["status"] == "elaborated" and result["assurance"] == "contextual-elaboration-only"
            and result["postflightUnchanged"] is True and result["selected"]["term"] == "n"
            and result["selected"]["id"] == goal["id"] and result["selected"]["type"] == "Nat",
            f"native non-filling candidate trial failed: {candidate!r}")
    for report in (listing, inspection, candidate):
        digest(report["observationId"], "native observationId")
        require(report["sourceId"] == listing["sourceId"] and report["resolutionId"] == listing["resolutionId"],
                "native operations lost listing source/resolution pins")
    # Remove the native compiler from PATH and AGDA_DIR from its prior location.
    # Offline verify commands must use retained evidence, not live Agda probes.
    offline_env = dict(cli.environment)
    offline_env["PATH"] = str(root / "no-executables")
    offline_env["AGDA_DIR"] = str(root / "no-live-registry")
    offline = CLI(cli.cwd, offline_env)
    for operation, path, expected in (("verify", listing_path, listing),
                                      ("verify", inspection_path, inspection),
                                      ("verify-check", candidate_path, candidate)):
        actual = offline.json("goals", operation, path)
        require(actual == expected, f"offline goals {operation} changed retained observation summary")
    require(tree_bytes(project) == before and not list(project.rglob("*.agdai")),
            "native non-filling workflow changed source bytes or wrote interfaces in original project")
    status("native goals list/inspect/check/offline verify",
           "listed/inspected/elaborated; n : Nat; postflight unchanged; source bytes unchanged (not proof completion)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agda-bin", help="optional real native Agda executable (not a shell command)")
    args = parser.parse_args()
    original_cwd = Path.cwd()
    try:
        agda_binary = None
        if args.agda_bin:
            found = shutil.which(args.agda_bin)
            require(found is not None, f"optional Agda executable not found: {args.agda_bin!r}")
            agda_binary = str(Path(found).resolve())
        temp_parent = Path(tempfile.gettempdir()).resolve()
        if temp_parent.is_relative_to(CHECKOUT):
            alternatives = [Path("/tmp"), Path.home(), Path(sys.executable).parent]
            if os.name == "nt" and os.environ.get("SYSTEMROOT"):
                alternatives.insert(0, Path(os.environ["SYSTEMROOT"]) / "Temp")
            temp_parent = next((candidate.resolve() for candidate in alternatives
                                if candidate.is_dir() and not candidate.resolve().is_relative_to(CHECKOUT)), temp_parent)
        require(temp_parent.is_dir() and not temp_parent.is_relative_to(CHECKOUT),
                "cannot select a temporary directory outside the checkout")
        with tempfile.TemporaryDirectory(prefix="agda-evidence-package-smoke-", dir=temp_parent) as directory:
            root = Path(directory).resolve()
            require(not root.is_relative_to(CHECKOUT), "smoke temporary directory is inside checkout")
            cwd, app_dir, internal_tmp, home = [root / name for name in ("cwd", "agda-app", "tmp", "home")]
            for path in (cwd, app_dir, internal_tmp, home):
                path.mkdir()
            environment = dict(os.environ)
            for name in ("PYTHONPATH", "PYTHONHOME"):
                environment.pop(name, None)
            environment.update(AGDA_DIR=str(app_dir), TMPDIR=str(internal_tmp),
                               TEMP=str(internal_tmp), TMP=str(internal_tmp), HOME=str(home))
            try:
                os.chdir(cwd)
                installed_version, count = inspect_installation()
                cli = CLI(cwd, environment)
                require(cli.run("--version").strip() == f"agda-evidence {installed_version}",
                        "CLI --version does not agree with installed metadata/module version")
                status("version", f"{installed_version}; metadata/module/CLI agree")
                fixture_workflows(cli, root, app_dir)
                if agda_binary:
                    native_workflow(cli, root, agda_binary)
                    native_source_workflow(cli, root, agda_binary)
                else:
                    status("native Agda", "skipped (opt in with --agda-bin); default requires no real Agda")
                status("PACKAGE SMOKE PASSED", f"version={installed_version}; schemas={count}; installed-artifact workflows verified")
            finally:
                os.chdir(original_cwd)
        return 0
    except Exception as error:
        print(f"PACKAGE SMOKE FAILED: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1


def native_source_workflow(cli: CLI, root: Path, binary: str) -> None:
    dependency, client = root / "source-dependency", root / "source-client"
    dependency.mkdir()
    client.mkdir()
    (dependency / "Mini.agda").write_text(
        "{-# OPTIONS --safe #-}\nmodule Mini where\n"
        "open import Agda.Builtin.Nat public\n"
        "identity : Nat → Nat\nidentity n = n\n", encoding="utf-8")
    (client / "Main.agda").write_text(
        "{-# OPTIONS --safe #-}\nmodule Main where\nopen import Mini\n"
        "goal : Nat → Nat\ngoal n = {! !}\n", encoding="utf-8")
    before = (tree_bytes(dependency), tree_bytes(client))
    bundle = root / "source-dependency.evidence"
    cli.json("capture", "--project-root", dependency, "--agda-bin", binary, "--output", bundle,
             "--scope", "native package dependency Mini module check", "--", binary,
             "--no-libraries", "--ignore-interfaces", "--safe", "-i", ".", "Mini.agda")
    require(read_object(bundle / "attestation.json")["outcome"]["status"] == "passed",
            "native source dependency module failed")
    common = ["--project-root", client, "--dependency-root", dependency,
              "--dependency-bundle", bundle, "--dependency-include", ".", "--agda-bin", binary]
    listing_path, context_path, candidate_path = [root / name for name in
                                               ("source-list.json", "source-context.json", "source-trial.json")]
    listed = cli.json("source", "list", *common, "--file", "Main.agda", "--safe", "--output", listing_path)
    listing = read_object(listing_path)
    require(listing["observation"]["result"]["status"] == "listed", "installed source listing failed")
    point = listing["observation"]["result"]["goals"][0]["id"]
    inspected = cli.json("source", "inspect", *common, "--listing", listing_path,
                         "--goal-id", point, "--output", context_path)
    checked = cli.json("source", "check", *common, "--listing", listing_path, "--goal-id", point,
                       "--expression", "Mini.identity n", "--output", candidate_path)
    context, candidate = read_object(context_path), read_object(candidate_path)
    require(context["observation"]["result"]["status"] == "inspected", "installed source inspection failed")
    result = candidate["observation"]["result"]
    require(result["status"] == "elaborated" and result["assurance"] == "contextual-elaboration-only"
            and result["postflightUnchanged"] is True, "installed source trial lost its bounded assurance")
    require("index-ref.json" not in listing["dependency"]["evidence"]["components"],
            "source availability must not require a lexical candidate index")
    require(canonical_json_for_smoke(candidate["listing"]) == canonical_json_for_smoke(listing),
            "source trial did not retain the exact source listing")
    offline_env = {**cli.environment, "PATH": str(root / "no-executables"), "AGDA_DIR": str(root / "no-registry")}
    offline = CLI(cli.cwd, offline_env)
    for path, expected in ((listing_path, listed), (context_path, inspected), (candidate_path, checked)):
        require(offline.json("source", "verify", path) == expected, "offline source summary changed")
    require(before == (tree_bytes(dependency), tree_bytes(client)), "native source work modified original source")
    status("native source list/inspect/check/offline verify", "passed; unindexed pinned dependency; no source edits")

    from unittest.mock import patch
    from agda_evidence.source_research import SourceResearchWorkspace
    from agda_evidence.sources import validate_source_observation
    with patch.dict(os.environ, cli.environment, clear=True):
        workspace = SourceResearchWorkspace(client, {"main": "Main.agda"}, dependency_root=dependency,
            dependency_bundle=bundle, dependency_includes=["."], agda_binary=binary, safe=True)
        def api(op: str, revision: str | None = None, **args: Any) -> dict:
            return workspace.handle({"apiVersion": 2, "requestId": "installed-source-api",
                                     "op": op, "revision": revision, "args": args})
        state = api("workspace.status")
        require(state["status"] == "ok" and state["result"]["dependencyMatchesPin"] is True,
                "installed source API did not admit its initial explicit pins")
        revision = state["currentRevision"]
        listed_api = api("goals.list", revision, documentId="main")
        require(listed_api["status"] == "ok" and listed_api["result"]["outcome"]["status"] == "listed",
                "installed source API native listing failed")
        goal = listed_api["result"]["outcome"]["goals"][0]["id"]
        trial_api = api("candidate.check", revision, listingId=listed_api["recordId"],
                        goalId=goal, expression="Mini.identity n")
        require(trial_api["status"] == "ok" and trial_api["result"]["outcome"]["status"] == "elaborated",
                "installed source API native trial failed")
        fetched = api("record.get", recordId=trial_api["recordId"])
        saved = validate_source_observation(fetched["result"]["artifact"])
        require(fetched["result"]["freshness"] == "current"
                and saved["sourceObservationId"] == trial_api["result"]["sourceObservationId"],
                "installed source API lost exact complete-envelope evidence")
        marker = dependency / "unrelated-installed-api-edit.txt"
        marker.write_text("private freshness fixture\n", encoding="utf-8")
        changed = api("workspace.status")
        require(changed["result"]["dependencyMatchesPin"] is False
                and changed["currentRevision"] != revision, "installed source API did not invalidate changed dependency")
        refused = api("goals.list", changed["currentRevision"], documentId="main")
        require(refused["status"] == "error" and refused["error"]["code"] == "dependency-changed",
                "installed source API refreshed immutable dependency pins implicitly")
        history = api("record.get", recordId=trial_api["recordId"])
        require(history["result"]["freshness"] == "stale"
                and canonical_json_for_smoke(history["result"]["artifact"]) == canonical_json_for_smoke(saved),
                "installed source API lost or promoted historical evidence")
        marker.unlink()
    require(before == (tree_bytes(dependency), tree_bytes(client)), "installed API fixture source was not restored")
    status("native source research API", "passed; exact envelope retrieval; frozen dependency pins; stale history")


def canonical_json_for_smoke(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    # -I removes the script directory, cwd, user site and PYTHON* overrides from
    # import lookup. Re-execute this *absolute* script, never inject src/sys.path.
    if not sys.flags.isolated:
        process = subprocess.run([sys.executable, "-I", str(SCRIPT_PATH), *sys.argv[1:]], check=False)
        raise SystemExit(process.returncode)
    raise SystemExit(main())
