"""Candidate trials: independent fake Agda/real pipes, offline evidence, optional 2.6.3."""

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
sys.path.insert(0, str(ROOT / "src"))

from agda_evidence import candidates, cli, core, goals


# Configuration, metadata and logs are outside both pinned source and executable.
# This is deliberately independent of the other test modules and their fixtures.
FAKE = r'''
import json
import os
from pathlib import Path
import sys
import time

LOG, CONFIG, VERSION, APP = map(Path, __PATHS__)

def record(**value):
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")

record(argv=sys.argv[1:], cwd=os.getcwd())
if "--version" in sys.argv:
    print(VERSION.read_text().strip())
    sys.exit(0)
if "--print-agda-app-dir" in sys.argv:
    print(APP)
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
            time.sleep(0.00005)
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

def emit(value):
    send((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))

def prompt():
    send(b"JSON> ")

if mode == "timeout-startup":
    time.sleep(30)
prompt()
for line in sys.stdin:
    command = line.rstrip("\n")
    record(command=command)
    if "Cmd_load" in command:
        phase = "load"
        Path("trial.agdai").write_bytes(b"generated only in stage")
        if mode == "mutate-stage":
            Path("notes.txt").write_text("unexpected compiler edit\n")
    elif "Cmd_goal_type_context_check" in command:
        phase = "check"
    elif "Cmd_metas AsIs" in command:
        phase = "postflight"
        if mode == "mutate-binary":
            with Path(sys.argv[0]).open("a") as stream:
                stream.write("\n# compiler modified during trial\n")
    elif "Cmd_goal_type_context Simplified" in command:
        phase = "inspect"
    else:
        sys.exit(3)
    if mode == "timeout-" + phase:
        time.sleep(30)
    if mode == "eof-" + phase:
        sys.exit(0)
    if phase == "check" and mode in ("stdout-limit", "stderr-limit", "combined-limit"):
        if mode != "stderr-limit":
            send(b"x" * (8192 if mode == "stdout-limit" else 2300))
        if mode != "stdout-limit":
            sys.stderr.buffer.write(b"y" * (8192 if mode == "stderr-limit" else 2300))
            sys.stderr.buffer.flush()
        time.sleep(30)
    if mode == "malformed-" + phase:
        send(b'{"kind": invalid-json}\n')
    else:
        if mode == "zero-exit-error" and phase == "check":
            sys.stderr.write("candidate diagnostic λ\n")
            sys.stderr.flush()
        for value in config[phase]:
            emit(value)
    prompt()
    if mode == "zero-exit-error" and phase == "check":
        sys.exit(0)
'''


def span(start=30, end=35):
    return [{"start": {"pos": start, "line": 2, "col": start},
             "end": {"pos": end, "line": 2, "col": end}}]


def info(value):
    return {"kind": "DisplayInfo", "info": value}


def responses():
    points = [{"id": 1, "range": span()}, {"id": 0, "range": span(60, 65)}]
    summary = {"kind": "AllGoalsWarnings", "visibleGoals": [
        {"kind": "OfType", "constraintObj": copy.deepcopy(points[0]), "type": "Alias n"},
        {"kind": "OfType", "constraintObj": 0, "type": "Nat"}],
        "invisibleGoals": [{"kind": "OfType", "constraintObj": {"name": "_隠9", "range": []}, "type": "Nat"}],
        "warnings": [], "errors": [], "metadata": {"restored": True, "generation": 1}}
    goal = {"kind": "GoalType", "rewrite": "Simplified", "type": "n ≡ n",
            "typeAux": {"kind": "GoalAndElaboration", "term": "refl"},
            "entries": [{"originalName": "n", "reifiedName": "n", "binding": "Nat", "inScope": True},
                        {"originalName": "α", "reifiedName": "α′", "binding": "n ≡ n", "inScope": False}],
            "boundary": ["α = n → refl"], "outputForms": ["n ≡ n", "λ α → α"]}
    inspected = copy.deepcopy(goal)
    inspected["typeAux"] = {"kind": "GoalOnly"}
    return {"mode": "normal", "load": [{"kind": "Status", "status": {"checked": False}},
            info(summary), {"kind": "InteractionPoints", "interactionPoints": points}],
            "check": [info({"kind": "GoalSpecific", "interactionPoint": copy.deepcopy(points[0]), "goalInfo": goal})],
            "inspect": [info({"kind": "GoalSpecific", "interactionPoint": copy.deepcopy(points[0]), "goalInfo": inspected})],
            "postflight": [info(copy.deepcopy(summary))]}


