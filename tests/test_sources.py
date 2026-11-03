"""Pinned unfinished client/dependency sources; native trials are not proof completion.

Fake sessions use real pipes and independently configurable metadata.  Optional
real Agda fixtures capture a tiny safe library without a declaration index.  All
source observations, including retained failures, must verify without Agda.
"""

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

from agda_evidence import candidates, checker, cli, core, goals, sources


FORMAT = "agda-evidence/source-observation-v1"
CLIENT = (
    "module Main where\n"
    "open import Agda.Builtin.Nat\n"
    "import Library\n"
    "identityproof : Nat → Nat\n"
    "identityproof n = {! !}\n"
)
LIBRARY = (
    "{-# OPTIONS --safe #-}\n"
    "module Library where\n"
    "open import Agda.Builtin.Nat\n"
    "identity : Nat → Nat\n"
    "identity n = n\n"
)
EXPRESSION = "Library.identity n"

# Config, version and log are outside both source roots and compiler bytes.
# The non-interaction branch represents the explicit library capture command;
# real Agda uses exactly the same safe argv in the optional integration suite.
FAKE = r'''
import json
import os
from pathlib import Path
import sys

LOG, CONFIG, VERSION, APP = map(Path, __PATHS__)
with LOG.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
if "--version" in sys.argv:
    print(VERSION.read_text(encoding="utf-8").strip())
    sys.exit(0)
if "--print-agda-app-dir" in sys.argv:
    print(APP)
    sys.exit(0)
if "--interaction-json" not in sys.argv:
    print("explicit safe library fixture capture")
    sys.exit(0)
config = json.loads(CONFIG.read_text(encoding="utf-8"))

def prompt():
    sys.stdout.write("JSON> ")
    sys.stdout.flush()

prompt()
for line in sys.stdin:
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"command": line.rstrip("\n")}) + "\n")
    if "Cmd_load" in line:
        phase = "load"
        Path("fixture.agdai").write_bytes(b"generated only in the isolated stage")
    elif "Cmd_goal_type_context_check" in line:
        phase = "check"
    elif "Cmd_goal_type_context Simplified" in line:
        phase = "inspect"
    elif "Cmd_metas AsIs" in line:
        phase = "postflight"
    else:
        sys.exit(3)
    for value in config[phase]:
        print(json.dumps(value, ensure_ascii=False), flush=True)
    prompt()
'''


def wire_fixture():
    start = len(CLIENT.split("{!", 1)[0].encode("utf-8")) + 1
    point = {"id": 0, "range": [{
        "start": {"pos": start, "line": 5, "col": 19},
        "end": {"pos": start + 5, "line": 5, "col": 24},
    }]}
    summary = {
        "kind": "AllGoalsWarnings",
        "visibleGoals": [{"kind": "OfType", "constraintObj": copy.deepcopy(point), "type": "Nat"}],
        "invisibleGoals": [], "warnings": [], "errors": [],
        "metadata": {"restored": True, "generation": 1},
    }
    goal = {
        "kind": "GoalType", "rewrite": "Simplified", "type": "Nat",
        "typeAux": {"kind": "GoalOnly"},
        "entries": [{"originalName": "n", "reifiedName": "n", "binding": "Nat", "inScope": True}],
        "boundary": [], "outputForms": [],
    }
    checked = copy.deepcopy(goal)
    checked["typeAux"] = {"kind": "GoalAndElaboration", "term": EXPRESSION}
    def display(info):
        return {"kind": "DisplayInfo", "info": info}
    return {
        "load": [{"kind": "Status", "status": {"checked": False}},
                 display(summary), {"kind": "InteractionPoints", "interactionPoints": [point]}],
        "inspect": [display({"kind": "GoalSpecific", "interactionPoint": copy.deepcopy(point), "goalInfo": goal})],
        "check": [display({"kind": "GoalSpecific", "interactionPoint": copy.deepcopy(point), "goalInfo": checked})],
        "postflight": [display(copy.deepcopy(summary))],
    }


