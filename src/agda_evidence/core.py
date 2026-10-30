"""Core implementation for the agda-evidence reference CLI.

The implementation deliberately captures the evidence it can justify.  It records
an explicit command and visible project configuration; it does not infer a build
policy, resolve packages, or claim a complete dependency closure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Sequence

BUNDLE_FORMAT = "agda-evidence/bundle-v1"
AGGREGATE_FORMAT = "agda-evidence/aggregate-v1"
SNAPSHOT_FORMAT = "agda-evidence/snapshot-v1"
RESOLUTION_FORMAT = "agda-evidence/resolution-v1"
ATTESTATION_FORMAT = "agda-evidence/attestation-v1"
DIAGNOSTICS_FORMAT = "agda-evidence/captured-process-output-v1"
INDEX_REFERENCE_FORMAT = "agda-evidence/index-reference-v1"
DECLARATION_INDEX_FORMAT = "agda-evidence/declaration-index-v1"
LEXICAL_DISCOVERY_FORMAT = "agda-evidence/lexical-discovery-v1"
RESOLUTION_IDENTITY_FORMAT = "agda-evidence/resolution-identity-v1"
ATTESTATION_IDENTITY_FORMAT = "agda-evidence/attestation-identity-v1"
NIX_PROBE_ADAPTER = "agda-evidence/nix-resolution-probe-v1"
AGGREGATE_SCHEMA = "schemas/evidence-aggregate-v1.schema.json"
LANE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,62}")
DECLARATION_KINDS = {"module", "signature", "data", "record", "postulate", "primitive"}
INDEXABLE_SOURCE_SUFFIXES = (".agda", ".lagda.md")
AGDA_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*(?:agda|agda2)\s*$", re.IGNORECASE)
FENCE_CLOSE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")
MODULE_CANDIDATE_RE = re.compile(r"^module\s+([^\s(]+)(?:\s|\().*\bwhere\b")
DECLARATION_CANDIDATE_RES = (
    ("data", re.compile(r"^data\s+([^\s:({]+)")),
    ("record", re.compile(r"^record\s+([^\s:({]+)")),
    ("postulate", re.compile(r"^postulate\s+([^\s:({]+)\s*:")),
    ("primitive", re.compile(r"^primitive\s+([^\s:({]+)\s*:")),
    ("signature", re.compile(r"^([^\s:(){};]+)\s*:")),
)

COMPONENT_FILENAMES = (
    "resolution.json",
    "snapshot.json",
    "attestation.json",
    "diagnostics.json",
)

IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".agda-evidence",
    ".direnv",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
IGNORED_SUFFIXES = {".agdai", ".pyc", ".pyo"}


class EvidenceError(RuntimeError):
    """Raised when evidence cannot be captured without making a weaker claim."""


@dataclass(frozen=True)
class FileEntry:
    relative_path: str
    sha256: str
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.relative_path,
            "sha256": f"sha256:{self.sha256}",
            "size": self.size,
        }


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize data deterministically for stable content identifiers."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_value(value: Any) -> str:
    return digest_bytes(canonical_json_bytes(value))


def _digest_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise EvidenceError(f"{field} must be a sha256 identifier")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise EvidenceError(f"{field} must be a lowercase sha256 identifier")
    return value


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{field} must be an object")
    return value


def _normalised_file_records(files: Any) -> list[dict[str, Any]]:
    if not isinstance(files, list):
        raise EvidenceError("snapshot.files must be an array")
    records: list[dict[str, Any]] = []
    paths: set[str] = set()
    for index, value in enumerate(files):
        record = _object(value, f"snapshot.files[{index}]")
        path = record.get("path")
        size = record.get("size")
        if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
            raise EvidenceError(f"snapshot.files[{index}].path must be a non-absolute slash-separated path")
        if path in paths:
            raise EvidenceError(f"snapshot.files contains duplicate path: {path}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise EvidenceError(f"snapshot.files[{index}].size must be a non-negative integer")
        paths.add(path)
        records.append({"path": path, "sha256": _digest_identifier(record.get("sha256"), f"snapshot.files[{index}].sha256"), "size": size})
    return sorted(records, key=lambda record: record["path"])


def derive_source_id(snapshot: dict[str, Any]) -> str:
    """Return the stable source-tree identity for a snapshot payload.

    Capture time, checkout directory name, and capture policy documentation are
    intentionally absent: this identifier answers only whether the recorded
    regular-file tree is byte-for-byte the same under the current file-listing
    algorithm.
    """

    algorithm = snapshot.get("treeAlgorithm")
    if not isinstance(algorithm, str) or not algorithm:
        raise EvidenceError("snapshot.treeAlgorithm must be a non-empty string")
    identity = {"algorithm": algorithm, "files": _normalised_file_records(snapshot.get("files"))}
    return f"sha256:{digest_value(identity)}"


def _normalised_library_records(library_files: Any) -> list[dict[str, str]]:
    if not isinstance(library_files, list):
        raise EvidenceError("resolution.projectLibraryFiles must be an array")
    records: list[dict[str, str]] = []
    paths: set[str] = set()
    for index, value in enumerate(library_files):
        record = _object(value, f"resolution.projectLibraryFiles[{index}]")
        path = record.get("path")
        if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
            raise EvidenceError(f"resolution.projectLibraryFiles[{index}].path must be a relative path")
        if path in paths:
            raise EvidenceError(f"resolution.projectLibraryFiles contains duplicate path: {path}")
        paths.add(path)
        records.append({"path": path, "sha256": _digest_identifier(record.get("sha256"), f"resolution.projectLibraryFiles[{index}].sha256")})
    return sorted(records, key=lambda record: record["path"])


def resolution_identity_projection(resolution: dict[str, Any]) -> dict[str, Any]:
    """Return the stable, host-path-free projection of visible resolution data."""

    status = resolution.get("resolutionStatus")
    if not isinstance(status, str) or not status:
        raise EvidenceError("resolution.resolutionStatus must be a non-empty string")
    agda = _object(resolution.get("agda"), "resolution.agda")
    requested = agda.get("requested")
    available = agda.get("available")
    if not isinstance(requested, str) or not requested or not isinstance(available, bool):
        raise EvidenceError("resolution.agda must contain requested and available fields")
    agda_projection: dict[str, Any] = {"requested": requested, "available": available}
    if available:
        binary_digest = agda.get("binarySha256")
        if binary_digest is not None:
            agda_projection["binarySha256"] = _digest_identifier(binary_digest, "resolution.agda.binarySha256")
        version = _object(agda.get("version"), "resolution.agda.version")
        agda_projection["version"] = version
    else:
        reason = agda.get("reason")
        if not isinstance(reason, str) or not reason:
            raise EvidenceError("unavailable resolution.agda must contain a reason")
        agda_projection["reason"] = reason

    registry = _object(resolution.get("registry"), "resolution.registry")
    registry_available = registry.get("available")
    if not isinstance(registry_available, bool):
        raise EvidenceError("resolution.registry.available must be boolean")
    registry_projection: dict[str, Any] = {"available": registry_available}
    if registry_available:
        environment = registry.get("agdaDirEnvironment")
        if environment not in {"set", "unset"}:
            raise EvidenceError("resolution.registry.agdaDirEnvironment must be set or unset")
        registries = registry.get("registries")
        if not isinstance(registries, list):
            raise EvidenceError("resolution.registry.registries must be an array")
        records: list[dict[str, str]] = []
        names: set[str] = set()
        for index, value in enumerate(registries):
            record = _object(value, f"resolution.registry.registries[{index}]")
            name = record.get("name")
            if not isinstance(name, str) or not name:
                raise EvidenceError(f"resolution.registry.registries[{index}].name must be a non-empty string")
            if name in names:
                raise EvidenceError(f"resolution.registry.registries contains duplicate name: {name}")
            names.add(name)
            digest_field = "resolutionSha256" if "resolutionSha256" in record else "sha256"
            records.append({"name": name, "sha256": _digest_identifier(record.get(digest_field), f"resolution.registry.registries[{index}].{digest_field}")})
        registry_projection["agdaDirEnvironment"] = environment
        registry_projection["registries"] = sorted(records, key=lambda record: record["name"])
    else:
        reason = registry.get("reason")
        if not isinstance(reason, str) or not reason:
            raise EvidenceError("unavailable resolution.registry must contain a reason")
        registry_projection["reason"] = reason

    projection = {
        "format": RESOLUTION_IDENTITY_FORMAT,
        "resolutionStatus": status,
        "agda": agda_projection,
        "projectLibraryFiles": _normalised_library_records(resolution.get("projectLibraryFiles")),
        "registry": registry_projection,
    }
    if "nix" in resolution:
        nix = _object(resolution.get("nix"), "resolution.nix")
        if nix.get("adapter") != NIX_PROBE_ADAPTER:
            raise EvidenceError("resolution.nix has an unrecognized adapter")
        flake = _object(nix.get("flake"), "resolution.nix.flake")
        projection["nix"] = {
            "adapter": NIX_PROBE_ADAPTER,
            "version": _object(nix.get("version"), "resolution.nix.version"),
            "flake": {
                "flakeNixSha256": _digest_identifier(flake.get("flakeNixSha256"), "resolution.nix.flake.flakeNixSha256"),
                "flakeLockSha256": _digest_identifier(flake.get("flakeLockSha256"), "resolution.nix.flake.flakeLockSha256"),
            },
        }
        # Older v1 Nix observations did not record a system. It remains optional
        # for compatibility, but new probes bind the result into resolutionId.
        if "system" in nix:
            projection["nix"]["system"] = _object(nix.get("system"), "resolution.nix.system")
    return projection


def derive_resolution_id(resolution: dict[str, Any]) -> str:
    return f"sha256:{digest_value(resolution_identity_projection(resolution))}"


def derive_diagnostics_digest(diagnostics: dict[str, Any]) -> str:
    if diagnostics.get("format") != DIAGNOSTICS_FORMAT:
        raise EvidenceError("diagnostics has an unrecognized format")
    return f"sha256:{digest_value(diagnostics)}"


def attestation_identity_projection(attestation: dict[str, Any]) -> dict[str, Any]:
    """Return the time-specific identity projection for a check occurrence."""

    if attestation.get("format") != ATTESTATION_FORMAT:
        raise EvidenceError("attestation has an unrecognized format")
    subjects = _object(attestation.get("subjects"), "attestation.subjects")
    subject_projection = {
        "sourceId": _digest_identifier(subjects.get("sourceId"), "attestation.subjects.sourceId"),
        "resolutionId": _digest_identifier(subjects.get("resolutionId"), "attestation.subjects.resolutionId"),
    }
    diagnostics_digest = _digest_identifier(attestation.get("diagnosticsDigest"), "attestation.diagnosticsDigest")
    command = attestation.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(argument, str) for argument in command):
        raise EvidenceError("attestation.command must be a non-empty string array")
    scope = attestation.get("scope")
    working_directory = attestation.get("workingDirectory")
    recorded_at = attestation.get("recordedAt")
    if not isinstance(scope, str) or not scope or not isinstance(working_directory, str) or not isinstance(recorded_at, str):
        raise EvidenceError("attestation scope, workingDirectory, and recordedAt must be strings")
    execution = _object(attestation.get("execution"), "attestation.execution")
    outcome = _object(attestation.get("outcome"), "attestation.outcome")
    return {
        "format": ATTESTATION_IDENTITY_FORMAT,
        "attestationFormat": ATTESTATION_FORMAT,
        "subjects": subject_projection,
        "diagnosticsDigest": diagnostics_digest,
        "scope": scope,
        "command": command,
        "workingDirectory": working_directory,
        "execution": execution,
        "outcome": outcome,
        "recordedAt": recorded_at,
    }


def derive_attestation_id(attestation: dict[str, Any]) -> str:
    return f"sha256:{digest_value(attestation_identity_projection(attestation))}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _relative_to(path: Path, parent: Path) -> Path | None:
    try:
        return path.resolve().relative_to(parent.resolve())
    except ValueError:
        return None


def _should_skip(relative: Path, is_directory: bool) -> bool:
    if any(part in IGNORED_DIRECTORY_NAMES for part in relative.parts):
        return True
    return not is_directory and relative.suffix in IGNORED_SUFFIXES


def iter_project_files(project_root: Path) -> list[FileEntry]:
    """Return the exact regular-file tree used for the project snapshot.

    Symlinks are rejected rather than followed.  Following them would make the
    recorded project boundary ambiguous and could unintentionally capture files
    outside the project root.
    """

    root = project_root.resolve()
    if not root.is_dir():
        raise EvidenceError(f"project root is not a directory: {project_root}")

    entries: list[FileEntry] = []
    for directory, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        retained_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = current / name
            relative = candidate.relative_to(root)
            if candidate.is_symlink():
                raise EvidenceError(f"symlinked directory is not supported: {relative}")
            if not _should_skip(relative, is_directory=True):
                retained_directories.append(name)
        directory_names[:] = retained_directories

        for name in sorted(file_names):
            candidate = current / name
            relative = candidate.relative_to(root)
            if _should_skip(relative, is_directory=False):
                continue
            if candidate.is_symlink():
                raise EvidenceError(f"symlinked file is not supported: {relative}")
            if not candidate.is_file():
                continue
            entries.append(
                FileEntry(
                    relative_path=relative.as_posix(),
                    sha256=sha256_file(candidate),
                    size=candidate.stat().st_size,
                )
            )
    return sorted(entries, key=lambda entry: entry.relative_path)


def build_snapshot(project_root: Path) -> tuple[dict[str, Any], list[FileEntry]]:
    files = iter_project_files(project_root)
    file_records = [entry.as_dict() for entry in files]
    snapshot = {
        "format": SNAPSHOT_FORMAT,
        "capturedAt": utc_now(),
        "rootName": project_root.resolve().name,
        "treeAlgorithm": "sha256",
        "files": file_records,
        "excludes": {
            "directoryNames": sorted(IGNORED_DIRECTORY_NAMES),
            "suffixes": sorted(IGNORED_SUFFIXES),
            "symlinks": "rejected",
        },
    }
    source_id = derive_source_id(snapshot)
    snapshot["sourceDigest"] = source_id
    snapshot["sourceId"] = source_id
    return snapshot, files


def _indexable_source_path(path: Any, field: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        raise EvidenceError(f"{field} must be a non-absolute slash-separated source path")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise EvidenceError(f"{field} must not contain empty, dot, or parent path segments")
    if not path.endswith(INDEXABLE_SOURCE_SUFFIXES):
        raise EvidenceError(f"{field} must name an .agda or .lagda.md source file")
    return path


def _index_entry_sort_key(entry: dict[str, Any]) -> tuple[str, int, str, str]:
    return (str(entry["path"]), int(entry["line"]), str(entry["kind"]), str(entry["qualifiedName"]))


def _normalised_declaration_entries(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise EvidenceError("declaration index entries must be an array")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    for number, value in enumerate(entries):
        record = _object(value, f"declaration index entries[{number}]")
        expected_fields = {"qualifiedName", "kind", "path", "line", "sourceSha256"}
        if set(record) != expected_fields:
            raise EvidenceError(
                f"declaration index entries[{number}] must contain exactly {', '.join(sorted(expected_fields))}"
            )
        qualified_name = record.get("qualifiedName")
        if not isinstance(qualified_name, str) or not qualified_name or qualified_name.strip() != qualified_name or "\n" in qualified_name:
            raise EvidenceError(f"declaration index entries[{number}].qualifiedName must be a non-empty one-line string")
        kind = record.get("kind")
        if kind not in DECLARATION_KINDS:
            raise EvidenceError(f"declaration index entries[{number}].kind is not a supported lexical candidate kind")
        line = record.get("line")
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            raise EvidenceError(f"declaration index entries[{number}].line must be a positive integer")
        normalized_record = {
            "qualifiedName": qualified_name,
            "kind": kind,
            "path": _indexable_source_path(record.get("path"), f"declaration index entries[{number}].path"),
            "line": line,
            "sourceSha256": _digest_identifier(
                record.get("sourceSha256"), f"declaration index entries[{number}].sourceSha256"
            ),
        }
        key = _index_entry_sort_key(normalized_record)
        if key in seen:
            raise EvidenceError(f"declaration index entries contains a duplicate candidate at {normalized_record['path']}:{line}")
        seen.add(key)
        normalized.append(normalized_record)
    normalized.sort(key=_index_entry_sort_key)
    if entries != normalized:
        raise EvidenceError("declaration index entries must be sorted by path, line, kind, and qualifiedName")
    return normalized


def declaration_index_identity_projection(index: dict[str, Any]) -> dict[str, Any]:
    """Return the deterministic identity projection of a lexical source index."""

    expected_fields = {"format", "indexId", "sourceId", "scanner", "entries"}
    if set(index) != expected_fields:
        raise EvidenceError(f"declaration index must contain exactly {', '.join(sorted(expected_fields))}")
    if index.get("format") != DECLARATION_INDEX_FORMAT:
        raise EvidenceError("declaration index has an unrecognized format")
    scanner = _object(index.get("scanner"), "declaration index scanner")
    if scanner != {"format": LEXICAL_DISCOVERY_FORMAT}:
        raise EvidenceError("declaration index has an unrecognized scanner policy")
    return {
        "format": DECLARATION_INDEX_FORMAT,
        "sourceId": _digest_identifier(index.get("sourceId"), "declaration index sourceId"),
        "scanner": {"format": LEXICAL_DISCOVERY_FORMAT},
        "entries": _normalised_declaration_entries(index.get("entries")),
    }


def derive_declaration_index_id(index: dict[str, Any]) -> str:
    return f"sha256:{digest_value(declaration_index_identity_projection(index))}"


def _qualified_candidate_name(module_name: str | None, name: str) -> str:
    return f"{module_name}.{name}" if module_name else name


def _scan_agda_code_line(
    line: str,
    *,
    path: str,
    line_number: int,
    source_sha256: str,
    module_name: str | None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Return lexical candidates for a physical code line, never a parsed AST claim."""

    if not line or line[:1].isspace():
        return module_name, []
    code = line.split("--", 1)[0].rstrip()
    if not code or code.startswith("{-"):
        return module_name, []
    module_match = MODULE_CANDIDATE_RE.match(code)
    if module_match:
        module_name = module_match.group(1)
        return module_name, [
            {
                "qualifiedName": module_name,
                "kind": "module",
                "path": path,
                "line": line_number,
                "sourceSha256": source_sha256,
            }
        ]
    for kind, pattern in DECLARATION_CANDIDATE_RES:
        candidate_match = pattern.match(code)
        if candidate_match:
            name = candidate_match.group(1)
            return module_name, [
                {
                    "qualifiedName": _qualified_candidate_name(module_name, name),
                    "kind": kind,
                    "path": path,
                    "line": line_number,
                    "sourceSha256": source_sha256,
                }
            ]
    return module_name, []


