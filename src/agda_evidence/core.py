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
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Sequence

BUNDLE_FORMAT = "agda-evidence/bundle-v1"
SNAPSHOT_FORMAT = "agda-evidence/snapshot-v1"
RESOLUTION_FORMAT = "agda-evidence/resolution-v1"
ATTESTATION_FORMAT = "agda-evidence/attestation-v1"
DIAGNOSTICS_FORMAT = "agda-evidence/captured-process-output-v1"
INDEX_REFERENCE_FORMAT = "agda-evidence/index-reference-v1"

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
    tree_digest = digest_value({"algorithm": "sha256", "files": file_records})
    return (
        {
            "format": SNAPSHOT_FORMAT,
            "capturedAt": utc_now(),
            "rootName": project_root.resolve().name,
            "treeAlgorithm": "sha256",
            "sourceDigest": f"sha256:{tree_digest}",
            "files": file_records,
            "excludes": {
                "directoryNames": sorted(IGNORED_DIRECTORY_NAMES),
                "suffixes": sorted(IGNORED_SUFFIXES),
                "symlinks": "rejected",
            },
        },
        files,
    )


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


def inspect_agda(agda_binary: str) -> dict[str, Any]:
    resolved = shutil.which(agda_binary)
    if not resolved:
        return {"requested": agda_binary, "available": False, "reason": "not-found"}

    binary_path = Path(resolved).resolve()
    version = _run_small_command([str(binary_path), "--version"])
    app_directory = _run_small_command([str(binary_path), "--print-agda-app-dir"])
    result: dict[str, Any] = {
        "requested": agda_binary,
        "available": True,
        "binaryPathReference": _path_reference(binary_path),
        "binarySha256": f"sha256:{sha256_file(binary_path)}" if binary_path.is_file() else None,
        "version": version,
    }
    if app_directory.get("available") and app_directory.get("stdout"):
        result["appDirectoryReference"] = _path_reference(Path(app_directory["stdout"]))
    return result


def inspect_registry(agda_binary: str, agda_info: dict[str, Any]) -> dict[str, Any]:
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
    return {
        "format": RESOLUTION_FORMAT,
        "capturedAt": utc_now(),
        "projectRootName": root.name,
        "agda": agda_info,
        "projectLibraryFiles": [parse_agda_library_file(path, root) for path in library_files],
        "registry": inspect_registry(agda_binary, agda_info),
        "resolutionStatus": "partial",
        "resolutionLimitations": [
            "Records visible project and registry configuration but does not resolve, fetch, or prove a complete dependency closure.",
            "Host paths are replaced with stable opaque references to avoid leaking local filesystem layout.",
        ],
    }


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
) -> dict[str, Any]:
    root = project_root.resolve()
    output = output_directory.resolve()
    if _relative_to(output, root) is not None:
        raise EvidenceError("output directory must be outside the project root")
    if output.exists() and any(output.iterdir()):
        raise EvidenceError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    snapshot, files = build_snapshot(root)
    resolution = build_resolution(root, agda_binary)
    attestation, diagnostics = run_check(
        command,
        root,
        files,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        scope=scope,
    )

    components: dict[str, Any] = {
        "resolution.json": resolution,
        "snapshot.json": snapshot,
        "attestation.json": attestation,
        "diagnostics.json": diagnostics,
    }
    if index_reference is not None:
        reference_payload = _read_json(index_reference)
        components["index-ref.json"] = {
            "format": INDEX_REFERENCE_FORMAT,
            "sourcePathReference": _path_reference(index_reference.resolve()),
            "inputSha256": f"sha256:{sha256_file(index_reference)}",
            "content": reference_payload,
        }

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
        actual = f"sha256:{digest_value(payload)}"
        if actual != expected:
            problems.append(f"digest mismatch for {filename}: expected {expected}, got {actual}")

    identity = {"format": bundle.get("format"), "components": components}
    expected_bundle_id = f"sha256:{digest_value(identity)}"
    if bundle.get("bundleId") != expected_bundle_id:
        problems.append("bundleId does not match the listed component digests")
    return problems
