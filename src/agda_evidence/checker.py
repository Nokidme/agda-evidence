"""POSIX native-Agda top-level type observations, separate from proof attestations."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Any, Sequence

from .core import (
    EvidenceError, _copy_snapshot, _digest_identifier, _indexable_source_path,
    _normalised_file_records, _object, _parse_timestamp, _read_json,
    build_resolution, build_snapshot, canonical_json_bytes, derive_resolution_id,
    derive_source_id, digest_value, load_verified_bundle, sha256_file, utc_now,
)

OBSERVATION_FORMAT = "agda-evidence/type-observation-v1"
TRANSPORT_STATUSES = {"completed", "timed-out", "output-limit", "protocol-error", "execution-error"}
RESULT_STATUSES = TRANSPORT_STATUSES - {"completed"} | {"inferred", "load-error", "load-incomplete", "query-error"}


class CheckerEvidenceError(EvidenceError):
    """Evidence pins or saved observation verification failed (CLI exit 1)."""


class SessionError(Exception):
    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(message)


def haskell_string(value: str) -> str:
    """Haskell Read strings accept literal Unicode, not JSON's \\u escapes."""
    result = []
    for char in value:
        if char in {'"', '\\'}:
            result.append('\\' + char)
        elif ord(char) < 32 or ord(char) == 127:
            result.append(f"\\{ord(char)}\\&")
        elif 0xD800 <= ord(char) <= 0xDFFF:
            raise EvidenceError("unpaired Unicode surrogate is not supported")
        else:
            result.append(char)
    return '"' + ''.join(result) + '"'


def _request(file: str, phase: str, expression: str) -> str:
    quoted = haskell_string(file)
    if phase == "load":
        return f"IOTCM {quoted} NonInteractive Direct (Cmd_load {quoted} [])"
    return f"IOTCM {quoted} None Direct (Cmd_infer_toplevel Simplified {haskell_string(expression)})"


def _normalise(value: Any, stage: Path) -> Any:
    if isinstance(value, str):
        return value.replace(str(stage), "$PROJECT_ROOT")
    if isinstance(value, list):
        return [_normalise(item, stage) for item in value]
    if isinstance(value, dict):
        return {key: _normalise(item, stage) for key, item in value.items()}
    return value


