#!/usr/bin/env python3
"""Validate local release inputs, without network, Git, installation or Agda.

Reports use release-input-validation-v1: they are release diagnostics, not
Agda evidence certificates or compiler-conformance claims. The caller obtains
REST workflow-run JSON and supplies the expected repository, commit and run ID.
The repository root must be the caller's clean release checkout; this program
compares declared source files, but does not establish Git tracking/cleanliness.
Keep reports outside dist-dir, which must contain exactly the three inputs.
"""
from __future__ import annotations

import argparse
import ast
import base64
import configparser
import csv
from email import policy
from email.parser import BytesParser
import hashlib
import io
import json
import lzma
from pathlib import Path
import re
import stat
import sys
import tarfile
import unicodedata
import zipfile
import zlib


FORMAT = "release-input-validation-v1"
SCHEMA_COUNT = 13
EXPECTED_CI_JOBS = frozenset({
    "test (3.11)", "test (3.12)", "distributions",
    "installed-package (ubuntu-24.04, 3.11)",
    "installed-package (ubuntu-24.04, 3.12)",
    "installed-package (windows-latest, 3.11)",
    "installed-package (windows-latest, 3.12)", "native-installed-package",
})
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
FORBIDDEN_PARTS = frozenset({
    "__pycache__", "node_modules", "venv", "env", "build", "dist",
    "evidence", "raw-evidence", "credentials", "secrets", "vm", "vms", "cloud",
})


class ReleaseInputError(ValueError):
    """A controlled, fail-closed release input validation failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseInputError(message)


def _report(kind: str, **fields: object) -> dict:
    return {"format": FORMAT, "kind": kind, "status": "valid", **fields,
            "scope": "Local release-input diagnostic; not an evidence certificate or compiler claim."}


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_ci_metadata(path: str | Path) -> dict:
    """Read REST workflow-run JSON, rejecting duplicate keys and error shapes."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"),
                           object_pairs_hook=_unique_json_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseInputError(f"cannot read CI metadata: {exc}") from exc
    _require(type(value) is dict, "CI metadata must be a JSON object")
    return value


def validate_ci_jobs(jobs: dict, *, run_id: int) -> list[str]:
    """Require all eight latest CI jobs to be completed/successful for this run."""
    _require(type(run_id) is int and run_id > 0, "expected run ID must be a positive integer, not a boolean")
    _require(type(jobs) is dict and not any(key in jobs for key in ("error", "errors", "message")),
             "CI jobs must be a JSON object without API error fields")
    _require(type(jobs.get("total_count")) is int and jobs["total_count"] == len(EXPECTED_CI_JOBS),
             "CI jobs total_count must be exactly eight")
    entries = jobs.get("jobs")
    _require(type(entries) is list and len(entries) == len(EXPECTED_CI_JOBS),
             "CI jobs must contain exactly eight entries (no missing page or partial run)")
    seen = set()
    for job in entries:
        _require(type(job) is dict, "CI job must be a JSON object")
        name = job.get("name")
        _require(type(name) is str and name in EXPECTED_CI_JOBS and name not in seen,
                 "CI job name is unexpected or duplicated")
        seen.add(name)
        _require(type(job.get("run_id")) is int and job["run_id"] == run_id,
                 f"CI job {name!r} run_id does not match the expected integer")
        _require(job.get("status") == "completed" and job.get("conclusion") == "success",
                 f"CI job {name!r} must be completed and successful (no skipped jobs)")
    _require(seen == EXPECTED_CI_JOBS, "CI expected job set is incomplete")
    return sorted(seen)


