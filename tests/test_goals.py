"""Read-only goal contracts: local fake Agda with real pipes, optional real Agda."""

from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from agda_evidence import checker, cli, core, goals


# Responses/modes live outside the project and executable, so changing a reload
# response does not accidentally change either pinned source or compiler bytes.
FAKE_AGDA = r'''
import json
import os
from pathlib import Path
import sys
import time

LOG = Path(__LOG__)
CONFIG = Path(__CONFIG__)
APP_DIR = __APP_DIR__
VERSION = Path(__VERSION__)


def log(**record):
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


log(argv=sys.argv[1:], cwd=os.getcwd())
if "--version" in sys.argv:
    print(VERSION.read_text(encoding="utf-8").strip())
    sys.exit(0)
if "--print-agda-app-dir" in sys.argv:
    print(APP_DIR)
    sys.exit(0)
if "--interaction-json" not in sys.argv:
    sys.exit(2)
config = json.loads(CONFIG.read_text(encoding="utf-8"))
mode = config.get("mode", "normal")


def send(data):
    if mode == "fragmented":
        for byte in data:
            sys.stdout.buffer.write(bytes([byte]))
            sys.stdout.buffer.flush()
            time.sleep(0.0001)
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def response(value):
    send((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))


def prompt():
    send(b"JSON> ")


if mode == "timeout-startup":
    time.sleep(30)
prompt()
for command in sys.stdin:
    log(command=command.rstrip("\n"))
    if "Cmd_load" in command:
        Path("generated.agdai").write_bytes(b"only in staged copy")
        if mode == "mutate-stage":
            with Path("notes.txt").open("a") as stream:
                stream.write("changed by compiler\n")
        if mode == "malformed-load":
            send(b'{"kind": not-json}\n')
        else:
            for value in config["load"]:
                response(value)
        prompt()
    elif "Cmd_goal_type_context" in command:
        if mode == "eof-goal":
            sys.exit(0)
        if mode == "timeout-goal":
            time.sleep(30)
        if mode == "stdout-limit":
            send(b"x" * 8192)
            time.sleep(30)
        if mode == "stderr-limit":
            sys.stderr.buffer.write(b"x" * 8192)
            sys.stderr.buffer.flush()
            time.sleep(30)
        if mode == "combined-limit":
            send(b"x" * 2200)
            sys.stderr.buffer.write(b"y" * 2200)
            sys.stderr.buffer.flush()
            time.sleep(30)
        if mode == "query-error":
            sys.stderr.write("goal diagnostic λ\n")
            sys.stderr.flush()
        for value in config["goal"]:
            response(value)
        prompt()
        if mode == "query-error":
            sys.exit(0)  # A successful OS exit is not an inspected goal.
    elif "Cmd_infer_toplevel" in command:
        response({"kind": "DisplayInfo", "info": {"kind": "InferredType", "expr": "Nat"}})
        prompt()
    else:
        sys.exit(3)
'''


def interval(start: int = 30, end: int = 31) -> list[dict]:
    return [{"start": {"pos": start, "line": 2, "col": start},
             "end": {"pos": end, "line": 2, "col": end}}]


def display(info: dict) -> dict:
    return {"kind": "DisplayInfo", "info": info}


def fixture() -> dict:
    points = [{"id": 4, "range": interval(60, 65)}, {"id": 0, "range": interval()}]
    hidden = [{"kind": "OfType", "constraintObj": {"name": "_隠99", "range": interval(90, 91)}, "type": "Nat"},
              {"kind": "JustSort", "constraintObj": {"name": "_sort", "range": []}}]
    summary = {"kind": "AllGoalsWarnings", "visibleGoals": [
        {"kind": "OfType", "constraintObj": copy.deepcopy(points[0]), "type": "n ≡ n"},
        {"kind": "OfType", "constraintObj": 0, "type": "Nat"}],
        "invisibleGoals": hidden, "warnings": [], "errors": []}
    goal = {"kind": "GoalType", "rewrite": "Simplified", "typeAux": {"kind": "GoalOnly"},
            "type": "n ≡ n", "entries": [
                {"originalName": "n", "reifiedName": "n", "binding": "Nat", "inScope": True},
                {"originalName": "α", "reifiedName": "α′", "binding": "(λ x → x) n ≡ n", "inScope": False}],
            "boundary": ["α = n → refl"], "outputForms": ["n ≡ n", "λ α → α"]}
    return {"mode": "normal", "load": [
        {"kind": "Status", "status": {"checked": False}}, display(summary),
        {"kind": "InteractionPoints", "interactionPoints": points}],
        "goal": [display({"kind": "GoalSpecific", "interactionPoint": copy.deepcopy(points[0]), "goalInfo": goal})]}