def _strict_json(line: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate response key {key}")
            result[key] = value
        return result

    def invalid(value: str) -> None:
        raise ValueError(f"non-JSON constant {value}")

    try:
        message = json.loads(line.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid)
        if not isinstance(message, dict) or not isinstance(message.get("kind"), str):
            raise ValueError("response must be an object with kind")
        return message
    except (ValueError, UnicodeError) as error:
        excerpt = line[:1024].decode("utf-8", errors="replace")
        raise SessionError("protocol-error", f"cannot parse Agda JSON response: {error}; output: {excerpt!r}") from error


class AgdaSession:
    """Consume NDJSON and non-newline prompts, with bounded memory and runtime."""

    def __init__(self, argv: list[str], stage: Path, timeout: int, limit: int):
        self.stage = stage
        self.deadline = time.monotonic() + timeout
        self.limit = limit
        self.total = 0
        self.stdout_bytes = 0
        self.stderr = bytearray()
        self.pending = bytearray()
        self.selector = selectors.DefaultSelector()
        self.process: subprocess.Popen[bytes] | None = None
        try:
            self.process = subprocess.Popen(
                argv, cwd=stage, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True,
                env={**os.environ, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
            )
            assert self.process.stdin is not None
            os.set_blocking(self.process.stdin.fileno(), False)
            for stream in (self.process.stdout, self.process.stderr):
                assert stream is not None
                os.set_blocking(stream.fileno(), False)
                self.selector.register(stream, selectors.EVENT_READ)
        except OSError as error:
            self.close()
            raise SessionError("execution-error", str(error)) from error

    def _read_stream(self, stream: Any) -> None:
        assert self.process is not None
        try:
            data = os.read(stream.fileno(), 65536)
        except BlockingIOError:
            return
        if not data:
            self.selector.unregister(stream)
            if stream is self.process.stdout:
                raise SessionError("protocol-error", "Agda stdout ended before the command prompt")
            return
        self.total += len(data)
        is_stdout = stream is self.process.stdout
        if is_stdout:
            self.stdout_bytes += len(data)
        if self.total > self.limit:
            raise SessionError("output-limit", "Agda interaction exceeded its combined stdout/stderr byte limit")
        if is_stdout:
            self.pending.extend(data)
        else:
            self.stderr.extend(data)

    def _events(self) -> list[Any]:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SessionError("timed-out", "Agda interaction exceeded its total session timeout")
        events = self.selector.select(remaining)
        if not events:
            raise SessionError("timed-out", "Agda interaction exceeded its total session timeout")
        return events

    def _send(self, request: str) -> None:
        assert self.process is not None and self.process.stdin is not None
        stream = self.process.stdin
        payload = memoryview((request + "\n").encode("utf-8"))
        self.selector.register(stream, selectors.EVENT_WRITE)
        try:
            while payload:
                for key, _ in self._events():
                    if key.fileobj is stream:
                        try:
                            written = os.write(stream.fileno(), payload)
                        except BlockingIOError:
                            continue
                        payload = payload[written:]
                    else:
                        self._read_stream(key.fileobj)
        except OSError as error:
            raise SessionError("execution-error", f"cannot send Agda request: {error}") from error
        finally:
            self.selector.unregister(stream)

    def exchange(self, record: dict[str, Any], actual_request: str | None) -> None:
        assert self.process is not None
        if actual_request is not None:
            self._send(actual_request)
        while True:
            # A flushed prompt is command completion, not a JSON record. It has
            # no newline; waiting on readline would deadlock here.
            if self.pending.startswith(b"JSON> "):
                del self.pending[:6]
                if self.pending:
                    raise SessionError("protocol-error", "unexpected output after Agda command prompt")
                record["complete"] = True
                return
            if b"\n" in self.pending:
                line, _, rest = self.pending.partition(b"\n")
                self.pending = bytearray(rest)
                if line.strip():
                    record["responses"].append(_normalise(_strict_json(bytes(line)), self.stage))
                continue
            for key, _ in self._events():
                self._read_stream(key.fileobj)

    def close(self) -> None:
        if self.process is not None:
            # Kill the session group even if its leader exited: a launcher must
            # not leave descendants behind on timeout or successful completion.
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream is not None:
                    stream.close()
        self.selector.close()


def _info(messages: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [message["info"] for message in messages
            if message.get("kind") == "DisplayInfo" and isinstance(message.get("info"), dict)
            and message["info"].get("kind") == kind]


def _load_status(messages: list[dict[str, Any]]) -> str:
    if _info(messages, "Error"):
        return "load-error"
    points = [message.get("interactionPoints") for message in messages if message.get("kind") == "InteractionPoints"]
    summaries = _info(messages, "AllGoalsWarnings")
    statuses = [message.get("status", {}).get("checked") for message in messages
                if message.get("kind") == "Status" and isinstance(message.get("status"), dict)]
    if len(points) != 1 or not isinstance(points[0], list) or len(summaries) != 1:
        return "protocol-error"
    summary = summaries[0]
    if any(not isinstance(summary.get(field), list) for field in ("visibleGoals", "invisibleGoals", "warnings", "errors")):
        return "protocol-error"
    if points[0] or any(summary[field] for field in ("visibleGoals", "invisibleGoals", "warnings", "errors")):
        return "load-incomplete"
    if not statuses or statuses[-1] is not True:
        return "load-incomplete"
    return "clean"


def response_result(transcript: list[dict[str, Any]], transport: dict[str, Any]) -> dict[str, Any]:
    """A successful OS exit never substitutes for load and inference responses."""
    if transport["status"] != "completed":
        return {"status": transport["status"], "type": None}
    if len(transcript) < 2 or not all(record["complete"] for record in transcript):
        return {"status": "protocol-error", "type": None}
    load_status = _load_status(transcript[1]["responses"])
    if load_status != "clean":
        return {"status": load_status, "type": None}
    if len(transcript) != 3:
        return {"status": "protocol-error", "type": None}
    messages = transcript[2]["responses"]
    if _info(messages, "Error"):
        return {"status": "query-error", "type": None}
    types = _info(messages, "InferredType")
    if len(types) != 1 or not isinstance(types[0].get("expr"), str) or not types[0]["expr"].strip():
        return {"status": "protocol-error", "type": None}
    return {"status": "inferred", "type": types[0]["expr"]}


def _include_roots(includes: Sequence[str]) -> list[str]:
    roots = ["."]
    for value in includes:
        if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or any(ord(c) < 32 for c in value):
            raise EvidenceError("include roots must be project-relative directories")
        if value != "." and any(part in {"", ".", ".."} for part in value.split("/")):
            raise EvidenceError("include roots must not contain empty, dot, or parent segments")
        if value not in roots:
            roots.append(value)
    return roots


def _argv(executable: str, includes: list[str], safe: bool) -> list[str]:
    args = [executable, "--interaction-json", "--no-libraries", "--ignore-interfaces"]
    if safe:
        args.append("--safe")
    for value in includes:
        args.extend(["-i", value])
    return args


def observation_id(observation: dict[str, Any]) -> str:
    return f"sha256:{digest_value({key: value for key, value in observation.items() if key != 'observationId'})}"


def infer_type(
    project_root: Path, file: str, expression: str, *, agda_binary: str = "agda",
    includes: Sequence[str] = (), safe: bool = False, timeout_seconds: int = 60,
    max_output_bytes: int = 4_194_304, bundle: Path | None = None,
) -> dict[str, Any]:
    """Infer in a native Agda module's top-level scope, never in-place."""
    if os.name != "posix":
        raise EvidenceError("the native checker adapter currently requires POSIX")
    file = _indexable_source_path(file, "checker file")
    if any(ord(c) < 32 for c in file):
        raise EvidenceError("checker file must not contain control characters")
    if not isinstance(expression, str) or not expression.strip():
        raise EvidenceError("an explicit non-empty expression is required")
    haskell_string(expression)
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds < 1:
        raise EvidenceError("checker timeout must be a positive integer")
    if not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool) or max_output_bytes < 1024:
        raise EvidenceError("checker output byte limit must be at least 1024")
    if not isinstance(safe, bool):
        raise EvidenceError("checker safe policy must be boolean")
    include_roots = _include_roots(includes)
    root = project_root.resolve()
    snapshot, files = build_snapshot(root)
    file_records = {record["path"]: record for record in snapshot["files"]}
    if file not in file_records:
        raise EvidenceError("checker file is absent from the source snapshot")
    for value in include_roots:
        if not (root / value).is_dir():
            raise EvidenceError(f"include root does not exist: {value}")
    resolution = build_resolution(root, agda_binary=agda_binary)
    basis = None
    if bundle is not None:
        try:
            manifest, payloads = load_verified_bundle(bundle)
            prior_source = _object(payloads["snapshot.json"], "basis snapshot")
            prior_resolution = _object(payloads["resolution.json"], "basis resolution")
            basis = {
                "bundleId": manifest["bundleId"],
                "sourceId": _digest_identifier(prior_source.get("sourceId"), "basis sourceId"),
                "resolutionId": _digest_identifier(prior_resolution.get("resolutionId"), "basis resolutionId"),
            }
        except EvidenceError as error:
            raise CheckerEvidenceError(f"invalid checker basis bundle: {error}") from error
        for field, actual in (("sourceId", snapshot["sourceId"]), ("resolutionId", resolution["resolutionId"])):
            if basis[field] != actual:
                raise CheckerEvidenceError(f"checker {field} pin mismatch: expected {basis[field]}, got {actual}")
    transcript: list[dict[str, Any]] = []
    transport: dict[str, Any] = {"status": "completed", "message": None, "stderr": "", "stdoutBytes": 0}
    session: AgdaSession | None = None
    started_at = utc_now()
    with tempfile.TemporaryDirectory(prefix="agda-evidence-checker-") as temporary:
        stage = Path(temporary) / "project"
        stage.mkdir()
        _copy_snapshot(root, files, stage)
        staged_snapshot, _ = build_snapshot(stage)
        if staged_snapshot["sourceId"] != snapshot["sourceId"]:
            raise CheckerEvidenceError("staged checker inputs do not match the captured source")
        for value in include_roots:
            (stage / value).mkdir(parents=True, exist_ok=True)
        try:
            executable = shutil.which(agda_binary)
            if not executable:
                raise SessionError("execution-error", "Agda executable was not found")
            compiler_path = Path(executable).resolve()
            if f"sha256:{sha256_file(compiler_path)}" != resolution["agda"].get("binarySha256"):
                raise CheckerEvidenceError("Agda executable changed after resolution capture")
            session = AgdaSession(_argv(str(Path(executable).resolve()), include_roots, safe), stage, timeout_seconds, max_output_bytes)
            for phase in ("startup", "load", "infer"):
                logical_request = None if phase == "startup" else _request(f"$PROJECT_ROOT/{file}", phase, expression)
                actual_request = None if phase == "startup" else _request(str(stage / file), phase, expression)
                record = {"phase": phase, "request": logical_request, "responses": [], "complete": False}
                transcript.append(record)
                session.exchange(record, actual_request)
                if phase == "load" and _load_status(record["responses"]) != "clean":
                    break
        except SessionError as error:
            transport["status"] = error.status
            transport["message"] = str(_normalise(str(error), stage))
        finally:
            if session is not None:
                transport["stderr"] = _normalise(session.stderr.decode("utf-8", errors="replace"), stage)
                transport["stdoutBytes"] = session.stdout_bytes
                session.close()
                if f"sha256:{sha256_file(compiler_path)}" != resolution["agda"].get("binarySha256"):
                    raise CheckerEvidenceError("Agda executable changed during checker inference")
        # Native inference shouldn't rewrite regular project inputs. Generated
        # .agdai files are deliberately outside the snapshot's identity policy.
        after, _ = build_snapshot(stage)
        if after["sourceId"] != snapshot["sourceId"]:
            raise CheckerEvidenceError("checker modified captured regular source inputs in the staged copy")
    finished_at = utc_now()
    observation = {
        "format": OBSERVATION_FORMAT,
        "observationId": "",
        "snapshot": snapshot,
        "resolution": resolution,
        "basis": basis,
        "query": {"file": file, "sourceSha256": file_records[file]["sha256"], "expression": expression,
                  "includes": include_roots, "safe": safe, "rewrite": "Simplified"},
        "execution": {"argv": _argv("$AGDA", include_roots, safe), "mode": "isolated-project-copy",
                      "timeoutSeconds": timeout_seconds, "maxOutputBytes": max_output_bytes,
                      "startedAt": started_at, "finishedAt": finished_at},
        "transcript": transcript,
        "transport": transport,
        "result": response_result(transcript, transport),
    }
    observation["observationId"] = observation_id(observation)
    validate_observation(observation)
    return observation


def validate_observation(value: Any) -> dict[str, Any]:
    """Validate retained response/result and source/environment bindings, no Agda."""
    observation = _object(value, "type observation")
    expected_fields = {"format", "observationId", "snapshot", "resolution", "basis", "query", "execution", "transcript", "transport", "result"}
    if set(observation) != expected_fields or observation["format"] != OBSERVATION_FORMAT:
        raise CheckerEvidenceError("type observation has an unsupported format or fields")
    snapshot = _object(observation["snapshot"], "observation snapshot")
    if snapshot.get("format") != "agda-evidence/snapshot-v1" or snapshot.get("treeAlgorithm") != "sha256":
        raise CheckerEvidenceError("observation snapshot has an unsupported format or algorithm")
    source_id = derive_source_id(snapshot)
    if snapshot.get("sourceId") != source_id or snapshot.get("sourceDigest") != source_id:
        raise CheckerEvidenceError("observation source identity does not match snapshot")
    records = _normalised_file_records(snapshot.get("files"))
    for record in records:
        if any(part in {"", ".", ".."} for part in record["path"].split("/")):
            raise CheckerEvidenceError("observation snapshot contains an unsafe source path")
    resolution = _object(observation["resolution"], "observation resolution")
    if resolution.get("format") != "agda-evidence/resolution-v1" or resolution.get("resolutionStatus") != "partial":
        raise CheckerEvidenceError("observation resolution has an unsupported format")
    resolution_id = derive_resolution_id(resolution)
    if resolution.get("resolutionId") != resolution_id:
        raise CheckerEvidenceError("observation resolution identity does not match its projection")
    query = _object(observation["query"], "observation query")
    if set(query) != {"file", "sourceSha256", "expression", "includes", "safe", "rewrite"}:
        raise CheckerEvidenceError("observation query has unsupported fields")
    file = _indexable_source_path(query["file"], "observation file")
    if {record["path"]: record["sha256"] for record in records}.get(file) != query["sourceSha256"]:
        raise CheckerEvidenceError("observation queried file is not bound to its snapshot digest")
    if not isinstance(query["expression"], str) or not query["expression"].strip():
        raise CheckerEvidenceError("observation expression must be a non-empty string")
    haskell_string(query["expression"])
    includes = query["includes"]
    if not isinstance(includes, list) or _include_roots(includes) != includes:
        raise CheckerEvidenceError("observation include roots are not canonical")
    if not isinstance(query["safe"], bool) or query["rewrite"] != "Simplified":
        raise CheckerEvidenceError("observation has an unsupported query policy")
    basis = observation["basis"]
    if basis is not None:
        basis = _object(basis, "observation basis")
        if set(basis) != {"bundleId", "sourceId", "resolutionId"}:
            raise CheckerEvidenceError("observation basis has unsupported fields")
        _digest_identifier(basis["bundleId"], "basis bundleId")
        if basis["sourceId"] != source_id or basis["resolutionId"] != resolution_id:
            raise CheckerEvidenceError("observation basis disagrees with its source/resolution")
    execution = _object(observation["execution"], "observation execution")
    if set(execution) != {"argv", "mode", "timeoutSeconds", "maxOutputBytes", "startedAt", "finishedAt"}:
        raise CheckerEvidenceError("observation execution has unsupported fields")
    if execution["argv"] != _argv("$AGDA", includes, query["safe"]) or execution["mode"] != "isolated-project-copy":
        raise CheckerEvidenceError("observation argv or staging mode does not match query policy")
    for field, minimum in (("timeoutSeconds", 1), ("maxOutputBytes", 1024)):
        if not isinstance(execution[field], int) or isinstance(execution[field], bool) or execution[field] < minimum:
            raise CheckerEvidenceError(f"observation {field} must be an integer >= {minimum}")
    times = [_parse_timestamp(snapshot.get("capturedAt"), "snapshot.capturedAt"),
             _parse_timestamp(resolution.get("capturedAt"), "resolution.capturedAt"),
             _parse_timestamp(execution["startedAt"], "execution.startedAt"),
             _parse_timestamp(execution["finishedAt"], "execution.finishedAt")]
    if times[0] > times[2] or times[1] > times[2] or times[2] > times[3]:
        raise CheckerEvidenceError("observation timestamps are not causally ordered")
    transcript = observation["transcript"]
    if not isinstance(transcript, list) or len(transcript) > 3:
        raise CheckerEvidenceError("observation transcript must contain at most three phases")
    for number, phase in enumerate(transcript):
        phase = _object(phase, "observation transcript phase")
        expected_phase = ("startup", "load", "infer")[number]
        expected_request = None if number == 0 else _request(f"$PROJECT_ROOT/{file}", expected_phase, query["expression"])
        if set(phase) != {"phase", "request", "responses", "complete"} or phase["phase"] != expected_phase or phase["request"] != expected_request:
            raise CheckerEvidenceError("observation phase/request does not match its query")
        if not isinstance(phase["complete"], bool) or not isinstance(phase["responses"], list):
            raise CheckerEvidenceError("observation phase completion/responses has an invalid shape")
        if number > 0 and not transcript[number - 1]["complete"]:
            raise CheckerEvidenceError("observation continued after an incomplete protocol phase")
        for response in phase["responses"]:
            if not isinstance(response, dict) or not isinstance(response.get("kind"), str):
                raise CheckerEvidenceError("observation response must be an object with kind")
        if number == 2 and _load_status(transcript[1]["responses"]) != "clean":
            raise CheckerEvidenceError("observation issued inference after a non-clean load")
    transport = _object(observation["transport"], "observation transport")
    if set(transport) != {"status", "message", "stderr", "stdoutBytes"} or not isinstance(transport["status"], str) or transport["status"] not in TRANSPORT_STATUSES:
        raise CheckerEvidenceError("observation transport has unsupported fields or status")
    if not isinstance(transport["stderr"], str) or (transport["message"] is not None and not isinstance(transport["message"], str)):
        raise CheckerEvidenceError("observation transport messages must be strings")
    if not isinstance(transport["stdoutBytes"], int) or isinstance(transport["stdoutBytes"], bool) or transport["stdoutBytes"] < 0:
        raise CheckerEvidenceError("observation stdoutBytes must be non-negative")
    if observation["result"] != response_result(transcript, transport):
        raise CheckerEvidenceError("observation result does not match retained protocol responses")
    if observation["result"]["status"] == "inferred":
        agda = _object(resolution.get("agda"), "observation Agda")
        if agda.get("available") is not True:
            raise CheckerEvidenceError("inferred observation requires an available Agda compiler")
        _digest_identifier(agda.get("binarySha256"), "observation Agda binarySha256")
    if observation["observationId"] != observation_id(observation):
        raise CheckerEvidenceError("observationId does not match complete observation contents")
    return observation


def write_observation(path: Path, observation: dict[str, Any]) -> None:
    validate_observation(observation)
    if path.exists() or path.is_symlink():
        raise EvidenceError(f"type observation output already exists: {path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(canonical_json_bytes(observation) + b"\n")
    except OSError as error:
        raise EvidenceError(f"cannot write type observation: {error}") from error


def load_observation(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise CheckerEvidenceError("type observation must be a regular non-symlinked file")
        return validate_observation(_read_json(path))
    except (EvidenceError, TypeError, ValueError, KeyError, AttributeError) as error:
        raise CheckerEvidenceError(str(error)) from error