def validate_ci_artifacts(artifacts: dict, *, run_id: int, commit: str,
                          repository_id: int, head_repository_id: int) -> dict:
    """Validate the single unexpired same-run alpha-distributions artifact."""
    _require(type(run_id) is int and run_id > 0, "expected run ID must be a positive integer, not a boolean")
    _require(type(commit) is str and re.fullmatch(r"[0-9a-f]{40}", commit) is not None,
             "expected artifact commit must be exactly 40 lowercase hexadecimal characters")
    _require(type(repository_id) is int and repository_id > 0
             and type(head_repository_id) is int and head_repository_id == repository_id,
             "expected artifact repository IDs must be identical positive integers")
    _require(type(artifacts) is dict and not any(key in artifacts for key in ("error", "errors", "message")),
             "CI artifacts must be a JSON object without API error fields")
    _require(type(artifacts.get("total_count")) is int and artifacts["total_count"] == 1,
             "CI artifacts total_count must be exactly one")
    entries = artifacts.get("artifacts")
    _require(type(entries) is list and len(entries) == 1,
             "CI artifacts must contain exactly one entry (no missing page or ambiguous artifact)")
    artifact = entries[0]
    _require(type(artifact) is dict, "CI artifact must be a JSON object")
    _require(artifact.get("name") == f"alpha-distributions-{commit}",
             "CI artifact name does not match the exact source commit")
    _require(artifact.get("expired") is False, "CI artifact expired must be exactly false")
    for field in ("id", "size_in_bytes"):
        _require(type(artifact.get(field)) is int and artifact[field] > 0,
                 f"CI artifact {field} must be a positive integer, not a boolean")
    workflow = artifact.get("workflow_run")
    _require(type(workflow) is dict, "CI artifact workflow_run is missing")
    for field, expected in (("id", run_id), ("repository_id", repository_id),
                            ("head_repository_id", head_repository_id)):
        _require(type(workflow.get(field)) is int and workflow[field] == expected,
                 f"CI artifact workflow_run.{field} does not match the expected integer")
    _require(workflow.get("head_sha") == commit, "CI artifact workflow_run.head_sha does not match source commit")
    return {"id": artifact["id"], "name": artifact["name"], "size_in_bytes": artifact["size_in_bytes"],
            "expired": False, "run_id": run_id, "source_sha": commit,
            "repository_id": repository_id, "head_repository_id": head_repository_id}


def validate_ci_run(metadata: dict, jobs: dict, artifacts: dict, *, repository: str, commit: str, run_id: int) -> dict:
    """Validate same-commit successful push CI, all eight jobs and one artifact."""
    _require(type(repository) is str and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is not None,
             "expected repository must be an owner/name")
    _require(type(commit) is str and re.fullmatch(r"[0-9a-f]{40}", commit) is not None,
             "expected commit must be exactly 40 lowercase hexadecimal characters")
    _require(type(run_id) is int and run_id > 0, "expected run ID must be a positive integer, not a boolean")
    _require(type(metadata) is dict, "CI metadata must be a JSON object")
    _require(not any(key in metadata for key in ("error", "errors", "message")),
             "CI metadata contains an API error field")
    _require(type(metadata.get("id")) is int and metadata["id"] > 0 and metadata["id"] == run_id,
             "CI run ID does not match the expected positive integer")
    for field in ("repository", "head_repository"):
        value = metadata.get(field)
        _require(type(value) is dict and value.get("full_name") == repository,
                 f"CI {field}.full_name does not match the expected repository")
        _require(type(value.get("id")) is int and value["id"] > 0,
                 f"CI {field}.id must be a positive integer, not a boolean")
    repository_id = metadata["repository"]["id"]
    head_repository_id = metadata["head_repository"]["id"]
    _require(repository_id == head_repository_id, "CI repository and head repository IDs differ")
    actual_sha = metadata.get("head_sha")
    _require(type(actual_sha) is str and re.fullmatch(r"[0-9a-f]{40}", actual_sha) is not None
             and actual_sha == commit, "CI head_sha does not match the exact source commit")
    for field, expected in (("path", ".github/workflows/ci.yml"), ("event", "push"),
                            ("status", "completed"), ("conclusion", "success")):
        _require(metadata.get(field) == expected, f"CI {field} must be {expected!r}")
    job_names = validate_ci_jobs(jobs, run_id=run_id)
    artifact = validate_ci_artifacts(artifacts, run_id=run_id, commit=commit,
                                     repository_id=repository_id, head_repository_id=head_repository_id)
    return _report("ci-run", repository=repository, run_id=run_id, source_sha=commit,
                   workflow_path=metadata["path"], event=metadata["event"],
                   status_observed=metadata["status"], conclusion=metadata["conclusion"],
                   repository_id=repository_id, head_repository_id=head_repository_id,
                   job_count=len(job_names), job_names=job_names, artifact=artifact)


