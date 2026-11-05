"""Optional editor integration, not a server, authentication system or certificate."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import json
from pathlib import Path
import re
import secrets
import threading
from typing import Any, Mapping, Sequence

from .candidates import _expression, check_candidate
from .catalog import CatalogConfigError, CatalogValidationError, query_catalog
from .checker import _include_roots
from ._discovery import _LexicalMemo
# Preserve the module-local builder spy seam, including forwarded private kwargs.
from .core import _build_declaration_index as build_declaration_index
from .core import (
    DECLARATION_KINDS, EvidenceError, _indexable_source_path,
    build_resolution, build_snapshot, canonical_json_bytes, derive_source_id, query_declaration_index,
)
from .goals import GoalEvidenceError, observe_goals, validate_goal_observation

OPS = {"workspace.status", "goals.list", "goals.inspect", "library.search", "candidate.check", "record.get"}
ID_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}")


class RequestError(EvidenceError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _text(value: Any, field: str, limit: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise RequestError("invalid-request", f"{field} must be a non-empty bounded string without controls")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise RequestError("invalid-request", f"{field} contains invalid Unicode") from error
    return value


def _number(value: Any, field: str, lower: int, upper: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not lower <= value <= upper:
        raise RequestError("invalid-request", f"{field} must be an integer from {lower} to {upper}")
    return value


class ResearchWorkspace:
    """One host-authorized workspace/session; do not share between users/tenants.

    The host saves buffers, calls notify_buffers on every edit/save event, owns
    scheduling/cancellation and authorization, and discards superseded UI replies.
    This facade serializes research operations and bounds its immutable FIFO store.
    """

    def __init__(
        self, project_root: Path, documents: Mapping[str, str], *, agda_binary: str = "agda",
        includes: Sequence[str] = (), safe: bool = False, catalog: Path | None = None,
        timeout_seconds: int = 60, max_output_bytes: int = 4_194_304,
        max_records: int = 64, max_stored_bytes: int = 33_554_432,
    ) -> None:
        if not documents or any(not isinstance(k, str) or not ID_RE.fullmatch(k) for k in documents):
            raise EvidenceError("host must configure non-empty, bounded document IDs")
        self._root = project_root.resolve()
        self._documents = {key: _indexable_source_path(value, "host document") for key, value in documents.items()}
        if len(set(self._documents.values())) != len(self._documents):
            raise EvidenceError("host document IDs must not alias the same source file")
        self._binary = _text(agda_binary, "host compiler", 4096)
        self._includes = _include_roots(includes)
        if not isinstance(safe, bool):
            raise EvidenceError("host safe setting must be Boolean")
        self._safe = safe
        self._catalog = catalog.resolve() if catalog is not None else None
        self._timeout = _number(timeout_seconds, "host timeout", 1, 3600)
        self._output = _number(max_output_bytes, "host output limit", 1024, 67_108_864)
        self._max_records = _number(max_records, "host record count", 1, 256)
        self._max_bytes = _number(max_stored_bytes, "host store bytes", 1024, 268_435_456)
        self._state = threading.RLock()
        self._operation = threading.Lock()
        self._session = secrets.token_hex(12)
        self._generation = 0
        self._lexical_memo = _LexicalMemo()
        self._dirty = False
        self._subjects: dict[str, str] | None = None
        self._records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._stored_bytes = 0

    def _revision(self) -> str:
        return f"{self._session}:{self._generation}"

    def _advance_generation_locked(self) -> None:
        """Advance the epoch under _state, taking the memo lock second."""
        self._generation += 1
        self._lexical_memo.invalidate(self._generation)

    def notify_buffers(self, *, dirty: bool) -> str:
        """Trusted host edit/save notification; not a client-dispatch operation.

        Notify every event, even edit-and-revert or same-content edits. Only mark
        clean after the requested revision's complete regular inputs are saved.
        """
        if not isinstance(dirty, bool):
            raise EvidenceError("host buffer state must be Boolean")
        with self._state:
            self._dirty = dirty
            self._advance_generation_locked()
            return self._revision()

    def _observe(self) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
        try:
            snapshot, _ = build_snapshot(self._root)
            resolution = build_resolution(self._root, agda_binary=self._binary)
            if build_snapshot(self._root)[0]["sourceId"] != snapshot["sourceId"]:
                raise EvidenceError("source changed during observation")
        except (EvidenceError, OSError, ValueError) as error:
            with self._state:
                self._advance_generation_locked()
                self._subjects = None
            raise RequestError("freshness-unavailable", "Current source and compiler inputs could not be observed") from error
        return {"sourceId": snapshot["sourceId"], "resolutionId": resolution["resolutionId"]}, snapshot, resolution

    def _sync(self, subjects: dict[str, str]) -> None:
        if self._subjects is not None and subjects != self._subjects:
            self._advance_generation_locked()
        self._subjects = dict(subjects)

    def _response(self, request: Any, status: str, *, result=None, record_id=None, code=None, message=None):
        request = request if isinstance(request, dict) else {}
        def echo(field):
            value = request.get(field)
            try:
                return _text(value, field) if value is not None else None
            except RequestError:
                return None
        with self._state:
            return {"apiVersion": 1, "requestId": echo("requestId"), "op": echo("op"),
                    "revision": echo("revision"), "currentRevision": self._revision(),
                    "workspace": deepcopy(self._subjects), "status": status, "recordId": record_id,
                    "result": result, "error": None if code is None else {"code": code, "message": message}}

    def _validate_request(self, request: Any) -> tuple[str, dict[str, Any]]:
        if not isinstance(request, dict) or set(request) != {"requestId", "op", "revision", "args"}:
            raise RequestError("invalid-request", "Request requires only requestId, op, revision and args")
        _text(request["requestId"], "requestId")
        op = _text(request["op"], "op", 32)
        if op not in OPS or not isinstance(request["args"], dict):
            raise RequestError("invalid-request", "Unsupported operation or non-object args")
        if request["revision"] is not None:
            _text(request["revision"], "revision")
        if op not in {"workspace.status", "record.get"} and request["revision"] is None:
            raise RequestError("invalid-request", "Research operations require the current revision")
        args = request["args"]
        required = {"workspace.status": set(), "goals.list": {"documentId"},
                    "goals.inspect": {"listingId", "goalId"}, "library.search": {"listingId", "goalId"},
                    "candidate.check": {"listingId", "goalId", "expression"}, "record.get": {"recordId"}}[op]
        optional = {"exact", "prefix", "kinds", "libraries", "scope", "limit"} if op == "library.search" else set()
        if not required <= args.keys() or not args.keys() <= required | optional:
            raise RequestError("invalid-request", "Unexpected or missing operation arguments")
        for field in {"listingId", "recordId"} & args.keys():
            _text(args[field], field)
        if op == "goals.list" and (not isinstance(args["documentId"], str) or args["documentId"] not in self._documents):
            raise RequestError("invalid-request", "Unknown host-configured document ID")
        if "goalId" in args:
            _number(args["goalId"], "goalId", 0, 2_147_483_647)
        if op == "candidate.check":
            try:
                _expression(args["expression"])
            except EvidenceError as error:
                raise RequestError("invalid-request", str(error)) from error
        if op == "library.search":
            if ("exact" in args) == ("prefix" in args):
                raise RequestError("invalid-request", "Search requires exactly one non-empty exact or prefix filter")
            _text(args.get("exact", args.get("prefix")), "search text", 256)
            if not isinstance(args.get("scope", "all"), str) or args.get("scope", "all") not in {"all", "project", "catalog"}:
                raise RequestError("invalid-request", "Search scope must be project, catalog or all")
            _number(args.get("limit", 30), "limit", 1, 100)
            for field in ("kinds", "libraries"):
                items = args.get(field, [])
                if not isinstance(items, list) or len(items) > 64:
                    raise RequestError("invalid-request", f"{field} must be a bounded array")
                for item in items:
                    _text(item, field, 64)
                if len(set(items)) != len(items):
                    raise RequestError("invalid-request", f"{field} must not contain duplicates")
            if set(args.get("kinds", [])) - DECLARATION_KINDS:
                raise RequestError("invalid-request", "Unsupported lexical declaration kind")
            if args.get("libraries") and args.get("scope", "all") == "project":
                raise RequestError("invalid-request", "Project-only search has no catalog library filter")
        return op, args

    def _lookup(self, record_id: str) -> dict[str, Any]:
        with self._state:
            record = self._records.get(record_id)
            if record is None:
                raise RequestError("record-unavailable", "Record is unavailable in this session")
            return {**record, "artifact": json.loads(record["payload"])}

    def _listing(self, record_id: str, goal_id: int) -> dict[str, Any]:
        record = self._lookup(record_id)
        value = record["artifact"]
        if record["kind"] != "listing" or value["result"]["status"] != "listed":
            raise RequestError("invalid-request", "Selection requires an accepted leaf listing")
        validate_goal_observation(value)
        if not any(point["id"] == goal_id for point in value["result"]["goals"]):
            raise RequestError("invalid-request", "Goal ID is not selectable in this listing")
        return record

    def _remember(self, artifact: dict[str, Any], kind: str, document_id: str, revision: str) -> str:
        payload = canonical_json_bytes(artifact)
        if len(payload) > self._max_bytes:
            raise RequestError("store-capacity", "Evidence exceeds the host session store budget")
        while self._records and (len(self._records) >= self._max_records or self._stored_bytes + len(payload) > self._max_bytes):
            _, removed = self._records.popitem(last=False)
            self._stored_bytes -= len(removed["payload"])
        record_id = secrets.token_urlsafe(24)
        self._records[record_id] = {"payload": payload, "kind": kind, "documentId": document_id,
                                    "revision": revision,
                                    "subjects": {"sourceId": artifact["snapshot"]["sourceId"], "resolutionId": artifact["resolution"]["resolutionId"]}}
        self._stored_bytes += len(payload)
        return record_id

    def _build_discovery_index(self, root, snapshot, *, generation, _builder):
        # Re-observe the entire regular-file tree, including nonindexed notes.
        # Cached lexical fragments never authorize skipping a freshness guard.
        source_id = derive_source_id(snapshot)
        if snapshot.get("sourceId") != source_id:
            raise EvidenceError("snapshot.sourceId does not match the recorded file tree")
        if build_snapshot(root)[0]["sourceId"] != source_id:
            raise EvidenceError("project changed while building declaration index")

        def candidates(path, data, source_sha256):
            return self._lexical_memo.scan(path, data, source_sha256, generation=generation)

        return _builder(root, snapshot, _candidate_scanner=candidates)

    def _search(self, args: dict[str, Any], snapshot: dict[str, Any], *, _generation: int) -> dict[str, Any]:
        matches = []
        checked_entries = []
        scope = args.get("scope", "all")
        filters = {key: args.get(key) for key in ("exact", "prefix")}
        kinds = args.get("kinds", [])
        if scope in {"all", "project"}:
            index = self._build_discovery_index(
                self._root, snapshot, generation=_generation, _builder=build_declaration_index,
            )
            for hit in query_declaration_index(index, **filters, kinds=kinds):
                matches.append({**hit, "origin": "project", "evidence": {"sourceId": index["sourceId"], "indexId": index["indexId"]}})
        if scope in {"all", "catalog"}:
            if self._catalog is None:
                if scope == "catalog" or args.get("libraries"):
                    raise RequestError("catalog-unavailable", "No catalog is configured by the host")
            else:
                found = query_catalog(self._catalog, **filters, kinds=kinds, libraries=args.get("libraries", []))
                checked_entries = found["checkedEntries"]
                matches.extend({**hit, "origin": "catalog"} for hit in found["entries"])
        matches.sort(key=lambda hit: (hit["qualifiedName"], hit["kind"], hit["origin"], hit["evidence"].get("entry", ""), hit["path"], hit["line"]))
        for hit in matches:
            hit.update(scopeStatus="not-established", candidateUsability="not-tested")
        limit = args.get("limit", 30)
        return {"entries": matches[:limit], "totalMatches": len(matches), "truncated": len(matches) > limit,
                "checkedCatalogEntries": checked_entries, "contextualRanking": False,
                "context": {"listingId": args["listingId"], "goalId": args["goalId"]}}

    def handle(self, request: Any) -> dict[str, Any]:
        """JSON-ready dispatch. Top-level ok is not native check/proof success."""
        record_id = None
        acquired = False
        try:
            op, args = self._validate_request(request)
            # Unknown/cross-session records fail identically before filesystem probes.
            record = self._lookup(args["recordId"]) if op == "record.get" else None
            listing = self._listing(args["listingId"], args["goalId"]) if "listingId" in args else None
            if op not in {"workspace.status", "record.get"}:
                acquired = self._operation.acquire(blocking=False)
                if not acquired:
                    raise RequestError("workspace-busy", "Another research operation is running")
            try:
                subjects, snapshot, resolution = self._observe()
            except RequestError:
                if op != "record.get" or request["revision"] is not None:
                    raise
                return self._response(request, "ok", record_id=args["recordId"], result={"kind": record["kind"],
                    "documentId": record["documentId"], "recordRevision": record["revision"], "freshness": "unknown",
                    "artifact": record["artifact"]})
            with self._state:
                self._sync(subjects)
                revision = self._revision()
                if request["revision"] is not None and request["revision"] != revision:
                    return self._response(request, "stale", code="workspace-changed", message="Refresh the workspace revision before retrying this operation")
                if op == "workspace.status":
                    return self._response(request, "ok", result={"documentIds": sorted(self._documents), "buffersDirty": self._dirty,
                        "compilerAvailable": resolution["agda"].get("available") is True,
                        "catalogConfigured": self._catalog is not None, "includes": list(self._includes), "safe": self._safe,
                        "limits": {"timeoutSeconds": self._timeout, "maxOutputBytes": self._output,
                                   "maxRecords": self._max_records, "maxStoredBytes": self._max_bytes}})
                if op == "record.get":
                    freshness = "current" if record["revision"] == revision and record["subjects"] == subjects and not self._dirty else "stale"
                    return self._response(request, "ok", record_id=args["recordId"], result={"kind": record["kind"],
                        "documentId": record["documentId"], "recordRevision": record["revision"], "freshness": freshness,
                        "artifact": record["artifact"]})
                if self._dirty or request["revision"] != revision:
                    return self._response(request, "stale", code="workspace-changed", message="Save the requested editor revision and refresh workspace status")
                if listing is not None and (listing["revision"] != revision or listing["subjects"] != subjects):
                    return self._response(request, "stale", code="listing-stale", message="Relist goals for this source and compiler context")
                generation = self._generation
            artifact = None
            error = None
            try:
                if op == "library.search":
                    result = self._search(args, snapshot, _generation=generation)
                else:
                    document_id = args["documentId"] if op == "goals.list" else listing["documentId"]
                    if op == "candidate.check":
                        artifact = check_candidate(self._root, listing["artifact"], args["goalId"], args["expression"],
                            agda_binary=self._binary, timeout_seconds=self._timeout, max_output_bytes=self._output)
                    else:
                        artifact = observe_goals(self._root, self._documents[document_id], agda_binary=self._binary,
                            includes=self._includes, safe=self._safe, timeout_seconds=self._timeout, max_output_bytes=self._output,
                            listing=None if listing is None else listing["artifact"], goal_id=None if listing is None else args["goalId"])
                    result = {"documentId": document_id, "observationId": artifact["observationId"], "outcome": deepcopy(artifact["result"])}
                    with self._state:
                        record_id = self._remember(artifact, "listing" if op == "goals.list" else "candidate" if op == "candidate.check" else "inspection", document_id, revision)
            except Exception as caught:
                error = caught
                result = None
            # Recheck live inputs after successful AND failed work. The original
            # native artifact can remain valid historical evidence for old inputs.
            after, _, _ = self._observe()
            with self._state:
                self._sync(after)
                if self._dirty or self._revision() != revision or after != subjects:
                    return self._response(request, "stale", result=result, record_id=record_id,
                        code="workspace-changed", message="Workspace changed during research; retained evidence is historical")
                if artifact is not None and {"sourceId": artifact["snapshot"]["sourceId"], "resolutionId": artifact["resolution"]["resolutionId"]} != after:
                    return self._response(request, "stale", result=result, record_id=record_id,
                        code="workspace-changed", message="Captured evidence differs from current workspace inputs")
                if error is not None:
                    raise error
                return self._response(request, "ok", result=result, record_id=record_id)
        except RequestError as error:
            return self._response(request, "error", record_id=record_id, code=error.code, message=str(error))
        except (CatalogConfigError, CatalogValidationError):
            return self._response(request, "error", record_id=record_id, code="catalog-invalid", message="Configured library evidence could not be verified")
        except GoalEvidenceError:
            return self._response(request, "error", record_id=record_id, code="evidence-invalid", message="Source, compiler or saved evidence failed validation")
        except (EvidenceError, OSError, ValueError):
            return self._response(request, "error", record_id=record_id, code="workspace-unavailable", message="Workspace inputs could not be observed or processed")
        except Exception:
            # The host may log exceptions in its authenticated worker boundary;
            # raw host paths, stack traces and secrets must not reach the UI.
            return self._response(request, "error", record_id=record_id, code="internal-error", message="Research operation failed unexpectedly")
        finally:
            if acquired:
                self._operation.release()
