"""Explicit local discovery references, not an Agda environment or archive."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

from .core import (
    EvidenceError,
    _digest_identifier,
    _object,
    _read_json,
    canonical_json_bytes,
    declaration_index_from_payloads,
    load_verified_bundle,
    query_declaration_index,
)

CATALOG_FORMAT = "agda-evidence/local-catalog-v1"
CATALOG_QUERY_FORMAT = "agda-evidence/catalog-query-v1"
CATALOG_VERIFY_FORMAT = "agda-evidence/catalog-verification-v1"
ENTRY_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,62}")
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


class CatalogConfigError(EvidenceError):
    """The local catalog is malformed (CLI exit 2)."""


class CatalogValidationError(EvidenceError):
    """An entry is missing, invalid, aliased, or disagrees with a pin (exit 1)."""


@dataclass(frozen=True)
class CatalogEntry:
    index: dict[str, Any]
    evidence: dict[str, Any]


def _entry_name(value: Any) -> str:
    if not isinstance(value, str) or not ENTRY_NAME_RE.fullmatch(value):
        raise CatalogConfigError(f"catalog entry name must match {ENTRY_NAME_RE.pattern!r}")
    return value


def _local_path(value: Any) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise CatalogConfigError("catalog bundle must be a non-empty local path without control characters")
    if URI_SCHEME_RE.match(value) or value.startswith("//"):
        raise CatalogConfigError("catalog bundle must be a local path, not a URL or URI")
    return value


def validate_catalog_config(value: Any) -> dict[str, Any]:
    """Validate exact config shape without opening a referenced bundle."""

    try:
        catalog = _object(value, "catalog")
        if set(catalog) != {"format", "entries"} or catalog.get("format") != CATALOG_FORMAT:
            raise CatalogConfigError(f"catalog must contain only format={CATALOG_FORMAT!r} and entries")
        entries = _object(catalog.get("entries"), "catalog.entries")
        if not entries:
            raise CatalogConfigError("catalog.entries must not be empty")
        for name, raw in entries.items():
            _entry_name(name)
            entry = _object(raw, f"catalog entry {name}")
            if set(entry) != {"bundle", "expected"}:
                raise CatalogConfigError(f"catalog entry {name} must contain only bundle and expected")
            _local_path(entry["bundle"])
            expected = _object(entry["expected"], f"catalog entry {name}.expected")
            if set(expected) != {"sourceId", "resolutionId"}:
                raise CatalogConfigError(f"catalog entry {name}.expected must contain only sourceId and resolutionId")
            for field in ("sourceId", "resolutionId"):
                _digest_identifier(expected[field], f"catalog entry {name}.expected.{field}")
        return catalog
    except EvidenceError as error:
        raise CatalogConfigError(str(error)) from error


def load_catalog(path: Path) -> dict[str, Any]:
    try:
        return validate_catalog_config(_read_json(path))
    except EvidenceError as error:
        raise CatalogConfigError(str(error)) from error


def _indexed_evidence(path: Path, name: str) -> CatalogEntry:
    """Use one verified payload set for pins, outcomes, and lexical candidates."""

    try:
        manifest, payloads = load_verified_bundle(path)
        index = declaration_index_from_payloads(payloads)
        snapshot = _object(payloads["snapshot.json"], "snapshot.json")
        resolution = _object(payloads["resolution.json"], "resolution.json")
        attestation = _object(payloads["attestation.json"], "attestation.json")
        evidence = {
            "entry": name,
            "bundleId": _digest_identifier(manifest.get("bundleId"), "bundleId"),
            "sourceId": _digest_identifier(snapshot.get("sourceId"), "enhanced sourceId"),
            "resolutionId": _digest_identifier(resolution.get("resolutionId"), "enhanced resolutionId"),
            "attestationId": _digest_identifier(attestation.get("attestationId"), "enhanced attestationId"),
            "indexId": index["indexId"],
            "scope": attestation["scope"],
            "command": attestation["command"],
            "outcome": attestation["outcome"],
        }
        return CatalogEntry(index=index, evidence=evidence)
    except (EvidenceError, OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise CatalogValidationError(f"catalog entry {name}: {error}") from error


def _reject_aliases(entries: dict[str, CatalogEntry]) -> None:
    seen: dict[str, str] = {}
    for name, entry in entries.items():
        bundle_id = entry.evidence["bundleId"]
        if bundle_id in seen:
            raise CatalogValidationError(f"catalog entries {seen[bundle_id]} and {name} alias the same bundleId")
        seen[bundle_id] = name


def verified_catalog_entries(path: Path) -> dict[str, CatalogEntry]:
    catalog = load_catalog(path)
    anchor = path.resolve().parent
    entries: dict[str, CatalogEntry] = {}
    for name, reference in sorted(catalog["entries"].items()):
        bundle_path = Path(reference["bundle"])
        if not bundle_path.is_absolute():
            bundle_path = anchor / bundle_path
        entry = _indexed_evidence(bundle_path, name)
        for field, expected in reference["expected"].items():
            actual = entry.evidence[field]
            if expected != actual:
                raise CatalogValidationError(
                    f"catalog entry {name}: {field} pin mismatch: expected {expected}, got {actual}"
                )
        entries[name] = entry
    _reject_aliases(entries)
    return entries


def create_catalog(output: Path, references: Sequence[tuple[str, Path]]) -> dict[str, Any]:
    """Pin explicit verified bundles; never infer dependencies or replace a file."""

    if output.exists() or output.is_symlink():
        raise CatalogConfigError(f"catalog output already exists: {output}")
    if not references:
        raise CatalogConfigError("catalog requires at least one named entry")
    indexed: dict[str, CatalogEntry] = {}
    paths: dict[str, Path] = {}
    target = output.resolve()
    for raw_name, path in references:
        name = _entry_name(raw_name)
        _local_path(str(path))
        if name in indexed:
            raise CatalogConfigError(f"duplicate catalog entry name: {name}")
        if target.is_relative_to(path.resolve()):
            raise CatalogConfigError("catalog output must be outside every referenced bundle")
        indexed[name] = _indexed_evidence(path, name)
        paths[name] = path.resolve()
    _reject_aliases(indexed)
    catalog = {
        "format": CATALOG_FORMAT,
        "entries": {
            name: {
                "bundle": Path(os.path.relpath(paths[name], target.parent)).as_posix(),
                "expected": {field: indexed[name].evidence[field] for field in ("sourceId", "resolutionId")},
            }
            for name in sorted(indexed)
        },
    }
    validate_catalog_config(catalog)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(canonical_json_bytes(catalog) + b"\n")
    except OSError as error:
        raise CatalogConfigError(f"cannot write catalog {output}: {error}") from error
    return catalog


def verify_catalog(path: Path) -> dict[str, Any]:
    entries = verified_catalog_entries(path)
    return {
        "format": CATALOG_VERIFY_FORMAT,
        "entries": [entry.evidence for entry in entries.values()],
    }


def query_catalog(
    path: Path, *, exact: str | None = None, prefix: str | None = None,
    kinds: Iterable[str] = (), libraries: Iterable[str] = (),
) -> dict[str, Any]:
    # Verify the whole configured set, even entries excluded by a filter.
    entries = verified_catalog_entries(path)
    selected = set(libraries)
    unknown = selected - entries.keys()
    if unknown:
        raise CatalogConfigError(f"unknown catalog entries: {', '.join(sorted(unknown))}")
    kinds = tuple(kinds)
    results: list[dict[str, Any]] = []
    for name, entry in entries.items():
        if selected and name not in selected:
            continue
        for candidate in query_declaration_index(entry.index, exact=exact, prefix=prefix, kinds=kinds):
            results.append({**candidate, "evidence": entry.evidence})
    results.sort(key=lambda value: (
        value["qualifiedName"], value["kind"], value["evidence"]["entry"], value["path"], value["line"],
    ))
    return {
        "format": CATALOG_QUERY_FORMAT,
        "checkedEntries": sorted(entries),
        "entries": results,
    }