@unittest.skipUnless(os.name == "posix", "native pipe sessions require POSIX")
class CandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="candidates-contract-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.project = self.home / "project λ"
        self.project.mkdir()
        (self.project / "src").mkdir()
        self.source = self.project / "Main.agda"
        self.source.write_text("module Main where\n-- " + "λ padded input " * 60 + "\n", encoding="utf-8")
        (self.project / "notes.txt").write_bytes(b"unrelated regular source\n")
        self.app = self.home / "config"
        self.app.mkdir()
        environment = patch.dict(os.environ, {"AGDA_DIR": str(self.app)})
        environment.start()
        self.addCleanup(environment.stop)
        self.log, self.config, self.version = [self.home / name for name in ("wire.jsonl", "config.json", "version.txt")]
        self.version.write_text("Agda version 2.6.3-candidate-fixture\n")
        self.binary = self.home / "own fake λ;not-shell"
        script = FAKE.replace("__PATHS__", repr(tuple(map(str, (self.log, self.config, self.version, self.app)))))
        self.binary.write_text(f"#!{sys.executable}\n" + script, encoding="utf-8")
        self.binary.chmod(0o755)
        self.configure()

    def configure(self, value=None, mode="normal"):
        value = copy.deepcopy(value) if value is not None else responses()
        value["mode"] = mode
        self.config.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        self.log.unlink(missing_ok=True)

    def records(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    def commands(self):
        return [record["command"] for record in self.records() if "command" in record]

    def listing(self, **options):
        return goals.observe_goals(self.project, "Main.agda", agda_binary=str(self.binary), **options)

    def check(self, listing, number=1, expression="refl", **options):
        return candidates.check_candidate(self.project, listing, number, expression, agda_binary=str(self.binary), **options)

    def assert_result(self, value, status, transport="completed"):
        result = value["result"]
        self.assertEqual(set(result), {"status", "assurance", "selected", "postflightUnchanged"})
        self.assertEqual(result["status"], status)
        self.assertEqual(result["assurance"], "contextual-elaboration-only")
        self.assertEqual(value["transport"]["status"], transport)
        if status == "elaborated":
            self.assertIs(result["postflightUnchanged"], True)
            self.assertIsInstance(result["selected"], dict)
        else:
            self.assertIsNone(result["selected"])
            self.assertIs(result["postflightUnchanged"], False if status == "postflight-changed" else None)
        self.assertEqual(candidates.validate_candidate_observation(value), value)

    def assert_no_interaction(self):
        self.assertFalse(any("--interaction-json" in r.get("argv", []) for r in self.records()))
        self.assertEqual(self.commands(), [])

    @staticmethod
    def tree(root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    @staticmethod
    def run_cli(arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                status = cli.main(["goals", *arguments])
            except SystemExit as error:
                status = error.code
        return status, out.getvalue(), err.getvalue()

    def check_args(self, listing, output):
        return ["check", "--project-root", str(self.project), "--listing", str(listing), "--goal-id", "1",
                "--expression", "refl", "--output", str(output), "--agda-bin", str(self.binary)]

    def test_structured_unicode_explicit_requests_restored_state_and_isolation(self):
        before = self.tree(self.project)
        listing = self.listing(includes=("src", ".", "src"), safe=True)
        self.assertEqual(listing["format"], "agda-evidence/goal-observation-v1")
        self.assertEqual(listing["query"]["operation"], "list")
        self.assertEqual(listing["result"]["status"], "listed")
        self.assertIsNone(listing["listing"])
        self.configure(mode="fragmented")
        expression = '  λ α → α "quoted" \\ line\nnext\t1\x7f2  '
        with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
            value = self.check(listing, expression=expression, timeout_seconds=10)
        self.assert_result(value, "elaborated")
        self.assertEqual(set(value), set(listing))
        self.assertEqual(value["format"], "agda-evidence/candidate-observation-v1")
        self.assertEqual(value["listing"], listing)
        self.assertEqual(value["query"], {**listing["query"], "operation": "check", "goalId": 1,
            "expression": expression, "candidatePolicy": "contextual-elaboration-restored-goals-v1"})
        self.assertEqual([p["phase"] for p in value["transcript"]], ["startup", "load", "check", "postflight"])
        self.assertTrue(all(p["complete"] for p in value["transcript"]))
        escaped = '"  λ α → α \\"quoted\\" \\\\ line\\10\\&next\\9\\&1\\127\\&2  "'
        expected = f'IOTCM "$PROJECT_ROOT/Main.agda" None Direct (Cmd_goal_type_context_check Simplified 1 noRange {escaped})'
        self.assertEqual(value["transcript"][2]["request"], expected)
        self.assertEqual(value["transcript"][3]["request"], 'IOTCM "$PROJECT_ROOT/Main.agda" None Direct (Cmd_metas AsIs)')
        selected = responses()["check"][0]["info"]["goalInfo"]
        self.assertEqual(value["result"]["selected"], {"id": 1, "range": span(), "term": "refl",
            **{k: selected[k] for k in ("type", "entries", "boundary", "outputForms")}})
        # Load types may differ from Simplified types; restored hidden metas,
        # boundaries and outputForms are not candidate residual constraints.
        self.assertNotEqual(selected["type"], listing["result"]["goals"][1]["type"])
        self.assertTrue(listing["result"]["invisibleGoals"])
        self.assertFalse(value["result"]["selected"]["entries"][1]["inScope"])
        self.assertEqual(value["transcript"][1]["responses"][1], value["transcript"][3]["responses"][0])
        self.assertEqual(len(self.commands()), 3)
        self.assertIn("λ α → α", self.commands()[1])
        self.assertNotIn(r"\u03bb", self.commands()[1])
        self.assertFalse(any(token in "\n".join(self.commands()) for token in ("Cmd_give", "Cmd_refine", "Cmd_infer", "Cmd_solve")))
        launches = [c for c in popen.call_args_list if "--interaction-json" in c.args[0]]
        self.assertEqual(len(launches), 1)
        launch = launches[0]
        self.assertIsInstance(launch.args[0], list)
        self.assertFalse(launch.kwargs.get("shell", False))
        self.assertNotEqual(Path(launch.kwargs["cwd"]), self.project)
        self.assertFalse(Path(launch.kwargs["cwd"]).exists())
        self.assertEqual(value["execution"]["argv"], ["$AGDA", "--interaction-json", "--no-libraries", "--ignore-interfaces",
            "--safe", "-i", "$PROJECT_ROOT", "-i", "$PROJECT_ROOT/src"])
        self.assertEqual(self.tree(self.project), before)
        self.assertEqual(list(self.project.rglob("*.agdai")), [])
        for number in (0, 1):
            config = responses()
            config["check"][0]["info"]["interactionPoint"] = number
            self.configure(config)
            numeric = self.check(listing, number)
            self.assert_result(numeric, "elaborated")
            self.assertEqual(numeric["result"]["selected"]["id"], number)

    def test_blocked_loads_and_reselected_id_or_range_stop_before_check(self):
        listing = self.listing()
        for label in ("warnings", "errors", "fatal", "range", "id"):
            with self.subTest(label=label):
                config = responses()
                if label in ("warnings", "errors"):
                    config["load"][1]["info"][label] = [{"message": "load diagnostic λ"}]
                elif label == "fatal":
                    config["load"].insert(0, info({"kind": "Error", "message": "load failure λ"}))
                else:
                    point = config["load"][2]["interactionPoints"][0]
                    point.update(range=span(31, 36)) if label == "range" else point.update(id=7)
                    config["load"][1]["info"]["visibleGoals"][0]["constraintObj"] = copy.deepcopy(point)
                self.configure(config)
                value = self.check(listing)
                self.assert_result(value, "load-blocked" if label in ("warnings", "errors") else
                                   "load-error" if label == "fatal" else "selection-error")
                self.assertEqual([p["phase"] for p in value["transcript"]], ["startup", "load"])
                self.assertEqual(len(self.commands()), 1)

    def test_check_payload_requires_exact_selection_and_structured_elaboration(self):
        listing = self.listing()
        mutations = {
            "wrong id": lambda i: i["interactionPoint"].update(id=0),
            "bool id": lambda i: i["interactionPoint"].update(id=True),
            "numeric bool": lambda i: i.update(interactionPoint=True),
            "float id": lambda i: i.update(interactionPoint=1.0),
            "wrong range": lambda i: i["interactionPoint"].update(range=span(31, 36)),
            "bool coordinate": lambda i: i["interactionPoint"]["range"][0]["start"].update(line=True),
            "missing range": lambda i: i["interactionPoint"].pop("range"),
            "rich extra": lambda i: i["interactionPoint"].update(name="unbound"),
            "wrong kind": lambda i: i["goalInfo"].update(kind="CurrentGoal"),
            "rewrite": lambda i: i["goalInfo"].update(rewrite="AsIs"),
            "GoalOnly": lambda i: i["goalInfo"].update(typeAux={"kind": "GoalOnly"}),
            "GoalAndHave": lambda i: i["goalInfo"].update(typeAux={"kind": "GoalAndHave", "term": "refl"}),
            "expr not term": lambda i: i["goalInfo"].update(typeAux={"kind": "GoalAndElaboration", "expr": "refl"}),
            "extra expr": lambda i: i["goalInfo"]["typeAux"].update(expr="refl"),
            "wrong term": lambda i: i["goalInfo"]["typeAux"].update(term={"expr": "refl"}),
            "blank term": lambda i: i["goalInfo"]["typeAux"].update(term=" "),
            "blank type": lambda i: i["goalInfo"].update(type=""),
            "string entries": lambda i: i["goalInfo"].update(entries=["n : Nat"]),
            "missing name": lambda i: i["goalInfo"]["entries"][0].pop("originalName"),
            "object binding": lambda i: i["goalInfo"]["entries"][0].update(binding={"type": "Nat"}),
            "integer scope": lambda i: i["goalInfo"]["entries"][0].update(inScope=1),
            "string boundary": lambda i: i["goalInfo"].update(boundary="refl"),
            "nonstring form": lambda i: i["goalInfo"].update(outputForms=[False]),
            "missing boundary": lambda i: i["goalInfo"].pop("boundary"),
        }
        for label, mutate in mutations.items():
            with self.subTest(payload=label):
                config = responses()
                mutate(config["check"][0]["info"])
                self.configure(config)
                value = self.check(listing)
                self.assert_result(value, "protocol-error")
                self.assertEqual(len(self.commands()), 3)  # Complete prompt still permits the restoration probe.
                self.assertEqual(value["transcript"][-1]["phase"], "postflight")
        for count in (0, 2):
            config = responses()
            config["check"] *= count
            self.configure(config)
            self.assert_result(self.check(listing), "protocol-error")

    def test_query_and_postflight_error_messages_are_not_os_exit_success(self):
        listing = self.listing()
        for phase in ("check", "postflight"):
            with self.subTest(phase=phase):
                config = responses()
                config[phase] = [info({"kind": "Error", "message": "explicit type error λ"})]
                self.configure(config, "zero-exit-error" if phase == "check" else "normal")
                value = self.check(listing)
                self.assert_result(value, "query-error" if phase == "check" else "postflight-error")
                self.assertEqual(len(self.commands()), 2 if phase == "check" else 3)
                self.assertIn("explicit type error λ", json.dumps(value["transcript"], ensure_ascii=False))
                self.assertTrue(value["transcript"][-1]["complete"])
                if phase == "check":
                    self.assertIn("candidate diagnostic λ", value["transport"]["stderr"])
        for phase in ("load", "check", "postflight"):
            for action in ("GiveAction", "MakeCase", "SolveAll", "Mimer"):
                with self.subTest(phase=phase, editing_response=action):
                    config = responses()
                    config[phase].insert(0, {"kind": action})
                    self.configure(config)
                    value = self.check(listing)
                    self.assert_result(value, "protocol-error")
                    self.assertEqual(value["transcript"][-1]["phase"], phase)

    def test_postflight_summary_is_unique_well_formed_and_canonically_identical(self):
        listing = self.listing()
        mutations = {
            "visible type": lambda s: s["visibleGoals"][0].update(type="Nat"),
            "visible rich id bool": lambda s: s["visibleGoals"][0]["constraintObj"].update(id=True),
            "visible numeric id bool": lambda s: s["visibleGoals"][1].update(constraintObj=False),
            "range bool": lambda s: s["visibleGoals"][0]["constraintObj"]["range"][0]["start"].update(line=True),
            "range float": lambda s: s["visibleGoals"][0]["constraintObj"]["range"][0]["start"].update(pos=30.0),
            "visible order": lambda s: s["visibleGoals"].reverse(),
            "hidden metas": lambda s: s.update(invisibleGoals=[]),
            "metadata bool int": lambda s: s["metadata"].update(restored=1),
            "metadata int bool": lambda s: s["metadata"].update(generation=True),
            "extra field": lambda s: s.update(extra="not in baseline"),
        }
        for label, mutate in mutations.items():
            with self.subTest(change=label):
                config = responses()
                mutate(config["postflight"][0]["info"])
                self.configure(config)
                self.assert_result(self.check(listing), "postflight-changed")
        for label in ("missing", "duplicate", "wrong shape", "missing field", "warnings", "errors"):
            with self.subTest(summary=label):
                config = responses()
                summary = config["postflight"][0]["info"]
                if label == "missing":
                    config["postflight"] = []
                elif label == "duplicate":
                    config["postflight"] *= 2
                elif label == "wrong shape":
                    summary["invisibleGoals"] = "not an array"
                elif label == "missing field":
                    summary.pop("visibleGoals")
                else:
                    summary[label] = [{"message": "restoration blocked"}]
                self.configure(config)
                self.assert_result(self.check(listing), "postflight-blocked" if label in ("warnings", "errors") else "protocol-error")
        config = responses()
        config["postflight"][0]["info"] = dict(reversed(list(config["postflight"][0]["info"].items())))
        self.configure(config)
        self.assert_result(self.check(listing), "elaborated")  # Object key order is irrelevant.

    def test_transport_failures_are_saved_valid_observations(self):
        listing = self.listing()
        cases = [("timeout-startup", "timed-out", "startup"), ("timeout-check", "timed-out", "check"),
                 ("timeout-postflight", "timed-out", "postflight"), ("eof-check", "protocol-error", "check"),
                 ("eof-postflight", "protocol-error", "postflight"), ("malformed-load", "protocol-error", "load"),
                 ("malformed-check", "protocol-error", "check"), ("stdout-limit", "output-limit", "check"),
                 ("stderr-limit", "output-limit", "check"), ("combined-limit", "output-limit", "check")]
        for mode, status, phase in cases:
            with self.subTest(mode=mode):
                self.configure(mode=mode)
                value = self.check(listing, timeout_seconds=1, max_output_bytes=4096)
                self.assert_result(value, status, status)
                self.assertEqual(value["transcript"][-1]["phase"], phase)
                self.assertFalse(value["transcript"][-1]["complete"])
                self.assertTrue(value["transport"]["message"])
                path = self.home / (mode + ".json")
                candidates.write_candidate_observation(path, value)
                with patch("subprocess.Popen", side_effect=AssertionError("offline failure launched Agda")):
                    self.assertEqual(candidates.load_candidate_observation(path), value)

    def test_invalid_expressions_selectors_and_leaf_listing_reject_before_process(self):
        listing = self.listing()
        inspected = goals.observe_goals(self.project, "Main.agda", listing=listing, goal_id=1, agda_binary=str(self.binary))
        bad = copy.deepcopy(listing)
        bad["result"]["goals"][0]["id"] = False
        bad["observationId"] = goals.goal_observation_id(bad)
        self.log.unlink(missing_ok=True)
        with patch("subprocess.Popen", side_effect=AssertionError("invalid request launched any process")):
            for expression in (None, 0, [], "", " \n\t", "\ud800", "a\udfff", "x" * 65_537, "λ" * 32_769):
                with self.subTest(expression_type=type(expression).__name__, length=len(expression) if isinstance(expression, str) else None):
                    with patch.object(candidates, "validate_goal_observation", side_effect=AssertionError("invalid expression validated a prior")):
                        with self.assertRaises(core.EvidenceError):
                            self.check(listing, expression=expression)
            for number in (-1, True, False, 1.0, "1", None, {"id": 1}, [], 99, 9):
                with self.subTest(goal_id=number), self.assertRaises(core.EvidenceError):
                    self.check(listing, number)
            for options in ({"timeout_seconds": 0}, {"timeout_seconds": True}, {"max_output_bytes": 512}, {"max_output_bytes": True}):
                with self.subTest(options=options), self.assertRaises(core.EvidenceError):
                    self.check(listing, **options)
            for prior in (inspected, bad):
                with self.subTest(prior=prior["query"]["operation"]), self.assertRaises(core.EvidenceError):
                    self.check(prior)
        self.assertEqual(self.records(), [])
        boundary = "λ" * 32_768  # The fixed cap counts UTF-8 bytes, not characters.
        value = self.check(listing, expression=boundary)
        self.assert_result(value, "elaborated")
        self.assertEqual(value["query"]["expression"], boundary)

    def test_stale_source_and_add_remove_unrelated_files_reject_before_metadata(self):
        listing = self.listing()
        original = self.tree(self.project)
        for action in ("selected", "unrelated", "add", "remove"):
            with self.subTest(action=action):
                for name, data in original.items():
                    (self.project / name).write_bytes(data)
                (self.project / "new.txt").unlink(missing_ok=True)
                if action == "add":
                    (self.project / "new.txt").write_bytes(b"new input")
                elif action == "remove":
                    (self.project / "notes.txt").unlink()
                else:
                    path = self.source if action == "selected" else self.project / "notes.txt"
                    path.write_bytes(path.read_bytes() + b"changed\n")
                self.log.unlink(missing_ok=True)
                with patch("subprocess.Popen", side_effect=AssertionError("stale source launched metadata")):
                    with self.assertRaisesRegex(goals.GoalEvidenceError, "source pin mismatch"):
                        self.check(listing)
                self.assertEqual(self.records(), [])

    def test_native_resolution_and_compiler_pins_prevent_interaction(self):
        listing = self.listing()
        binary, version = self.binary.read_bytes(), self.version.read_bytes()
        registry = self.app / "libraries"
        for action in ("registry", "version", "binary"):
            with self.subTest(action=action):
                registry.unlink(missing_ok=True)
                self.binary.write_bytes(binary)
                self.version.write_bytes(version)
                if action == "registry":
                    registry.write_text("/changed/library.agda-lib\n")
                elif action == "version":
                    self.version.write_text("Agda version different\n")
                else:
                    self.binary.write_bytes(binary + b"\n# changed compiler\n")
                self.log.unlink(missing_ok=True)
                with self.assertRaisesRegex(goals.GoalEvidenceError, "resolution pin mismatch"):
                    self.check(listing)
                self.assert_no_interaction()
        registry.unlink(missing_ok=True)
        self.binary.write_bytes(binary)
        self.version.write_bytes(version)
        capture = goals.build_resolution
        def change_after_capture(*args, **kwargs):
            value = capture(*args, **kwargs)
            self.binary.write_bytes(binary + b"\n# after resolution\n")
            return value
        self.log.unlink(missing_ok=True)
        with patch.object(goals, "build_resolution", side_effect=change_after_capture):
            with self.assertRaisesRegex(goals.GoalEvidenceError, "compiler changed after resolution"):
                self.check(listing)
        self.assert_no_interaction()
        self.binary.write_bytes(binary)
        self.configure(mode="mutate-binary")
        with self.assertRaisesRegex(goals.GoalEvidenceError, "compiler changed during"):
            self.check(listing)

    def test_staging_and_compiler_source_mutation_hooks_preserve_originals(self):
        listing = self.listing()
        original = self.tree(self.project)
        copy_snapshot = goals._copy_snapshot
        for location in ("stage", "source"):
            for action in ("edit", "add", "remove"):
                with self.subTest(location=location, action=action):
                    for name, data in original.items():
                        (self.project / name).write_bytes(data)
                    (self.project / "added.txt").unlink(missing_ok=True)
                    def mutate(root, files, stage):
                        copy_snapshot(root, files, stage)
                        tree = stage if location == "stage" else root
                        if action == "add":
                            (tree / "added.txt").write_bytes(b"new staged source")
                        elif action == "remove":
                            (tree / "notes.txt").unlink()
                        else:
                            (tree / "notes.txt").write_bytes(b"changed staged source")
                    self.log.unlink(missing_ok=True)
                    with patch.object(goals, "_copy_snapshot", side_effect=mutate):
                        with self.assertRaisesRegex(goals.GoalEvidenceError, "changed during staging"):
                            self.check(listing)
                    self.assert_no_interaction()
        for name, data in original.items():
            (self.project / name).write_bytes(data)
        (self.project / "added.txt").unlink(missing_ok=True)
        self.configure(mode="mutate-stage")
        with self.assertRaisesRegex(goals.GoalEvidenceError, "modified captured regular source"):
            self.check(listing)
        self.assertEqual(self.tree(self.project), original)
        self.assertEqual(list(self.project.rglob("*.agdai")), [])

    def test_offline_validation_loading_and_cli_verify_accept_success_and_failure(self):
        listing = self.listing()
        success = self.check(listing)
        config = responses()
        config["check"] = [info({"kind": "Error", "message": "retained failed trial"})]
        self.configure(config)
        failure = self.check(listing)
        for name, value in (("success", success), ("failure", failure)):
            path = self.home / (name + ".json")
            candidates.write_candidate_observation(path, value)
            saved = path.read_bytes()
            with patch("subprocess.Popen", side_effect=AssertionError("offline verification launched a process")):
                self.assertEqual(candidates.validate_candidate_observation(value), value)
                self.assertEqual(candidates.load_candidate_observation(path), value)
                status, out, err = self.run_cli(["verify-check", str(path)])
                self.assertEqual(status, 0, err)
                self.assertEqual(json.loads(out)["result"], value["result"])
                self.assertEqual(self.run_cli(["verify", str(path)])[0], 1)
            with self.assertRaises(core.EvidenceError):
                candidates.write_candidate_observation(path, value)
            self.assertEqual(path.read_bytes(), saved)
            link = self.home / (name + "-link.json")
            link.symlink_to(path)
            with self.assertRaises(goals.GoalEvidenceError):
                candidates.load_candidate_observation(link)
        path = self.home / "listing.json"
        goals.write_goal_observation(path, listing)
        with patch("subprocess.Popen", side_effect=AssertionError("format check launched a process")):
            self.assertEqual(self.run_cli(["verify-check", str(path)])[0], 1)
            with self.assertRaises(goals.GoalEvidenceError):
                candidates.load_candidate_observation(path)
            with self.assertRaises(goals.GoalEvidenceError):
                goals.validate_goal_observation(success)
        malformed = self.home / "malformed.json"
        malformed.write_text('{"format":1,"format":2}\n')
        with self.assertRaises(goals.GoalEvidenceError):
            candidates.load_candidate_observation(malformed)

    def test_rehashed_forgery_cannot_change_result_bindings_policy_or_prior_leaf(self):
        listing = self.listing(includes=("src",), safe=True)
        value = json.loads(json.dumps(self.check(listing), ensure_ascii=False))  # No aliased result/transcript objects.
        inspected = goals.observe_goals(self.project, "Main.agda", listing=listing, goal_id=1, agda_binary=str(self.binary))
        mutations = {
            "assurance": lambda o: o["result"].update(assurance="proof-complete"),
            "term": lambda o: o["result"]["selected"].update(term="invented"),
            "boolean selected id": lambda o: o["result"]["selected"].update(id=True),
            "integer scope": lambda o: o["result"]["selected"]["entries"][1].update(inScope=0),
            "integer postflight flag": lambda o: o["result"].update(postflightUnchanged=1),
            "proof certificate": lambda o: o["result"].update(proofComplete=True),
            "type": lambda o: o["result"]["selected"].update(type="Set"),
            "context": lambda o: o["result"]["selected"]["entries"][0].update(binding="Set"),
            "source digest": lambda o: o["query"].update(sourceSha256="sha256:" + "0" * 64),
            "boolean query id": lambda o: o["query"].update(goalId=True),
            "expression binding": lambda o: o["query"].update(expression="different"),
            "include binding": lambda o: o["query"].update(includes=["."]),
            "safe binding": lambda o: o["query"].update(safe=False),
            "policy": lambda o: o["query"].update(candidatePolicy="candidate-constraint-free"),
            "request": lambda o: o["transcript"][2].update(request="Cmd_give 1 noRange refl"),
            "phase": lambda o: o["transcript"][3].update(phase="infer"),
            "postflight raw": lambda o: o["transcript"][3]["responses"][0]["info"].update(invisibleGoals=[]),
            "continued incomplete": lambda o: o["transcript"][2].update(complete=False),
            "prior identity": lambda o: o["listing"].update(observationId="sha256:" + "0" * 64),
            "inspected prior": lambda o: o.update(listing=copy.deepcopy(inspected)),
            "missing full prior": lambda o: o.update(listing={"observationId": listing["observationId"]}),
            "extra history": lambda o: o["listing"].update(listing=copy.deepcopy(listing)),
        }
        def corrupt_prior(o):
            o["listing"]["result"]["goals"][0]["id"] = False  # False must not alias ID 0.
            o["listing"]["observationId"] = goals.goal_observation_id(o["listing"])
        def oversized_bound_expression(o):
            o["query"]["expression"] = "λ" * 32_769
            o["transcript"][2]["request"] = ('IOTCM "$PROJECT_ROOT/Main.agda" None Direct '
                '(Cmd_goal_type_context_check Simplified 1 noRange "' + o["query"]["expression"] + '")')
        mutations["rehashed prior false id"] = corrupt_prior
        mutations["oversized bound Unicode expression"] = oversized_bound_expression
        path = self.home / "tampered.json"
        for label, mutate in mutations.items():
            with self.subTest(forgery=label):
                changed = copy.deepcopy(value)
                mutate(changed)
                changed["observationId"] = goals.goal_observation_id(changed)
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
                with patch("subprocess.Popen", side_effect=AssertionError("forgery check launched a process")):
                    with self.assertRaises(goals.GoalEvidenceError):
                        candidates.validate_candidate_observation(changed)
                    with self.assertRaises(goals.GoalEvidenceError):
                        candidates.load_candidate_observation(path)
        changed = copy.deepcopy(value)
        changed["transport"]["stderr"] = "not rehashed"
        with self.assertRaises(goals.GoalEvidenceError):
            candidates.validate_candidate_observation(changed)

    def test_cli_check_saves_trials_and_inherits_pins_with_documented_exit_codes(self):
        listing_path = self.home / "listing.json"
        listing = self.listing(includes=("src",), safe=True)
        goals.write_goal_observation(listing_path, listing)
        for failed in (False, True):
            config = responses()
            if failed:
                config["check"] = [info({"kind": "Error", "message": "saved CLI failure λ"})]
            self.configure(config)
            output = self.home / ("failed.json" if failed else "elaborated.json")
            status, out, err = self.run_cli(self.check_args(listing_path, output) +
                ["--timeout-seconds", "5", "--max-output-bytes", "8192"])
            self.assertEqual(status, 1 if failed else 0, err)
            value = candidates.load_candidate_observation(output)
            self.assert_result(value, "query-error" if failed else "elaborated")
            self.assertEqual(json.loads(out)["result"], value["result"])
            self.assertEqual(value["listing"], listing)
            self.assertEqual(value["query"]["includes"], [".", "src"])
            self.assertIs(value["query"]["safe"], True)
            self.assertEqual(value["execution"]["timeoutSeconds"], 5)
            self.assertEqual(value["execution"]["maxOutputBytes"], 8192)
        self.source.write_bytes(self.source.read_bytes() + b"-- stale\n")
        output = self.home / "stale.json"
        with patch("subprocess.Popen", side_effect=AssertionError("CLI stale pin launched metadata")):
            status, _, err = self.run_cli(self.check_args(listing_path, output))
        self.assertEqual(status, 1, err)
        self.assertIn("source pin mismatch", err)
        self.assertFalse(output.exists())

    def test_cli_rejects_bad_arguments_outputs_and_repeated_selectors_preprocess(self):
        listing = self.home / "listing.json"
        goals.write_goal_observation(listing, self.listing())
        existing = self.home / "existing.json"
        existing.write_bytes(b"keep me\n")
        link = self.home / "output-link.json"
        link.symlink_to(existing)
        dangling = self.home / "dangling.json"
        dangling.symlink_to(self.home / "absent.json")
        project_link = self.home / "project-link"
        project_link.symlink_to(self.project, target_is_directory=True)
        output = self.home / "not-written.json"
        self.log.unlink(missing_ok=True)
        with patch("subprocess.Popen", side_effect=AssertionError("invalid CLI launched any process")):
            for path in (existing, link, dangling, listing, self.project / "out.json", project_link / "out.json"):
                with self.subTest(output=str(path)):
                    status, _, err = self.run_cli(self.check_args(listing, path))
                    self.assertEqual(status, 2, err)
            base = self.check_args(listing, output)
            for extra in (["--file", "Main.agda"], ["--include", "src"], ["--safe"], ["--bundle", str(self.home)]):
                with self.subTest(forbidden=extra):
                    self.assertEqual(self.run_cli(base + extra)[0], 2)
            for flag, invalid in (("--expression", " "), ("--goal-id", "-1"), ("--goal-id", "99"),
                                  ("--goal-id", "x"), ("--timeout-seconds", "0"), ("--max-output-bytes", "512")):
                args = base.copy()
                if flag in args:
                    args[args.index(flag) + 1] = invalid
                else:
                    args += [flag, invalid]
                with self.subTest(flag=flag, value=invalid):
                    self.assertEqual(self.run_cli(args)[0], 2)
            self.assertEqual(self.run_cli(["check", "--project-root", str(self.project)])[0], 2)
            for flag in ("--project-root", "--listing", "--goal-id", "--expression", "--output", "--agda-bin",
                         "--timeout-seconds", "--max-output-bytes"):
                args = base.copy()
                if flag not in args:
                    args += [flag, "5" if flag == "--timeout-seconds" else "8192"]
                with self.subTest(repeated=flag):
                    status, _, err = self.run_cli(args + [flag, args[args.index(flag) + 1]])
                    self.assertEqual(status, 2, err)
                    self.assertIn("only once", err)
        self.assertEqual(existing.read_bytes(), b"keep me\n")
        self.assertFalse(output.exists())
        self.assertFalse((self.project / "out.json").exists())
        self.assertEqual(self.records(), [])


@unittest.skipUnless(os.name == "posix" and shutil.which("agda"), "optional real Agda is unavailable")
class RealAgdaCandidateTests(unittest.TestCase):
    def setUp(self):
        version = subprocess.run(["agda", "--version"], text=True, capture_output=True, timeout=10, check=False)
        if version.stdout.strip() != "Agda version 2.6.3":
            self.skipTest("optional wire-contract cases target Agda 2.6.3")
        temporary = tempfile.TemporaryDirectory(prefix="candidates-real-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "project"
        self.project.mkdir()
        app = Path(temporary.name) / "agda-config"
        app.mkdir()
        environment = patch.dict(os.environ, {"AGDA_DIR": str(app)})
        environment.start()
        self.addCleanup(environment.stop)
        source = self.project / "Main.agda"
        source.write_text("module Main where\nopen import Agda.Builtin.Nat\nopen import Agda.Builtin.Equality\n"
            "local : Nat → Nat\nlocal n = {! !}\n"
            "unicode : Nat → Nat\nunicode λ1 = {! !}\n"
            "dependent : (n : Nat) → n ≡ n\ndependent n = {! !}\n", encoding="utf-8")
        self.before = CandidateTests.tree(self.project)
        self.listing = goals.observe_goals(self.project, "Main.agda", timeout_seconds=15)
        self.assertEqual(self.listing["result"]["status"], "listed", self.listing["transcript"])
        self.numbers = [g["id"] for g in self.listing["result"]["goals"]]
        self.assertEqual(len(self.numbers), 3)
        self.addCleanup(self.assert_unchanged)

    def assert_unchanged(self):
        self.assertEqual(CandidateTests.tree(self.project), self.before)
        self.assertEqual(list(self.project.rglob("*.agdai")), [])

    def trial(self, number, expression):
        value = candidates.check_candidate(self.project, self.listing, number, expression, timeout_seconds=15)
        self.assertEqual(candidates.validate_candidate_observation(value), value)
        self.assertEqual(value["result"]["assurance"], "contextual-elaboration-only")
        self.assertEqual(set(value["result"]), {"status", "selected", "assurance", "postflightUnchanged"})
        return value

    def test_contextual_locals_unicode_dependent_refl_and_type_scope_errors(self):
        for number, expression, term in ((self.numbers[0], "n", "n"), (self.numbers[1], "λ1", "λ1"),
                                         (self.numbers[2], "refl", "refl")):
            with self.subTest(expression=expression):
                value = self.trial(number, expression)
                self.assertEqual(value["result"]["status"], "elaborated", value["transcript"])
                self.assertIs(value["result"]["postflightUnchanged"], True)
                self.assertEqual(value["result"]["selected"]["term"], term)
                self.assertEqual([p["phase"] for p in value["transcript"]], ["startup", "load", "check", "postflight"])
        for expression in ("λ x → x", "notInScopeAnywhere"):
            with self.subTest(expression=expression):
                value = self.trial(self.numbers[0], expression)
                self.assertEqual(value["result"]["status"], "query-error", value["transcript"])
                self.assertIsNone(value["result"]["selected"])
                self.assertEqual(len(value["transcript"]), 3)

    def test_underscore_internal_error_and_discarded_meta_never_certify_a_proof(self):
        value = self.trial(self.numbers[0], "_")
        # Agda 2.6.3 may throw its own internal error for a bare underscore.
        # Preserve that diagnostic verbatim; a complete prompt is not success.
        self.assertNotEqual(value["result"]["status"], "elaborated", value["transcript"])
        self.assertIsNone(value["result"]["selected"])
        retained = json.dumps(value["transcript"], ensure_ascii=False) + str(value["transport"]["message"])
        self.assertTrue("internal error" in retained.lower() or "Error" in retained, retained)
        value = self.trial(self.numbers[2], "let x = _ in refl")
        self.assertEqual(value["result"]["status"], "elaborated", value["transcript"])
        self.assertEqual(value["result"]["selected"]["term"], "refl")
        self.assertIs(value["result"]["postflightUnchanged"], True)
        self.assertEqual(value["result"]["assurance"], "contextual-elaboration-only")
        # Cmd_metas reports restored state, not absence of candidate-local metas.
        summaries = [[r["info"] for r in value["transcript"][phase]["responses"]
                      if r.get("kind") == "DisplayInfo" and r.get("info", {}).get("kind") == "AllGoalsWarnings"]
                     for phase in (1, 3)]
        self.assertEqual(len(summaries[0]), 1)
        self.assertEqual(summaries[0], summaries[1])
        self.assertEqual(summaries[1][0]["invisibleGoals"], [])


if __name__ == "__main__":
    unittest.main()
