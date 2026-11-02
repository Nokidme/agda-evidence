"""Read-only goal observations; unfinished work is not a passed proof check."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import tempfile
from typing import Any, Sequence

from .checker import (
    AgdaSession, CheckerEvidenceError, SessionError, TRANSPORT_STATUSES,
    _argv, _include_roots, _info, _normalise, _request, haskell_string,
)
from .core import (
    EvidenceError, _copy_snapshot, _digest_identifier, _indexable_source_path,
    _normalised_file_records, _object, _parse_timestamp, _read_json,
    build_resolution, build_snapshot, canonical_json_bytes, derive_resolution_id,
    derive_source_id, digest_value, sha256_file, utc_now,
)

GOAL_FORMAT = "agda-evidence/goal-observation-v1"
LOAD_POLICY = "unfinished-no-diagnostics-v1"
EDIT_ACTIONS = {"GiveAction", "MakeCase", "SolveAll"}


class GoalEvidenceError(CheckerEvidenceError):
    """A prior listing, source/environment pin, or saved observation is invalid."""


def goal_observation_id(value: dict[str, Any]) -> str:
    return f"sha256:{digest_value({key: item for key, item in value.items() if key != 'observationId'})}"


def _goal_id(value: Any) -> int:
    if isinstance(value, dict):
        value = value.get("id")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GoalEvidenceError("interaction ID must be a non-negative integer")
    return value


def _ranges(value: Any, size: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise GoalEvidenceError("interaction range must be an interval array")
    for interval in value:
        if not isinstance(interval, dict) or set(interval) != {"start", "end"}:
            raise GoalEvidenceError("interaction range has an unsupported interval shape")
        for endpoint in (interval["start"], interval["end"]):
            if not isinstance(endpoint, dict) or set(endpoint) != {"pos", "line", "col"}:
                raise GoalEvidenceError("interaction range has an unsupported endpoint")
            if any(not isinstance(endpoint[k], int) or isinstance(endpoint[k], bool) or endpoint[k] < 1 for k in endpoint):
                raise GoalEvidenceError("interaction range coordinates must be positive integers")
            if endpoint["pos"] > size + 1:
                raise GoalEvidenceError("interaction range exceeds the queried source byte length")
        if interval["start"]["pos"] > interval["end"]["pos"]:
            raise GoalEvidenceError("interaction interval is reversed")
    return value


def _inventory(messages: list[dict[str, Any]], size: int) -> tuple[str, list[dict[str, Any]], list[Any]]:
    if any(message.get("kind") in EDIT_ACTIONS for message in messages):
        return "protocol-error", [], []
    if _info(messages, "Error"):
        return "load-error", [], []
    points = [m.get("interactionPoints") for m in messages if m.get("kind") == "InteractionPoints"]
    summaries = _info(messages, "AllGoalsWarnings")
    if len(points) != 1 or not isinstance(points[0], list) or len(summaries) != 1:
        return "protocol-error", [], []
    summary = summaries[0]
    if any(not isinstance(summary.get(k), list) for k in ("visibleGoals", "invisibleGoals", "warnings", "errors")):
        return "protocol-error", [], []
    try:
        by_id = {}
        for point in points[0]:
            if not isinstance(point, dict) or set(point) != {"id", "range"}:
                raise GoalEvidenceError("interaction point must contain id and range")
            number = _goal_id(point)
            if number in by_id:
                raise GoalEvidenceError("duplicate interaction ID")
            by_id[number] = {"id": number, "range": _ranges(point["range"], size)}
        visible = {}
        for item in summary["visibleGoals"]:
            if not isinstance(item, dict) or item.get("kind") != "OfType" or not isinstance(item.get("type"), str) or not item["type"].strip():
                raise GoalEvidenceError("visible goal requires an OfType display")
            number = _goal_id(item.get("constraintObj"))
            if number in visible or number not in by_id:
                raise GoalEvidenceError("visible goal ID does not uniquely match interaction points")
            reference = item["constraintObj"]
            if isinstance(reference, dict) and "range" in reference and reference["range"] != by_id[number]["range"]:
                raise GoalEvidenceError("visible goal range disagrees with its interaction point")
            visible[number] = item["type"]
        if set(visible) != set(by_id):
            raise GoalEvidenceError("interaction points and visible goals disagree")
        goals = [{**by_id[number], "type": visible[number]} for number in sorted(by_id)]
    except EvidenceError:
        return "protocol-error", [], []
    status = "load-blocked" if summary["warnings"] or summary["errors"] else "available"
    return status, goals, summary["invisibleGoals"]


def _goal_request(file: str, number: int) -> str:
    return f"IOTCM {haskell_string(file)} None Direct (Cmd_goal_type_context Simplified {number} noRange \"\")"


def _selected(goals: list[dict[str, Any]], number: int) -> dict[str, Any] | None:
    return next((goal for goal in goals if goal["id"] == number), None)


def _selection_matches(prior: dict[str, Any], current: dict[str, Any] | None) -> bool:
    return current is not None and prior["id"] == current["id"] and prior["range"] == current["range"]


def goal_result(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "protocol-error", "goals": [], "invisibleGoals": [], "selected": None}
    transcript = value["transcript"]
    if len(transcript) >= 2 and transcript[1]["complete"]:
        size = next(record["size"] for record in value["snapshot"]["files"] if record["path"] == value["query"]["file"])
        status, goals, invisible = _inventory(transcript[1]["responses"], size)
        result.update(goals=goals, invisibleGoals=invisible)
    else:
        status = "protocol-error"
    if value["transport"]["status"] != "completed":
        result["status"] = value["transport"]["status"]
        return result
    if any(message.get("kind") in EDIT_ACTIONS for phase in transcript for message in phase["responses"]):
        return result
    if len(transcript) < 2 or not all(record["complete"] for record in transcript):
        return result
    if _info(transcript[0]["responses"], "Error"):
        return result
    if status != "available":
        result["status"] = status
        return result
    query = value["query"]
    if query["operation"] == "list":
        result["status"] = "listed"
        return result
    number = query["goalId"]
    current = _selected(result["goals"], number)
    prior = _selected(value["listing"]["result"]["goals"], number)
    if prior is None or not _selection_matches(prior, current):
        result["status"] = "selection-error"
        return result
    if len(transcript) != 3:
        return result
    messages = transcript[2]["responses"]
    if any(message.get("kind") in EDIT_ACTIONS for message in messages):
        return result
    if _info(messages, "Error"):
        result["status"] = "query-error"
        return result
    infos = _info(messages, "GoalSpecific")
    if len(infos) != 1:
        return result
    try:
        info = infos[0]
        reference = info.get("interactionPoint")
        if _goal_id(reference) != number:
            return result
        if isinstance(reference, dict) and reference.get("range") != current["range"]:
            return result
        goal = _object(info.get("goalInfo"), "goal information")
        if goal.get("kind") != "GoalType" or goal.get("rewrite") != "Simplified" or goal.get("typeAux") != {"kind": "GoalOnly"}:
            return result
        if not isinstance(goal.get("type"), str) or not goal["type"].strip() or not isinstance(goal.get("entries"), list):
            return result
        for entry in goal["entries"]:
            if not isinstance(entry, dict) or any(not isinstance(entry.get(k), str) for k in ("originalName", "reifiedName", "binding")) or not isinstance(entry.get("inScope"), bool):
                return result
        for field in ("boundary", "outputForms"):
            if not isinstance(goal.get(field), list) or any(not isinstance(item, str) for item in goal[field]):
                return result
        result["selected"] = {"id": number, "range": current["range"], "type": goal["type"],
                              "entries": goal["entries"], "boundary": goal["boundary"], "outputForms": goal["outputForms"]}
        result["status"] = "inspected"
    except EvidenceError:
        pass
    return result


def _validate(value: Any) -> dict[str, Any]:
    observation = _object(value, "goal observation")
    fields = {"format", "observationId", "snapshot", "resolution", "listing", "query", "execution", "transcript", "transport", "result"}
    if set(observation) != fields or observation["format"] != GOAL_FORMAT:
        raise GoalEvidenceError("goal observation has unsupported fields or format")
    snapshot = _object(observation["snapshot"], "goal snapshot")
    if snapshot.get("format") != "agda-evidence/snapshot-v1" or snapshot.get("treeAlgorithm") != "sha256":
        raise GoalEvidenceError("goal snapshot has unsupported format")
    source_id = derive_source_id(snapshot)
    if snapshot.get("sourceId") != source_id or snapshot.get("sourceDigest") != source_id:
        raise GoalEvidenceError("goal source identity does not match its snapshot")
    records = _normalised_file_records(snapshot.get("files"))
    if any(any(part in {"", ".", ".."} for part in record["path"].split("/")) for record in records):
        raise GoalEvidenceError("goal snapshot contains an unsafe source path")
    resolution = _object(observation["resolution"], "goal resolution")
    if resolution.get("format") != "agda-evidence/resolution-v1" or resolution.get("resolutionStatus") != "partial" or "nix" in resolution:
        raise GoalEvidenceError("goal resolution must be a partial native observation")
    if resolution.get("resolutionId") != derive_resolution_id(resolution):
        raise GoalEvidenceError("goal resolution identity does not match its projection")
    query = _object(observation["query"], "goal query")
    if set(query) != {"file", "sourceSha256", "operation", "goalId", "includes", "safe", "rewrite", "loadPolicy"}:
        raise GoalEvidenceError("goal query has unsupported fields")
    file = _indexable_source_path(query["file"], "goal file")
    file_record = next((r for r in records if r["path"] == file), None)
    if file_record is None or file_record["sha256"] != query["sourceSha256"]:
        raise GoalEvidenceError("goal file is not bound to its source snapshot")
    roots = query["includes"]
    if not isinstance(roots, list) or _include_roots(roots) != roots:
        raise GoalEvidenceError("goal includes are not canonical")
    if not isinstance(query["safe"], bool) or query["rewrite"] != "Simplified" or query["loadPolicy"] != LOAD_POLICY:
        raise GoalEvidenceError("goal query has an unsupported policy")
    prior = observation["listing"]
    if query["operation"] == "list":
        if query["goalId"] is not None or prior is not None:
            raise GoalEvidenceError("a goal listing must not contain a selection or prior observation")
    elif query["operation"] == "inspect":
        _goal_id(query["goalId"])
        if not isinstance(query["goalId"], int):
            raise GoalEvidenceError("selected goal ID must be a scalar integer")
        prior = _object(prior, "prior goal listing")
        if not isinstance(prior.get("query"), dict) or prior["query"].get("operation") != "list" or prior.get("listing") is not None:
            raise GoalEvidenceError("inspection requires a leaf listing, not nested inspection history")
        _validate(prior)
        if prior["result"]["status"] != "listed" or _selected(prior["result"]["goals"], query["goalId"]) is None:
            raise GoalEvidenceError("selected interaction ID is not in an accepted prior listing")
        for field in ("file", "sourceSha256", "includes", "safe", "rewrite", "loadPolicy"):
            if query[field] != prior["query"][field]:
                raise GoalEvidenceError("inspection policy differs from its prior listing")
        if source_id != prior["snapshot"]["sourceId"] or resolution["resolutionId"] != prior["resolution"]["resolutionId"]:
            raise GoalEvidenceError("inspection source/resolution subjects differ from its listing")
    else:
        raise GoalEvidenceError("goal operation must be list or inspect")
    execution = _object(observation["execution"], "goal execution")
    if set(execution) != {"argv", "mode", "timeoutSeconds", "maxOutputBytes", "startedAt", "finishedAt"}:
        raise GoalEvidenceError("goal execution has unsupported fields")
    if execution["argv"] != _argv("$AGDA", roots, query["safe"], anchor="$PROJECT_ROOT") or execution["mode"] != "isolated-project-copy":
        raise GoalEvidenceError("goal execution argv does not match anchored query policy")
    for field, minimum in (("timeoutSeconds", 1), ("maxOutputBytes", 1024)):
        if not isinstance(execution[field], int) or isinstance(execution[field], bool) or execution[field] < minimum:
            raise GoalEvidenceError("goal execution limits are invalid")
    started = _parse_timestamp(execution["startedAt"], "goal start")
    finished = _parse_timestamp(execution["finishedAt"], "goal finish")
    if started > finished or any(_parse_timestamp(item["capturedAt"], "goal capture") > started for item in (snapshot, resolution)):
        raise GoalEvidenceError("goal timestamps are not causally ordered")
    if prior is not None and _parse_timestamp(prior["execution"]["finishedAt"], "prior listing finish") > started:
        raise GoalEvidenceError("inspection began before the prior listing finished")
    transcript = observation["transcript"]
    limit = 2 if query["operation"] == "list" else 3
    if not isinstance(transcript, list) or len(transcript) > limit:
        raise GoalEvidenceError("goal transcript has unsupported phase count")
    for number, record in enumerate(transcript):
        record = _object(record, "goal phase")
        phase = ("startup", "load", "goal")[number]
        request = None if number == 0 else (_request(f"$PROJECT_ROOT/{file}", "load", "") if number == 1 else _goal_request(f"$PROJECT_ROOT/{file}", query["goalId"]))
        if set(record) != {"phase", "request", "responses", "complete"} or record["phase"] != phase or record["request"] != request:
            raise GoalEvidenceError("goal phase/request does not match the recorded operation")
        if not isinstance(record["complete"], bool) or not isinstance(record["responses"], list) or any(not isinstance(m, dict) or not isinstance(m.get("kind"), str) for m in record["responses"]):
            raise GoalEvidenceError("goal phase response/completion shape is invalid")
        if number > 0 and not transcript[number - 1]["complete"]:
            raise GoalEvidenceError("goal observation continued after an incomplete phase")
        if number > 0 and any(_info(previous["responses"], "Error") or
                              any(message.get("kind") in EDIT_ACTIONS for message in previous["responses"])
                              for previous in transcript[:number]):
            raise GoalEvidenceError("goal observation continued after a fatal or editing response")
        if number == 2:
            state, goals, _ = _inventory(transcript[1]["responses"], file_record["size"])
            previous = _selected(prior["result"]["goals"], query["goalId"])
            if state != "available" or not _selection_matches(previous, _selected(goals, query["goalId"])):
                raise GoalEvidenceError("goal query was issued after a blocked load or mismatched selection")
    transport = _object(observation["transport"], "goal transport")
    if set(transport) != {"status", "message", "stderr", "stdoutBytes"} or not isinstance(transport["status"], str) or transport["status"] not in TRANSPORT_STATUSES:
        raise GoalEvidenceError("goal transport has unsupported status or fields")
    if not isinstance(transport["stderr"], str) or (transport["message"] is not None and not isinstance(transport["message"], str)) or not isinstance(transport["stdoutBytes"], int) or isinstance(transport["stdoutBytes"], bool) or transport["stdoutBytes"] < 0:
        raise GoalEvidenceError("goal transport diagnostics are invalid")
    if canonical_json_bytes(observation["result"]) != canonical_json_bytes(goal_result(observation)):
        raise GoalEvidenceError("goal result does not match retained responses")
    if observation["result"]["status"] in {"listed", "inspected"}:
        if resolution["agda"].get("available") is not True:
            raise GoalEvidenceError("successful goal observation requires an available compiler")
        _digest_identifier(resolution["agda"].get("binarySha256"), "goal compiler digest")
    if observation["observationId"] != goal_observation_id(observation):
        raise GoalEvidenceError("goal observationId does not match complete contents")
    return observation


def validate_goal_observation(value: Any) -> dict[str, Any]:
    try:
        return _validate(value)
    except (EvidenceError, TypeError, ValueError, KeyError, AttributeError, StopIteration) as error:
        raise GoalEvidenceError(str(error)) from error


def observe_goals(
    project_root: Path, file: str, *, agda_binary: str = "agda", includes: Sequence[str] = (), safe: bool = False,
    timeout_seconds: int = 60, max_output_bytes: int = 4_194_304,
    listing: dict[str, Any] | None = None, goal_id: int | None = None,
) -> dict[str, Any]:
    if os.name != "posix":
        raise EvidenceError("the native goal adapter currently requires POSIX")
    if listing is not None:
        listing = validate_goal_observation(listing)
        if listing["query"]["operation"] != "list" or listing["result"]["status"] != "listed":
            raise GoalEvidenceError("inspection requires an accepted saved listing")
        _goal_id(goal_id)
        if not isinstance(goal_id, int):
            raise EvidenceError("goal ID must be a scalar integer")
        if _selected(listing["result"]["goals"], goal_id) is None:
            raise EvidenceError("goal ID is not a selectable interaction point in the listing")
        file, includes, safe = listing["query"]["file"], listing["query"]["includes"], listing["query"]["safe"]
    elif goal_id is not None:
        raise EvidenceError("goal inspection requires an explicit prior listing")
    file = _indexable_source_path(file, "goal file")
    if any(ord(c) < 32 for c in file):
        raise EvidenceError("goal file must not contain control characters")
    if not isinstance(safe, bool) or not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds < 1:
        raise EvidenceError("goal safe policy/timeout is invalid")
    if not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool) or max_output_bytes < 1024:
        raise EvidenceError("goal output limit must be at least 1024 bytes")
    roots = _include_roots(includes)
    root = project_root.resolve()
    snapshot, files = build_snapshot(root)
    if listing and snapshot["sourceId"] != listing["snapshot"]["sourceId"]:
        raise GoalEvidenceError("goal listing source pin mismatch before interaction")
    records = {r["path"]: r for r in snapshot["files"]}
    if file not in records:
        raise EvidenceError("goal file is absent from the source snapshot")
    for directory in roots:
        if not (root / directory).is_dir():
            raise EvidenceError(f"goal include root does not exist: {directory}")
    resolution = build_resolution(root, agda_binary=agda_binary)
    if listing and resolution["resolutionId"] != listing["resolution"]["resolutionId"]:
        raise GoalEvidenceError("goal listing native resolution pin mismatch before interaction")
    value = {
        "format": GOAL_FORMAT, "observationId": "", "snapshot": snapshot, "resolution": resolution, "listing": listing,
        "query": {"file": file, "sourceSha256": records[file]["sha256"], "operation": "inspect" if listing else "list",
                  "goalId": goal_id, "includes": roots, "safe": safe, "rewrite": "Simplified", "loadPolicy": LOAD_POLICY},
        "execution": {"argv": _argv("$AGDA", roots, safe, anchor="$PROJECT_ROOT"), "mode": "isolated-project-copy",
                      "timeoutSeconds": timeout_seconds, "maxOutputBytes": max_output_bytes, "startedAt": utc_now(), "finishedAt": ""},
        "transcript": [], "transport": {"status": "completed", "message": None, "stderr": "", "stdoutBytes": 0}, "result": {},
    }
    session = None
    with tempfile.TemporaryDirectory(prefix="agda-evidence-goals-") as temporary:
        stage = Path(temporary) / "project"; stage.mkdir()
        _copy_snapshot(root, files, stage)
        for directory in roots:
            (stage / directory).mkdir(parents=True, exist_ok=True)
        if build_snapshot(stage)[0]["sourceId"] != snapshot["sourceId"] or build_snapshot(root)[0]["sourceId"] != snapshot["sourceId"]:
            raise GoalEvidenceError("goal source inputs changed during staging")
        try:
            executable = shutil.which(agda_binary)
            if not executable:
                raise SessionError("execution-error", "Agda executable was not found")
            binary = Path(executable).resolve()
            if f"sha256:{sha256_file(binary)}" != resolution["agda"].get("binarySha256"):
                raise GoalEvidenceError("goal compiler changed after resolution capture")
            session = AgdaSession(_argv(str(binary), roots, safe, anchor=str(stage)), stage, timeout_seconds, max_output_bytes)
            for phase in ("startup", "load", "goal") if listing else ("startup", "load"):
                actual = None if phase == "startup" else (_request(str(stage / file), "load", "") if phase == "load" else _goal_request(str(stage / file), goal_id))
                logical = None if phase == "startup" else (_request(f"$PROJECT_ROOT/{file}", "load", "") if phase == "load" else _goal_request(f"$PROJECT_ROOT/{file}", goal_id))
                record = {"phase": phase, "request": logical, "responses": [], "complete": False}
                value["transcript"].append(record); session.exchange(record, actual)
                if _info(record["responses"], "Error") or any(message.get("kind") in EDIT_ACTIONS for message in record["responses"]):
                    break
                if phase == "load":
                    status, goals, _ = _inventory(record["responses"], records[file]["size"])
                    if status != "available":
                        break
                    if listing and not _selection_matches(_selected(listing["result"]["goals"], goal_id), _selected(goals, goal_id)):
                        break
        except SessionError as error:
            value["transport"]["status"] = error.status
            value["transport"]["message"] = _normalise(str(error), stage)
        finally:
            if session is not None:
                value["transport"]["stderr"] = _normalise(session.stderr.decode("utf-8", errors="replace"), stage)
                value["transport"]["stdoutBytes"] = session.stdout_bytes
                session.close()
                if f"sha256:{sha256_file(binary)}" != resolution["agda"].get("binarySha256"):
                    raise GoalEvidenceError("goal compiler changed during inspection")
        if build_snapshot(stage)[0]["sourceId"] != snapshot["sourceId"]:
            raise GoalEvidenceError("goal queries modified captured regular source inputs")
    value["execution"]["finishedAt"] = utc_now()
    value["result"] = goal_result(value)
    value["observationId"] = goal_observation_id(value)
    return validate_goal_observation(value)


def write_goal_observation(path: Path, value: dict[str, Any]) -> None:
    validate_goal_observation(value)
    if path.exists() or path.is_symlink():
        raise EvidenceError(f"goal observation output already exists: {path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(canonical_json_bytes(value) + b"\n")
    except OSError as error:
        raise EvidenceError(f"cannot write goal observation: {error}") from error


def load_goal_observation(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise GoalEvidenceError("goal observation must be a regular non-symlinked file")
        return validate_goal_observation(_read_json(path))
    except EvidenceError as error:
        raise GoalEvidenceError(str(error)) from error
