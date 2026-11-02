"""One pinned source library in an unchanged client's native Agda environment."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Sequence

from .checker import (
    CheckerEvidenceError, _argv, _include_roots, haskell_string, infer_type, validate_observation,
)
from .core import (
    DECLARATION_KINDS, EvidenceError, _copy_snapshot, _digest_identifier,
    _indexable_source_path, _normalised_file_records, _object, _parse_timestamp,
    _read_json, _verify_bundle_payloads, build_resolution, build_snapshot,
    canonical_json_bytes, declaration_index_from_payloads, derive_resolution_id,
    derive_source_id, digest_value, load_verified_bundle, resolution_identity_projection,
)

CLIENT_FORMAT = "agda-evidence/client-observation-v1"
COMPOSITION_POLICY = "one-library-source-copy-v1"


class ClientEvidenceError(CheckerEvidenceError):
    """An evidence selection, source/environment pin, or cross-binding failed."""


def client_observation_id(value: dict[str, Any]) -> str:
    return f"sha256:{digest_value({key: item for key, item in value.items() if key != 'clientObservationId'})}"


def _snapshot_records(value: Any, field: str) -> list[dict[str, Any]]:
    snapshot = _object(value, field)
    if snapshot.get("format") != "agda-evidence/snapshot-v1" or snapshot.get("treeAlgorithm") != "sha256":
        raise ClientEvidenceError(f"{field} has an unsupported format or tree algorithm")
    source_id = derive_source_id(snapshot)
    if snapshot.get("sourceId") != source_id or snapshot.get("sourceDigest") != source_id:
        raise ClientEvidenceError(f"{field} source identity disagrees with its file manifest")
    records = _normalised_file_records(snapshot.get("files"))
    for record in records:
        if any(part in {"", ".", ".."} for part in record["path"].split("/")) or any(ord(c) < 32 for c in record["path"]):
            raise ClientEvidenceError(f"{field} contains an unsafe source path")
    return records


def _native_resolution(value: Any, snapshot: dict[str, Any], field: str) -> dict[str, Any]:
    resolution = _object(value, field)
    if resolution.get("format") != "agda-evidence/resolution-v1" or resolution.get("resolutionStatus") != "partial" or "nix" in resolution:
        raise ClientEvidenceError(f"{field} must be a partial native resolution, not a Nix observation")
    if resolution.get("resolutionId") != derive_resolution_id(resolution):
        raise ClientEvidenceError(f"{field} resolution identity disagrees with its projection")
    compiler = resolution_identity_projection(resolution)["agda"]
    if compiler["available"] is not True:
        raise ClientEvidenceError(f"{field} requires an available native compiler")
    _digest_identifier(compiler.get("binarySha256"), f"{field} compiler digest")
    records = _snapshot_records(snapshot, f"{field} source snapshot")
    manifests = sorted([
        {"path": record["path"], "sha256": record["sha256"]}
        for record in records if "/" not in record["path"] and record["path"].endswith(".agda-lib")
    ], key=lambda record: record["path"])
    observed = resolution_identity_projection(resolution)["projectLibraryFiles"]
    if observed != manifests:
        raise ClientEvidenceError(f"{field} root library manifests do not match its source snapshot")
    return compiler


def _evidence(value: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    evidence = _object(value, "library evidence")
    if set(evidence) != {"manifest", "components"}:
        raise ClientEvidenceError("library evidence must contain only manifest and components")
    manifest = _object(evidence["manifest"], "library manifest")
    payloads = _object(evidence["components"], "library components")
    declared = _object(manifest.get("components"), "library manifest components")
    if set(declared) != set(payloads):
        raise ClientEvidenceError("embedded library components must exactly match the manifest")
    for name in declared:
        if not isinstance(name, str) or not name or name in {".", "..", "bundle.json"} or "/" in name or "\\" in name:
            raise ClientEvidenceError("embedded library contains an unsafe component name")
    problems = _verify_bundle_payloads(manifest, payloads)
    if problems:
        raise ClientEvidenceError(f"invalid embedded library evidence: {'; '.join(problems)}")
    for filename, field in (("snapshot.json", "sourceId"), ("resolution.json", "resolutionId"), ("attestation.json", "attestationId")):
        _digest_identifier(_object(payloads[filename], filename).get(field), f"library {field}")
    index = declaration_index_from_payloads(payloads)
    return manifest, payloads, index


def _selection_tuple(value: Any) -> dict[str, Any]:
    selection = _object(value, "candidate selection")
    if set(selection) != {"path", "line", "qualifiedName", "kind"}:
        raise EvidenceError("candidate selection must contain exactly path, line, qualifiedName and kind")
    _indexable_source_path(selection["path"], "candidate path")
    if not isinstance(selection["line"], int) or isinstance(selection["line"], bool) or selection["line"] < 1:
        raise EvidenceError("candidate line must be a positive integer")
    if not isinstance(selection["qualifiedName"], str) or not selection["qualifiedName"].strip() or any(ord(c) < 32 for c in selection["qualifiedName"]):
        raise EvidenceError("candidate qualified name must be a non-empty one-line string")
    if not isinstance(selection["kind"], str) or selection["kind"] not in DECLARATION_KINDS:
        raise EvidenceError("candidate kind is unsupported")
    return selection


def select_candidate(index: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    selection = _selection_tuple(selection)
    hits = [entry for entry in index["entries"] if all(entry[key] == value for key, value in selection.items())]
    if len(hits) != 1:
        raise ClientEvidenceError("candidate selection must match exactly one recorded lexical entry")
    return dict(hits[0])


def _library_includes(values: Sequence[str]) -> list[str]:
    if not isinstance(values, (list, tuple)) or not values:
        raise EvidenceError("at least one explicit library include root is required")
    _include_roots(values)
    return list(dict.fromkeys(values))


def effective_includes(client: list[str], library: list[str]) -> list[str]:
    mapped = ["."]
    for prefix, roots in (("client", client), ("library", library)):
        for root in roots:
            value = prefix if root == "." else f"{prefix}/{root}"
            if value not in mapped:
                mapped.append(value)
    return mapped


def composed_records(client_snapshot: dict[str, Any], library_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for prefix, snapshot in (("client", client_snapshot), ("library", library_snapshot)):
        for record in _snapshot_records(snapshot, f"{prefix} snapshot"):
            records.append({**record, "path": f"{prefix}/{record['path']}"})
    return sorted(records, key=lambda record: record["path"])


def _validate_client(value: Any) -> dict[str, Any]:
    observation = _object(value, "client observation")
    fields = {"format", "clientObservationId", "clientSnapshot", "library", "composition", "typeObservation"}
    if set(observation) != fields or observation["format"] != CLIENT_FORMAT:
        raise ClientEvidenceError("client observation has an unsupported format or fields")
    client_snapshot = _object(observation["clientSnapshot"], "client snapshot")
    _snapshot_records(client_snapshot, "client snapshot")
    library = _object(observation["library"], "client library")
    if set(library) != {"evidence", "nativeResolution", "candidate"}:
        raise ClientEvidenceError("client library has unsupported fields")
    _, payloads, index = _evidence(library["evidence"])
    library_snapshot = _object(payloads["snapshot.json"], "library snapshot")
    _snapshot_records(library_snapshot, "library snapshot")
    recorded_compiler = _native_resolution(payloads["resolution.json"], library_snapshot, "library recorded resolution")
    native = _object(library["nativeResolution"], "library native resolution")
    native_compiler = _native_resolution(native, library_snapshot, "library native resolution")
    if native["resolutionId"] != payloads["resolution.json"]["resolutionId"] or native_compiler != recorded_compiler:
        raise ClientEvidenceError("library native resolution pin mismatch")
    candidate = _object(library["candidate"], "library candidate")
    if set(candidate) != {"path", "line", "qualifiedName", "kind", "sourceSha256"}:
        raise ClientEvidenceError("library candidate has unsupported fields")
    actual = select_candidate(index, {key: candidate[key] for key in ("path", "line", "qualifiedName", "kind")})
    if candidate != actual:
        raise ClientEvidenceError("library candidate does not match the complete recorded lexical entry")
    composition = _object(observation["composition"], "client composition")
    if set(composition) != {"policy", "clientIncludes", "libraryIncludes"} or composition["policy"] != COMPOSITION_POLICY:
        raise ClientEvidenceError("client composition has an unsupported policy or fields")
    client_roots = composition["clientIncludes"]
    library_roots = composition["libraryIncludes"]
    if not isinstance(client_roots, list) or _include_roots(client_roots) != client_roots:
        raise ClientEvidenceError("client include roots are not canonical")
    if not isinstance(library_roots, list) or _library_includes(library_roots) != library_roots:
        raise ClientEvidenceError("library include roots are not canonical")
    inner = validate_observation(observation["typeObservation"])
    if inner["execution"]["argv"] != _argv("$AGDA", inner["query"]["includes"], inner["query"]["safe"], anchor="$PROJECT_ROOT"):
        raise ClientEvidenceError("client composition requires workspace-anchored checker include paths")
    if inner["basis"] is not None:
        raise ClientEvidenceError("composed type observation must not reuse a single-library basis")
    if _normalised_file_records(inner["snapshot"]["files"]) != composed_records(client_snapshot, library_snapshot):
        raise ClientEvidenceError("workspace file manifest is not exactly the prefixed client/library union")
    query = inner["query"]
    if not query["file"].startswith("client/"):
        raise ClientEvidenceError("composed query must load a client source file")
    client_file = query["file"].removeprefix("client/")
    client_files = {record["path"]: record["sha256"] for record in _snapshot_records(client_snapshot, "client snapshot")}
    if client_files.get(client_file) != query["sourceSha256"]:
        raise ClientEvidenceError("queried client file does not match client snapshot")
    if query["includes"] != effective_includes(client_roots, library_roots):
        raise ClientEvidenceError("workspace include roots do not match the explicit composition")
    inner_compiler = _native_resolution(inner["resolution"], inner["snapshot"], "workspace resolution")
    if inner_compiler != native_compiler:
        raise ClientEvidenceError("workspace compiler does not match the pinned library compiler")
    started = _parse_timestamp(inner["execution"]["startedAt"], "workspace execution start")
    native_time = _parse_timestamp(native["capturedAt"], "native library capture")
    workspace_time = _parse_timestamp(inner["snapshot"]["capturedAt"], "workspace capture")
    if native_time > workspace_time:
        raise ClientEvidenceError("native library resolution was captured after the workspace snapshot")
    for snapshot in (client_snapshot, library_snapshot):
        if _parse_timestamp(snapshot["capturedAt"], "source capture") > native_time:
            raise ClientEvidenceError("source capture must precede native library preflight")
    for field, value in (("client snapshot", client_snapshot["capturedAt"]),
                         ("native library resolution", native["capturedAt"])):
        if _parse_timestamp(value, f"{field} capture") > started:
            raise ClientEvidenceError(f"{field} was captured after workspace execution began")
    if observation["clientObservationId"] != client_observation_id(observation):
        raise ClientEvidenceError("clientObservationId does not match the complete envelope")
    return observation


def validate_client_observation(value: Any) -> dict[str, Any]:
    try:
        return _validate_client(value)
    except (EvidenceError, TypeError, ValueError, KeyError, AttributeError) as error:
        raise ClientEvidenceError(str(error)) from error


def infer_client(
    project_root: Path, file: str, expression: str, *, library_bundle: Path,
    library_root: Path, library_includes: Sequence[str], candidate: dict[str, Any],
    agda_binary: str = "agda", includes: Sequence[str] = (), safe: bool = False,
    timeout_seconds: int = 60, max_output_bytes: int = 4_194_304,
) -> dict[str, Any]:
    """Test an explicit expression, not expression-to-selected-candidate identity."""
    file = _indexable_source_path(file, "client file")
    _selection_tuple(candidate)
    if not isinstance(expression, str) or not expression.strip():
        raise EvidenceError("an explicit client expression is required")
    haskell_string(expression)
    if any(ord(c) < 32 for c in file):
        raise EvidenceError("client file must not contain control characters")
    if not isinstance(safe, bool) or not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds < 1:
        raise EvidenceError("client safe policy/timeout is invalid")
    if not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool) or max_output_bytes < 1024:
        raise EvidenceError("client output limit must be at least 1024 bytes")
    client_roots = _include_roots(includes)
    library_roots = _library_includes(library_includes)
    client_root = project_root.resolve()
    library_root = library_root.resolve()
    if client_root.is_relative_to(library_root) or library_root.is_relative_to(client_root):
        raise EvidenceError("client and library roots must be separate, non-overlapping directories")
    try:
        manifest, payloads = load_verified_bundle(library_bundle)
        evidence = {"manifest": manifest, "components": payloads}
        _, payloads, index = _evidence(evidence)
        recorded = _object(payloads["resolution.json"], "library recorded resolution")
        library_snapshot = _object(payloads["snapshot.json"], "library snapshot")
        _native_resolution(recorded, library_snapshot, "library recorded resolution")
        selected = select_candidate(index, candidate)
    except EvidenceError as error:
        raise ClientEvidenceError(str(error)) from error
    current_library, library_files = build_snapshot(library_root)
    if current_library["sourceId"] != library_snapshot["sourceId"]:
        raise ClientEvidenceError(f"library source pin mismatch: expected {library_snapshot['sourceId']}, got {current_library['sourceId']}")
    client_snapshot, client_files = build_snapshot(client_root)
    if file not in {record["path"] for record in client_snapshot["files"]}:
        raise EvidenceError("client file is absent from the source snapshot")
    for root, directories in ((client_root, client_roots), (library_root, library_roots)):
        for directory in directories:
            if not (root / directory).is_dir():
                raise EvidenceError(f"include root does not exist: {directory}")
    native = build_resolution(library_root, agda_binary=agda_binary)
    compiler = _native_resolution(native, library_snapshot, "library native resolution")
    if native["resolutionId"] != recorded["resolutionId"]:
        raise ClientEvidenceError(f"library resolution pin mismatch: expected {recorded['resolutionId']}, got {native['resolutionId']}")
    with tempfile.TemporaryDirectory(prefix="agda-evidence-client-") as temporary:
        workspace = Path(temporary) / "workspace"
        for prefix, root, files, directories in (("client", client_root, client_files, client_roots),
                                                  ("library", library_root, library_files, library_roots)):
            target = workspace / prefix
            target.mkdir(parents=True)
            _copy_snapshot(root, files, target)
            for directory in directories:
                (target / directory).mkdir(parents=True, exist_ok=True)
        staged, _ = build_snapshot(workspace)
        if staged["files"] != composed_records(client_snapshot, library_snapshot):
            raise ClientEvidenceError("staged client/library source union differs from captured inputs")
        for root, captured in ((client_root, client_snapshot), (library_root, library_snapshot)):
            current, _ = build_snapshot(root)
            if current["sourceId"] != captured["sourceId"]:
                raise ClientEvidenceError("original client/library source changed during composition preflight")
        inner = infer_type(
            workspace, f"client/{file}", expression, agda_binary=agda_binary,
            includes=effective_includes(client_roots, library_roots), safe=safe,
            timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes,
            _expected_agda=compiler, _expected_source_id=staged["sourceId"],
        )
    observation = {
        "format": CLIENT_FORMAT, "clientObservationId": "",
        "clientSnapshot": client_snapshot,
        "library": {"evidence": evidence, "nativeResolution": native, "candidate": selected},
        "composition": {"policy": COMPOSITION_POLICY, "clientIncludes": client_roots, "libraryIncludes": library_roots},
        "typeObservation": inner,
    }
    observation["clientObservationId"] = client_observation_id(observation)
    return validate_client_observation(observation)


def client_summary(value: dict[str, Any]) -> dict[str, Any]:
    inner = value["typeObservation"]
    payloads = value["library"]["evidence"]["components"]
    return {
        "clientObservationId": value["clientObservationId"],
        "clientSourceId": value["clientSnapshot"]["sourceId"],
        "librarySourceId": payloads["snapshot.json"]["sourceId"],
        "workspaceSourceId": inner["snapshot"]["sourceId"],
        "libraryResolutionId": value["library"]["nativeResolution"]["resolutionId"],
        "workspaceResolutionId": inner["resolution"]["resolutionId"],
        "selection": value["library"]["candidate"],
        "selectionRelation": "lexical-context-only",
        "result": inner["result"],
    }


def write_client_observation(path: Path, value: dict[str, Any]) -> None:
    validate_client_observation(value)
    if path.exists() or path.is_symlink():
        raise EvidenceError(f"client observation output already exists: {path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(canonical_json_bytes(value) + b"\n")
    except OSError as error:
        raise EvidenceError(f"cannot write client observation: {error}") from error


def load_client_observation(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise ClientEvidenceError("client observation must be a regular non-symlinked file")
        return validate_client_observation(_read_json(path))
    except EvidenceError as error:
        raise ClientEvidenceError(str(error)) from error