def _safe_name(name: str, *, directory: bool = False, public_workflows: bool = False) -> str:
    _require(type(name) is str and bool(name), "archive path is empty")
    _require(not name.startswith("/") and "\\" not in name
             and not any(unicodedata.category(c).startswith("C") for c in name),
             f"unsafe archive path: {name!r}")
    if directory and name.endswith("/"):
        name = name[:-1]
    parts = name.split("/")
    _require(all(part and part not in (".", "..") and ":" not in part for part in parts),
             f"unsafe archive path segments: {name!r}")
    workflow_parts = parts[1:] if parts[0].startswith("agda_evidence-") else parts
    public_path = public_workflows and (
        (directory and workflow_parts in ([".github"], [".github", "workflows"]))
        or (len(workflow_parts) == 3 and workflow_parts[:2] == [".github", "workflows"]
            and not workflow_parts[2].startswith(".") and workflow_parts[2].endswith(".yml")))
    _require(not any((part.startswith(".") and not (part == ".github" and public_path))
                     or part.lower() in FORBIDDEN_PARTS for part in parts),
             f"forbidden private/generated archive path: {name!r}")
    _require(not name.endswith((".pyc", ".pyo", ".agdai")), f"generated archive file: {name!r}")
    return name


def _read_zip(path: Path) -> tuple[dict[str, bytes], set[str]]:
    files, directories, seen = {}, set(), set()
    total = 0
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            is_directory = member.is_dir()
            _require(member.orig_filename == member.filename,
                     f"noncanonical wheel member filename: {member.orig_filename!r}")
            name = _safe_name(member.filename, directory=is_directory)
            _require(name not in seen, f"duplicate wheel member: {name}")
            seen.add(name)
            mode = stat.S_IFMT(member.external_attr >> 16)
            _require(mode in (0, stat.S_IFREG, stat.S_IFDIR), f"nonregular wheel member: {name}")
            _require(mode != stat.S_IFDIR or is_directory, f"wheel directory mode/name mismatch: {name}")
            _require(mode != stat.S_IFREG or not is_directory, f"wheel file mode/name mismatch: {name}")
            _require(not member.flag_bits & 1, f"encrypted wheel member: {name}")
            total += member.file_size
            _require(0 <= member.file_size <= MAX_MEMBER_BYTES and total <= MAX_ARCHIVE_BYTES,
                     "wheel exceeds bounded inspection size")
            if is_directory:
                _require(member.file_size == 0, f"wheel directory contains data: {name}")
                directories.add(name)
            else:
                files[name] = archive.read(member)
    return files, directories


def _read_tar(path: Path) -> tuple[dict[str, bytes], set[str]]:
    files, directories, seen = {}, set(), set()
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            _require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE)
                     and member.sparse is None, f"nonregular sdist member: {member.name!r}")
            name = _safe_name(member.name, directory=member.isdir(), public_workflows=True)
            _require(name not in seen, f"duplicate sdist member: {name}")
            seen.add(name)
            # Extended headers may not redirect/link names or carry private data.
            _require(set(member.pax_headers) <= {"mtime", "atime", "ctime", "path", "size"},
                     f"unsupported sdist extended metadata: {name}")
            total += member.size
            _require(0 <= member.size <= MAX_MEMBER_BYTES and total <= MAX_ARCHIVE_BYTES,
                     "sdist exceeds bounded inspection size")
            if member.isdir():
                _require(member.size == 0, f"sdist directory contains data: {name}")
                directories.add(name)
            else:
                stream = archive.extractfile(member)
                _require(stream is not None, f"cannot read sdist member: {name}")
                with stream:
                    files[name] = stream.read(MAX_MEMBER_BYTES + 1)
                _require(len(files[name]) == member.size, f"truncated sdist member: {name}")
    return files, directories


def _ancestors(names: set[str]) -> set[str]:
    return {"/".join(parts[:i]) for name in names for parts in [name.split("/")]
            for i in range(1, len(parts))}


def _exact_members(files: dict[str, bytes], directories: set[str], expected: set[str], label: str) -> None:
    missing, extra = expected - files.keys(), files.keys() - expected
    _require(not missing, f"{label} missing members: {', '.join(sorted(missing))}")
    _require(not extra, f"{label} unexpected members: {', '.join(sorted(extra))}")
    _require(directories <= _ancestors(expected), f"{label} unexpected directory members")
    _require(not directories.intersection(files), f"{label} file/directory path collision")


def _canonical_bytes(root: Path, relative: str) -> bytes:
    _safe_name(relative, public_workflows=True)
    path = root / relative
    _require(not any(part.is_symlink() for part in [path, *path.parents] if part != root.parent),
             f"canonical source is a symlink: {relative}")
    _require(path.is_file(), f"missing canonical source: {relative}")
    _require(path.stat().st_size <= MAX_MEMBER_BYTES, f"canonical source too large: {relative}")
    return path.read_bytes()


