#!/usr/bin/env python3
"""Offline size diagnostic for explicit existing observations; never runs Agda."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

FORMAT = "evidence-accounting-diagnostic-v1"
MAX_ARTIFACTS = 64
DEFAULT_INPUT_BYTES = 16_777_216
MAX_TOTAL_BYTES = 67_108_864
MAX_DEPTH = 128
SCOPE = ("Offline retained-evidence accounting only; not a public evidence schema, "
         "certificate, proof-success, native-conformance, workload-performance, "
         "process-memory, freshness, or authenticity claim.")


class AccountingError(ValueError):
    """Malformed, unsupported, or invalid retained evidence (CLI exit 1)."""


class ConfigurationError(ValueError):
    """Invalid limits or unsafe/unavailable filesystem operation (CLI exit 2)."""


def _positive(value, name, ceiling=None):
    if type(value) is not int or value < 1 or (ceiling is not None and value > ceiling):
        raise ConfigurationError(f"{name} must be a positive integer" +
                                 (f" at most {ceiling}" if ceiling is not None else ""))
    return value


def _json_shape(value, depth=0):
    if type(value) in (dict, list):
        if depth >= MAX_DEPTH:
            raise AccountingError("JSON container depth exceeds 128")
        if type(value) is dict:
            for key, child in value.items():
                if type(key) is not str:
                    raise AccountingError("JSON object keys must be strings")
                key.encode("utf-8")
                _json_shape(child, depth + 1)
        else:
            for child in value:
                _json_shape(child, depth + 1)
    elif type(value) is str:
        value.encode("utf-8")
    elif type(value) is float:
        if not math.isfinite(value):
            raise AccountingError("non-finite JSON number")
    elif value is not None and type(value) not in (int, bool):
        raise AccountingError("unsupported JSON scalar type")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AccountingError("duplicate JSON object key")
        result[key] = value
    return result


def _nonfinite(_):
    raise AccountingError("non-finite JSON number")


def _parse(input_bytes):
    if type(input_bytes) is not bytes:
        raise AccountingError("input_bytes must be bytes")
    if len(input_bytes) > MAX_TOTAL_BYTES:
        raise AccountingError("serialized input exceeds the 67108864-byte ceiling")
    try:
        text = input_bytes.decode("utf-8")
        # Bound nesting before the standard parser allocates a deeply nested tree.
        depth, quoted, escaped = 0, False, False
        for char in text:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                if depth > MAX_DEPTH:
                    raise AccountingError("JSON container depth exceeds 128")
            elif char in "]}":
                depth -= 1
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
        _json_shape(value)
        if type(value) is not dict:
            raise AccountingError("artifact must be a JSON object")
        return value
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        raise AccountingError("invalid bounded UTF-8 JSON artifact") from error


def _helpers():
    # Installed package imports only: no repository fallback or sys.path changes.
    try:
        from agda_evidence import candidates, checker, client, core, goals, sources
    except ImportError as error:
        raise ConfigurationError("agda-evidence must be installed in this interpreter") from error
    validators = {
        checker.OBSERVATION_FORMAT: checker.validate_observation,
        goals.GOAL_FORMAT: goals.validate_goal_observation,
        candidates.CANDIDATE_FORMAT: candidates.validate_candidate_observation,
        client.CLIENT_FORMAT: client.validate_client_observation,
        sources.SOURCE_FORMAT: sources.validate_source_observation,
    }
    return core, checker, validators


def _sha(payload):
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def account_artifact(value, *, input_bytes: bytes) -> dict:
    """Validate and measure value, binding it to the supplied original JSON bytes.

    No mutation or filesystem access. Validation and all section measurements use
    value itself, not the separately parsed byte-binding comparison object.
    """
    parsed = _parse(input_bytes)
    core, checker, validators = _helpers()
    try:
        _json_shape(value)
        if type(value) is not dict or type(value.get("format")) is not str:
            raise AccountingError("artifact must have a string format")
        payload = core.canonical_json_bytes(value)
        if payload != core.canonical_json_bytes(parsed):
            raise AccountingError("input_bytes do not encode the supplied value")
        validator = validators.get(value["format"])
        if validator is None:
            raise AccountingError("unsupported artifact format")
        validator(value)
        inner = value.get("observation", value.get("typeObservation", value))
        # Type-v1 historically compares results with Python equality. Retain JSON
        # scalar distinctions in this diagnostic as well as invoking its validator.
        if inner["format"] == checker.OBSERVATION_FORMAT:
            expected = checker.response_result(inner["transcript"], inner["transport"])
            if core.canonical_json_bytes(inner["result"]) != core.canonical_json_bytes(expected):
                raise AccountingError("native result has non-exact JSON scalar types")
        member_sizes = {key: len(core.canonical_json_bytes(child))
                        for key, child in sorted(value.items())}
        size = lambda child: 0 if child is None else len(core.canonical_json_bytes(child))
        dependency = value.get("dependency", value.get("library"))
        snapshots = {"workspace": inner["snapshot"]}
        if "clientSnapshot" in value:
            snapshots["client"] = value["clientSnapshot"]
        if dependency is not None:
            snapshots["dependency"] = dependency["evidence"]["components"]["snapshot.json"]
        return {
            "artifactFormat": value["format"],
            "artifactId": value.get("sourceObservationId", value.get("clientObservationId", value.get("observationId"))),
            "validation": "valid-retained-evidence",
            "nativeStatus": inner["result"]["status"],
            "nativeResult": deepcopy(inner["result"]),
            "nativeTransportStatus": inner["transport"]["status"],
            "inputBytes": len(input_bytes), "inputSha256": _sha(input_bytes),
            "canonicalPayloadBytes": len(payload), "canonicalPayloadSha256": _sha(payload),
            "sectionValueBytes": member_sizes,
            "topLevelFramingBytes": len(payload) - sum(member_sizes.values()),
            "clientSnapshotBytes": size(value.get("clientSnapshot")),
            "dependencyEvidenceBytes": size(dependency["evidence"] if dependency else None),
            "innerObservationBytes": size(inner) if inner is not value else 0,
            "embeddedSourceListingBytes": size(value.get("listing")) if "sourceObservationId" in value else 0,
            "embeddedNativeListingBytes": size(inner.get("listing")),
            "snapshotFileCounts": {role: len(snapshot["files"]) for role, snapshot in sorted(snapshots.items())},
            "sourceContentBytes": {role: sum(record["size"] for record in snapshot["files"])
                                   for role, snapshot in sorted(snapshots.items())},
        }
    except (core.EvidenceError, TypeError, ValueError, KeyError, AttributeError,
            StopIteration, RecursionError, OverflowError) as error:
        raise AccountingError("invalid retained evidence or byte binding") from error


def simulate_history(sizes: list[int], *, max_records: int = 24,
                     max_stored_bytes: int = 8_388_608) -> dict:
    """Exact canonical-payload FIFO policy; every list position is a new arrival."""
    _positive(max_records, "max_records")
    _positive(max_stored_bytes, "max_stored_bytes")
    if type(sizes) is not list or any(type(size) is not int or size < 1 for size in sizes):
        raise ConfigurationError("sizes must be a list of positive scalar integers")
    retained, used, events = [], 0, []
    for index, size in enumerate(sizes):
        evicted = []
        accepted = size <= max_stored_bytes
        if accepted:
            while retained and (len(retained) >= max_records or used + size > max_stored_bytes):
                old = retained.pop(0)
                used -= sizes[old]
                evicted.append(old)
            retained.append(index)
            used += size
        events.append({"inputIndex": index, "payloadBytes": size, "accepted": accepted,
                       "evictedInputIndexes": evicted, "retainedInputIndexes": retained.copy(),
                       "storedBytes": used})
    return {"maxRecords": max_records, "maxStoredBytes": max_stored_bytes,
            "events": events, "retainedInputIndexes": retained.copy(), "storedBytes": used}


def _safe_path(name):
    path = Path(name)
    if ".." in path.parts:
        raise ConfigurationError("parent traversal in filesystem paths is unsupported")
    path = Path(os.path.abspath(path))
    cursor = Path(path.anchor)
    for part in path.parts[1:-1]:
        cursor /= part
        info = cursor.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ConfigurationError("path parents must be existing non-symlink directories")
    return path


def _preflight(names, output_name):
    inputs = [_safe_path(name) for name in names]
    output = _safe_path(output_name)
    if output in inputs:
        raise ConfigurationError("output must not alias an input")
    if os.path.lexists(output):
        raise ConfigurationError("output must not already exist")
    for path in inputs:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ConfigurationError("inputs must be regular non-symlink files")
    if not os.access(output.parent, os.W_OK):
        raise ConfigurationError("output parent must be writable")
    return inputs, output


def _read_input(path, limit):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ConfigurationError("inputs must remain regular files")
        if info.st_size > limit:
            raise ConfigurationError("input or total serialized-byte limit exceeded")
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ConfigurationError("input or total serialized-byte limit exceeded")
        return raw


def _write_output(path, payload):
    # Preflight is repeated after validation; exclusive creation never overwrites.
    _safe_path(str(path))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    created = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
    except BaseException:
        # Best-effort cleanup only of the inode created by this invocation.
        try:
            current = path.lstat()
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                path.unlink()
        except OSError:
            pass
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", action="append", required=True, help="existing JSON observation; repeat in arrival order")
    parser.add_argument("--output", required=True, help="new report path in an existing non-symlink directory")
    parser.add_argument("--max-records", type=int, default=24)
    parser.add_argument("--max-stored-bytes", type=int, default=8_388_608)
    parser.add_argument("--max-input-bytes", type=int, default=DEFAULT_INPUT_BYTES)
    try:
        args = parser.parse_args(argv)
        _positive(args.max_records, "max-records")
        _positive(args.max_stored_bytes, "max-stored-bytes")
        _positive(args.max_input_bytes, "max-input-bytes", MAX_TOTAL_BYTES)
        if len(args.artifact) > MAX_ARTIFACTS:
            raise ConfigurationError("at most 64 explicit artifact inputs are allowed")
        inputs, output = _preflight(args.artifact, args.output)
        _helpers()
        records, total = [], 0
        for index, path in enumerate(inputs):
            raw = _read_input(path, min(args.max_input_bytes, MAX_TOTAL_BYTES - total))
            total += len(raw)
            try:
                value = _parse(raw)
                record = account_artifact(value, input_bytes=raw)
            except AccountingError as error:
                raise AccountingError(f"input {index}: invalid retained evidence or JSON") from error
            records.append({"inputIndex": index, **record})
        history = simulate_history([record["canonicalPayloadBytes"] for record in records],
                                   max_records=args.max_records, max_stored_bytes=args.max_stored_bytes)
        report = {"format": FORMAT, "scope": SCOPE, "records": records, "history": history,
                  "totalInputBytes": total,
                  "limits": {"maxArtifacts": MAX_ARTIFACTS, "maxInputBytes": args.max_input_bytes,
                             "maxTotalInputBytes": MAX_TOTAL_BYTES, "maxContainerDepth": MAX_DEPTH},
                  "sectionAccounting": "Top-level member values are disjoint; framing is separate. Nested section sizes overlap and are not additive envelope totals. Null/absent optional sections count as zero."}
        core, _, _ = _helpers()
        _write_output(output, core.canonical_json_bytes(report) + b"\n")
        return 0
    except SystemExit as error:
        return int(error.code)
    except AccountingError as error:
        print(f"evidence-accounting: {error}", file=sys.stderr)
        return 1
    except (ConfigurationError, OSError) as error:
        message = str(error) if isinstance(error, ConfigurationError) else "filesystem operation failed"
        print(f"evidence-accounting: {message}", file=sys.stderr)
        return 2
    except (UnicodeError, RecursionError, OverflowError, MemoryError):
        print("evidence-accounting: bounded input could not be processed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