def _literate_agda_lines(text: str) -> Iterable[tuple[int, str]]:
    """Yield only physical lines in explicitly tagged Markdown Agda fences."""

    opening: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if opening is None:
            match = AGDA_FENCE_RE.match(line)
            if match:
                opening = match.group(1)[0]
            continue
        closing = FENCE_CLOSE_RE.match(line)
        if closing and closing.group(1)[0] == opening:
            opening = None
            continue
        yield line_number, line


def _lexical_candidates_for_file(path: str, text: str, source_sha256: str) -> list[dict[str, Any]]:
    source_lines: Iterable[tuple[int, str]]
    if path.endswith(".lagda.md"):
        source_lines = _literate_agda_lines(text)
    else:
        source_lines = enumerate(text.splitlines(), start=1)
    module_name: str | None = None
    entries: list[dict[str, Any]] = []
    for line_number, line in source_lines:
        module_name, candidates = _scan_agda_code_line(
            line,
            path=path,
            line_number=line_number,
            source_sha256=source_sha256,
            module_name=module_name,
        )
        entries.extend(candidates)
    return entries


def build_declaration_index(project_root: Path, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a deterministic lexical discovery index for snapshot-visible Agda source.

    The scanner intentionally does not invoke Agda or resolve scope. Its records are
    candidate heads found in source text, bound to the source file digest that was
    included in the snapshot.
    """

    root = project_root.resolve()
    if snapshot is None:
        snapshot, _ = build_snapshot(root)
    source_id = derive_source_id(snapshot)
    if snapshot.get("sourceId") != source_id:
        raise EvidenceError("snapshot.sourceId does not match the recorded file tree")
    files = _normalised_file_records(snapshot.get("files"))
    entries: list[dict[str, Any]] = []
    for record in files:
        path = record["path"]
        if not path.endswith(INDEXABLE_SOURCE_SUFFIXES):
            continue
        safe_path = _indexable_source_path(path, "snapshot indexed source path")
        source = root / safe_path
        if source.is_symlink() or not source.is_file() or f"sha256:{sha256_file(source)}" != record["sha256"]:
            raise EvidenceError(f"project changed while building declaration index: {safe_path}")
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise EvidenceError(f"indexed Agda source is not valid UTF-8: {safe_path}") from error
        entries.extend(_lexical_candidates_for_file(safe_path, text, record["sha256"]))
    entries.sort(key=_index_entry_sort_key)
    index: dict[str, Any] = {
        "format": DECLARATION_INDEX_FORMAT,
        "indexId": "",
        "sourceId": source_id,
        "scanner": {"format": LEXICAL_DISCOVERY_FORMAT},
        "entries": entries,
    }
    index["indexId"] = derive_declaration_index_id(index)
    return index


def validate_declaration_index(
    index: dict[str, Any], snapshot: dict[str, Any], project_root: Path | None = None
) -> None:
    """Reject an index that is malformed, stale, or mismatched to a snapshot."""

    expected_index_id = derive_declaration_index_id(index)
    if index.get("indexId") != expected_index_id:
        raise EvidenceError("declaration index indexId does not match its lexical-entry projection")
    source_id = derive_source_id(snapshot)
    if snapshot.get("sourceId") != source_id:
        raise EvidenceError("snapshot.sourceId does not match the recorded file tree")
    if index.get("sourceId") != source_id:
        raise EvidenceError("declaration index sourceId does not match the captured source snapshot")
    source_files = {record["path"]: record["sha256"] for record in _normalised_file_records(snapshot.get("files"))}
    for entry in declaration_index_identity_projection(index)["entries"]:
        path = str(entry["path"])
        if source_files.get(path) != entry["sourceSha256"]:
            raise EvidenceError(f"declaration index entry does not match snapshot source digest: {path}")
    if project_root is not None:
        generated = build_declaration_index(project_root, snapshot)
        if generated != index:
            raise EvidenceError("declaration index does not match the current project's lexical source scan")


def load_declaration_index(path: Path) -> dict[str, Any]:
    index = _object(_read_json(path), "declaration index")
    expected = derive_declaration_index_id(index)
    if index.get("indexId") != expected:
        raise EvidenceError("declaration index indexId does not match its lexical-entry projection")
    return index


def write_declaration_index(path: Path, index: dict[str, Any]) -> None:
    if path.exists():
        raise EvidenceError(f"declaration index output already exists: {path}")
    expected = derive_declaration_index_id(index)
    if index.get("indexId") != expected:
        raise EvidenceError("declaration index indexId does not match its lexical-entry projection")
    _write_json(path, index)


def query_declaration_index(
    index: dict[str, Any], *, exact: str | None = None, prefix: str | None = None, kinds: Iterable[str] = ()
) -> list[dict[str, Any]]:
    """Return deterministic lexical candidates without adding typechecking claims."""

    if exact is not None and prefix is not None:
        raise EvidenceError("declaration-index query accepts at most one of exact and prefix")
    expected = derive_declaration_index_id(index)
    if index.get("indexId") != expected:
        raise EvidenceError("declaration index indexId does not match its lexical-entry projection")
    requested_kinds = set(kinds)
    unsupported_kinds = requested_kinds - DECLARATION_KINDS
    if unsupported_kinds:
        raise EvidenceError(f"unsupported declaration-index kinds: {', '.join(sorted(unsupported_kinds))}")
    matches: list[dict[str, Any]] = []
    for entry in declaration_index_identity_projection(index)["entries"]:
        name = str(entry["qualifiedName"])
        if exact is not None and name != exact:
            continue
        if prefix is not None and not name.startswith(prefix):
            continue
        if requested_kinds and entry["kind"] not in requested_kinds:
            continue
        matches.append(entry)
    return sorted(matches, key=lambda entry: (str(entry["qualifiedName"]), str(entry["kind"]), str(entry["path"]), int(entry["line"])))


def parse_agda_library_file(path: Path, project_root: Path) -> dict[str, Any]:
    """Parse the small declarative subset of an `.agda-lib` file.

    The raw file digest remains authoritative.  This parser is only a convenient
    summary and intentionally does not pretend to reproduce every compiler detail.
    """

    known_fields = {"name", "depend", "include", "flags"}
    fields: dict[str, list[str]] = {key: [] for key in known_fields}
    active: str | None = None
    content = path.read_text(encoding="utf-8")

    for original_line in content.splitlines():
        line = original_line.split("--", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            if key in known_fields:
                active = key
                if value.strip():
                    fields[key].extend(value.split())
                continue
        if active and original_line[:1].isspace():
            fields[active].extend(line.split())
        else:
            active = None

    relative = path.resolve().relative_to(project_root.resolve()).as_posix()
    return {
        "path": relative,
        "sha256": f"sha256:{sha256_file(path)}",
        "fields": {key: values for key, values in fields.items() if values},
    }


def _run_small_command(command: Sequence[str], timeout_seconds: int = 5) -> dict[str, Any]:
    try:
        process = subprocess.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return {"available": False, "reason": "not-found"}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "timed-out"}

    return {
        "available": process.returncode == 0,
        "exitCode": process.returncode,
        "stdout": process.stdout.decode("utf-8", errors="replace").strip(),
        "stderr": process.stderr.decode("utf-8", errors="replace").strip(),
    }


def _path_reference(path: Path) -> str:
    """Avoid publishing host paths while allowing bundle comparisons."""

    return f"path-sha256:{digest_bytes(str(path).encode('utf-8'))}"


def _binary_request_reference(requested: str) -> str:
    """Keep a command name readable but do not disclose an absolute binary path."""

    expanded = Path(requested).expanduser()
    if expanded.is_absolute():
        return _path_reference(expanded)
    return requested


def inspect_agda(agda_binary: str) -> dict[str, Any]:
    resolved = shutil.which(agda_binary)
    if not resolved:
        return {"requested": _binary_request_reference(agda_binary), "available": False, "reason": "not-found"}

    binary_path = Path(resolved).resolve()
    version = _run_small_command([str(binary_path), "--version"])
    app_directory = _run_small_command([str(binary_path), "--print-agda-app-dir"])
    result: dict[str, Any] = {
        "requested": _binary_request_reference(agda_binary),
        "available": True,
        "binaryPathReference": _path_reference(binary_path),
        "binarySha256": f"sha256:{sha256_file(binary_path)}" if binary_path.is_file() else None,
        "version": version,
    }
    if app_directory.get("available") and app_directory.get("stdout"):
        result["appDirectoryReference"] = _path_reference(Path(app_directory["stdout"]))
    return result


def _normalise_registry_entry(entry: str, project_root: Path | None) -> str:
    candidate = Path(entry).expanduser()
    if candidate.is_absolute() and project_root is not None:
        relative = _relative_to(candidate, project_root)
        if relative is not None:
            return f"$PROJECT_ROOT/{relative.as_posix()}"
    if candidate.is_absolute():
        return _path_reference(candidate)
    return entry


def inspect_registry(
    agda_binary: str, agda_info: dict[str, Any], project_root: Path | None = None
) -> dict[str, Any]:
    """Capture registry evidence without exporting absolute machine paths."""

    configured_app_dir = os.environ.get("AGDA_DIR")
    app_dir: Path | None = Path(configured_app_dir).expanduser() if configured_app_dir else None
    if app_dir is None and agda_info.get("available"):
        printed = _run_small_command([agda_binary, "--print-agda-app-dir"])
        if printed.get("available") and printed.get("stdout"):
            app_dir = Path(str(printed["stdout"]))

    if app_dir is None:
        return {"available": False, "reason": "agda-app-directory-unavailable"}

    registry_candidates = sorted(
        [candidate for candidate in app_dir.glob("libraries*") if candidate.is_file()],
        key=lambda candidate: candidate.name,
    )
    registries: list[dict[str, Any]] = []
    for registry in registry_candidates:
        lines = [
            line.strip()
            for line in registry.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith("--")
        ]
        registries.append(
            {
                "name": registry.name,
                "sha256": f"sha256:{sha256_file(registry)}",
                "resolutionSha256": f"sha256:{digest_value({'entries': [_normalise_registry_entry(line, project_root) for line in lines]})}",
                "entryCount": len(lines),
                "entryPathReferences": [_path_reference(Path(line)) for line in lines],
            }
        )
    return {
        "available": True,
        "appDirectoryReference": _path_reference(app_dir),
        "agdaDirEnvironment": "set" if configured_app_dir else "unset",
        "registries": registries,
    }


def build_resolution(project_root: Path, agda_binary: str) -> dict[str, Any]:
    root = project_root.resolve()
    library_files = sorted(root.glob("*.agda-lib"))
    agda_info = inspect_agda(agda_binary)
    resolution = {
        "format": RESOLUTION_FORMAT,
        "capturedAt": utc_now(),
        "projectRootName": root.name,
        "agda": agda_info,
        "projectLibraryFiles": [parse_agda_library_file(path, root) for path in library_files],
        "registry": inspect_registry(agda_binary, agda_info, root),
        "resolutionStatus": "partial",
        "resolutionLimitations": [
            "Records visible project and registry configuration but does not resolve, fetch, or prove a complete dependency closure.",
            "Host paths are replaced with stable opaque references to avoid leaking local filesystem layout.",
        ],
    }
    resolution["resolutionId"] = derive_resolution_id(resolution)
    return resolution


def _unwrap_nix_agda_launcher(agda_info: dict[str, Any], project_root: Path, agda_binary: str) -> dict[str, Any]:
    """Replace the generated project launcher identity with its Nix-store target."""

    resolved = shutil.which(agda_binary)
    if not resolved or not agda_info.get("available"):
        return agda_info
    launcher = Path(resolved).resolve()
    expected_launcher = (project_root / ".agda" / "bin" / "agda").resolve()
    if launcher != expected_launcher or not launcher.is_file():
        return agda_info
    match = re.search(r'exec\s+"([^"]+)"', launcher.read_text(encoding="utf-8", errors="replace"))
    if not match:
        return agda_info
    target = Path(match.group(1))
    if not target.is_file():
        return agda_info
    observed = dict(agda_info)
    observed["binaryPathReference"] = _path_reference(target)
    observed["binarySha256"] = f"sha256:{sha256_file(target)}"
    observed["launcher"] = "project-local-nix-wrapper-unwrapped"
    return observed


def build_nix_resolution(project_root: Path, *, nix_binary: str = "nix", agda_binary: str = "agda") -> dict[str, Any]:
    """Observe an Agda environment already activated by ``nix develop``.

    The caller is responsible for running this command from the same pinned flake
    as the subsequent staged check.  The generated `.agda` directory is observed
    here but must be absent again before the source snapshot is taken.
    """

    root = project_root.resolve()
    flake_nix = root / "flake.nix"
    flake_lock = root / "flake.lock"
    if not flake_nix.is_file() or not flake_lock.is_file():
        raise EvidenceError("Nix resolution probe requires flake.nix and flake.lock in the project root")
    agda_info = _unwrap_nix_agda_launcher(inspect_agda(agda_binary), root, agda_binary)
    if not agda_info.get("available"):
        raise EvidenceError("Nix resolution probe requires an Agda executable on PATH; run it with 'nix develop --command'")
    resolution = {
        "format": RESOLUTION_FORMAT,
        "capturedAt": utc_now(),
        "projectRootName": root.name,
        "agda": agda_info,
        "projectLibraryFiles": [parse_agda_library_file(path, root) for path in sorted(root.glob("*.agda-lib"))],
        "registry": inspect_registry(agda_binary, agda_info, root),
        "nix": {
            "adapter": NIX_PROBE_ADAPTER,
            "version": _run_small_command([nix_binary, "--version"]),
            "system": _run_small_command(
                [nix_binary, "eval", "--raw", "--impure", "--expr", "builtins.currentSystem"]
            ),
            "flake": {
                "flakeNixSha256": f"sha256:{sha256_file(flake_nix)}",
                "flakeLockSha256": f"sha256:{sha256_file(flake_lock)}",
            },
        },
        "resolutionStatus": "partial",
        "resolutionLimitations": [
            "Records a Nix-flake toolchain observation and visible project registry, but does not archive the Nix store closure or prove offline replayability.",
            "The probe must be created from the same pinned flake source as the staged check; it does not authorize inherited host Agda configuration.",
        ],
    }
    resolution["resolutionId"] = derive_resolution_id(resolution)
    return resolution


def _copy_snapshot(project_root: Path, files: Iterable[FileEntry], destination: Path) -> None:
    root = project_root.resolve()
    for entry in files:
        source = root / entry.relative_path
        if not source.is_file() or source.is_symlink():
            raise EvidenceError(f"project changed while being captured: {entry.relative_path}")
        actual = sha256_file(source)
        if actual != entry.sha256:
            raise EvidenceError(f"project changed while being captured: {entry.relative_path}")
        target = destination / entry.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _truncate_output(payload: bytes, limit: int) -> tuple[str, bool, int]:
    total = len(payload)
    retained = payload[:limit]
    return retained.decode("utf-8", errors="replace"), total > limit, total


def run_check(
    command: Sequence[str],
    project_root: Path,
    snapshot_files: Iterable[FileEntry],
    timeout_seconds: int,
    max_output_bytes: int,
    scope: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not command:
        raise EvidenceError("an explicit check command is required after '--'")
    if timeout_seconds <= 0:
        raise EvidenceError("timeout must be positive")
    if max_output_bytes < 1024:
        raise EvidenceError("max output bytes must be at least 1024")

    with tempfile.TemporaryDirectory(prefix="agda-evidence-") as temporary:
        staged_root = Path(temporary) / project_root.resolve().name
        staged_root.mkdir()
        _copy_snapshot(project_root, snapshot_files, staged_root)
        started_at = utc_now()
        timed_out = False
        execution_error: str | None = None
        try:
            process = subprocess.run(
                list(command),
                cwd=staged_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout_seconds,
            )
            stdout, stdout_truncated, stdout_total = _truncate_output(process.stdout, max_output_bytes)
            stderr, stderr_truncated, stderr_total = _truncate_output(process.stderr, max_output_bytes)
            exit_code: int | None = process.returncode
        except subprocess.TimeoutExpired as error:
            timed_out = True
            stdout, stdout_truncated, stdout_total = _truncate_output(error.stdout or b"", max_output_bytes)
            stderr, stderr_truncated, stderr_total = _truncate_output(error.stderr or b"", max_output_bytes)
            exit_code = None
        except OSError as error:
            execution_error = str(error)
            stdout, stdout_truncated, stdout_total = "", False, 0
            stderr, stderr_truncated, stderr_total = "", False, 0
            exit_code = None
        finished_at = utc_now()

        stage_marker = str(staged_root)
        source_marker = str(project_root.resolve())
        stdout = stdout.replace(stage_marker, "$PROJECT_ROOT").replace(source_marker, "$SOURCE_ROOT")
        stderr = stderr.replace(stage_marker, "$PROJECT_ROOT").replace(source_marker, "$SOURCE_ROOT")

    if timed_out:
        status = "timed-out"
    elif execution_error is not None:
        status = "execution-error"
    elif exit_code == 0:
        status = "passed"
    else:
        status = "failed"

    attestation = {
        "format": ATTESTATION_FORMAT,
        "recordedAt": finished_at,
        "scope": scope,
        "command": list(command),
        "workingDirectory": "$PROJECT_ROOT",
        "execution": {
            "mode": "isolated-project-copy",
            "timeoutSeconds": timeout_seconds,
            "interfaceReuse": "not-determined",
        },
        "outcome": {
            "status": status,
            "exitCode": exit_code,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "executionError": execution_error,
        },
    }
    diagnostics = {
        "format": DIAGNOSTICS_FORMAT,
        "normalization": {
            "parser": "none",
            "pathReplacement": ["$PROJECT_ROOT", "$SOURCE_ROOT"],
            "note": "v0.1 retains bounded process output; an Agda diagnostic parser is an adapter concern.",
        },
        "stdout": {"text": stdout, "totalBytes": stdout_total, "truncated": stdout_truncated},
        "stderr": {"text": stderr, "totalBytes": stderr_total, "truncated": stderr_truncated},
    }
    return attestation, diagnostics


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload) + b"\n")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"cannot read JSON file {path}: {error}") from error


def _declaration_index_reference(index_path: Path, index: dict[str, Any]) -> dict[str, Any]:
    """Wrap a verified lexical index as an optional bundle component."""

    return {
        "format": INDEX_REFERENCE_FORMAT,
        "sourcePathReference": _path_reference(index_path.resolve()),
        "inputSha256": f"sha256:{sha256_file(index_path)}",
        "index": index,
    }


def bound_declaration_index(reference: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Validate an index-ref component and return its semantic v1 index when present.

    The former opaque ``content`` shape remains byte-integrity-compatible so old
    bundles can still verify. New captures always use the source-bound ``index``
    shape, which this function validates against snapshot metadata.
    """

    if reference.get("format") != INDEX_REFERENCE_FORMAT:
        raise EvidenceError("index-ref has an unrecognized format")
    if not isinstance(reference.get("sourcePathReference"), str) or not reference["sourcePathReference"]:
        raise EvidenceError("index-ref.sourcePathReference must be a non-empty string")
    _digest_identifier(reference.get("inputSha256"), "index-ref.inputSha256")
    fields = set(reference)
    legacy_fields = {"format", "sourcePathReference", "inputSha256", "content"}
    semantic_fields = {"format", "sourcePathReference", "inputSha256", "index"}
    if fields == legacy_fields:
        return None
    if fields != semantic_fields:
        raise EvidenceError("index-ref must use either the legacy content or source-bound index shape")
    index = _object(reference.get("index"), "index-ref.index")
    validate_declaration_index(index, snapshot)
    return index


def declaration_index_from_bundle(bundle_directory: Path) -> dict[str, Any]:
    """Load a verified source-bound lexical index from an evidence bundle."""

    problems = verify_bundle(bundle_directory)
    if problems:
        raise EvidenceError(f"bundle cannot supply a declaration index: {'; '.join(problems)}")
    root = bundle_directory.resolve()
    bundle = _object(_read_json(root / "bundle.json"), "bundle.json")
    components = _object(bundle.get("components"), "bundle.json components")
    if "index-ref.json" not in components:
        raise EvidenceError("bundle does not contain a declaration index")
    reference = _object(_read_json(root / "index-ref.json"), "index-ref.json")
    snapshot = _object(_read_json(root / "snapshot.json"), "snapshot.json")
    index = bound_declaration_index(reference, snapshot)
    if index is None:
        raise EvidenceError("bundle contains a legacy opaque index reference, not a source-bound declaration index")
    return index


def load_resolution_observation(path: Path) -> dict[str, Any]:
    """Read and semantically verify a resolution handoff before it enters a bundle."""

    resolution = _object(_read_json(path), "resolution observation")
    if resolution.get("format") != RESOLUTION_FORMAT:
        raise EvidenceError("resolution observation has an unrecognized format")
    expected = derive_resolution_id(resolution)
    if resolution.get("resolutionId") != expected:
        raise EvidenceError("resolution observation does not match its visible-resolution projection")
    return resolution


def write_resolution_observation(path: Path, resolution: dict[str, Any]) -> None:
    if path.exists():
        raise EvidenceError(f"resolution observation output already exists: {path}")
    _write_json(path, resolution)


def validate_resolution_for_project(project_root: Path, resolution: dict[str, Any]) -> None:
    """Reject a valid-but-unrelated handoff before binding it to a snapshot."""

    root = project_root.resolve()
    observed_libraries = _normalised_library_records(resolution.get("projectLibraryFiles"))
    current_libraries = _normalised_library_records(
        [parse_agda_library_file(path, root) for path in sorted(root.glob("*.agda-lib"))]
    )
    if observed_libraries != current_libraries:
        raise EvidenceError("supplied resolution observation does not match the project's root .agda-lib files")
    if "nix" not in resolution:
        return
    flake = _object(_object(resolution["nix"], "resolution.nix").get("flake"), "resolution.nix.flake")
    for filename, field in (("flake.nix", "flakeNixSha256"), ("flake.lock", "flakeLockSha256")):
        path = root / filename
        if not path.is_file():
            raise EvidenceError(f"supplied Nix resolution observation requires {filename} in the project root")
        if flake.get(field) != f"sha256:{sha256_file(path)}":
            raise EvidenceError(f"supplied Nix resolution observation does not match {filename}")


def capture_bundle(
    project_root: Path,
    output_directory: Path,
    command: Sequence[str],
    *,
    agda_binary: str = "agda",
    scope: str = "explicit-project-check",
    timeout_seconds: int = 600,
    max_output_bytes: int = 262_144,
    index_reference: Path | None = None,
    resolution_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    output = output_directory.resolve()
    if _relative_to(output, root) is not None:
        raise EvidenceError("output directory must be outside the project root")
    if output.exists() and any(output.iterdir()):
        raise EvidenceError(f"output directory is not empty: {output}")
    if resolution_observation is not None:
        expected_resolution_id = derive_resolution_id(resolution_observation)
        if resolution_observation.get("resolutionId") != expected_resolution_id:
            raise EvidenceError("supplied resolution observation does not match its visible-resolution projection")
        validate_resolution_for_project(root, resolution_observation)
    snapshot, files = build_snapshot(root)
    resolution = resolution_observation if resolution_observation is not None else build_resolution(root, agda_binary)
    index_component: dict[str, Any] | None = None
    if index_reference is not None:
        index = load_declaration_index(index_reference)
        validate_declaration_index(index, snapshot, root)
        index_component = _declaration_index_reference(index_reference, index)

    output.mkdir(parents=True, exist_ok=True)
    attestation, diagnostics = run_check(
        command,
        root,
        files,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        scope=scope,
    )
    attestation["subjects"] = {
        "sourceId": snapshot["sourceId"],
        "resolutionId": resolution["resolutionId"],
    }
    attestation["diagnosticsDigest"] = derive_diagnostics_digest(diagnostics)
    attestation["attestationId"] = derive_attestation_id(attestation)

    components: dict[str, Any] = {
        "resolution.json": resolution,
        "snapshot.json": snapshot,
        "attestation.json": attestation,
        "diagnostics.json": diagnostics,
    }
    if index_component is not None:
        components["index-ref.json"] = index_component

    component_digests: dict[str, str] = {}
    for filename, payload in components.items():
        _write_json(output / filename, payload)
        component_digests[filename] = f"sha256:{digest_value(payload)}"

    bundle_identity = {
        "format": BUNDLE_FORMAT,
        "components": component_digests,
    }
    bundle = {
        **bundle_identity,
        "bundleId": f"sha256:{digest_value(bundle_identity)}",
        "createdAt": utc_now(),
        "schema": "schemas/evidence-bundle-v1.schema.json",
        "components": component_digests,
        "limitations": [
            "This bundle does not prove a complete dependency closure or offline replayability.",
            "A passed outcome reports only the explicit recorded command and scope.",
        ],
    }
    _write_json(output / "bundle.json", bundle)
    return bundle


CORE_COMPONENT_FILENAMES = {"snapshot.json", "resolution.json", "attestation.json", "diagnostics.json"}


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise EvidenceError(f"{field} must be an RFC 3339 timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"{field} must be an RFC 3339 timestamp string") from error
    if parsed.tzinfo is None:
        raise EvidenceError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _verify_enhanced_timestamps(
    snapshot: dict[str, Any],
    resolution: dict[str, Any],
    attestation: dict[str, Any],
    bundle: dict[str, Any],
) -> list[str]:
    try:
        snapshot_at = _parse_timestamp(snapshot.get("capturedAt"), "snapshot.capturedAt")
        resolution_at = _parse_timestamp(resolution.get("capturedAt"), "resolution.capturedAt")
        outcome = _object(attestation.get("outcome"), "attestation.outcome")
        started_at = _parse_timestamp(outcome.get("startedAt"), "attestation.outcome.startedAt")
        finished_at = _parse_timestamp(outcome.get("finishedAt"), "attestation.outcome.finishedAt")
        recorded_at = _parse_timestamp(attestation.get("recordedAt"), "attestation.recordedAt")
        bundle_at = _parse_timestamp(bundle.get("createdAt"), "bundle.createdAt")
    except EvidenceError as error:
        return [str(error)]

    problems: list[str] = []
    if snapshot_at > started_at:
        problems.append("snapshot.capturedAt is later than the check start")
    if resolution_at > started_at:
        problems.append("resolution.capturedAt is later than the check start")
    if started_at > finished_at:
        problems.append("attestation check start is later than its finish")
    if finished_at > recorded_at:
        problems.append("attestation.recordedAt is earlier than the check finish")
    if recorded_at > bundle_at:
        problems.append("bundle.createdAt is earlier than attestation.recordedAt")
    return problems


def _verify_enhanced_identities(
    payloads: dict[str, Any], bundle: dict[str, Any]
) -> list[str]:
    try:
        snapshot = _object(payloads["snapshot.json"], "snapshot.json")
        resolution = _object(payloads["resolution.json"], "resolution.json")
        attestation = _object(payloads["attestation.json"], "attestation.json")
        diagnostics = _object(payloads["diagnostics.json"], "diagnostics.json")
    except EvidenceError as error:
        return [str(error)]
    enhanced_fields = [
        "sourceId" in snapshot,
        "resolutionId" in resolution,
        "subjects" in attestation,
        "diagnosticsDigest" in attestation,
        "attestationId" in attestation,
    ]
    if not any(enhanced_fields):
        return []
    if not all(enhanced_fields):
        return ["bundle has a partial enhanced identity profile"]

    problems: list[str] = []
    try:
        source_id = derive_source_id(snapshot)
        if snapshot.get("sourceDigest") != source_id:
            problems.append("snapshot.sourceDigest does not match the recorded file tree")
        if snapshot.get("sourceId") != source_id:
            problems.append("snapshot.sourceId does not match the recorded file tree")

        resolution_id = derive_resolution_id(resolution)
        if resolution.get("resolutionId") != resolution_id:
            problems.append("resolution.resolutionId does not match its visible-resolution projection")

        diagnostics_digest = derive_diagnostics_digest(diagnostics)
        if attestation.get("diagnosticsDigest") != diagnostics_digest:
            problems.append("attestation.diagnosticsDigest does not match diagnostics.json")

        subjects = _object(attestation.get("subjects"), "attestation.subjects")
        if subjects.get("sourceId") != source_id:
            problems.append("attestation.subjects.sourceId does not match snapshot.sourceId")
        if subjects.get("resolutionId") != resolution_id:
            problems.append("attestation.subjects.resolutionId does not match resolution.resolutionId")

        attestation_id = derive_attestation_id(attestation)
        if attestation.get("attestationId") != attestation_id:
            problems.append("attestation.attestationId does not match its time-specific projection")
    except EvidenceError as error:
        problems.append(str(error))
        return problems

    return problems + _verify_enhanced_timestamps(snapshot, resolution, attestation, bundle)


def verify_bundle(bundle_directory: Path) -> list[str]:
    root = bundle_directory.resolve()
    problems: list[str] = []
    try:
        bundle = _read_json(root / "bundle.json")
    except EvidenceError as error:
        return [str(error)]

    if bundle.get("format") != BUNDLE_FORMAT:
        problems.append("bundle.json has an unrecognized format")
    components = bundle.get("components")
    if not isinstance(components, dict):
        return problems + ["bundle.json does not contain a components object"]

    payloads: dict[str, Any] = {}
    for filename, expected in sorted(components.items()):
        if not isinstance(filename, str) or "/" in filename or "\\" in filename:
            problems.append(f"unsafe component filename: {filename!r}")
            continue
        component_path = root / filename
        if not component_path.is_file():
            problems.append(f"missing component: {filename}")
            continue
        try:
            payload = _read_json(component_path)
        except EvidenceError as error:
            problems.append(str(error))
            continue
        payloads[filename] = payload
        actual = f"sha256:{digest_value(payload)}"
        if actual != expected:
            problems.append(f"digest mismatch for {filename}: expected {expected}, got {actual}")

    identity = {"format": bundle.get("format"), "components": components}
    expected_bundle_id = f"sha256:{digest_value(identity)}"
    if bundle.get("bundleId") != expected_bundle_id:
        problems.append("bundleId does not match the listed component digests")

    missing_core_components = sorted(CORE_COMPONENT_FILENAMES - set(payloads))
    if missing_core_components:
        problems.append(f"missing required core components: {', '.join(missing_core_components)}")
        return problems
    problems.extend(_verify_enhanced_identities(payloads, bundle))
    if "index-ref.json" in payloads:
        try:
            bound_declaration_index(
                _object(payloads["index-ref.json"], "index-ref.json"),
                _object(payloads["snapshot.json"], "snapshot.json"),
            )
        except EvidenceError as error:
            problems.append(str(error))
    return problems


def _lane_name(value: Any, field: str = "lane name") -> str:
    if not isinstance(value, str) or not LANE_NAME_RE.fullmatch(value):
        raise EvidenceError(f"{field} must match {LANE_NAME_RE.pattern!r}")
    return value


def _green_outcome(value: Any, field: str) -> dict[str, Any]:
    outcome = _object(value, field)
    if set(outcome) != {"status", "exitCode"}:
        raise EvidenceError(f"{field} must contain only status and exitCode")
    exit_code = outcome.get("exitCode")
    if outcome.get("status") != "passed" or not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code != 0:
        raise EvidenceError(f"{field} must report passed with exitCode 0")
    return {"status": "passed", "exitCode": 0}


def _aggregate_lane_record(value: Any, field: str) -> dict[str, Any]:
    record = _object(value, field)
    expected_fields = {"bundleId", "sourceId", "resolutionId", "attestationId", "outcome"}
    if set(record) != expected_fields:
        raise EvidenceError(f"{field} must contain exactly {', '.join(sorted(expected_fields))}")
    return {
        "bundleId": _digest_identifier(record.get("bundleId"), f"{field}.bundleId"),
        "sourceId": _digest_identifier(record.get("sourceId"), f"{field}.sourceId"),
        "resolutionId": _digest_identifier(record.get("resolutionId"), f"{field}.resolutionId"),
        "attestationId": _digest_identifier(record.get("attestationId"), f"{field}.attestationId"),
        "outcome": _green_outcome(record.get("outcome"), f"{field}.outcome"),
    }


def aggregate_identity_projection(aggregate: dict[str, Any]) -> dict[str, Any]:
    """Return the stable lane-selection identity for a closed aggregate."""

    if aggregate.get("format") != AGGREGATE_FORMAT:
        raise EvidenceError("aggregate.json has an unrecognized format")
    source_id = _digest_identifier(aggregate.get("sourceId"), "aggregate.sourceId")
    lanes = aggregate.get("lanes")
    if not isinstance(lanes, dict) or not lanes:
        raise EvidenceError("aggregate.lanes must be a non-empty object")
    normalized_lanes: dict[str, dict[str, Any]] = {}
    for name, record in lanes.items():
        lane_name = _lane_name(name, "aggregate.lanes key")
        normalized_lanes[lane_name] = _aggregate_lane_record(record, f"aggregate.lanes.{lane_name}")
    return {
        "format": AGGREGATE_FORMAT,
        "sourceId": source_id,
        "lanes": {name: normalized_lanes[name] for name in sorted(normalized_lanes)},
    }


def derive_aggregate_id(aggregate: dict[str, Any]) -> str:
    return f"sha256:{digest_value(aggregate_identity_projection(aggregate))}"


def _enhanced_green_bundle_record(bundle_directory: Path, context: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the aggregate lane record and child manifest for one verified bundle."""

    problems = verify_bundle(bundle_directory)
    if problems:
        raise EvidenceError(f"{context} is not a valid bundle: {'; '.join(problems)}")
    bundle = _object(_read_json(bundle_directory / "bundle.json"), f"{context} bundle.json")
    snapshot = _object(_read_json(bundle_directory / "snapshot.json"), f"{context} snapshot.json")
    resolution = _object(_read_json(bundle_directory / "resolution.json"), f"{context} resolution.json")
    attestation = _object(_read_json(bundle_directory / "attestation.json"), f"{context} attestation.json")

    required_fields = {
        "sourceId": snapshot.get("sourceId"),
        "resolutionId": resolution.get("resolutionId"),
        "attestationId": attestation.get("attestationId"),
    }
    if any(value is None for value in required_fields.values()):
        raise EvidenceError(f"{context} must use the complete enhanced identity profile")
    outcome = _object(attestation.get("outcome"), f"{context} attestation.outcome")
    if outcome.get("executionError") is not None:
        raise EvidenceError(f"{context} has an execution error and cannot be aggregated")
    lane_record = {
        "bundleId": _digest_identifier(bundle.get("bundleId"), f"{context} bundleId"),
        "sourceId": _digest_identifier(snapshot.get("sourceId"), f"{context} sourceId"),
        "resolutionId": _digest_identifier(resolution.get("resolutionId"), f"{context} resolutionId"),
        "attestationId": _digest_identifier(attestation.get("attestationId"), f"{context} attestationId"),
        "outcome": _green_outcome(
            {"status": outcome.get("status"), "exitCode": outcome.get("exitCode")},
            f"{context} attestation.outcome",
        ),
    }
    return lane_record, bundle


def _copy_verified_bundle(source: Path, destination: Path, bundle: dict[str, Any]) -> None:
    """Materialize only a verified child manifest and its declared components."""

    components = bundle.get("components")
    if not isinstance(components, dict):
        raise EvidenceError("verified child bundle does not contain a components object")
    destination.mkdir(parents=True, exist_ok=False)
    for filename in ["bundle.json", *sorted(components)]:
        source_file = source / filename
        if source_file.is_symlink() or not source_file.is_file():
            raise EvidenceError(f"cannot materialize unsafe child bundle file: {source_file}")
        shutil.copy2(source_file, destination / filename)


def _verify_closed_child_directory(child_root: Path, lane_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if child_root.is_symlink() or not child_root.is_dir():
        raise EvidenceError(f"aggregate lane {lane_name} is missing its fixed child directory")
    lane_record, bundle = _enhanced_green_bundle_record(child_root, f"aggregate lane {lane_name}")
    components = bundle.get("components")
    if not isinstance(components, dict):
        raise EvidenceError(f"aggregate lane {lane_name} does not contain a components object")
    expected_names = {"bundle.json", *components}
    actual_names: set[str] = set()
    for entry in child_root.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise EvidenceError(f"aggregate lane {lane_name} contains an unsafe child entry: {entry.name}")
        actual_names.add(entry.name)
    if actual_names != expected_names:
        unexpected = sorted(actual_names - expected_names)
        missing = sorted(expected_names - actual_names)
        details: list[str] = []
        if unexpected:
            details.append(f"unexpected files: {', '.join(unexpected)}")
        if missing:
            details.append(f"missing files: {', '.join(missing)}")
        raise EvidenceError(f"aggregate lane {lane_name} is not a closed child bundle ({'; '.join(details)})")
    return lane_record, bundle


def create_aggregate(
    output_directory: Path,
    lane_inputs: Sequence[tuple[str, Path]],
) -> dict[str, Any]:
    """Create a self-contained, green aggregate from verified child bundles."""

    output = output_directory.resolve()
    if output.exists():
        if not output.is_dir():
            raise EvidenceError(f"aggregate output path is not a directory: {output}")
        if any(output.iterdir()):
            raise EvidenceError(f"output directory is not empty: {output}")
    if not lane_inputs:
        raise EvidenceError("at least one --lane NAME=BUNDLE input is required")

    child_data: list[tuple[str, Path, dict[str, Any], dict[str, Any]]] = []
    names: set[str] = set()
    bundle_ids: set[str] = set()
    attestation_ids: set[str] = set()
    source_ids: set[str] = set()
    for raw_name, raw_path in lane_inputs:
        name = _lane_name(raw_name)
        if name in names:
            raise EvidenceError(f"aggregate lane name is repeated: {name}")
        names.add(name)
        source = raw_path.resolve()
        record, bundle = _enhanced_green_bundle_record(source, f"aggregate lane {name}")
        if record["bundleId"] in bundle_ids:
            raise EvidenceError(f"aggregate cannot count the same bundle twice: {record['bundleId']}")
        if record["attestationId"] in attestation_ids:
            raise EvidenceError(f"aggregate cannot count the same attestation twice: {record['attestationId']}")
        bundle_ids.add(record["bundleId"])
        attestation_ids.add(record["attestationId"])
        source_ids.add(record["sourceId"])
        child_data.append((name, source, record, bundle))
    if len(source_ids) != 1:
        raise EvidenceError("aggregate child bundles must have one identical sourceId")

    output.mkdir(parents=True, exist_ok=True)
    lanes_directory = output / "lanes"
    lanes_directory.mkdir()
    lanes: dict[str, dict[str, Any]] = {}
    for name, source, record, bundle in sorted(child_data, key=lambda item: item[0]):
        _copy_verified_bundle(source, lanes_directory / name, bundle)
        lanes[name] = record
    aggregate = {
        "format": AGGREGATE_FORMAT,
        "createdAt": utc_now(),
        "schema": AGGREGATE_SCHEMA,
        "sourceId": next(iter(source_ids)),
        "lanes": lanes,
        "limitations": [
            "Each lane attests only its included child bundle's explicit command and scope.",
            "Lane resolution observations are partial and are not compared, merged, or treated as a dependency closure.",
            "This aggregate does not establish all-project CI coverage, offline replayability, signatures, authorship, or trust.",
        ],
    }
    aggregate["aggregateId"] = derive_aggregate_id(aggregate)
    _write_json(output / "aggregate.json", aggregate)
    problems = verify_aggregate(output)
    if problems:
        raise EvidenceError(f"created aggregate did not verify: {'; '.join(problems)}")
    return aggregate


def verify_aggregate(aggregate_directory: Path) -> list[str]:
    """Verify a closed aggregate and every child bundle it includes."""

    if aggregate_directory.is_symlink():
        return ["aggregate directory must not be a symlink"]
    root = aggregate_directory.resolve()
    if not root.is_dir():
        return [f"aggregate directory is not a directory: {aggregate_directory}"]
    manifest_path = root / "aggregate.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return ["aggregate is missing a regular aggregate.json manifest"]
    root_entries = {entry.name for entry in root.iterdir()}
    if root_entries != {"aggregate.json", "lanes"}:
        unexpected = sorted(root_entries - {"aggregate.json", "lanes"})
        missing = sorted({"aggregate.json", "lanes"} - root_entries)
        details: list[str] = []
        if unexpected:
            details.append(f"unexpected entries: {', '.join(unexpected)}")
        if missing:
            details.append(f"missing entries: {', '.join(missing)}")
        return [f"aggregate directory is not closed ({'; '.join(details)})"]
    try:
        aggregate = _object(_read_json(manifest_path), "aggregate.json")
        expected_root_fields = {"format", "aggregateId", "createdAt", "schema", "sourceId", "lanes", "limitations"}
        if set(aggregate) != expected_root_fields:
            return [f"aggregate.json must contain exactly {', '.join(sorted(expected_root_fields))}"]
        if aggregate.get("schema") != AGGREGATE_SCHEMA:
            return ["aggregate.json has an unrecognized schema path"]
        _parse_timestamp(aggregate.get("createdAt"), "aggregate.createdAt")
        limitations = aggregate.get("limitations")
        if not isinstance(limitations, list) or not all(isinstance(value, str) for value in limitations):
            return ["aggregate.limitations must be a string array"]
        identity = aggregate_identity_projection(aggregate)
    except EvidenceError as error:
        return [str(error)]

    problems: list[str] = []
    expected_aggregate_id = f"sha256:{digest_value(identity)}"
    if aggregate.get("aggregateId") != expected_aggregate_id:
        problems.append("aggregateId does not match the selected lane records")

    source_id = identity["sourceId"]
    lanes = identity["lanes"]
    if not isinstance(lanes, dict):  # Satisfies static type narrowing and is unreachable after projection.
        return problems + ["aggregate.lanes must be an object"]
    lanes_directory = root / "lanes"
    if lanes_directory.is_symlink() or not lanes_directory.is_dir():
        return problems + ["aggregate is missing its fixed lanes directory"]
    actual_lane_names = {entry.name for entry in lanes_directory.iterdir()}
    expected_lane_names = set(lanes)
    if actual_lane_names != expected_lane_names:
        unexpected = sorted(actual_lane_names - expected_lane_names)
        missing = sorted(expected_lane_names - actual_lane_names)
        details: list[str] = []
        if unexpected:
            details.append(f"unexpected lanes: {', '.join(unexpected)}")
        if missing:
            details.append(f"missing lanes: {', '.join(missing)}")
        problems.append(f"aggregate lanes directory is not closed ({'; '.join(details)})")
    bundle_ids: set[str] = set()
    attestation_ids: set[str] = set()
    for name, claimed_record in lanes.items():
        try:
            actual_record, _ = _verify_closed_child_directory(root / "lanes" / name, name)
        except EvidenceError as error:
            problems.append(str(error))
            continue
        if actual_record != claimed_record:
            problems.append(f"aggregate lane {name} does not match its included child bundle")
        if actual_record["sourceId"] != source_id:
            problems.append(f"aggregate lane {name} has a different sourceId")
        bundle_id = actual_record["bundleId"]
        attestation_id = actual_record["attestationId"]
        if bundle_id in bundle_ids:
            problems.append(f"aggregate duplicates child bundleId: {bundle_id}")
        if attestation_id in attestation_ids:
            problems.append(f"aggregate duplicates child attestationId: {attestation_id}")
        bundle_ids.add(bundle_id)
        attestation_ids.add(attestation_id)
    return problems