def _source_inventory(root: Path, expected_version: str) -> tuple[dict[str, bytes], dict[str, bytes], int]:
    modules = sorted((root / "src/agda_evidence").glob("*.py"))
    _require(any(path.name == "__init__.py" for path in modules), "canonical package __init__.py is missing")
    schemas = sorted((root / "schemas").glob("*.schema.json"))
    _require(len(schemas) == SCHEMA_COUNT, f"canonical repository must contain exactly {SCHEMA_COUNT} JSON schemas")
    source = {name: _canonical_bytes(root, name) for name in (
        "pyproject.toml", "MANIFEST.in", "LICENSE", "README.md", "CHANGELOG.md", "CONTRIBUTING.md",
        "schemas/__init__.py")}
    wheel = {}
    for path in modules:
        relative = path.relative_to(root).as_posix()
        source[relative] = _canonical_bytes(root, relative)
        wheel[f"agda_evidence/{path.name}"] = source[relative]
    wheel["agda_evidence/schemas/__init__.py"] = source["schemas/__init__.py"]
    for path in schemas:
        relative = path.relative_to(root).as_posix()
        source[relative] = _canonical_bytes(root, relative)
        wheel[f"agda_evidence/schemas/{path.name}"] = source[relative]
    for directory, suffixes in (("schemas", (".py",)), ("docs", (".md",)),
                                ("examples", (".agda", ".agda-lib")),
                                ("scripts", (".py",)), ("tests", (".py",))):
        for path in sorted((root / directory).rglob("*")):
            relative = path.relative_to(root).as_posix()
            parts = relative.split("/")
            # Local generated/hidden work trees are not declared source inputs.
            if any(part.startswith(".") or part.lower() in FORBIDDEN_PARTS for part in parts):
                continue
            if path.suffix in suffixes and not path.is_dir():
                source[relative] = _canonical_bytes(root, relative)
    # Public workflow regression fixtures are explicitly declared in MANIFEST.in;
    # this exception does not permit other .github content or Git metadata.
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        if not path.name.startswith("."):
            relative = path.relative_to(root).as_posix()
            source[relative] = _canonical_bytes(root, relative)
    try:
        tree = ast.parse(source["src/agda_evidence/__init__.py"])
    except (SyntaxError, UnicodeError) as exc:
        raise ReleaseInputError(f"cannot parse canonical version declaration: {exc}") from exc
    versions = []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == "__version__" for target in targets):
            value = node.value
            versions.append(value.value if isinstance(value, ast.Constant) else None)
    _require(versions == [expected_version], "canonical __version__ does not match expected version unambiguously")
    return source, wheel, len(modules)


def _header(message: object, name: str, expected: str, label: str) -> None:
    values = message.get_all(name, [])
    _require(len(values) == 1 and str(values[0]) == expected,
             f"{label} must contain exactly one {name}: {expected}")


def _metadata(data: bytes, expected_version: str, label: str) -> None:
    data.decode("utf-8")
    message = BytesParser(policy=policy.default).parsebytes(data)
    _require(not message.defects and not any(getattr(value, "defects", ()) for value in message.values()),
             f"malformed {label} metadata headers")
    _header(message, "Name", "agda-evidence", label)
    _header(message, "Version", expected_version, label)
    _header(message, "Requires-Python", ">=3.11", label)
    metadata_versions = message.get_all("Metadata-Version", [])
    _require(len(metadata_versions) == 1 and str(metadata_versions[0]) in {"2.1", "2.2", "2.3", "2.4"},
             f"ambiguous/unsupported {label} Metadata-Version")
    _require(not message.get_all("Requires-Dist"), f"{label} declares runtime dependencies")
    _require(not any(str(value).strip().lower() in {"name", "version", "requires-python", "requires-dist"}
                     for value in message.get_all("Dynamic", [])), f"{label} declares dynamic release requirements")


def _entry_points(data: bytes, label: str) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(data.decode("utf-8"))
    _require(parser.defaults() == {} and parser.sections() == ["console_scripts"]
             and dict(parser["console_scripts"]) == {"agda-evidence": "agda_evidence.cli:main"},
             f"unexpected {label} entry points")