@unittest.skipUnless(os.name == "posix", "native fake Agda sessions require POSIX")
class GoalTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="goals-contract-")
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.project = self.temporary / "project λ"
        self.project.mkdir()
        (self.project / "src").mkdir()
        self.source = self.project / "Main.agda"
        # Source byte bounds must accommodate all retained wire ranges.
        self.source.write_text("module Main where\n-- " + "λ source padding " * 80 + "\n", encoding="utf-8")
        (self.project / "notes.txt").write_text("unrelated regular source input\n", encoding="utf-8")
        self.app_dir = self.temporary / "agda-config"
        self.app_dir.mkdir()
        environment = patch.dict(os.environ, {"AGDA_DIR": str(self.app_dir)})
        environment.start()
        self.addCleanup(environment.stop)
        self.binary = self.temporary / "fake agda λ;not-shell"
        self.log = self.temporary / "commands.jsonl"
        self.config = self.temporary / "responses.json"
        self.version = self.temporary / "version.txt"
        self.version.write_text("Agda version 2.6.3-fixture\n", encoding="utf-8")
        source = (FAKE_AGDA.replace("__LOG__", repr(str(self.log)))
                  .replace("__CONFIG__", repr(str(self.config)))
                  .replace("__APP_DIR__", repr(str(self.app_dir)))
                  .replace("__VERSION__", repr(str(self.version))))
        self.binary.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
        self.binary.chmod(0o755)
        self.configure()

    def configure(self, value: dict | None = None, *, mode: str = "normal") -> None:
        value = copy.deepcopy(value) if value is not None else fixture()
        value["mode"] = mode
        self.config.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
        self.log.unlink(missing_ok=True)

    def records(self) -> list[dict]:
        return ([json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
                if self.log.exists() else [])

    def commands(self) -> list[str]:
        return [record["command"] for record in self.records() if "command" in record]

    def observe(self, **options) -> dict:
        return goals.observe_goals(self.project, "Main.agda", agda_binary=str(self.binary), **options)

    def inspect(self, listing: dict, number: int = 4, **options) -> dict:
        return self.observe(listing=listing, goal_id=number, **options)

    def assert_status(self, value: dict, status: str, transport: str = "completed") -> None:
        self.assertEqual(value["result"]["status"], status)
        self.assertEqual(value["transport"]["status"], transport)
        if status != "inspected":
            self.assertIsNone(value["result"]["selected"])
        self.assertEqual(goals.validate_goal_observation(value), value)

    def assert_no_interaction(self) -> None:
        self.assertFalse(any("--interaction-json" in record.get("argv", []) for record in self.records()))
        self.assertEqual(self.commands(), [])

    @staticmethod
    def tree_bytes(root: Path) -> dict[str, bytes]:
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*") if path.is_file()}

    @staticmethod
    def run_cli(arguments: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                status = cli.main(["goals", *arguments])
            except SystemExit as error:
                status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    def list_args(self, output: Path) -> list[str]:
        return ["list", "--project-root", str(self.project), "--file", "Main.agda",
                "--output", str(output), "--agda-bin", str(self.binary)]

    def inspect_args(self, listing: Path, output: Path) -> list[str]:
        return ["inspect", "--project-root", str(self.project), "--listing", str(listing),
                "--goal-id", "4", "--output", str(output), "--agda-bin", str(self.binary)]

    def test_list_and_explicit_inspect_preserve_structured_unicode_and_isolation(self) -> None:
        before = self.tree_bytes(self.project)
        with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
            listing = self.observe(includes=("src", ".", "src"), safe=True)
            inspected = goals.observe_goals(
                self.project, "ignored.agda", agda_binary=str(self.binary), listing=listing, goal_id=4,
                includes=("../ignored",), safe=False)
        self.assert_status(listing, "listed")
        self.assert_status(inspected, "inspected")
        self.assertEqual(set(listing), {"format", "observationId", "snapshot", "resolution", "listing", "query",
                                       "execution", "transcript", "transport", "result"})
        self.assertEqual(listing["format"], "agda-evidence/goal-observation-v1")
        self.assertIsNone(listing["listing"])
        self.assertEqual(inspected["listing"], listing)
        self.assertEqual(listing["query"]["operation"], "list")
        self.assertIsNone(listing["query"]["goalId"])
        self.assertEqual(inspected["query"], {**listing["query"], "operation": "inspect", "goalId": 4})
        self.assertEqual(listing["query"]["includes"], [".", "src"])
        self.assertTrue(inspected["query"]["safe"])
        expected = [{"id": 0, "range": interval(), "type": "Nat"},
                    {"id": 4, "range": interval(60, 65), "type": "n ≡ n"}]
        self.assertEqual(listing["result"]["goals"], expected)
        self.assertEqual(listing["result"]["invisibleGoals"], fixture()["load"][1]["info"]["invisibleGoals"])
        payload = fixture()["goal"][0]["info"]["goalInfo"]
        self.assertEqual(inspected["result"]["selected"], {
            **expected[1], **{key: payload[key] for key in ("type", "entries", "boundary", "outputForms")}})
        self.assertFalse(inspected["result"]["selected"]["entries"][1]["inScope"])
        self.assertEqual([record["phase"] for record in inspected["transcript"]], ["startup", "load", "goal"])
        self.assertTrue(all(record["complete"] for record in inspected["transcript"]))
        self.assertEqual(inspected["transcript"][2]["request"],
                         'IOTCM "$PROJECT_ROOT/Main.agda" None Direct (Cmd_goal_type_context Simplified 4 noRange "")')
        self.assertEqual(len(self.commands()), 3)  # One list load; one reload and one selected query.
        self.assertEqual(sum("Cmd_goal_type_context" in command for command in self.commands()), 1)
        self.assertFalse(any("Cmd_give" in command or "Cmd_infer" in command for command in self.commands()))
        self.assertTrue(any("--version" in record.get("argv", []) for record in self.records()))
        self.assertTrue(any("--print-agda-app-dir" in record.get("argv", []) for record in self.records()))
        launches = [call for call in popen.call_args_list if "--interaction-json" in call.args[0]]
        self.assertEqual(len(launches), 2)
        for launch in launches:
            self.assertIsInstance(launch.args[0], list)
            self.assertFalse(launch.kwargs.get("shell", False))
            stage = Path(launch.kwargs["cwd"])
            self.assertNotEqual(stage, self.project)
            self.assertFalse(stage.exists())
            self.assertIn(str(stage / "src"), launch.args[0])
        self.assertEqual(inspected["execution"]["argv"], ["$AGDA", "--interaction-json", "--no-libraries",
                         "--ignore-interfaces", "--safe", "-i", "$PROJECT_ROOT", "-i", "$PROJECT_ROOT/src"])
        self.assertEqual(self.tree_bytes(self.project), before)
        self.assertEqual(list(self.project.rglob("*.agdai")), [])
        self.assertEqual(inspected["observationId"], goals.goal_observation_id(inspected))

    def test_empty_list_and_hidden_metas_are_available_without_relaxing_native_checker(self) -> None:
        for hidden in ([], fixture()["load"][1]["info"]["invisibleGoals"]):
            with self.subTest(hidden=bool(hidden)):
                config = fixture()
                config["load"][1]["info"].update(visibleGoals=[], invisibleGoals=hidden)
                config["load"][2]["interactionPoints"] = []
                self.configure(config)
                value = self.observe()
                self.assert_status(value, "listed")
                self.assertEqual(value["result"]["goals"], [])
                self.assertEqual(value["result"]["invisibleGoals"], hidden)
                self.assertEqual(len(self.commands()), 1)
        for config in (fixture(), config):
            with self.subTest(native_visible=bool(config["load"][2]["interactionPoints"])):
                self.configure(config)
                native = checker.infer_type(self.project, "Main.agda", "identity", agda_binary=str(self.binary))
                self.assertEqual(native["result"], {"status": "load-incomplete", "type": None})
                self.assertEqual(len(self.commands()), 1)

    def test_warnings_nonfatal_errors_and_fatal_error_block_goal_query(self) -> None:
        listing = self.observe()
        for diagnostic in ("warnings", "errors", "fatalError"):
            with self.subTest(diagnostic=diagnostic):
                config = fixture()
                if diagnostic == "fatalError":
                    config["load"].insert(0, display({"kind": "Error", "error": {"message": "Main.agda: fatal λ"}, "warnings": []}))
                else:
                    config["load"][1]["info"][diagnostic] = [{"message": "nonfatal diagnostic λ"}]
                self.configure(config)
                value = self.inspect(listing)
                self.assert_status(value, "load-error" if diagnostic == "fatalError" else "load-blocked")
                self.assertEqual(len(value["transcript"]), 2)
                self.assertEqual(len(self.commands()), 1)
                self.assertIn("diagnostic λ" if diagnostic != "fatalError" else "fatal λ",
                              json.dumps(value["transcript"], ensure_ascii=False))
                if diagnostic != "fatalError":
                    self.assertEqual(value["result"]["goals"], listing["result"]["goals"])

    def test_inventory_requires_exact_unique_ids_oftype_and_bounded_ranges(self) -> None:
        mutations = {
            "duplicate points": lambda c: c["load"][2]["interactionPoints"].append(copy.deepcopy(c["load"][2]["interactionPoints"][0])),
            "missing point": lambda c: c["load"][2]["interactionPoints"].pop(),
            "duplicate visible": lambda c: c["load"][1]["info"]["visibleGoals"].append(copy.deepcopy(c["load"][1]["info"]["visibleGoals"][0])),
            "missing visible": lambda c: c["load"][1]["info"]["visibleGoals"].pop(),
            "unmatched visible": lambda c: c["load"][1]["info"]["visibleGoals"][1].update(constraintObj=99),
            "not OfType": lambda c: c["load"][1]["info"]["visibleGoals"][0].update(kind="JustSort"),
            "empty type": lambda c: c["load"][1]["info"]["visibleGoals"][0].update(type=" "),
            "visible range mismatch": lambda c: c["load"][1]["info"]["visibleGoals"][0]["constraintObj"].update(range=interval(61, 65)),
            "missing id": lambda c: c["load"][2]["interactionPoints"][0].pop("id"),
            "missing range": lambda c: c["load"][2]["interactionPoints"][0].pop("range"),
            "not interval array": lambda c: c["load"][2]["interactionPoints"][0].update(range="60-65"),
            "missing endpoint": lambda c: c["load"][2]["interactionPoints"][0]["range"][0].pop("end"),
            "reversed interval": lambda c: c["load"][2]["interactionPoints"][0].update(range=interval(65, 60)),
            "out of source": lambda c: c["load"][2]["interactionPoints"][0].update(range=interval(1, 100000)),
        }
        for invalid in (-1, True, "4", 4.0, None):
            mutations[f"id {invalid!r}"] = lambda c, v=invalid: c["load"][2]["interactionPoints"][0].update(id=v)
        for field, invalid in (("pos", 0), ("line", True), ("col", "1")):
            mutations[f"coordinate {field}"] = lambda c, f=field, v=invalid: c["load"][2]["interactionPoints"][0]["range"][0]["start"].update({f: v})
        for label, mutate in mutations.items():
            with self.subTest(malformed=label):
                config = fixture()
                mutate(config)
                self.configure(config)
                value = self.observe()
                self.assert_status(value, "protocol-error")
                self.assertEqual(value["result"]["goals"], [])
                self.assertEqual(len(self.commands()), 1)

    def test_goal_specific_requires_matching_id_and_structured_goal_type_payload(self) -> None:
        listing = self.observe()
        mutations = {
            "wrong id": lambda i: i["interactionPoint"].update(id=0),
            "boolean id": lambda i: i.update(interactionPoint=True),
            "missing id": lambda i: i.pop("interactionPoint"),
            "wrong range": lambda i: i["interactionPoint"].update(range=interval()),
            "missing range": lambda i: i["interactionPoint"].pop("range"),
            "wrong kind": lambda i: i["goalInfo"].update(kind="CurrentGoal"),
            "wrong rewrite": lambda i: i["goalInfo"].update(rewrite="AsIs"),
            "wrong auxiliary": lambda i: i["goalInfo"].update(typeAux={"kind": "GoalAndHave"}),
            "missing auxiliary": lambda i: i["goalInfo"].pop("typeAux"),
            "empty type": lambda i: i["goalInfo"].update(type=""),
            "object binding": lambda i: i["goalInfo"]["entries"][0].update(binding={"type": "Nat"}),
            "nonboolean scope": lambda i: i["goalInfo"]["entries"][0].update(inScope=0),
            "missing name": lambda i: i["goalInfo"]["entries"][0].pop("originalName"),
            "string entry": lambda i: i["goalInfo"].update(entries=["n : Nat"]),
            "missing entries": lambda i: i["goalInfo"].pop("entries"),
            "nonstring boundary": lambda i: i["goalInfo"].update(boundary=[{}]),
            "missing boundary": lambda i: i["goalInfo"].pop("boundary"),
            "nonarray output forms": lambda i: i["goalInfo"].update(outputForms="n ≡ n"),
            "nonstring output form": lambda i: i["goalInfo"].update(outputForms=[False]),
        }
        for label, mutate in mutations.items():
            with self.subTest(payload=label):
                config = fixture()
                mutate(config["goal"][0]["info"])
                self.configure(config)
                value = self.inspect(listing)
                self.assert_status(value, "protocol-error")
                self.assertEqual(len(self.commands()), 2)
        for responses in ([], fixture()["goal"] * 2):
            with self.subTest(goal_response_count=len(responses)):
                config = fixture()
                config["goal"] = responses
                self.configure(config)
                self.assert_status(self.inspect(listing), "protocol-error")
        config = fixture()
        config["goal"][0]["info"]["interactionPoint"] = 4
        config["goal"][0]["info"]["goalInfo"]["type"] = "simplified dependent type"
        self.configure(config)
        value = self.inspect(listing)
        self.assert_status(value, "inspected")
        self.assertEqual(value["result"]["selected"]["type"], "simplified dependent type")
        self.assertEqual(value["result"]["goals"][1]["type"], "n ≡ n")

    def test_query_error_with_zero_exit_is_retained_not_promoted_to_success(self) -> None:
        listing = self.observe()
        config = fixture()
        config["goal"] = [display({"kind": "Error", "error": {"message": "unknown local λ"}, "warnings": []})]
        self.configure(config, mode="query-error")
        value = self.inspect(listing)
        self.assert_status(value, "query-error")
        self.assertTrue(value["transcript"][-1]["complete"])
        self.assertEqual(len(self.commands()), 2)
        self.assertIn("unknown local λ", json.dumps(value["transcript"], ensure_ascii=False))
        self.assertIn("goal diagnostic λ", value["transport"]["stderr"])

    def test_prompt_fragments_eof_timeout_and_output_limits_yield_valid_records(self) -> None:
        self.configure(mode="fragmented")
        listing = self.observe(timeout_seconds=5)
        self.assert_status(self.inspect(listing, timeout_seconds=5), "inspected")
        for mode, status, phase in (("eof-goal", "protocol-error", "goal"),
                                    ("malformed-load", "protocol-error", "load"),
                                    ("timeout-startup", "timed-out", "startup"),
                                    ("timeout-goal", "timed-out", "goal"),
                                    ("stdout-limit", "output-limit", "goal"),
                                    ("stderr-limit", "output-limit", "goal"),
                                    ("combined-limit", "output-limit", "goal")):
            with self.subTest(mode=mode):
                self.configure(mode=mode)
                value = self.inspect(listing, timeout_seconds=1, max_output_bytes=4096)
                self.assert_status(value, status, status)
                self.assertEqual(value["transcript"][-1]["phase"], phase)
                self.assertFalse(value["transcript"][-1]["complete"])
                self.assertTrue(value["transport"]["message"])
                self.assertLessEqual(len(value["transport"]["stderr"].encode("utf-8")), 4096)
                path = self.temporary / (mode + ".json")
                goals.write_goal_observation(path, value)
                with patch("subprocess.Popen", side_effect=AssertionError("failure verification launched Agda")):
                    self.assertEqual(goals.load_goal_observation(path), value)

    def test_missing_hidden_and_invalid_selectors_reject_before_any_process(self) -> None:
        listing = self.observe()
        self.log.unlink()
        for number in (99, 1, -1, True, "4", None, {"id": 4}, []):
            with self.subTest(goal_id=number):
                with patch("subprocess.Popen", side_effect=AssertionError("invalid selection launched a process")):
                    with self.assertRaises(core.EvidenceError):
                        self.inspect(listing, number)
        with patch("subprocess.Popen", side_effect=AssertionError("invalid arguments launched a process")):
            with self.assertRaises(core.EvidenceError):
                self.observe(goal_id=4)
            for options in ({"timeout_seconds": 0}, {"max_output_bytes": 512}, {"safe": "true"},
                            {"includes": ("../src",)}, {"includes": ("absent",)}):
                with self.subTest(options=options), self.assertRaises(core.EvidenceError):
                    self.observe(**options)
            with self.assertRaises(core.EvidenceError):
                goals.observe_goals(self.project, "../Main.agda", agda_binary=str(self.binary))
            invalid = copy.deepcopy(listing)
            invalid["result"]["status"] = "load-blocked"
            invalid["observationId"] = goals.goal_observation_id(invalid)
            with self.assertRaises(core.EvidenceError):
                self.inspect(invalid)
        self.assertEqual(self.records(), [])

    def test_stale_source_edit_add_remove_is_rejected_before_metadata(self) -> None:
        listing = self.observe()
        original = self.tree_bytes(self.project)
        for action in ("selected edit", "unrelated edit", "addition", "removal", "selected removal"):
            with self.subTest(action=action):
                for name, data in original.items():
                    (self.project / name).write_bytes(data)
                (self.project / "added.txt").unlink(missing_ok=True)
                if action == "addition":
                    (self.project / "added.txt").write_text("unrelated added input\n", encoding="utf-8")
                elif action in {"removal", "selected removal"}:
                    (self.project / ("Main.agda" if action == "selected removal" else "notes.txt")).unlink()
                else:
                    path = self.source if action == "selected edit" else self.project / "notes.txt"
                    path.write_bytes(path.read_bytes() + b"changed\n")
                self.log.unlink(missing_ok=True)
                with patch("subprocess.Popen", side_effect=AssertionError("stale source launched metadata or interaction")):
                    with self.assertRaisesRegex(goals.GoalEvidenceError, "source pin mismatch"):
                        self.inspect(listing)
                self.assertEqual(self.records(), [])

    def test_registry_native_metadata_and_compiler_changes_prevent_interaction(self) -> None:
        listing = self.observe()
        original = self.binary.read_bytes()
        version = self.version.read_bytes()
        registry = self.app_dir / "libraries"
        for action in ("registry", "version", "binary"):
            with self.subTest(action=action):
                registry.unlink(missing_ok=True)
                self.binary.write_bytes(original)
                self.version.write_bytes(version)
                if action == "registry":
                    registry.write_text("/different/library.agda-lib\n", encoding="utf-8")
                elif action == "version":
                    self.version.write_text("Agda version changed-with-identical-binary\n", encoding="utf-8")
                else:
                    self.binary.write_bytes(original + b"\n# changed compiler bytes\n")
                self.log.unlink(missing_ok=True)
                with self.assertRaisesRegex(goals.GoalEvidenceError, "resolution pin mismatch"):
                    self.inspect(listing)
                self.assertTrue(any("--version" in record.get("argv", []) for record in self.records()))
                self.assert_no_interaction()
        registry.unlink(missing_ok=True)
        self.binary.write_bytes(original)
        self.version.write_bytes(version)
        capture = goals.build_resolution
        def change_after_capture(*args, **options):
            value = capture(*args, **options)
            self.binary.write_bytes(original + b"\n# changed after capture\n")
            return value
        self.log.unlink(missing_ok=True)
        with patch.object(goals, "build_resolution", side_effect=change_after_capture):
            with self.assertRaisesRegex(goals.GoalEvidenceError, "compiler changed after resolution"):
                self.inspect(listing)
        self.assert_no_interaction()

    def test_fresh_selected_id_or_range_change_after_reload_is_saved_without_query(self) -> None:
        listing = self.observe()
        for action in ("range", "id"):
            with self.subTest(action=action):
                config = fixture()
                point = config["load"][2]["interactionPoints"][0]
                point.update(range=interval(61, 66)) if action == "range" else point.update(id=5)
                config["load"][1]["info"]["visibleGoals"][0]["constraintObj"] = copy.deepcopy(point)
                self.configure(config)
                value = self.inspect(listing)
                self.assert_status(value, "selection-error")
                self.assertEqual(len(value["transcript"]), 2)
                self.assertEqual(len(self.commands()), 1)
                self.assertEqual(value["listing"], listing)
                path = self.temporary / ("selection-" + action + ".json")
                goals.write_goal_observation(path, value)
                self.assertEqual(goals.load_goal_observation(path), value)

    def test_offline_verification_roundtrips_failures_and_rejects_rehashed_corruption_and_history(self) -> None:
        listing = self.observe()
        # Saved JSON has no shared references between result and transcript.
        inspected = json.loads(json.dumps(self.inspect(listing), ensure_ascii=False))
        config = fixture()
        config["goal"] = [display({"kind": "Error", "error": {"message": "retained failure"}})]
        self.configure(config)
        failure = self.inspect(listing)
        for label, value in (("list", listing), ("inspect", inspected), ("failure", failure)):
            path = self.temporary / (label + ".json")
            goals.write_goal_observation(path, value)
            saved = path.read_bytes()
            with patch("subprocess.Popen", side_effect=AssertionError("offline verifier launched a process")):
                self.assertEqual(goals.validate_goal_observation(value), value)
                self.assertEqual(goals.load_goal_observation(path), value)
                status, stdout, stderr = self.run_cli(["verify", str(path)])
                self.assertEqual(status, 0, stderr)
                self.assertEqual(json.loads(stdout)["result"]["status"], value["result"]["status"])
            with self.assertRaises(core.EvidenceError):
                goals.write_goal_observation(path, value)
            self.assertEqual(path.read_bytes(), saved)
            link = self.temporary / (label + "-link.json")
            link.symlink_to(path)
            with self.assertRaises(goals.GoalEvidenceError):
                goals.load_goal_observation(link)
        mutations = {
            "goal": lambda o: o["result"]["goals"][0].update(id=7),
            "boolean result id": lambda o: o["result"]["goals"][0].update(id=False),
            "type": lambda o: o["result"]["selected"].update(type="Set"),
            "context": lambda o: o["result"]["selected"]["entries"][1].update(inScope=True),
            "numeric result scope": lambda o: o["result"]["selected"]["entries"][1].update(inScope=0),
            "source": lambda o: o["snapshot"]["files"][0].update(sha256="sha256:" + "0" * 64),
            "source query": lambda o: o["query"].update(sourceSha256="sha256:" + "0" * 64),
            "query id": lambda o: o["query"].update(goalId=0),
            "query policy": lambda o: o["query"].update(safe=True),
            "phase": lambda o: o["transcript"][2].update(phase="infer"),
            "request": lambda o: o["transcript"][2].update(request='Cmd_goal_type_context Simplified 0 noRange ""'),
            "continued incomplete": lambda o: o["transcript"][1].update(complete=False),
            "raw goal payload": lambda o: o["transcript"][2]["responses"][0]["info"]["goalInfo"].update(type="Set"),
            "listing result": lambda o: o["listing"]["result"]["goals"][0].update(type="Set"),
            "listing identity": lambda o: o["listing"].update(observationId="sha256:" + "0" * 64),
            "nested history": lambda o: o.update(listing=copy.deepcopy(inspected)),
            "extra history": lambda o: o["listing"].update(listing=copy.deepcopy(listing)),
            "extra field": lambda o: o.update(proofPassed=True),
        }
        def rehashed_listing_range(o):
            prior = o["listing"]
            prior["result"]["goals"][1]["range"] = interval(61, 66)
            prior["transcript"][1]["responses"][2]["interactionPoints"][0]["range"] = interval(61, 66)
            prior["transcript"][1]["responses"][1]["info"]["visibleGoals"][0]["constraintObj"]["range"] = interval(61, 66)
            prior["observationId"] = goals.goal_observation_id(prior)
        mutations["fully rehashed prior selection"] = rehashed_listing_range
        path = self.temporary / "tampered.json"
        for label, mutate in mutations.items():
            with self.subTest(corruption=label):
                changed = copy.deepcopy(inspected)
                mutate(changed)
                if label == "listing result":
                    changed["listing"]["observationId"] = goals.goal_observation_id(changed["listing"])
                changed["observationId"] = goals.goal_observation_id(changed)
                path.write_text(json.dumps(changed, ensure_ascii=False) + "\n", encoding="utf-8")
                with patch("subprocess.Popen", side_effect=AssertionError("tamper verification launched a process")):
                    with self.assertRaises(goals.GoalEvidenceError):
                        goals.validate_goal_observation(changed)
                    with self.assertRaises(goals.GoalEvidenceError):
                        goals.load_goal_observation(path)
        changed = copy.deepcopy(inspected)
        changed["transport"]["stderr"] = "changed without rehash"
        with self.assertRaises(goals.GoalEvidenceError):
            goals.validate_goal_observation(changed)
        path.write_text('{"format":1,"format":2}\n', encoding="utf-8")
        with self.assertRaises(goals.GoalEvidenceError):
            goals.load_goal_observation(path)

    def test_copy_and_compiler_mutations_are_detected_without_touching_original_sources(self) -> None:
        original = self.tree_bytes(self.project)
        copy_snapshot = goals._copy_snapshot
        for location in ("stage", "source"):
            for action in ("addition", "removal", "edit"):
                with self.subTest(location=location, action=action):
                    for name, data in original.items():
                        (self.project / name).write_bytes(data)
                    (self.project / "added.txt").unlink(missing_ok=True)
                    self.log.unlink(missing_ok=True)
                    def mutate_copy(root, files, target):
                        copy_snapshot(root, files, target)
                        tree = target if location == "stage" else root
                        if action == "addition":
                            (tree / "added.txt").write_text("new source input\n", encoding="utf-8")
                        elif action == "removal":
                            (tree / "notes.txt").unlink()
                        else:
                            (tree / "notes.txt").write_text("changed source input\n", encoding="utf-8")
                    with patch.object(goals, "_copy_snapshot", side_effect=mutate_copy):
                        with self.assertRaisesRegex(goals.GoalEvidenceError, "changed during staging"):
                            self.observe()
                    self.assert_no_interaction()
        for name, data in original.items():
            (self.project / name).write_bytes(data)
        (self.project / "added.txt").unlink(missing_ok=True)
        self.configure(mode="mutate-stage")
        with self.assertRaisesRegex(goals.GoalEvidenceError, "modified captured regular source"):
            self.observe()
        self.assertEqual(self.tree_bytes(self.project), original)
        self.assertEqual(list(self.project.rglob("*.agdai")), [])

    def test_cli_list_inspect_inherit_policy_and_save_failure_with_exit_one(self) -> None:
        listing_path = self.temporary / "listing.json"
        status, stdout, stderr = self.run_cli(self.list_args(listing_path) + ["--include", "src", "--safe"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(stdout)["result"]["status"], "listed")
        listing = goals.load_goal_observation(listing_path)
        inspected_path = self.temporary / "inspected.json"
        status, stdout, stderr = self.run_cli(self.inspect_args(listing_path, inspected_path) +
                                            ["--timeout-seconds", "5", "--max-output-bytes", "8192"])
        self.assertEqual(status, 0, stderr)
        inspected = goals.load_goal_observation(inspected_path)
        self.assertEqual(inspected["listing"], listing)
        self.assertEqual(inspected["query"], {**listing["query"], "operation": "inspect", "goalId": 4})
        self.assertEqual(inspected["execution"]["timeoutSeconds"], 5)
        self.assertEqual(inspected["execution"]["maxOutputBytes"], 8192)
        self.assertEqual(json.loads(stdout)["result"]["selected"], inspected["result"]["selected"])
        for operation in ("list", "inspect"):
            config = fixture()
            if operation == "list":
                config["load"][1]["info"]["warnings"] = [{"message": "retained warning"}]
            else:
                config["goal"] = [display({"kind": "Error", "error": {"message": "retained error"}})]
            self.configure(config)
            path = self.temporary / ("cli-failed-" + operation + ".json")
            arguments = self.list_args(path) if operation == "list" else self.inspect_args(listing_path, path)
            status, stdout, stderr = self.run_cli(arguments)
            self.assertEqual(status, 1, stderr)
            value = goals.load_goal_observation(path)
            self.assertEqual(value["result"]["status"], "load-blocked" if operation == "list" else "query-error")
            self.assertEqual(json.loads(stdout)["result"], value["result"])
            self.log.unlink(missing_ok=True)
            with patch("subprocess.Popen", side_effect=AssertionError("CLI verification launched a process")):
                status, _, stderr = self.run_cli(["verify", str(path)])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(self.records(), [])

    def test_cli_output_guards_invalid_flags_and_repeated_selectors_precede_execution(self) -> None:
        listing_path = self.temporary / "listing.json"
        goals.write_goal_observation(listing_path, self.observe())
        existing = self.temporary / "existing.json"
        existing.write_bytes(b"keep existing output\n")
        link = self.temporary / "link.json"
        link.symlink_to(existing)
        project_link = self.temporary / "project-link"
        project_link.symlink_to(self.project, target_is_directory=True)
        output = self.temporary / "not-written.json"
        self.log.unlink(missing_ok=True)
        for path in (existing, link, listing_path, self.project / "out.json", project_link / "out.json"):
            for operation in ("list", "inspect"):
                with self.subTest(output=str(path), operation=operation):
                    arguments = self.list_args(path) if operation == "list" else self.inspect_args(listing_path, path)
                    with patch("subprocess.Popen", side_effect=AssertionError("unsafe output launched a process")):
                        status, _, stderr = self.run_cli(arguments)
                    self.assertEqual(status, 2, stderr)
                    self.assertTrue("outside" in stderr or "already exists" in stderr, stderr)
        self.assertEqual(existing.read_bytes(), b"keep existing output\n")
        self.assertFalse((self.project / "out.json").exists())
        for forbidden in (["--file", "Main.agda"], ["--include", "src"], ["--safe"], ["--bundle", str(self.temporary)]):
            with self.subTest(forbidden=forbidden):
                with patch("subprocess.Popen", side_effect=AssertionError("forbidden inspect flag launched a process")):
                    status, _, stderr = self.run_cli(self.inspect_args(listing_path, output) + forbidden)
                self.assertEqual(status, 2, stderr)
        for arguments in (self.list_args(output) + ["--timeout-seconds", "0"],
                          self.inspect_args(listing_path, output) + ["--max-output-bytes", "512"],
                          self.list_args(output) + ["--include", "../src"],
                          self.inspect_args(listing_path, output)[:-2] + ["--goal-id", "-1"],
                          ["list", "--project-root", str(self.project)],
                          ["inspect", "--project-root", str(self.project)]):
            with self.subTest(invalid=arguments):
                with patch("subprocess.Popen", side_effect=AssertionError("invalid CLI arguments launched a process")):
                    status, _, stderr = self.run_cli(arguments)
                self.assertEqual(status, 2, stderr)
                self.assertFalse(output.exists())
        for arguments in (self.list_args(output), self.inspect_args(listing_path, output)):
            selectors = ["--project-root", "--output", "--agda-bin"] + (
                ["--file"] if arguments[0] == "list" else ["--listing", "--goal-id"])
            for flag, value in [(flag, arguments[arguments.index(flag) + 1]) for flag in selectors] + [
                    ("--timeout-seconds", "5"), ("--max-output-bytes", "8192")]:
                base = arguments if flag in arguments else arguments + [flag, value]
                with self.subTest(operation=arguments[0], repeated=flag):
                    with patch("subprocess.Popen", side_effect=AssertionError("repeated selector launched a process")):
                        status, _, stderr = self.run_cli(base + [flag, value])
                    self.assertEqual(status, 2, stderr)
                    self.assertIn("only once", stderr)
        listing = goals.load_goal_observation(listing_path)
        with patch("subprocess.Popen", side_effect=AssertionError("unselectable ID launched a process")):
            arguments = self.inspect_args(listing_path, output)
            arguments[arguments.index("--goal-id") + 1] = "99"
            status, _, stderr = self.run_cli(arguments)
        self.assertEqual(status, 2, stderr)
        self.assertEqual(goals.load_goal_observation(listing_path), listing)
        self.assertEqual(self.records(), [])
        self.assertFalse(output.exists())


@unittest.skipUnless(os.name == "posix" and shutil.which("agda"), "optional native Agda is unavailable")
class RealAgdaGoalTests(unittest.TestCase):
    def test_multiple_holes_unicode_dependent_context_zero_goals_and_load_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="goals-real-") as directory:
            project = Path(directory) / "project"
            project.mkdir()
            app_dir = Path(directory) / "agda-config"
            app_dir.mkdir()
            source = project / "Main.agda"
            base = "module Main where\nopen import Agda.Builtin.Nat\nopen import Agda.Builtin.Equality\n"
            unfinished = base + "dependent : (n : Nat) → n ≡ n\ndependent n = {! !}\nother : Nat → Nat\nother α = ?\n"
            with patch.dict(os.environ, {"AGDA_DIR": str(app_dir)}):
                source.write_text(unfinished, encoding="utf-8")
                listing = goals.observe_goals(project, "Main.agda", timeout_seconds=15)
                self.assertEqual(listing["result"]["status"], "listed", listing["transcript"])
                self.assertEqual(len(listing["result"]["goals"]), 2)
                for goal in listing["result"]["goals"]:
                    with self.subTest(goal=goal["id"]):
                        value = goals.observe_goals(project, "Main.agda", listing=listing, goal_id=goal["id"], timeout_seconds=15)
                        self.assertEqual(value["result"]["status"], "inspected", value["transcript"])
                        selected = value["result"]["selected"]
                        self.assertEqual(selected["range"], goal["range"])
                        self.assertEqual(selected["type"], goal["type"])
                        name = "n" if goal["type"] == "n ≡ n" else "α"
                        self.assertTrue(any(entry["reifiedName"] == name and entry["binding"] == "Nat"
                                            and entry["inScope"] for entry in selected["entries"]), selected)
                        self.assertEqual(goals.validate_goal_observation(value), value)
                cases = [(base + "identity : Nat → Nat\nidentity x = x\n", "listed"),
                         (base + "broken : MissingName\nbroken = ?\n", "load-error"),
                         (unfinished + "f : Nat → Nat\nf zero = zero\nf _ = zero\nf (suc n) = n\n", "load-blocked"),
                         (unfinished + "loop : Nat\nloop = loop\n", "load-blocked"),
                         (unfinished + "f : Nat → Nat\nf zero = zero\nf (suc n) = zero\n"
                          "q : f _ ≡ zero\nq = refl\n", "load-blocked")]
                for text, expected in cases:
                    with self.subTest(status=expected, source=text):
                        source.write_text(text, encoding="utf-8")
                        value = goals.observe_goals(project, "Main.agda", timeout_seconds=15)
                        self.assertEqual(value["result"]["status"], expected, value["transcript"])
                        self.assertEqual(len(value["transcript"]), 2)
                        if expected == "listed":
                            self.assertEqual(value["result"]["goals"], [])
                        self.assertEqual(goals.validate_goal_observation(value), value)
                        self.assertEqual(source.read_text(encoding="utf-8"), text)
                        self.assertEqual(list(project.rglob("*.agdai")), [])


if __name__ == "__main__":
    unittest.main()
