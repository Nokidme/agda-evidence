"""Optional v2 editor facade for one host-bound source-copy dependency.

No server, dependency closure, contextual lexical ranking, or proof completion.
Rebinding requires a new instance. Hosts must notify_buffers on *all* client and
 dependency edit/save events, including edit-and-revert, and save complete inputs.
"""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import secrets
import threading
from typing import Any, Mapping, Sequence

from .catalog import CatalogConfigError, CatalogValidationError, query_catalog
from .client import _native_resolution
from .core import (
    EvidenceError, build_declaration_index, build_resolution, build_snapshot,
    canonical_json_bytes, derive_resolution_id, digest_value, load_verified_bundle,
    query_declaration_index, resolution_identity_projection,
)
from .research import ResearchWorkspace, RequestError
from .sources import (
    SOURCE_POLICY, SourceEvidenceError, _client_roots, _dependency_roots,
    _directories, _same, _source_evidence, check_source_candidate,
    observe_source_goals, validate_source_observation,
)

SOURCE_RESEARCH_VERSION = 2


def _composition(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"policy", "clientIncludes", "dependencyIncludes", "safe"}:
        raise SourceEvidenceError("Composition requires policy, clientIncludes, dependencyIncludes and safe")
    if value["policy"] != SOURCE_POLICY or not isinstance(value["safe"], bool):
        raise SourceEvidenceError("Unsupported source composition policy or safe setting")
    return {"policy": SOURCE_POLICY, "clientIncludes": _client_roots(value["clientIncludes"]),
            "dependencyIncludes": _dependency_roots(value["dependencyIncludes"]), "safe": value["safe"]}


def composition_identity(composition: dict[str, Any]) -> str:
    """Path-free identity of canonical explicit composition and inner safe policy."""
    return f"sha256:{digest_value({'format': 'agda-evidence/source-research-composition-v2', 'composition': _composition(composition)})}"


def source_profile(value: dict[str, Any]) -> dict[str, Any]:
    """Return a detached complete composition, with safe from the inner query."""
    return _composition({**value["composition"], "safe": value["observation"]["query"]["safe"]})


def _source_subjects(value: dict[str, Any]) -> dict[str, str]:
    evidence = value["dependency"]["evidence"]
    return {"clientSourceId": value["clientSnapshot"]["sourceId"],
            "clientResolutionId": value["clientResolution"]["resolutionId"],
            "dependencySourceId": evidence["components"]["snapshot.json"]["sourceId"],
            "dependencyResolutionId": value["dependency"]["nativeResolution"]["resolutionId"],
            "dependencyBundleId": evidence["manifest"]["bundleId"],
            "compositionId": composition_identity(source_profile(value))}


def _current_native(resolution: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any] | None:
    # Unavailable compiler is a known native context, not unobservable inputs.
    projection = resolution_identity_projection(resolution)
    if (resolution.get("format") != "agda-evidence/resolution-v1" or
            resolution.get("resolutionStatus") != "partial" or "nix" in resolution or
            resolution.get("resolutionId") != derive_resolution_id(resolution)):
        raise SourceEvidenceError("Invalid current native resolution")
    manifests = [{"path": item["path"], "sha256": item["sha256"]} for item in snapshot["files"]
                 if "/" not in item["path"] and item["path"].endswith(".agda-lib")]
    if projection["projectLibraryFiles"] != sorted(manifests, key=lambda item: item["path"]):
        raise SourceEvidenceError("Current native resolution differs from its own source snapshot")
    return _native_resolution(resolution, snapshot, "current native context") if projection["agda"]["available"] else None