def _record(files: dict[str, bytes], record_name: str) -> None:
    seen = set()
    for row in csv.reader(io.StringIO(files[record_name].decode("utf-8")), strict=True):
        _require(len(row) == 3, "malformed wheel RECORD row")
        name, digest, size = row
        _safe_name(name)
        _require(name in files and name not in seen, f"unexpected/duplicate wheel RECORD path: {name}")
        seen.add(name)
        if name == record_name:
            _require(digest == size == "", "wheel RECORD self-entry must have empty digest and size")
        else:
            expected = base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).decode("ascii").rstrip("=")
            _require(digest == f"sha256={expected}" and size == str(len(files[name])),
                     f"wheel RECORD digest/size mismatch: {name}")
    _require(seen == files.keys(), "wheel RECORD must list every file exactly once")


def _validate_wheel(files: dict[str, bytes], directories: set[str], canonical: dict[str, bytes],
                    source: dict[str, bytes], version: str) -> None:
    prefix = f"agda_evidence-{version}.dist-info/"
    licenses = [prefix + name for name in ("licenses/LICENSE", "LICENSE") if prefix + name in files]
    _require(len(licenses) == 1, "wheel must contain exactly one canonical setuptools license file")
    generated = {prefix + name for name in ("METADATA", "WHEEL", "RECORD", "top_level.txt", "entry_points.txt")}
    _exact_members(files, directories, set(canonical) | generated | set(licenses), "wheel")
    for name, expected in canonical.items():
        _require(files[name] == expected, f"wheel canonical source bytes differ: {name}")
    _require(files[licenses[0]] == source["LICENSE"], "wheel license bytes differ from repository")
    _metadata(files[prefix + "METADATA"], version, "wheel METADATA")
    message = BytesParser(policy=policy.default).parsebytes(files[prefix + "WHEEL"])
    _require(not message.defects, "malformed WHEEL headers")
    for name, value in (("Wheel-Version", "1.0"), ("Root-Is-Purelib", "true"), ("Tag", "py3-none-any")):
        _header(message, name, value, "WHEEL")
    _require(files[prefix + "top_level.txt"].decode("utf-8").strip() == "agda_evidence", "unexpected wheel top-level packages")
    _entry_points(files[prefix + "entry_points.txt"], "wheel")
    _record(files, prefix + "RECORD")


