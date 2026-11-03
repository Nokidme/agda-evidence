"""Contextual expression elaboration, not proof completion or residual freedom."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .checker import _info, haskell_string
from .core import EvidenceError, _digest_identifier, _object, _read_json, canonical_json_bytes
from .goals import (
    EDIT_ACTIONS, GoalEvidenceError, _capture_goals, _inventory, _selected,
    _selection_matches, _validate_capture, goal_observation_id, validate_goal_observation,
)

CANDIDATE_FORMAT = "agda-evidence/candidate-observation-v1"
CANDIDATE_POLICY = "contextual-elaboration-restored-goals-v1"
ASSURANCE = "contextual-elaboration-only"
MAX_EXPRESSION_BYTES = 65_536


def _expression(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError("candidate expression must be an explicit non-empty string")
    haskell_string(value)
    if len(value.encode("utf-8")) > MAX_EXPRESSION_BYTES:
        raise EvidenceError("candidate expression exceeds the 65536-byte UTF-8 input limit")
    return value


def _check_request(file: str, number: int, expression: str) -> str:
    return f"IOTCM {haskell_string(file)} None Direct (Cmd_goal_type_context_check Simplified {number} noRange {haskell_string(expression)})"


def _metas_request(file: str, number: int) -> str:
    return f"IOTCM {haskell_string(file)} None Direct (Cmd_metas AsIs)"


def _phases(expression: str):
    return (("check", lambda file, number: _check_request(file, number, expression)), ("postflight", _metas_request))


def _elaboration(messages: list[dict[str, Any]], point: dict[str, Any]) -> dict[str, Any] | None:
    infos = _info(messages, "GoalSpecific")
    if len(infos) != 1:
        return None
    info = infos[0]
    reference = info.get("interactionPoint")
    # Numeric compatibility retains selection from the load. Rich IDs must have
    # the complete correctly typed ID/range pair, never a Boolean alias.
    if isinstance(reference, dict):
        if canonical_json_bytes(reference) != canonical_json_bytes({"id": point["id"], "range": point["range"]}):
            return None
    elif not isinstance(reference, int) or isinstance(reference, bool) or reference != point["id"]:
        return None
    goal = info.get("goalInfo")
    if not isinstance(goal, dict) or goal.get("kind") != "GoalType" or goal.get("rewrite") != "Simplified":
        return None
    aux = goal.get("typeAux")
    if not isinstance(aux, dict) or set(aux) != {"kind", "term"} or aux["kind"] != "GoalAndElaboration" or not isinstance(aux["term"], str) or not aux["term"].strip():
        return None
    if not isinstance(goal.get("type"), str) or not goal["type"].strip() or not isinstance(goal.get("entries"), list):
        return None
    for entry in goal["entries"]:
        if not isinstance(entry, dict) or any(not isinstance(entry.get(k), str) for k in ("originalName", "reifiedName", "binding")) or not isinstance(entry.get("inScope"), bool):
            return None
    for field in ("boundary", "outputForms"):
        if not isinstance(goal.get(field), list) or any(not isinstance(item, str) for item in goal[field]):
            return None
    return {"id": point["id"], "range": point["range"], "type": goal["type"], "term": aux["term"],
            "entries": goal["entries"], "boundary": goal["boundary"], "outputForms": goal["outputForms"]}


def candidate_result(value: dict[str, Any]) -> dict[str, Any]:
    result = {"status": "protocol-error", "assurance": ASSURANCE, "selected": None, "postflightUnchanged": None}
    transcript = value["transcript"]
    if value["transport"]["status"] != "completed":
        result["status"] = value["transport"]["status"]
        return result
    if len(transcript) < 2 or not all(record["complete"] for record in transcript):
        return result
    if any(message.get("kind") in EDIT_ACTIONS for phase in transcript for message in phase["responses"]) or _info(transcript[0]["responses"], "Error"):
        return result
    size = next(record["size"] for record in value["snapshot"]["files"] if record["path"] == value["query"]["file"])
    status, points, _ = _inventory(transcript[1]["responses"], size)
    if status != "available":
        result["status"] = status
        return result
    number = value["query"]["goalId"]
    point = _selected(points, number)
    prior = _selected(value["listing"]["result"]["goals"], number)
    if not _selection_matches(prior, point):
        result["status"] = "selection-error"
        return result
    if len(transcript) < 3:
        return result
    if _info(transcript[2]["responses"], "Error"):
        result["status"] = "query-error"
        return result
    selected = _elaboration(transcript[2]["responses"], point)
    if selected is None or len(transcript) != 4:
        return result
    messages = transcript[3]["responses"]
    if _info(messages, "Error"):
        result["status"] = "postflight-error"
        return result
    summaries = _info(messages, "AllGoalsWarnings")
    if len(summaries) != 1 or any(not isinstance(summaries[0].get(k), list) for k in ("visibleGoals", "invisibleGoals", "warnings", "errors")):
        return result
    if summaries[0]["warnings"] or summaries[0]["errors"]:
        result["status"] = "postflight-blocked"
        return result
    baseline = _info(transcript[1]["responses"], "AllGoalsWarnings")[0]
    same = canonical_json_bytes(summaries[0]) == canonical_json_bytes(baseline)
    result["postflightUnchanged"] = same
    if not same:
        result["status"] = "postflight-changed"
        return result
    result.update(status="elaborated", selected=selected)
    return result


def validate_candidate_observation(value: Any) -> dict[str, Any]:
    try:
        observation = _object(value, "candidate observation")
        if observation.get("format") != CANDIDATE_FORMAT:
            raise GoalEvidenceError("candidate observation has an unsupported format")
        query = _object(observation.get("query"), "candidate query")
        expression = _expression(query.get("expression"))
        if query.get("operation") != "check" or query.get("candidatePolicy") != CANDIDATE_POLICY:
            raise GoalEvidenceError("candidate observation has unsupported operation or assurance policy")
        _validate_capture(observation, probe_operation="check", probe_phases=_phases(expression),
                          extra_query_fields=frozenset({"expression", "candidatePolicy"}))
        if canonical_json_bytes(observation["result"]) != canonical_json_bytes(candidate_result(observation)):
            raise GoalEvidenceError("candidate result does not match retained responses")
        if observation["result"]["status"] == "elaborated":
            agda = observation["resolution"]["agda"]
            if agda.get("available") is not True:
                raise GoalEvidenceError("elaborated candidate requires an available compiler")
            _digest_identifier(agda.get("binarySha256"), "candidate compiler digest")
        if observation["observationId"] != goal_observation_id(observation):
            raise GoalEvidenceError("candidate observationId does not match complete contents")
        return observation
    except (EvidenceError, TypeError, ValueError, KeyError, AttributeError, StopIteration) as error:
        raise GoalEvidenceError(str(error)) from error


def check_candidate(
    project_root: Path, listing: dict[str, Any], goal_id: int, expression: str, *, agda_binary: str = "agda",
    timeout_seconds: int = 60, max_output_bytes: int = 4_194_304,
    _expected_source_id: str | None = None, _expected_agda: dict[str, Any] | None = None,
    _expected_resolution_id: str | None = None,
) -> dict[str, Any]:
    expression = _expression(expression)
    listing = validate_goal_observation(listing)
    value = _capture_goals(
        project_root, listing["query"]["file"], listing=listing, goal_id=goal_id, agda_binary=agda_binary,
        timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes, probe_phases=_phases(expression),
        _expected_source_id=_expected_source_id, _expected_agda=_expected_agda,
        _expected_resolution_id=_expected_resolution_id,
    )
    value["format"] = CANDIDATE_FORMAT
    value["query"].update(operation="check", expression=expression, candidatePolicy=CANDIDATE_POLICY)
    value["result"] = candidate_result(value)
    value["observationId"] = goal_observation_id(value)
    return validate_candidate_observation(value)


def write_candidate_observation(path: Path, value: dict[str, Any]) -> None:
    validate_candidate_observation(value)
    if path.exists() or path.is_symlink():
        raise EvidenceError(f"candidate output already exists: {path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(canonical_json_bytes(value) + b"\n")
    except OSError as error:
        raise EvidenceError(f"cannot write candidate observation: {error}") from error


def load_candidate_observation(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise GoalEvidenceError("candidate observation must be a regular non-symlinked file")
        return validate_candidate_observation(_read_json(path))
    except EvidenceError as error:
        raise GoalEvidenceError(str(error)) from error
