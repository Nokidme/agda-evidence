"""Unfinished client goals with one explicit, locally pinned source dependency.

This is source-copy composition, not dependency closure, lexical candidate
selection, proof completion, or an atomic filesystem observation. Native goal
and candidate records are retained unchanged inside the complete envelope.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any, Sequence

from .candidates import (
    CANDIDATE_FORMAT, _expression, check_candidate, validate_candidate_observation,
)
from .checker import CheckerEvidenceError, _argv, _include_roots
from .client import _native_resolution, _snapshot_records, composed_records, effective_includes
from .core import (
    EvidenceError, _copy_snapshot, _digest_identifier, _indexable_source_path,
    _object, _parse_timestamp, _read_json, _verify_bundle_payloads,
    build_resolution, build_snapshot, canonical_json_bytes, digest_value,
    load_verified_bundle, resolution_identity_projection,
)
from .goals import GOAL_FORMAT, _selected, observe_goals, validate_goal_observation

SOURCE_FORMAT = "agda-evidence/source-observation-v1"
SOURCE_POLICY = "one-dependency-source-copy-v1"


class SourceEvidenceError(CheckerEvidenceError):
    """Source evidence, native pins, prior selections, or cross-bindings failed."""


def source_observation_id(value: dict[str, Any]) -> str:
    return f"sha256:{digest_value({key: item for key, item in value.items() if key != 'sourceObservationId'})}"


def _same(left: Any, right: Any) -> bool:
    """JSON equality, including scalar types (True is never an alias for 1)."""
    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _records(snapshot: Any, field: str) -> list[dict[str, Any]]:
    records = _snapshot_records(snapshot, field)
    if not _same(snapshot["files"], records):
        raise SourceEvidenceError(f"{field} file records must be exact and canonically ordered")
    _parse_timestamp(snapshot.get("capturedAt"), f"{field} capture")
    return records


def _source_evidence(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify the complete enhanced payload set; no declaration index is needed."""
    evidence = _object(value, "dependency evidence")
    if set(evidence) != {"manifest", "components"}:
        raise SourceEvidenceError("dependency evidence must contain only manifest and components")
    manifest = _object(evidence["manifest"], "dependency manifest")
    payloads = _object(evidence["components"], "dependency components")
    declared = _object(manifest.get("components"), "dependency manifest components")
    if set(declared) != set(payloads):
        raise SourceEvidenceError("embedded dependency components must exactly match the manifest")
    for name in declared:
        if not isinstance(name, str) or not name or name in {".", "..", "bundle.json"} or "/" in name or "\\" in name:
            raise SourceEvidenceError("embedded dependency contains an unsafe component name")
    problems = _verify_bundle_payloads(manifest, payloads)
    if problems:
        raise SourceEvidenceError(f"invalid embedded dependency evidence: {'; '.join(problems)}")
    _digest_identifier(manifest.get("bundleId"), "dependency bundleId")
    for filename, field in (("snapshot.json", "sourceId"), ("resolution.json", "resolutionId"),
                            ("attestation.json", "attestationId")):
        _digest_identifier(_object(payloads[filename], filename).get(field), f"dependency {field}")
    attestation = payloads["attestation.json"]
    _digest_identifier(attestation.get("diagnosticsDigest"), "dependency diagnostics digest")
    if set(_object(attestation.get("subjects"), "dependency attestation subjects")) != {"sourceId", "resolutionId"}:
        raise SourceEvidenceError("dependency requires complete enhanced source/resolution subjects")
    _records(payloads["snapshot.json"], "dependency snapshot")
    _native_resolution(payloads["resolution.json"], payloads["snapshot.json"], "dependency recorded resolution")
    return manifest, payloads