def _validate_sdist(files: dict[str, bytes], directories: set[str], source: dict[str, bytes], version: str) -> None:
    prefix = f"agda_evidence-{version}/"
    egg = "src/agda_evidence.egg-info/"
    auto = {"PKG-INFO", "setup.cfg", *(egg + name for name in (
        "PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "top_level.txt"))}
    _exact_members(files, directories, {prefix + name for name in source.keys() | auto}, "sdist")
    for name, expected in source.items():
        _require(files[prefix + name] == expected, f"sdist canonical source bytes differ: {name}")
    for name in ("PKG-INFO", egg + "PKG-INFO"):
        _metadata(files[prefix + name], version, f"sdist {name}")
    _entry_points(files[prefix + egg + "entry_points.txt"], "sdist")
    _require(files[prefix + egg + "top_level.txt"].decode("utf-8").strip() == "agda_evidence", "unexpected sdist top-level packages")
    _require(not files[prefix + egg + "dependency_links.txt"].strip(), "sdist declares dependency links")
    setup = configparser.ConfigParser(interpolation=None)
    setup.read_string(files[prefix + "setup.cfg"].decode("utf-8"))
    _require(setup.defaults() == {} and setup.sections() == ["egg_info"]
             and dict(setup["egg_info"]) == {"tag_build": "", "tag_date": "0"},
             "unexpected generated sdist setup.cfg settings")
    sources = files[prefix + egg + "SOURCES.txt"].decode("utf-8").splitlines()
    for name in sources:
        _safe_name(name, public_workflows=True)
    _require(len(sources) == len(set(sources)) and set(sources) == set(source) | (auto - {"PKG-INFO", "setup.cfg"}),
             "sdist SOURCES.txt does not list the canonical source and egg-info files exactly once")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checksums(path: Path, expected_names: set[str]) -> dict[str, str]:
    data = path.read_bytes().decode("ascii")
    lines = data.splitlines()
    _require(len(lines) == 2, "SHA256SUMS must contain exactly two entries")
    entries = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})[ \t]+([^ \t\r\n]+)", line, flags=re.ASCII)
        _require(match is not None, "malformed SHA256SUMS entry (lowercase SHA256 and basename required)")
        digest, name = match.groups()
        _safe_name(name)
        _require("/" not in name and name in expected_names, f"unexpected SHA256SUMS artifact basename: {name}")
        _require(name not in entries, f"duplicate SHA256SUMS entry: {name}")
        entries[name] = digest
    _require(entries.keys() == expected_names, "SHA256SUMS artifact entries are missing")
    return entries


def validate_distributions(dist_dir: str | Path, repository_root: str | Path, expected_version: str) -> dict:
    """Inspect checksums, archive safety, metadata and canonical source bytes.

    No files are extracted, imported or executed. Declared filesystem selectors
    match MANIFEST.in, not Git state; the caller must provide a clean checkout.
    """
    try:
        _require(type(expected_version) is str and re.fullmatch(
            r"[0-9]+(?:\.[0-9]+)+(?:a[0-9]+|b[0-9]+|rc[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?", expected_version) is not None,
            "expected version must be a canonical release/development version")
        directory, root = Path(dist_dir), Path(repository_root).resolve(strict=True)
        _require(directory.is_dir() and not directory.is_symlink(), "dist-dir must be a regular local directory")
        wheel_name = f"agda_evidence-{expected_version}-py3-none-any.whl"
        sdist_name = f"agda_evidence-{expected_version}.tar.gz"
        names = {wheel_name, sdist_name}
        _require({path.name for path in directory.iterdir()} == names | {"SHA256SUMS"},
                 "dist-dir must contain exactly the canonical wheel, sdist and SHA256SUMS; write reports elsewhere")
        for name in names | {"SHA256SUMS"}:
            path = directory / name
            _require(path.is_file() and not path.is_symlink(), f"release input is not a regular file: {name}")
        expected_digests = _checksums(directory / "SHA256SUMS", names)
        actual_digests = {name: _digest(directory / name) for name in sorted(names)}
        for name in sorted(names):
            _require(actual_digests[name] == expected_digests[name], f"SHA256SUMS digest mismatch: {name}")
        source, wheel_source, module_count = _source_inventory(root, expected_version)
        wheel_files, wheel_dirs = _read_zip(directory / wheel_name)
        _validate_wheel(wheel_files, wheel_dirs, wheel_source, source, expected_version)
        sdist_files, sdist_dirs = _read_tar(directory / sdist_name)
        _validate_sdist(sdist_files, sdist_dirs, source, expected_version)
        return _report("distributions", expected_version=expected_version, module_count=module_count,
                       schema_count=SCHEMA_COUNT, schema_module_count=1, canonical_source_file_count=len(source),
                       artifacts=[{"filename": name, "sha256": actual_digests[name],
                                   "file_count": len(wheel_files if name == wheel_name else sdist_files)}
                                  for name in sorted(names)])
    except ReleaseInputError:
        raise
    except (OSError, UnicodeError, EOFError, tarfile.TarError, zipfile.BadZipFile, zipfile.LargeZipFile,
            zlib.error, lzma.LZMAError,
            RuntimeError, configparser.Error, csv.Error, ValueError) as exc:
        raise ReleaseInputError(f"cannot validate distribution inputs: {exc}") from exc


def _run_id(value: str) -> int:
    if re.fullmatch(r"[1-9][0-9]*", value, flags=re.ASCII) is None:
        raise argparse.ArgumentTypeError("run ID must be a positive decimal integer")
    return int(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ci = commands.add_parser("ci-run", help="validate caller-supplied GitHub REST workflow-run JSON")
    ci.add_argument("--metadata", type=Path, required=True)
    ci.add_argument("--jobs", type=Path, required=True)
    ci.add_argument("--artifacts", type=Path, required=True)
    ci.add_argument("--repository", required=True)
    ci.add_argument("--commit", required=True)
    ci.add_argument("--run-id", type=_run_id, required=True)
    dist = commands.add_parser("distributions", help="validate local wheel, sdist and SHA256SUMS")
    dist.add_argument("--dist-dir", type=Path, required=True)
    dist.add_argument("--repository-root", type=Path, required=True)
    dist.add_argument("--expected-version", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "ci-run":
            report = validate_ci_run(load_ci_metadata(args.metadata), load_ci_metadata(args.jobs),
                                     load_ci_metadata(args.artifacts), repository=args.repository,
                                     commit=args.commit, run_id=args.run_id)
        else:
            report = validate_distributions(args.dist_dir, args.repository_root, args.expected_version)
    except ReleaseInputError as exc:
        print(f"release input validation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