def detached(value):
    """Saved JSON has no result/transcript or outer/inner prior aliases."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class _SourceFixtures:
    real = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        temporary = tempfile.TemporaryDirectory(prefix="source-evidence-real-" if cls.real else "source-evidence-fake-")
        cls.addClassCleanup(temporary.cleanup)
        cls.home = Path(temporary.name)
        cls.project = cls.home / "client checkout λ"
        cls.library = cls.home / "dependency checkout λ"
        cls.project.mkdir()
        (cls.project / "src").mkdir()
        (cls.library / "src").mkdir(parents=True)
        cls.source = cls.project / "Main.agda"
        cls.source.write_text(CLIENT, encoding="utf-8")
        (cls.project / "client.agda-lib").write_text("name: source-client\ninclude: .\n", encoding="utf-8")
        (cls.library / "sourceLib.agda-lib").write_text("name: sourceLib\ninclude: src\n", encoding="utf-8")
        (cls.library / "src" / "Library.agda").write_text(LIBRARY, encoding="utf-8")
        for root in (cls.project, cls.library):
            (root / "notes.txt").write_bytes(b"unrelated captured regular source\n")
            (root / "existing.agdai").write_bytes(b"original interface must remain untouched")
        cls.app = cls.home / "empty-agda-config"
        cls.app.mkdir()
        # One fixed, empty AGDA_DIR lasts through capture and every trial.  A
        # per-method directory would accidentally change the resolution pins.
        environment = patch.dict(os.environ, {"AGDA_DIR": str(cls.app)})
        environment.start()
        cls.addClassCleanup(environment.stop)
        cls.log = cls.home / "native.jsonl"
        cls.config = cls.home / "responses.json"
        cls.version = cls.home / "version.txt"
        cls.version.write_text("Agda version 2.6.3-source-fixture\n", encoding="utf-8")
        if cls.real:
            cls.binary = Path(shutil.which("agda"))
        else:
            cls.binary = cls.home / "fake agda λ;not-shell"
            script = FAKE.replace("__PATHS__", repr(tuple(map(str, (cls.log, cls.config, cls.version, cls.app)))))
            cls.binary.write_text(f"#!{sys.executable}\n" + script, encoding="utf-8")
            cls.binary.chmod(0o755)
            cls.binary_bytes = cls.binary.read_bytes()
            cls.config.write_text(json.dumps(wire_fixture(), ensure_ascii=False), encoding="utf-8")
        cls.bundle = cls.home / "dependency-evidence"
        command = [str(cls.binary), "--safe", "--no-libraries", "--ignore-interfaces", "-i", "src", "src/Library.agda"]
        core.capture_bundle(cls.library, cls.bundle, command, agda_binary=str(cls.binary), timeout_seconds=30)
        cls.manifest, cls.components = core.load_verified_bundle(cls.bundle)
        if cls.components["attestation.json"]["outcome"]["status"] != "passed":
            raise AssertionError(cls.components["diagnostics.json"])
        if "index-ref.json" in cls.components:
            raise AssertionError("source dependencies must not require an index")
        cls.original_trees = {root: tree_bytes(root) for root in (cls.project, cls.library, cls.bundle)}
        cls.listed = detached(sources.observe_source_goals(
            cls.project, "Main.agda", dependency_bundle=cls.bundle, dependency_root=cls.library,
            dependency_includes=("src",), agda_binary=str(cls.binary), includes=("src",), safe=True,
            timeout_seconds=30,
        ))
        if cls.listed["observation"]["result"]["status"] != "listed":
            raise AssertionError(cls.listed["observation"]["transcript"])
        cls.number = cls.listed["observation"]["result"]["goals"][0]["id"]
        cls.inspected = detached(sources.observe_source_goals(
            cls.project, "Main.agda", dependency_bundle=cls.bundle, dependency_root=cls.library,
            dependency_includes=("src",), agda_binary=str(cls.binary), listing=cls.listed,
            goal_id=cls.number, includes=("src",), safe=True, timeout_seconds=30,
        ))
        cls.elaborated = detached(sources.check_source_candidate(
            cls.project, cls.listed, cls.number, EXPRESSION, dependency_bundle=cls.bundle,
            dependency_root=cls.library, dependency_includes=("src",), agda_binary=str(cls.binary),
            timeout_seconds=30,
        ))
        if not cls.real:
            value = wire_fixture()
            value["check"] = [{"kind": "DisplayInfo", "info": {"kind": "Error", "message": "Set is not Nat"}}]
            cls.config.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        cls.failed = detached(sources.check_source_candidate(
            cls.project, cls.listed, cls.number, "Nat", dependency_bundle=cls.bundle,
            dependency_root=cls.library, dependency_includes=("src",), agda_binary=str(cls.binary),
            timeout_seconds=30,
        ))
        if {root: tree_bytes(root) for root in cls.original_trees} != cls.original_trees:
            raise AssertionError("fixture trials changed an original source tree or dependency evidence")

    def setUp(self):
        super().setUp()
        for root, original in self.original_trees.items():
            for path in root.rglob("*"):
                if path.is_file() and path.relative_to(root).as_posix() not in original:
                    path.unlink()
            for name, data in original.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_bytes(data)
        (self.app / "libraries").unlink(missing_ok=True)
        if not self.real:
            self.binary.write_bytes(self.binary_bytes)
            self.version.write_text("Agda version 2.6.3-source-fixture\n", encoding="utf-8")
            self.configure()
        temporary = tempfile.TemporaryDirectory(prefix="outputs-", dir=self.home)
        self.addCleanup(temporary.cleanup)
        self.output_dir = Path(temporary.name)

    def configure(self, value=None):
        self.config.write_text(json.dumps(wire_fixture() if value is None else value, ensure_ascii=False), encoding="utf-8")
        self.log.unlink(missing_ok=True)

    def options(self, **overrides):
        options = dict(dependency_bundle=self.bundle, dependency_root=self.library,
                       dependency_includes=("src",), agda_binary=str(self.binary), timeout_seconds=30)
        options.update(overrides)
        return options

    def observe(self, **overrides):
        options = self.options(includes=("src",), safe=True)
        options.update(overrides)
        return sources.observe_source_goals(self.project, "Main.agda", **options)

    def inspect(self, listing=None, number=None, **overrides):
        return self.observe(listing=self.listed if listing is None else listing,
                            goal_id=self.number if number is None else number, **overrides)

    def check(self, listing=None, number=None, expression=EXPRESSION, **overrides):
        return sources.check_source_candidate(
            self.project, self.listed if listing is None else listing,
            self.number if number is None else number, expression, **self.options(**overrides),
        )

    def records(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    def assert_pristine(self, before=None):
        expected = self.original_trees if before is None else before
        self.assertEqual({root: tree_bytes(root) for root in expected}, expected)

    def assert_source(self, value, status):
        self.assertEqual(value["format"], FORMAT)
        self.assertEqual(value["observation"]["result"]["status"], status, value["observation"]["transcript"])
        self.assertEqual(sources.validate_source_observation(value), value)
        self.assertEqual(value["sourceObservationId"], sources.source_observation_id(value))
        inner = value["observation"]
        validator = candidates.validate_candidate_observation if inner["query"]["operation"] == "check" else goals.validate_goal_observation
        self.assertEqual(validator(inner), inner)

    @staticmethod
    def rehash(value):
        inner = value["observation"]
        inner["observationId"] = goals.goal_observation_id(inner)
        value["sourceObservationId"] = sources.source_observation_id(value)

    @staticmethod
    def run_cli(arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                status = cli.main(["source", *arguments])
            except SystemExit as error:
                status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    def list_args(self, output):
        return ["list", "--project-root", str(self.project), "--file", "Main.agda",
                "--dependency-root", str(self.library), "--dependency-bundle", str(self.bundle),
                "--dependency-include", "src", "--agda-bin", str(self.binary), "--safe", "--output", str(output)]


@unittest.skipUnless(os.name == "posix", "fake native pipe sessions require POSIX")
class SourceTests(_SourceFixtures, unittest.TestCase):
    def test_exact_envelope_prefixed_union_and_index_free_dependency(self):
        value = self.listed
        self.assert_source(value, "listed")
        self.assertEqual(set(value), {"format", "sourceObservationId", "clientSnapshot", "clientResolution",
                                     "dependency", "composition", "observation", "listing"})
        self.assertEqual(set(value["dependency"]), {"evidence", "nativeResolution"})
        self.assertEqual(value["dependency"]["evidence"], {"manifest": self.manifest, "components": self.components})
        self.assertEqual(set(self.components), core.CORE_COMPONENT_FILENAMES)
        self.assertEqual(core.verify_bundle(self.bundle), [])
        self.assertEqual(value["composition"], {"policy": "one-dependency-source-copy-v1",
                                              "clientIncludes": [".", "src"], "dependencyIncludes": ["src"]})
        self.assertIsNone(value["listing"])
        inner = value["observation"]
        self.assertIsNone(inner["listing"])
        expected = sorted([{**record, "path": f"{prefix}/{record['path']}"}
                           for prefix, snapshot in (("client", value["clientSnapshot"]),
                                                    ("library", self.components["snapshot.json"]))
                           for record in snapshot["files"]], key=lambda record: record["path"])
        self.assertEqual(inner["snapshot"]["files"], expected)
        self.assertEqual(inner["query"]["file"], "client/Main.agda")
        self.assertEqual(inner["query"]["includes"], [".", "client", "client/src", "library/src"])
        self.assertEqual(value["dependency"]["nativeResolution"]["resolutionId"], self.components["resolution.json"]["resolutionId"])
        self.assertEqual(value["clientResolution"]["projectLibraryFiles"][0]["sha256"], next(
            f["sha256"] for f in value["clientSnapshot"]["files"] if f["path"] == "client.agda-lib"))
        self.assertTrue(inner["query"]["safe"])
        self.assert_pristine()

    def test_list_inspect_candidate_are_real_independent_isolated_sessions(self):
        before = {root: tree_bytes(root) for root in self.original_trees}
        with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
            listed = self.observe()
            inspected = self.inspect(listed)
            checked = self.check(listed)
        for value, status in ((listed, "listed"), (inspected, "inspected"), (checked, "elaborated")):
            self.assert_source(value, status)
        self.assertEqual(inspected["listing"], listed)
        self.assertEqual(checked["listing"], listed)
        self.assertEqual(inspected["observation"]["listing"], listed["observation"])
        self.assertEqual(checked["observation"]["listing"], listed["observation"])
        self.assertEqual(inspected["observation"]["result"]["selected"]["type"], "Nat")
        self.assertEqual(checked["observation"]["query"]["expression"], EXPRESSION)
        result = checked["observation"]["result"]
        self.assertEqual(result["assurance"], "contextual-elaboration-only")
        self.assertIs(result["postflightUnchanged"], True)
        self.assertNotIn("proofComplete", result)
        launches = [call for call in popen.call_args_list if "--interaction-json" in call.args[0]]
        self.assertEqual(len(launches), 3)
        for call in launches:
            stage = Path(call.kwargs["cwd"])
            self.assertNotIn(stage, (self.project, self.library))
            self.assertFalse(stage.exists())
            self.assertFalse(call.kwargs.get("shell", False))
            self.assertIn(str(stage / "library/src"), call.args[0])
        commands = [record["command"] for record in self.records() if "command" in record]
        self.assertFalse(any(token in "\n".join(commands) for token in ("Cmd_give", "Cmd_refine", "Cmd_solve")))
        self.assert_pristine(before)

    def test_wrong_type_is_a_retained_query_error_not_a_passed_trial(self):
        self.assert_source(self.failed, "query-error")
        result = self.failed["observation"]["result"]
        self.assertIsNone(result["selected"])
        self.assertIsNone(result["postflightUnchanged"])
        self.assertEqual(result["assurance"], "contextual-elaboration-only")
        self.assertTrue(any(response.get("info", {}).get("kind") == "Error"
                            for phase in self.failed["observation"]["transcript"] for response in phase["responses"]))

    def test_stale_unrelated_dependency_and_client_edits_reject_before_any_process(self):
        for root in (self.library, self.project):
            path = root / "notes.txt"
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"changed without touching the selected module\n")
                for operation in (self.inspect, self.check) if root == self.project else (self.observe, self.inspect, self.check):
                    with self.subTest(root=root.name, operation=operation.__name__):
                        with patch("subprocess.Popen", side_effect=AssertionError("stale source launched metadata/native Agda")):
                            with self.assertRaises(sources.SourceEvidenceError):
                                operation()
            finally:
                path.write_bytes(original)
        self.assertEqual(self.records(), [])

    def test_selected_client_edit_and_client_include_or_safe_policy_changes_preflight(self):
        original = self.source.read_bytes()
        try:
            self.source.write_bytes(original + b"-- edited unfinished client\n")
            for operation in (self.inspect, self.check):
                with patch("subprocess.Popen", side_effect=AssertionError("edited client launched metadata")):
                    with self.assertRaises(sources.SourceEvidenceError):
                        operation()
        finally:
            self.source.write_bytes(original)
        for options in ({"includes": ()}, {"safe": False}):
            with self.subTest(policy=options):
                with patch("subprocess.Popen", side_effect=AssertionError("changed client policy launched metadata")):
                    with self.assertRaises(sources.SourceEvidenceError):
                        self.inspect(**options)

    def test_dependency_file_addition_and_removal_are_full_source_pin_changes(self):
        added = self.library / "unrelated-new.txt"
        notes = self.library / "notes.txt"
        original = notes.read_bytes()
        for action in ("addition", "removal"):
            with self.subTest(action=action):
                try:
                    added.write_bytes(b"new regular file") if action == "addition" else notes.unlink()
                    with patch("subprocess.Popen", side_effect=AssertionError("changed dependency inventory launched a process")):
                        with self.assertRaises(sources.SourceEvidenceError):
                            self.observe()
                finally:
                    added.unlink(missing_ok=True)
                    notes.write_bytes(original)

    def test_changed_dependency_includes_are_not_silently_inherited_or_substituted(self):
        for operation in (self.inspect, self.check):
            with self.subTest(operation=operation.__name__):
                with patch("subprocess.Popen", side_effect=AssertionError("changed includes launched metadata or Agda")):
                    with self.assertRaises(sources.SourceEvidenceError):
                        operation(dependency_includes=(".",))

    def test_same_source_and_resolution_new_capture_is_not_the_saved_exact_bundle(self):
        second = self.home / "same-pins-new-capture"
        if not second.exists():
            core.capture_bundle(self.library, second,
                                [str(self.binary), "--safe", "--no-libraries", "--ignore-interfaces", "-i", "src", "src/Library.agda"],
                                agda_binary=str(self.binary))
        manifest, components = core.load_verified_bundle(second)
        self.assertEqual(components["snapshot.json"]["sourceId"], self.components["snapshot.json"]["sourceId"])
        self.assertEqual(components["resolution.json"]["resolutionId"], self.components["resolution.json"]["resolutionId"])
        self.assertNotEqual(manifest["bundleId"], self.manifest["bundleId"])
        for operation in (self.inspect, self.check):
            with self.subTest(operation=operation.__name__):
                with patch("subprocess.Popen", side_effect=AssertionError("wrong exact bundle launched a process")):
                    with self.assertRaises(sources.SourceEvidenceError):
                        operation(dependency_bundle=second)

    def test_compiler_version_bytes_and_registry_mismatch_never_launch_interaction(self):
        for change in ("version", "compiler bytes", "registry"):
            with self.subTest(change=change):
                self.binary.write_bytes(self.binary_bytes)
                self.version.write_text("Agda version 2.6.3-source-fixture\n", encoding="utf-8")
                (self.app / "libraries").unlink(missing_ok=True)
                if change == "version":
                    self.version.write_text("Agda version changed with identical executable bytes\n", encoding="utf-8")
                elif change == "compiler bytes":
                    self.binary.write_bytes(self.binary_bytes + b"\n# changed compiler bytes\n")
                else:
                    (self.app / "libraries").write_text("/different/library.agda-lib\n", encoding="utf-8")
                for operation in (self.observe, self.inspect, self.check):
                    with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
                        with self.assertRaises(sources.SourceEvidenceError):
                            operation()
                    self.assertFalse(any("--interaction-json" in call.args[0] for call in popen.call_args_list))

    def test_expected_source_compiler_and_full_resolution_guards_reject_inner_capture_races(self):
        for operation, entrypoint in ((self.observe, "observe_goals"), (self.inspect, "observe_goals"),
                                      (self.check, "check_candidate")):
            original = getattr(sources, entrypoint)
            for mutation in ("workspace source", "compiler metadata", "native registry"):
                with self.subTest(operation=operation.__name__, mutation=mutation):
                    self.configure()
                    self.version.write_text("Agda version 2.6.3-source-fixture\n", encoding="utf-8")
                    (self.app / "libraries").unlink(missing_ok=True)
                    def mutate_then_capture(root, *args, **options):
                        self.assertEqual(options["_expected_source_id"], core.build_snapshot(root)[0]["sourceId"])
                        self.assertEqual(options["_expected_resolution_id"], core.build_resolution(root, str(self.binary))["resolutionId"])
                        self.assertEqual(options["_expected_agda"], core.resolution_identity_projection(self.components["resolution.json"])["agda"])
                        if mutation == "workspace source":
                            (root / "library" / "notes.txt").write_bytes(b"changed just before the inner source capture\n")
                        elif mutation == "compiler metadata":
                            self.version.write_text("Agda version changed after composition preflight\n", encoding="utf-8")
                        else:
                            (self.app / "libraries").write_text("/changed/registry.agda-lib\n", encoding="utf-8")
                        with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
                            try:
                                return original(root, *args, **options)
                            finally:
                                self.assertFalse(any("--interaction-json" in call.args[0] for call in popen.call_args_list))
                                if mutation == "workspace source":
                                    popen.assert_not_called()
                    try:
                        with patch.object(sources, entrypoint, side_effect=mutate_then_capture) as inner:
                            with self.assertRaises(sources.SourceEvidenceError):
                                operation()
                        inner.assert_called_once()
                    finally:
                        self.version.write_text("Agda version 2.6.3-source-fixture\n", encoding="utf-8")
                        (self.app / "libraries").unlink(missing_ok=True)
                    self.assertFalse(any("--interaction-json" in record.get("argv", []) for record in self.records()))
        self.assert_pristine()

    def test_invalid_roots_includes_limits_and_selectors_reject_before_process(self):
        cases = (
            {"dependency_root": self.project}, {"dependency_root": self.project / "src"},
            {"dependency_root": self.home}, {"dependency_includes": ()},
            {"dependency_includes": ("../src",)}, {"dependency_includes": ("absent",)},
            {"dependency_includes": (str(self.library / "src"),)},
            {"timeout_seconds": True}, {"timeout_seconds": 0}, {"max_output_bytes": True},
            {"max_output_bytes": 512},
        )
        for options in cases:
            with self.subTest(options=options):
                with patch("subprocess.Popen", side_effect=AssertionError("invalid configuration launched a process")):
                    with self.assertRaises(core.EvidenceError):
                        self.observe(**options)
        for number in (True, False, -1, "0", 0.0, 99):
            for operation in (self.inspect, self.check):
                with self.subTest(number=number, operation=operation.__name__):
                    with patch("subprocess.Popen", side_effect=AssertionError("invalid goal selector launched a process")):
                        with self.assertRaises(core.EvidenceError):
                            operation(number=number)
        for prior in (self.inspected, self.elaborated):
            with patch("subprocess.Popen", side_effect=AssertionError("non-leaf prior launched a process")):
                with self.assertRaises(core.EvidenceError):
                    self.check(prior)

    def test_rehashed_inner_cannot_hide_source_union_include_or_compiler_tampering(self):
        def union(value):
            snapshot = value["observation"]["snapshot"]
            next(record for record in snapshot["files"] if record["path"] == "library/notes.txt")["sha256"] = "sha256:" + "0" * 64
            snapshot["sourceId"] = snapshot["sourceDigest"] = core.derive_source_id(snapshot)
        def includes(value):
            inner = value["observation"]
            inner["query"]["includes"] = [".", "client", "client/src"]
            inner["execution"]["argv"] = checker._argv("$AGDA", inner["query"]["includes"], True, anchor="$PROJECT_ROOT")
        def compiler(value):
            resolution = value["observation"]["resolution"]
            resolution["agda"]["version"]["stdout"] = "Agda version forged"
            resolution["resolutionId"] = core.derive_resolution_id(resolution)
        for label, mutate in (("source union", union), ("dependency include", includes), ("compiler", compiler)):
            with self.subTest(binding=label):
                value = detached(self.listed)
                mutate(value)
                self.rehash(value)
                # A valid old-format inner artifact alone is insufficient.
                self.assertEqual(goals.validate_goal_observation(value["observation"]), value["observation"])
                with patch("subprocess.Popen", side_effect=AssertionError("offline tamper validation launched Agda")):
                    with self.assertRaises(sources.SourceEvidenceError):
                        sources.validate_source_observation(value)

    def test_client_resolution_root_manifest_and_composition_are_cross_bound(self):
        def client_manifest(value):
            value["clientResolution"]["projectLibraryFiles"] = []
            value["clientResolution"]["resolutionId"] = core.derive_resolution_id(value["clientResolution"])
        mutations = {
            "client root manifest": client_manifest,
            "dependency include": lambda v: v["composition"].update(dependencyIncludes=["."]),
            "client include": lambda v: v["composition"].update(clientIncludes=["."]),
            "composition policy": lambda v: v["composition"].update(policy="unrestricted-source-copy"),
            "extra completion claim": lambda v: v.update(proofComplete=True),
        }
        for label, mutate in mutations.items():
            with self.subTest(binding=label):
                value = detached(self.listed)
                mutate(value)
                self.rehash(value)
                with patch("subprocess.Popen", side_effect=AssertionError("offline cross-binding launched a process")):
                    with self.assertRaises(sources.SourceEvidenceError):
                        sources.validate_source_observation(value)

    def test_exact_prior_inner_uses_canonical_json_not_python_bool_integer_equality(self):
        for template, validator in ((self.inspected, goals.validate_goal_observation),
                                    (self.elaborated, candidates.validate_candidate_observation)):
            with self.subTest(operation=template["observation"]["query"]["operation"]):
                value = detached(template)
                prior = value["observation"]["listing"]
                summary = next(response["info"] for response in prior["transcript"][1]["responses"]
                               if response.get("info", {}).get("kind") == "AllGoalsWarnings")
                summary["metadata"]["restored"] = 1  # Python considers 1 == True.
                prior["observationId"] = goals.goal_observation_id(prior)
                self.rehash(value)
                self.assertEqual(validator(value["observation"]), value["observation"])
                self.assertNotEqual(core.canonical_json_bytes(prior), core.canonical_json_bytes(value["listing"]["observation"]))
                with self.assertRaises(sources.SourceEvidenceError):
                    sources.validate_source_observation(value)

    def test_rehashed_boolean_goal_id_and_non_leaf_history_are_invalid(self):
        for label in ("bool selected", "bool query", "nested outer", "missing exact prior"):
            with self.subTest(corruption=label):
                value = detached(self.elaborated)
                if label == "bool selected":
                    value["observation"]["result"]["selected"]["id"] = False
                elif label == "bool query":
                    value["observation"]["query"]["goalId"] = False
                elif label == "nested outer":
                    value["listing"] = detached(self.inspected)
                else:
                    value["listing"] = {"sourceObservationId": self.listed["sourceObservationId"]}
                self.rehash(value)
                with patch("subprocess.Popen", side_effect=AssertionError("invalid history verification launched a process")):
                    with self.assertRaises(sources.SourceEvidenceError):
                        sources.validate_source_observation(value)

    def test_all_success_and_failure_outputs_verify_offline_without_mutation(self):
        for name, value in (("list", self.listed), ("inspect", self.inspected),
                            ("check", self.elaborated), ("wrong-type", self.failed)):
            with self.subTest(artifact=name):
                path = self.output_dir / (name + ".json")
                with patch("subprocess.Popen", side_effect=AssertionError("offline output verification launched Agda")):
                    sources.write_source_observation(path, value)
                    self.assertEqual(sources.validate_source_observation(value), value)
                    self.assertEqual(sources.load_source_observation(path), value)
                    summary = sources.source_summary(value)
                    self.assertEqual(summary["sourceObservationId"], value["sourceObservationId"])
                    self.assertEqual(summary["result"], value["observation"]["result"])
                saved = path.read_bytes()
                with self.assertRaises(core.EvidenceError):
                    sources.write_source_observation(path, value)
                self.assertEqual(path.read_bytes(), saved)
                link = self.output_dir / (name + "-link.json")
                link.symlink_to(path)
                with self.assertRaises(sources.SourceEvidenceError):
                    sources.load_source_observation(link)
        malformed = self.output_dir / "duplicate.json"
        malformed.write_text('{"format":1,"format":2}\n', encoding="utf-8")
        with self.assertRaises(sources.SourceEvidenceError):
            sources.load_source_observation(malformed)
        value = detached(self.listed)
        value["observation"]["transport"]["stderr"] = "changed without rehash"
        with self.assertRaises(sources.SourceEvidenceError):
            sources.validate_source_observation(value)
        self.assert_pristine()

    def test_existing_goal_and_candidate_formats_and_validators_are_unchanged(self):
        expected_fields = {"format", "observationId", "snapshot", "resolution", "listing", "query",
                           "execution", "transcript", "transport", "result"}
        for value in (self.listed, self.inspected, self.elaborated, self.failed):
            inner = value["observation"]
            self.assertEqual(set(inner), expected_fields)
            expected_format = "agda-evidence/candidate-observation-v1" if inner["query"]["operation"] == "check" else "agda-evidence/goal-observation-v1"
            self.assertEqual(inner["format"], expected_format)
        with patch("subprocess.Popen", side_effect=AssertionError("old-format verification launched a process")):
            self.assertEqual(goals.validate_goal_observation(self.listed["observation"]), self.listed["observation"])
            self.assertEqual(candidates.validate_candidate_observation(self.elaborated["observation"]), self.elaborated["observation"])
            with self.assertRaises(checker.CheckerEvidenceError):
                goals.validate_goal_observation(self.elaborated["observation"])
            with self.assertRaises(checker.CheckerEvidenceError):
                candidates.validate_candidate_observation(self.listed["observation"])
            for validator in (goals.validate_goal_observation, candidates.validate_candidate_observation):
                with self.assertRaises(checker.CheckerEvidenceError):
                    validator(self.listed)

    def test_cli_rejects_outputs_in_either_source_root_bundle_or_existing_file(self):
        existing = self.output_dir / "existing.json"
        existing.write_bytes(b"keep output\n")
        link = self.output_dir / "output-link.json"
        link.symlink_to(existing)
        before = {root: tree_bytes(root) for root in self.original_trees}
        for output in (self.project / "out.json", self.library / "out.json", self.bundle / "out.json", existing, link):
            with self.subTest(output=str(output)):
                with patch("subprocess.Popen", side_effect=AssertionError("unsafe CLI output launched a process")):
                    status, _, stderr = self.run_cli(self.list_args(output))
                self.assertEqual(status, 2, stderr)
                if output not in (existing, link):
                    self.assertFalse(output.exists())
        self.assertEqual(existing.read_bytes(), b"keep output\n")
        self.assert_pristine(before)

    def test_cli_list_inspect_check_and_verify_preserve_success_and_failure_outputs(self):
        listing_path = self.output_dir / "cli-list.json"
        status, stdout, stderr = self.run_cli(self.list_args(listing_path) + ["--include", "src"])
        self.assertEqual(status, 0, stderr)
        listing = sources.load_source_observation(listing_path)
        self.assertEqual(json.loads(stdout)["result"], listing["observation"]["result"])
        number = listing["observation"]["result"]["goals"][0]["id"]
        common = ["--project-root", str(self.project), "--listing", str(listing_path), "--goal-id", str(number),
                  "--dependency-root", str(self.library), "--dependency-bundle", str(self.bundle),
                  "--dependency-include", "src", "--agda-bin", str(self.binary)]
        for operation, failure in (("inspect", False), ("check", False), ("check", True)):
            if failure:
                value = wire_fixture()
                value["check"] = [{"kind": "DisplayInfo", "info": {"kind": "Error", "message": "wrong CLI candidate type"}}]
                self.configure(value)
            path = self.output_dir / (operation + ("-failure" if failure else "") + ".json")
            arguments = [operation, *common, "--output", str(path)]
            if operation == "check":
                arguments += ["--expression", "Nat" if failure else EXPRESSION]
            status, stdout, stderr = self.run_cli(arguments)
            self.assertEqual(status, 1 if failure else 0, stderr)
            saved = sources.load_source_observation(path)
            self.assert_source(saved, "query-error" if failure else "inspected" if operation == "inspect" else "elaborated")
            self.assertEqual(saved["listing"], listing)
            self.assertEqual(saved["observation"]["listing"], listing["observation"])
            self.assertEqual(json.loads(stdout)["result"], saved["observation"]["result"])
            with patch("subprocess.Popen", side_effect=AssertionError("source CLI verification launched a process")):
                status, stdout, stderr = self.run_cli(["verify", str(path)])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout), sources.source_summary(saved))
        self.assert_pristine()

    def test_cli_bad_roots_includes_and_repeated_single_selectors_do_not_launch(self):
        output = self.output_dir / "not-written.json"
        base = self.list_args(output)
        for flag, value in (("--dependency-root", str(self.project)), ("--dependency-include", "../src")):
            arguments = base.copy()
            arguments[arguments.index(flag) + 1] = value
            with patch("subprocess.Popen", side_effect=AssertionError("bad CLI source configuration launched a process")):
                status, _, stderr = self.run_cli(arguments)
            self.assertEqual(status, 2, stderr)
            self.assertFalse(output.exists())
        for flag in ("--project-root", "--dependency-root", "--dependency-bundle", "--file", "--agda-bin", "--output"):
            with self.subTest(flag=flag):
                value = base[base.index(flag) + 1]
                with patch("subprocess.Popen", side_effect=AssertionError("duplicate CLI selector launched a process")):
                    status, _, stderr = self.run_cli(base + [flag, value])
                self.assertEqual(status, 2, stderr)
                self.assertFalse(output.exists())


@unittest.skipUnless(shutil.which("agda") is not None and os.name == "posix", "optional native Agda requires installed Agda and POSIX")
class RealAgdaSourceTests(_SourceFixtures, unittest.TestCase):
    real = True

    def test_safe_library_import_goal_inspection_and_contextual_candidate(self):
        for value, status in ((self.listed, "listed"), (self.inspected, "inspected"),
                              (self.elaborated, "elaborated"), (self.failed, "query-error")):
            self.assert_source(value, status)
        selected = self.inspected["observation"]["result"]["selected"]
        self.assertEqual(selected["type"], "Nat")
        self.assertTrue(any(entry["reifiedName"] == "n" and entry["binding"] == "Nat" and entry["inScope"] for entry in selected["entries"]))
        self.assertEqual(self.elaborated["observation"]["result"]["assurance"], "contextual-elaboration-only")
        self.assertEqual(self.components["attestation.json"]["outcome"]["status"], "passed")
        self.assertNotIn("index-ref.json", self.components)
        self.assert_pristine()

    def test_missing_import_and_wrong_fresh_dependency_include_retain_load_failure(self):
        original = self.source.read_bytes()
        for case in ("missing import", "wrong include"):
            with self.subTest(case=case):
                self.source.write_bytes(original)
                if case == "missing import":
                    self.source.write_text(CLIENT.replace("import Library", "import MissingLibrary"), encoding="utf-8")
                before = {root: tree_bytes(root) for root in self.original_trees}
                value = self.observe(dependency_includes=(".",) if case == "wrong include" else ("src",))
                self.assert_source(value, "load-error")
                path = self.output_dir / (case.replace(" ", "-") + ".json")
                with patch("subprocess.Popen", side_effect=AssertionError("offline failure launched native Agda")):
                    sources.write_source_observation(path, value)
                    self.assertEqual(sources.load_source_observation(path), value)
                self.assert_pristine(before)
        self.source.write_bytes(original)

    def test_native_outputs_all_verify_offline_and_unrelated_dependency_edit_preflights(self):
        for name, value in (("list", self.listed), ("inspect", self.inspected),
                            ("candidate", self.elaborated), ("failure", self.failed)):
            path = self.output_dir / (name + ".json")
            with patch("subprocess.Popen", side_effect=AssertionError("offline native observation launched a process")):
                sources.write_source_observation(path, value)
                self.assertEqual(sources.validate_source_observation(value), value)
                self.assertEqual(sources.load_source_observation(path), value)
        notes = self.library / "notes.txt"
        notes.write_bytes(notes.read_bytes() + b"unrelated native-fixture source edit\n")
        for operation in (self.observe, self.inspect, self.check):
            with patch("subprocess.Popen", side_effect=AssertionError("stale native dependency launched a process")):
                with self.assertRaises(sources.SourceEvidenceError):
                    operation()


if __name__ == "__main__":
    unittest.main()