def _dependency_roots(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
        raise EvidenceError("at least one explicit dependency include root is required")
    _include_roots(values)
    return list(dict.fromkeys(values))


def _client_roots(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise EvidenceError("client include roots must be a sequence of relative directories")
    return _include_roots(values)


def _pins(value: dict[str, Any]) -> dict[str, str]:
    evidence = value["dependency"]["evidence"]
    payloads = evidence["components"]
    return {"bundleId": evidence["manifest"]["bundleId"],
            "sourceId": payloads["snapshot.json"]["sourceId"],
            "resolutionId": payloads["resolution.json"]["resolutionId"]}


def _matching_prior(prior: dict[str, Any], current: dict[str, Any]) -> None:
    if prior["clientSnapshot"]["sourceId"] != current["clientSnapshot"]["sourceId"]:
        raise SourceEvidenceError("source listing client source pin mismatch")
    if not _same(resolution_identity_projection(prior["clientResolution"]),
                 resolution_identity_projection(current["clientResolution"])):
        raise SourceEvidenceError("source listing client native resolution pin mismatch")
    if not _same(_pins(prior), _pins(current)):
        raise SourceEvidenceError("source listing dependency bundle/source/resolution pin mismatch")
    if not _same(prior["composition"], current["composition"]):
        raise SourceEvidenceError("source listing composition pin mismatch")


def _leaf_listing(value: Any) -> dict[str, Any]:
    try:
        prior = _object(value, "prior source listing")
        inner = _object(prior.get("observation"), "prior source goal observation")
        query = _object(inner.get("query"), "prior source goal query")
        if prior.get("listing") is not None or query.get("operation") != "list" or inner.get("listing") is not None:
            raise SourceEvidenceError("source selection requires a leaf source listing, not nested history")
        return validate_source_observation(prior)
    except EvidenceError as error:
        raise SourceEvidenceError(str(error)) from error


def _validate_source(value: Any) -> dict[str, Any]:
    value = _object(value, "source observation")
    fields = {"format", "sourceObservationId", "clientSnapshot", "clientResolution", "dependency",
              "composition", "observation", "listing"}
    if set(value) != fields or value["format"] != SOURCE_FORMAT:
        raise SourceEvidenceError("source observation has an unsupported format or fields")
    client_snapshot = _object(value["clientSnapshot"], "client snapshot")
    client_records = _records(client_snapshot, "client snapshot")
    client_resolution = _object(value["clientResolution"], "client resolution")
    client_compiler = _native_resolution(client_resolution, client_snapshot, "client native resolution")
    dependency = _object(value["dependency"], "source dependency")
    if set(dependency) != {"evidence", "nativeResolution"}:
        raise SourceEvidenceError("source dependency has unsupported fields")
    _, payloads = _source_evidence(dependency["evidence"])
    dependency_snapshot = payloads["snapshot.json"]
    recorded = payloads["resolution.json"]
    native = _object(dependency["nativeResolution"], "dependency native resolution")
    dependency_compiler = _native_resolution(native, dependency_snapshot, "dependency native resolution")
    if not _same(resolution_identity_projection(native), resolution_identity_projection(recorded)):
        raise SourceEvidenceError("dependency full native resolution pin mismatch")
    if not _same(client_compiler, dependency_compiler):
        raise SourceEvidenceError("client compiler does not match the pinned dependency compiler")
    composition = _object(value["composition"], "source composition")
    if set(composition) != {"policy", "clientIncludes", "dependencyIncludes"} or composition["policy"] != SOURCE_POLICY:
        raise SourceEvidenceError("source composition has an unsupported policy or fields")
    client_roots = composition["clientIncludes"]
    dependency_roots = composition["dependencyIncludes"]
    if not isinstance(client_roots, list) or not _same(_client_roots(client_roots), client_roots):
        raise SourceEvidenceError("source client include roots are not canonical")
    if not isinstance(dependency_roots, list) or not _same(_dependency_roots(dependency_roots), dependency_roots):
        raise SourceEvidenceError("source dependency include roots are not canonical")
    inner = _object(value["observation"], "source native observation")
    if inner.get("format") == GOAL_FORMAT:
        validate_goal_observation(inner)
    elif inner.get("format") == CANDIDATE_FORMAT:
        validate_candidate_observation(inner)
    else:
        raise SourceEvidenceError("source inner observation must be a goal or candidate observation")
    workspace_records = _records(inner["snapshot"], "workspace snapshot")
    if not _same(workspace_records, composed_records(client_snapshot, dependency_snapshot)):
        raise SourceEvidenceError("workspace manifest is not exactly the prefixed client/library file union")
    query = inner["query"]
    if not query["file"].startswith("client/"):
        raise SourceEvidenceError("source query must load a client source file")
    file = _indexable_source_path(query["file"].removeprefix("client/"), "client file")
    client_file = next((record for record in client_records if record["path"] == file), None)
    if client_file is None or client_file["sha256"] != query["sourceSha256"]:
        raise SourceEvidenceError("source query is not bound to the original client file")
    if not _same(query["includes"], effective_includes(client_roots, dependency_roots)):
        raise SourceEvidenceError("workspace includes do not match explicit source composition")
    if not _same(inner["execution"]["argv"], _argv("$AGDA", query["includes"], query["safe"], anchor="$PROJECT_ROOT")):
        raise SourceEvidenceError("source interaction requires workspace-anchored no-libraries argv")
    workspace_compiler = _native_resolution(inner["resolution"], inner["snapshot"], "workspace native resolution")
    if not _same(workspace_compiler, client_compiler):
        raise SourceEvidenceError("workspace compiler does not match client/dependency compiler pins")
    # The workspace has its own subjects: never equate its full resolution to
    # the dependency's root-manifest/registry resolution.
    workspace_at = _parse_timestamp(inner["snapshot"]["capturedAt"], "workspace source capture")
    workspace_resolution_at = _parse_timestamp(inner["resolution"]["capturedAt"], "workspace resolution capture")
    started = _parse_timestamp(inner["execution"]["startedAt"], "workspace execution start")
    for capture in (client_snapshot, dependency_snapshot, client_resolution, native):
        captured = _parse_timestamp(capture.get("capturedAt"), "source preflight capture")
        if captured > workspace_at or captured > workspace_resolution_at or captured > started:
            raise SourceEvidenceError("source/native preflight must precede inner capture and execution")
    for snapshot in (client_snapshot, dependency_snapshot):
        source_at = _parse_timestamp(snapshot["capturedAt"], "source capture")
        if any(source_at > _parse_timestamp(resolution["capturedAt"], "native preflight capture")
               for resolution in (client_resolution, native)):
            raise SourceEvidenceError("both source captures must precede native preflight")
    prior = value["listing"]
    if query["operation"] == "list":
        if prior is not None or inner["listing"] is not None:
            raise SourceEvidenceError("a source goal listing must be a leaf envelope")
    else:
        prior = _leaf_listing(prior)
        if not _same(inner["listing"], prior["observation"]):
            raise SourceEvidenceError("selected inner listing must exactly equal the prior source observation")
        _matching_prior(prior, value)
        if _parse_timestamp(prior["observation"]["execution"]["finishedAt"], "prior source listing finish") > started:
            raise SourceEvidenceError("source selection began before its prior listing finished")
        # Goal-v1 rich references historically used Python equality for ranges;
        # source cross-bindings additionally retain exact JSON scalar types.
        point = _selected(prior["observation"]["result"]["goals"], query["goalId"])
        for phase in inner["transcript"][2:]:
            for response in phase["responses"]:
                info = response.get("info")
                if inner["result"]["status"] in {"inspected", "elaborated"} and response.get("kind") == "DisplayInfo" and isinstance(info, dict) and info.get("kind") == "GoalSpecific":
                    reference = info.get("interactionPoint")
                    if isinstance(reference, dict) and not _same(reference, {"id": point["id"], "range": point["range"]}):
                        raise SourceEvidenceError("selected native response disagrees with the exact prior ID/range")
    if value["sourceObservationId"] != source_observation_id(value):
        raise SourceEvidenceError("sourceObservationId does not match the complete envelope")
    return value


def validate_source_observation(value: Any) -> dict[str, Any]:
    try:
        return _validate_source(value)
    except (EvidenceError, TypeError, ValueError, KeyError, AttributeError, StopIteration, RecursionError, OverflowError) as error:
        raise SourceEvidenceError(str(error)) from error


def _directories(root: Path, values: Sequence[str]) -> None:
    for directory in values:
        target = root / directory
        if not target.is_dir() or not target.resolve().is_relative_to(root):
            raise EvidenceError(f"source include root must exist and remain inside its snapshot: {directory}")
        cursor = root
        for part in Path(directory).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise EvidenceError(f"symlinked source include root is unsupported: {directory}")


def _unchanged(root: Path, snapshot: dict[str, Any], resolution: dict[str, Any],
               directories: Sequence[str], agda_binary: str, field: str) -> None:
    _directories(root, directories)
    current, _ = build_snapshot(root)
    if current["sourceId"] != snapshot["sourceId"] or not _same(current["files"], snapshot["files"]):
        raise SourceEvidenceError(f"{field} source changed after composition capture")
    native = build_resolution(root, agda_binary=agda_binary)
    _native_resolution(native, current, f"{field} fresh native resolution")
    if not _same(resolution_identity_projection(native), resolution_identity_projection(resolution)):
        raise SourceEvidenceError(f"{field} full native resolution changed after composition capture")


def _capture_source(
    project_root: Path, file: str, *, dependency_bundle: Path, dependency_root: Path,
    dependency_includes: Sequence[str], agda_binary: str, includes: Sequence[str], safe: bool,
    listing: dict[str, Any] | None, goal_id: int | None, expression: str | None,
    timeout_seconds: int, max_output_bytes: int,
) -> dict[str, Any]:
    if os.name != "posix":
        raise EvidenceError("the native source adapter currently requires POSIX")
    file = _indexable_source_path(file, "client file")
    if any(ord(c) < 32 for c in file):
        raise EvidenceError("client file must not contain control characters")
    if not isinstance(agda_binary, str) or not agda_binary or "\x00" in agda_binary:
        raise EvidenceError("source Agda binary must be a non-empty executable name")
    if not isinstance(safe, bool) or not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds < 1:
        raise EvidenceError("source safe policy/timeout is invalid")
    if not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool) or max_output_bytes < 1024:
        raise EvidenceError("source output limit must be at least 1024 bytes")
    client_roots = _client_roots(includes)
    dependency_roots = _dependency_roots(dependency_includes)
    client_root = project_root.resolve()
    dependency_root = dependency_root.resolve()
    if not client_root.is_dir() or not dependency_root.is_dir():
        raise EvidenceError("client and dependency roots must be directories")
    if client_root.is_relative_to(dependency_root) or dependency_root.is_relative_to(client_root):
        raise EvidenceError("client and dependency roots must be separate, non-overlapping directories")
    _directories(client_root, client_roots)
    _directories(dependency_root, dependency_roots)
    if expression is not None:
        expression = _expression(expression)
    if listing is not None:
        listing = _leaf_listing(listing)
        prior_inner = listing["observation"]
        if prior_inner["result"]["status"] != "listed":
            raise SourceEvidenceError("source selection requires an accepted saved listing")
        if not isinstance(goal_id, int) or isinstance(goal_id, bool) or goal_id < 0:
            raise EvidenceError("goal ID must be a non-negative scalar integer")
        if _selected(prior_inner["result"]["goals"], goal_id) is None:
            raise EvidenceError("goal ID is not a selectable interaction point in the source listing")
        if file != prior_inner["query"]["file"].removeprefix("client/") or not _same(safe, prior_inner["query"]["safe"]):
            raise SourceEvidenceError("source inspection file/safe policy differs from its listing")
    elif goal_id is not None or expression is not None:
        raise EvidenceError("source inspection/candidate checking requires an explicit prior source listing")
    try:
        # Read each bundle component once; embed these same verified objects.
        manifest, payloads = load_verified_bundle(dependency_bundle)
        evidence = {"manifest": manifest, "components": payloads}
        _source_evidence(evidence)
    except EvidenceError as error:
        raise SourceEvidenceError(str(error)) from error
    dependency_snapshot = payloads["snapshot.json"]
    recorded = payloads["resolution.json"]
    composition = {"policy": SOURCE_POLICY, "clientIncludes": client_roots, "dependencyIncludes": dependency_roots}
    value = {"format": SOURCE_FORMAT, "sourceObservationId": "", "clientSnapshot": {}, "clientResolution": {},
             "dependency": {"evidence": evidence, "nativeResolution": {}}, "composition": composition,
             "observation": {}, "listing": listing}
    if listing is not None:
        if not _same(_pins(listing), _pins(value)) or not _same(listing["composition"], composition):
            raise SourceEvidenceError("source listing dependency/composition pin mismatch before interaction")
    current_dependency, dependency_files = build_snapshot(dependency_root)
    if current_dependency["sourceId"] != dependency_snapshot["sourceId"] or not _same(current_dependency["files"], dependency_snapshot["files"]):
        raise SourceEvidenceError("dependency source pin mismatch before interaction")
    client_snapshot, client_files = build_snapshot(client_root)
    value["clientSnapshot"] = client_snapshot
    if file not in {record["path"] for record in client_snapshot["files"]}:
        raise EvidenceError("client file is absent from the source snapshot")
    if listing is not None and listing["clientSnapshot"]["sourceId"] != client_snapshot["sourceId"]:
        raise SourceEvidenceError("source listing client source pin mismatch before interaction")
    try:
        native = build_resolution(dependency_root, agda_binary=agda_binary)
        compiler = _native_resolution(native, dependency_snapshot, "dependency native resolution")
        if not _same(resolution_identity_projection(native), resolution_identity_projection(recorded)):
            raise SourceEvidenceError("dependency full native resolution pin mismatch before interaction")
        client_resolution = build_resolution(client_root, agda_binary=agda_binary)
        client_compiler = _native_resolution(client_resolution, client_snapshot, "client native resolution")
        if not _same(client_compiler, compiler):
            raise SourceEvidenceError("client/dependency compiler pin mismatch before interaction")
        value["clientResolution"] = client_resolution
        value["dependency"]["nativeResolution"] = native
        if listing is not None:
            _matching_prior(listing, value)
        with tempfile.TemporaryDirectory(prefix="agda-evidence-source-") as temporary:
            workspace = Path(temporary) / "workspace"
            for prefix, root, files, directories in (("client", client_root, client_files, client_roots),
                                                      ("library", dependency_root, dependency_files, dependency_roots)):
                target = workspace / prefix
                target.mkdir(parents=True)
                _copy_snapshot(root, files, target)
                for directory in directories:
                    (target / directory).mkdir(parents=True, exist_ok=True)
            staged, _ = build_snapshot(workspace)
            if not _same(staged["files"], composed_records(client_snapshot, dependency_snapshot)):
                raise SourceEvidenceError("staged source union differs from captured inputs")
            workspace_resolution = build_resolution(workspace, agda_binary=agda_binary)
            workspace_compiler = _native_resolution(workspace_resolution, staged, "workspace native preflight")
            if not _same(workspace_compiler, compiler):
                raise SourceEvidenceError("workspace compiler changed during composition preflight")
            for root, snapshot, resolution, directories, field in (
                (client_root, client_snapshot, client_resolution, client_roots, "client"),
                (dependency_root, dependency_snapshot, native, dependency_roots, "dependency"),
            ):
                _unchanged(root, snapshot, resolution, directories, agda_binary, field)
            guards = {"_expected_source_id": staged["sourceId"], "_expected_agda": compiler,
                      "_expected_resolution_id": workspace_resolution["resolutionId"]}
            options = {"agda_binary": agda_binary, "timeout_seconds": timeout_seconds,
                       "max_output_bytes": max_output_bytes, **guards}
            prior = listing["observation"] if listing is not None else None
            if expression is None:
                inner = observe_goals(workspace, f"client/{file}", includes=effective_includes(client_roots, dependency_roots),
                                      safe=safe, listing=prior, goal_id=goal_id, **options)
            else:
                inner = check_candidate(workspace, prior, goal_id, expression, **options)
            # Retain the genuine inner snapshot's capture time and namespace;
            # never replace it with the earlier composition-preflight snapshot.
            value["observation"] = inner
            for root, snapshot, resolution, directories, field in (
                (client_root, client_snapshot, client_resolution, client_roots, "client"),
                (dependency_root, dependency_snapshot, native, dependency_roots, "dependency"),
            ):
                _unchanged(root, snapshot, resolution, directories, agda_binary, field)
            _unchanged(workspace, inner["snapshot"], inner["resolution"], inner["query"]["includes"], agda_binary, "workspace")
    except (EvidenceError, OSError) as error:
        raise SourceEvidenceError(str(error)) from error
    value["sourceObservationId"] = source_observation_id(value)
    return validate_source_observation(value)


def observe_source_goals(
    project_root: Path, file: str, *, dependency_bundle: Path, dependency_root: Path,
    dependency_includes: Sequence[str], agda_binary: str = "agda", includes: Sequence[str] = (),
    safe: bool = False, listing: dict[str, Any] | None = None, goal_id: int | None = None,
    timeout_seconds: int = 60, max_output_bytes: int = 4_194_304,
) -> dict[str, Any]:
    """List, or inspect a selected native goal using an explicit source listing."""
    return _capture_source(project_root, file, dependency_bundle=dependency_bundle, dependency_root=dependency_root,
                           dependency_includes=dependency_includes, agda_binary=agda_binary, includes=includes, safe=safe,
                           listing=listing, goal_id=goal_id, expression=None, timeout_seconds=timeout_seconds,
                           max_output_bytes=max_output_bytes)


def check_source_candidate(
    project_root: Path, listing: dict[str, Any], goal_id: int, expression: str, *, dependency_bundle: Path,
    dependency_root: Path, dependency_includes: Sequence[str], agda_binary: str = "agda",
    timeout_seconds: int = 60, max_output_bytes: int = 4_194_304,
) -> dict[str, Any]:
    """Contextual elaboration only; inherit the prior client file/includes/safe."""
    if os.name != "posix":
        raise EvidenceError("the native source adapter currently requires POSIX")
    expression = _expression(expression)
    listing = _leaf_listing(listing)
    query = listing["observation"]["query"]
    return _capture_source(project_root, query["file"].removeprefix("client/"), dependency_bundle=dependency_bundle,
                           dependency_root=dependency_root, dependency_includes=dependency_includes,
                           agda_binary=agda_binary, includes=listing["composition"]["clientIncludes"], safe=query["safe"],
                           listing=listing, goal_id=goal_id, expression=expression, timeout_seconds=timeout_seconds,
                           max_output_bytes=max_output_bytes)


def source_summary(value: dict[str, Any]) -> dict[str, Any]:
    inner = value["observation"]
    pins = _pins(value)
    return {"sourceObservationId": value["sourceObservationId"], "clientSourceId": value["clientSnapshot"]["sourceId"],
            "clientResolutionId": value["clientResolution"]["resolutionId"], "dependencyBundleId": pins["bundleId"],
            "dependencySourceId": pins["sourceId"], "dependencyResolutionId": pins["resolutionId"],
            "workspaceSourceId": inner["snapshot"]["sourceId"], "workspaceResolutionId": inner["resolution"]["resolutionId"],
            "result": inner["result"]}


def load_source_observation(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise SourceEvidenceError("source observation must be a regular non-symlinked file")
        return validate_source_observation(_read_json(path))
    except EvidenceError as error:
        raise SourceEvidenceError(str(error)) from error


def write_source_observation(path: Path, value: dict[str, Any]) -> None:
    validate_source_observation(value)
    if path.exists() or path.is_symlink():
        raise EvidenceError(f"source observation output already exists: {path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(canonical_json_bytes(value) + b"\n")
    except OSError as error:
        raise EvidenceError(f"cannot write source observation: {error}") from error