class SourceResearchWorkspace(ResearchWorkspace):
    """One immutable host configuration, frozen pins and an opaque FIFO history.

    notify_buffers applies to every client/dependency input event; it remains
    callable while native operations run. Filesystem observation is serialized
    through revision publication, independently of the native operation lock.
    """

    def __init__(
        self, project_root: Path, documents: Mapping[str, str], *, dependency_root: Path,
        dependency_bundle: Path, dependency_includes: Sequence[str], agda_binary: str = "agda",
        includes: Sequence[str] = (), safe: bool = False, catalog: Path | None = None,
        timeout_seconds: int = 60, max_output_bytes: int = 4_194_304,
        max_records: int = 64, max_stored_bytes: int = 67_108_864,
    ) -> None:
        if os.name != "posix":
            raise EvidenceError("Native source research configuration currently requires POSIX")
        client_includes = _client_roots(includes)
        dep_includes = _dependency_roots(dependency_includes)
        super().__init__(project_root, documents, agda_binary=agda_binary, includes=client_includes,
                         safe=safe, catalog=catalog, timeout_seconds=timeout_seconds,
                         max_output_bytes=max_output_bytes, max_records=max_records, max_stored_bytes=max_stored_bytes)
        self._dependency_root = dependency_root.resolve()
        self._dependency_bundle = dependency_bundle.absolute()
        self._dependency_includes = tuple(dep_includes)
        if (self._root.is_relative_to(self._dependency_root) or
                self._dependency_root.is_relative_to(self._root)):
            raise EvidenceError("Client and dependency roots must be separate, non-overlapping directories")
        manifest, payloads = load_verified_bundle(self._dependency_bundle)
        _source_evidence({"manifest": manifest, "components": payloads})
        self._dependency_evidence = deepcopy({"manifest": manifest, "components": payloads})
        self._expectedDependency = {"dependencySourceId": payloads["snapshot.json"]["sourceId"],
                                    "dependencyResolutionId": payloads["resolution.json"]["resolutionId"],
                                    "dependencyBundleId": manifest["bundleId"]}
        self._composition = _composition({"policy": SOURCE_POLICY, "clientIncludes": client_includes,
                                          "dependencyIncludes": dep_includes, "safe": safe})
        self._observation = threading.RLock()
        subjects, _, observed = self._observe()
        if not observed["dependencyMatchesPin"]:
            raise SourceEvidenceError("Initial live source/native inputs must match the complete bound dependency context")
        with self._state:
            self._sync(subjects)

    def _observe(self) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
        def capture():
            for root, includes in ((self._root, self._includes), (self._dependency_root, self._dependency_includes)):
                if root.is_symlink() or not root.is_dir():
                    raise SourceEvidenceError("Required source root must remain a regular directory")
                _directories(root, includes)
            client, _ = build_snapshot(self._root)
            dependency, _ = build_snapshot(self._dependency_root)
            if not set(self._documents.values()) <= {item["path"] for item in client["files"]}:
                raise SourceEvidenceError("Required host document is absent")
            manifest, payloads = load_verified_bundle(self._dependency_bundle)
            evidence = {"manifest": manifest, "components": payloads}
            _source_evidence(evidence)
            client_res = build_resolution(self._root, agda_binary=self._binary)
            dep_res = build_resolution(self._dependency_root, agda_binary=self._binary)
            client_compiler = _current_native(client_res, client)
            dep_compiler = _current_native(dep_res, dependency)
            subjects = {"clientSourceId": client["sourceId"], "clientResolutionId": client_res["resolutionId"],
                        "dependencySourceId": dependency["sourceId"], "dependencyResolutionId": dep_res["resolutionId"],
                        "dependencyBundleId": manifest["bundleId"], "compositionId": composition_identity(self._composition)}
            bound = self._dependency_evidence["components"]["resolution.json"]
            matches = (all(subjects[key] == item for key, item in self._expectedDependency.items()) and
                       _same(resolution_identity_projection(dep_res), resolution_identity_projection(bound)) and
                       dep_compiler is not None and client_compiler is not None and _same(client_compiler, dep_compiler))
            return subjects, client, {"clientResolution": client_res, "dependencySnapshot": dependency,
                                     "dependencyResolution": dep_res, "evidence": evidence, "dependencyMatchesPin": matches}
        first = capture()
        if capture()[0] != first[0]:
            raise SourceEvidenceError("Inputs changed during source observation")
        return first

    def _refresh(self):
        with self._observation:
            try:
                subjects, snapshot, observed = self._observe()
            except (EvidenceError, OSError, ValueError) as error:
                with self._state:
                    self._generation += 1
                    self._subjects = None
                raise RequestError("freshness-unavailable", "Current source, dependency and compiler inputs could not be observed") from error
            with self._state:
                self._sync(subjects)
                observed["revision"] = self._revision()
            return subjects, snapshot, observed

    def _response(self, request: Any, status: str, **options):
        response = super()._response(request, status, **options)
        response["apiVersion"] = SOURCE_RESEARCH_VERSION
        return response

    def _validate_request(self, request: Any):
        if (not isinstance(request, dict) or set(request) != {"apiVersion", "requestId", "op", "revision", "args"} or
                type(request.get("apiVersion")) is not int or request["apiVersion"] != SOURCE_RESEARCH_VERSION):
            raise RequestError("invalid-request", "Request requires apiVersion integer 2, requestId, op, revision and args")
        base = deepcopy(request)
        del base["apiVersion"]
        if isinstance(base["args"], dict) and base["args"].get("scope") == "dependency":
            base["args"]["scope"] = "project"  # validation only; rejects catalog filters for dependency-only search
        op, _ = super()._validate_request(base)
        return op, deepcopy(request["args"])

    def _listing(self, record_id: str, goal_id: int):
        record = self._lookup(record_id)
        value = validate_source_observation(record["artifact"])
        inner = value["observation"]
        if (record["kind"] != "listing" or value["listing"] is not None or
                inner["listing"] is not None or inner["query"]["operation"] != "list" or inner["result"]["status"] != "listed"):
            raise RequestError("invalid-request", "Selection requires an accepted leaf source listing")
        if not any(point["id"] == goal_id for point in inner["result"]["goals"]):
            raise RequestError("invalid-request", "Goal ID is not selectable in this listing")
        return record

    def _remember(self, artifact: dict[str, Any], kind: str, document_id: str, revision: str):
        stored = deepcopy(artifact)
        validate_source_observation(stored)
        payload = canonical_json_bytes(stored)
        subjects = _source_subjects(stored)
        if len(payload) > self._max_bytes:
            raise RequestError("store-capacity", "Evidence exceeds the host session store budget")
        with self._state:
            while self._records and (len(self._records) >= self._max_records or self._stored_bytes + len(payload) > self._max_bytes):
                _, removed = self._records.popitem(last=False)
                self._stored_bytes -= len(removed["payload"])
            record_id = secrets.token_urlsafe(24)
            self._records[record_id] = {"payload": payload, "kind": kind, "documentId": document_id,
                                        "revision": revision, "subjects": subjects}
            self._stored_bytes += len(payload)
        return record_id

    def _search(self, args: dict[str, Any], snapshot: dict[str, Any], observed: dict[str, Any]):
        matches, checked = [], []
        scope = args.get("scope", "all")
        filters = {key: args.get(key) for key in ("exact", "prefix")}
        kinds = args.get("kinds", [])
        for origin, root, source in (("project", self._root, snapshot),
                                     ("dependency", self._dependency_root, observed["dependencySnapshot"])):
            if scope not in {"all", origin}:
                continue
            if not observed["dependencyMatchesPin"]:
                raise RequestError("dependency-changed", "Dependency inputs no longer match the host-bound pins")
            index = build_declaration_index(root, source)
            evidence = {"sourceId": index["sourceId"], "indexId": index["indexId"]}
            if origin == "dependency":
                bound = self._dependency_evidence
                attestation = bound["components"]["attestation.json"]
                evidence.update(bundleId=bound["manifest"]["bundleId"],
                                resolutionId=observed["dependencyResolution"]["resolutionId"],
                                attestationId=attestation["attestationId"],
                                **{key: deepcopy(attestation[key]) for key in ("command", "scope", "outcome")})
            matches.extend({**hit, "origin": origin, "evidence": deepcopy(evidence)}
                           for hit in query_declaration_index(index, **filters, kinds=kinds))
        if scope in {"all", "catalog"}:
            if self._catalog is None:
                if scope == "catalog" or args.get("libraries"):
                    raise RequestError("catalog-unavailable", "No catalog is configured by the host")
            else:
                found = query_catalog(self._catalog, **filters, kinds=kinds, libraries=args.get("libraries", []))
                checked = found["checkedEntries"]
                matches.extend({**hit, "origin": "catalog"} for hit in found["entries"])
        matches.sort(key=lambda hit: (hit["qualifiedName"], hit["kind"], hit["origin"], hit["evidence"].get("entry", ""), hit["path"], hit["line"]))
        for hit in matches:
            hit.update(scopeStatus="not-established", candidateUsability="not-tested")
        limit = args.get("limit", 30)
        return {"entries": matches[:limit], "totalMatches": len(matches), "truncated": len(matches) > limit,
                "checkedCatalogEntries": checked, "contextualRanking": False,
                "context": {"listingId": args["listingId"], "goalId": args["goalId"]}}

    def _record_result(self, record, freshness, matches):
        return {"kind": record["kind"], "documentId": record["documentId"], "recordRevision": record["revision"],
                "artifact": record["artifact"], "freshness": freshness, "dependencyMatchesPin": matches}

    def handle(self, request: Any) -> dict[str, Any]:
        record_id, acquired = None, False
        try:
            op, args = self._validate_request(request)
            record = self._lookup(args["recordId"]) if op == "record.get" else None
            listing = self._listing(args["listingId"], args["goalId"]) if "listingId" in args else None
            if op not in {"workspace.status", "record.get"}:
                acquired = self._operation.acquire(blocking=False)
                if not acquired:
                    raise RequestError("workspace-busy", "Another research operation is running")
            with self._observation:
                try:
                    subjects, snapshot, observed = self._refresh()
                except RequestError as error:
                    if op != "record.get" or request["revision"] is not None:
                        return self._response(request, "error", code=error.code, message=str(error))
                    return self._response(request, "ok", record_id=args["recordId"],
                                          result=self._record_result(record, "unknown", None))
                with self._state:
                    revision = observed["revision"]
                    if ((request["revision"] is not None and request["revision"] != self._revision()) or
                            revision != self._revision() or subjects != self._subjects):
                        return self._response(request, "stale", code="workspace-changed", message="Refresh the workspace revision before retrying this operation")
                    matches = observed["dependencyMatchesPin"]
                    if op == "workspace.status":
                        return self._response(request, "ok", result={"documentIds": sorted(self._documents), "buffersDirty": self._dirty,
                            "compilerAvailable": observed["clientResolution"]["agda"].get("available") is True,
                            "catalogConfigured": self._catalog is not None, "includes": list(self._includes), "safe": self._safe,
                            "dependencyPins": deepcopy(self._expectedDependency), "dependencyMatchesPin": matches,
                            "composition": deepcopy(self._composition),
                            "limits": {"timeoutSeconds": self._timeout, "maxOutputBytes": self._output,
                                       "maxRecords": self._max_records, "maxStoredBytes": self._max_bytes}})
                    if op == "record.get":
                        fresh = record["revision"] == revision and record["subjects"] == subjects and not self._dirty and matches
                        return self._response(request, "ok", record_id=args["recordId"],
                                              result=self._record_result(record, "current" if fresh else "stale", matches))
                    if self._dirty:
                        return self._response(request, "stale", code="workspace-changed", message="Save complete inputs and refresh workspace status")
                    if not matches:
                        return self._response(request, "error", code="dependency-changed",
                            message="Dependency inputs no longer match the host-bound pins; rebinding requires a new workspace")
                    if listing is not None and (listing["revision"] != revision or listing["subjects"] != subjects):
                        return self._response(request, "stale", code="listing-stale", message="Relist goals for this source and compiler context")
            artifact, result, error = None, None, None
            try:
                if op == "library.search":
                    result = self._search(args, snapshot, observed)
                else:
                    document_id = args["documentId"] if op == "goals.list" else listing["documentId"]
                    options = {"dependency_bundle": self._dependency_bundle, "dependency_root": self._dependency_root,
                               "dependency_includes": self._dependency_includes, "agda_binary": self._binary,
                               "timeout_seconds": self._timeout, "max_output_bytes": self._output,
                               "_expected_subjects": {key: item for key, item in subjects.items() if key != "compositionId"}}
                    if op == "candidate.check":
                        artifact = check_source_candidate(self._root, listing["artifact"], args["goalId"], args["expression"], **options)
                    else:
                        artifact = observe_source_goals(self._root, self._documents[document_id], includes=self._includes,
                            safe=self._safe, listing=None if listing is None else listing["artifact"],
                            goal_id=None if listing is None else args["goalId"], **options)
                    validate_source_observation(artifact)
                    inner = artifact["observation"]
                    result = {"documentId": document_id, "sourceObservationId": artifact["sourceObservationId"],
                              "observationId": inner["observationId"], "outcome": deepcopy(inner["result"])}
                    kind = "listing" if op == "goals.list" else "candidate" if op == "candidate.check" else "inspection"
                    record_id = self._remember(artifact, kind, document_id, revision)
            except Exception as caught:
                error, result = caught, None
            # Always observe after failed native work, failed storage, and search.
            with self._observation:
                try:
                    after, _, final = self._refresh()
                except RequestError as unavailable:
                    return self._response(request, "error", record_id=record_id,
                                          code=unavailable.code, message=str(unavailable))
                with self._state:
                    invalid_capture = isinstance(error, SourceEvidenceError) and after == subjects
                    otherwise_current = not self._dirty and self._revision() == revision
                    if invalid_capture:
                        self._generation += 1  # invalid no-envelope capture must never reactivate an old selection
                    if not final["dependencyMatchesPin"]:
                        return self._response(request, "error", result=result, record_id=record_id,
                            code="dependency-changed", message="Dependency changed during research; retained evidence is historical")
                    if invalid_capture and otherwise_current:
                        return self._response(request, "error", record_id=record_id, code="evidence-invalid",
                                              message="Source capture failed validation; refresh workspace status and relist goals")
                    if self._dirty or self._revision() != revision or after != subjects or self._subjects != after:
                        return self._response(request, "stale", result=result, record_id=record_id,
                            code="workspace-changed", message="Workspace changed during research; retained evidence is historical")
                    if artifact is not None and _source_subjects(artifact) != after:
                        return self._response(request, "stale", result=result, record_id=record_id,
                            code="workspace-changed", message="Captured evidence differs from current workspace inputs")
                    if error is not None:
                        raise error
                    return self._response(request, "ok", result=result, record_id=record_id)
        except RequestError as error:
            return self._response(request, "error", record_id=record_id, code=error.code, message=str(error))
        except (CatalogConfigError, CatalogValidationError):
            return self._response(request, "error", record_id=record_id, code="catalog-invalid", message="Configured library evidence could not be verified")
        except SourceEvidenceError:
            return self._response(request, "error", record_id=record_id, code="evidence-invalid", message="Source, compiler or saved evidence failed validation")
        except (EvidenceError, OSError, ValueError):
            return self._response(request, "error", record_id=record_id, code="workspace-unavailable", message="Workspace inputs could not be observed or processed")
        except Exception:
            return self._response(request, "error", record_id=record_id, code="internal-error", message="Research operation failed unexpectedly")
        finally:
            if acquired:
                self._operation.release()
