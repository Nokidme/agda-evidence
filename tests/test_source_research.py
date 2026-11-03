"""Source-copy editor facade boundaries, not certificates of proof completion.

Deterministic tests use an explicitly fake JSON wire protocol through real pipes;
only the three optional native tests make assertions about actual Agda outcomes.
All fixture metadata, captures, and generated interfaces live outside the repo.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agda_evidence import candidates, catalog, core, goals, research, sources, source_research

CLIENT = ("module Main where\n"
          "open import Agda.Builtin.Nat\n"
          "import Library\n"
          "identityproof : Nat → Nat\n"
          "identityproof n = {! !}\n")
LIBRARY = ("{-# OPTIONS --safe #-}\n"
           "module Library where\n"
           "open import Agda.Builtin.Nat\n"
           "identity : Nat → Nat\n"
           "identity n = n\n")
EXPRESSION = "Library.identity n"
DEFAULT = object()
RESPONSE_FIELDS = {"apiVersion", "requestId", "op", "revision", "currentRevision",
                   "workspace", "status", "recordId", "result", "error"}
SUBJECT_FIELDS = {"clientSourceId", "clientResolutionId", "dependencySourceId",
                  "dependencyResolutionId", "dependencyBundleId", "compositionId"}
PIN_FIELDS = {"dependencySourceId", "dependencyResolutionId", "dependencyBundleId"}

# This is a fake protocol fixture, never a claim of kernel-checked typing.
# Changing CONFIG or VERSION does not change either captured source tree or the
# compiler executable bytes. Capture commands and interaction commands are logged.
FAKE = r'''
import json
import os
from pathlib import Path
import sys
CONFIG, VERSION, LOG, APP = map(Path, __PATHS__)
with LOG.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
if "--version" in sys.argv:
    print(VERSION.read_text(encoding="utf-8").strip())
    sys.exit(0)
if "--print-agda-app-dir" in sys.argv:
    print(APP)
    sys.exit(0)
if "--interaction-json" not in sys.argv:
    print("explicit FAKE safe library capture; not a kernel typing claim")
    sys.exit(0)
config = json.loads(CONFIG.read_text(encoding="utf-8"))
def prompt():
    print("JSON> ", end="", flush=True)
prompt()
for command in sys.stdin:
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"command": command}) + "\n")
    if "Cmd_load" in command:
        phase = "load"
        Path("fixture.agdai").write_bytes(b"isolated generated interface")
    elif "Cmd_goal_type_context_check" in command:
        phase = "check"
    elif "Cmd_goal_type_context Simplified" in command:
        phase = "inspect"
    elif "Cmd_metas AsIs" in command:
        phase = "postflight"
    else:
        sys.exit(3)
    for value in config[phase]:
        print(json.dumps(value, ensure_ascii=False), flush=True)
    prompt()
'''


def wire_fixture(*, check_error=False, blocked=False):
    start = len(CLIENT.split("{!", 1)[0].encode("utf-8")) + 1
    point = {"id": 0, "range": [{"start": {"pos": start, "line": 5, "col": 19},
                                 "end": {"pos": start + 5, "line": 5, "col": 24}}]}
    summary = {"kind": "AllGoalsWarnings", "visibleGoals": [
        {"kind": "OfType", "constraintObj": deepcopy(point), "type": "Nat"}],
        "invisibleGoals": [], "warnings": [{"message": "fixture warning"}] if blocked else [],
        "errors": [], "metadata": {"restored": True, "generation": 1}}
    goal = {"kind": "GoalType", "rewrite": "Simplified", "type": "Nat",
            "typeAux": {"kind": "GoalOnly"}, "entries": [
                {"originalName": "n", "reifiedName": "n", "binding": "Nat", "inScope": True}],
            "boundary": [], "outputForms": []}
    checked = deepcopy(goal)
    checked["typeAux"] = {"kind": "GoalAndElaboration", "term": EXPRESSION}
    def display(info):
        return {"kind": "DisplayInfo", "info": info}
    return {"load": [display(summary), {"kind": "InteractionPoints", "interactionPoints": [point]}],
            "inspect": [display({"kind": "GoalSpecific", "interactionPoint": deepcopy(point), "goalInfo": goal})],
            "check": [display({"kind": "Error", "message": "fixture: Set is not Nat"})] if check_error else [
                display({"kind": "GoalSpecific", "interactionPoint": deepcopy(point), "goalInfo": checked})],
            "postflight": [display(deepcopy(summary))]}


def tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@contextmanager
def hidden(path):
    moved = path.with_name(path.name + ".temporarily-hidden")
    path.rename(moved)
    try:
        yield
    finally:
        moved.rename(path)


@contextmanager
def replaced_bundle(path, replacement):
    with hidden(path):
        shutil.copytree(replacement, path)
        try:
            yield
        finally:
            shutil.rmtree(path)


class _WorkspaceFixtures:
    real = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        temporary = tempfile.TemporaryDirectory(prefix="source-research-native-" if cls.real else "source-research-fake-")
        cls.addClassCleanup(temporary.cleanup)
        cls.home = Path(temporary.name)
        cls.project = cls.home / "client checkout λ"
        cls.library = cls.home / "dependency checkout λ"
        cls.project.mkdir()
        (cls.library / "src").mkdir(parents=True)
        cls.source = cls.project / "Main.agda"
        cls.source.write_text(CLIENT, encoding="utf-8")
        (cls.project / "client.agda-lib").write_text("name: source-client\ninclude: .\n", encoding="utf-8")
        (cls.library / "sourceLib.agda-lib").write_text("name: sourceLib\ninclude: src\n", encoding="utf-8")
        (cls.library / "src" / "Library.agda").write_text(LIBRARY, encoding="utf-8")
        for root in (cls.project, cls.library):
            (root / "notes.txt").write_bytes(b"unrelated regular source input\n")
            (root / "existing.agdai").write_bytes(b"original interface must stay untouched")
        cls.app = cls.home / "fixed-empty-AGDA_DIR"
        cls.app.mkdir()
        environment = patch.dict(os.environ, {"AGDA_DIR": str(cls.app)})
        environment.start()
        cls.addClassCleanup(environment.stop)
        cls.config, cls.version, cls.log = (cls.home / name for name in ("wire.json", "version.txt", "commands.jsonl"))
        cls.version_bytes = b"Agda version 2.6.3-source-research-fixture\n"
        cls.version.write_bytes(cls.version_bytes)
        if cls.real:
            cls.binary = Path(shutil.which("agda"))
        else:
            cls.binary = cls.home / "fake agda λ;not-shell"
            cls.binary.write_text(f"#!{sys.executable}\n" + FAKE.replace(
                "__PATHS__", repr(tuple(map(str, (cls.config, cls.version, cls.log, cls.app))))), encoding="utf-8")
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
            raise AssertionError("source research must not require a dependency declaration index")
        cls.original_trees = {root: tree_bytes(root) for root in (cls.project, cls.library, cls.bundle)}

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
            self.version.write_bytes(self.version_bytes)
            self.configure()
        self.workspace = self.make_workspace()
        self.rev = self.status()["currentRevision"]

    def configure(self, **options):
        self.config.write_text(json.dumps(wire_fixture(**options), ensure_ascii=False), encoding="utf-8")
        self.log.unlink(missing_ok=True)

    def make_workspace(self, **options):
        configuration = dict(dependency_root=self.library, dependency_bundle=self.bundle,
                             dependency_includes=("src",), agda_binary=str(self.binary), safe=True,
                             timeout_seconds=30)
        configuration.update(options)
        return source_research.SourceResearchWorkspace(self.project, {"main": "Main.agda"}, **configuration)

    def request(self, op, args=None, *, revision=DEFAULT):
        if revision is DEFAULT:
            revision = None if op in {"workspace.status", "record.get"} else self.rev
        return {"apiVersion": 2, "requestId": "request-λ", "op": op, "revision": revision,
                "args": {} if args is None else args}

    def call(self, op, args=None, *, workspace=None, revision=DEFAULT):
        return (self.workspace if workspace is None else workspace).handle(self.request(op, args, revision=revision))

    def status(self, **options):
        response = self.call("workspace.status", **options)
        self.assertEqual(response["status"], "ok", response)
        return response

    def listed(self, **options):
        response = self.call("goals.list", {"documentId": "main"}, **options)
        self.assertEqual(response["status"], "ok", response)
        self.assertEqual(response["result"]["outcome"]["status"], "listed", response)
        return response

    @staticmethod
    def select(listing, **options):
        return {"listingId": listing["recordId"], "goalId": listing["result"]["outcome"]["goals"][0]["id"], **options}

    def get(self, record_id, **options):
        return self.call("record.get", {"recordId": record_id}, **options)

    def error(self, response, code):
        self.assertEqual(response["status"], "error", response)
        self.assertEqual(response["error"]["code"], code, response)

    def assert_offline(self, artifact):
        with patch("subprocess.Popen", side_effect=AssertionError("offline validation launched Agda")):
            self.assertEqual(sources.validate_source_observation(artifact), artifact)
            inner = artifact["observation"]
            validator = candidates.validate_candidate_observation if inner["query"]["operation"] == "check" else goals.validate_goal_observation
            self.assertEqual(validator(inner), inner)

    def assert_pristine(self, expected=None):
        expected = self.original_trees if expected is None else expected
        self.assertEqual({root: tree_bytes(root) for root in expected}, expected)

    def assert_no_interaction(self, popen):
        self.assertFalse(any("--interaction-json" in call.args[0] for call in popen.call_args_list), popen.call_args_list)

    def second_bundle(self, *, failed=False):
        temporary = tempfile.TemporaryDirectory(prefix="recapture-", dir=self.home)
        self.addCleanup(temporary.cleanup)
        bundle = Path(temporary.name) / "bundle"
        # A real explicit capture with deliberately different diagnostics/command;
        # a failed attestation is useful source evidence, not a successful check.
        command = [sys.executable, "-c", "raise SystemExit(1)" if failed else "print('distinct recapture')"]
        core.capture_bundle(self.library, bundle, command, agda_binary=str(self.binary), timeout_seconds=30)
        return bundle

    def exercise_roundtrip(self):
        before = {root: tree_bytes(root) for root in self.original_trees}
        listed = self.listed()
        inspected = self.call("goals.inspect", self.select(listed))
        checked = self.call("candidate.check", self.select(listed, expression=EXPRESSION))
        if not self.real:
            self.configure(check_error=True)
        failed = self.call("candidate.check", self.select(listed, expression="Nat"))
        original_listing = self.get(listed["recordId"])["result"]["artifact"]
        for reply, kind, outcome in ((listed, "listing", "listed"), (inspected, "inspection", "inspected"),
                                     (checked, "candidate", "elaborated"), (failed, "candidate", "query-error")):
            self.assertEqual(reply["status"], "ok", reply)
            self.assertEqual(set(reply), RESPONSE_FIELDS)
            self.assertEqual(set(reply["result"]), {"documentId", "sourceObservationId", "observationId", "outcome"})
            self.assertEqual(reply["result"]["outcome"]["status"], outcome)
            self.assertIsNone(reply["error"])
            record = self.get(reply["recordId"])["result"]
            self.assertEqual(set(record), {"kind", "documentId", "recordRevision", "freshness", "dependencyMatchesPin", "artifact"})
            self.assertEqual(record["kind"], kind)
            self.assertEqual(record["documentId"], "main")
            self.assertEqual(record["recordRevision"], self.rev)
            self.assertEqual(record["freshness"], "current")
            self.assertIs(record["dependencyMatchesPin"], True)
            artifact = record["artifact"]
            self.assertEqual(artifact["format"], sources.SOURCE_FORMAT)
            self.assertEqual(artifact["sourceObservationId"], reply["result"]["sourceObservationId"])
            self.assertEqual(artifact["observation"]["observationId"], reply["result"]["observationId"])
            self.assertNotEqual(reply["recordId"], artifact["sourceObservationId"])
            self.assertEqual(artifact["observation"]["result"], reply["result"]["outcome"])
            self.assertEqual(artifact["dependency"]["evidence"], {"manifest": self.manifest, "components": self.components})
            self.assertTrue(artifact["observation"]["query"]["safe"])
            self.assertEqual(artifact["composition"]["clientIncludes"], ["."])
            if kind == "listing":
                self.assertIsNone(artifact["listing"])
                self.assertIsNone(artifact["observation"]["listing"])
            else:
                self.assertEqual(core.canonical_json_bytes(artifact["listing"]), core.canonical_json_bytes(original_listing))
                self.assertEqual(artifact["observation"]["listing"], original_listing["observation"])
            self.assert_offline(artifact)
        self.assertEqual(checked["result"]["outcome"]["assurance"], "contextual-elaboration-only")
        self.assertNotIn("proofComplete", checked["result"]["outcome"])
        self.assert_pristine(before)
        return listed, inspected, checked, failed

    def exercise_dirty_and_dependency_change(self):
        listed = self.listed()
        baseline = self.status()
        dirty = self.workspace.notify_buffers(dirty=True)
        with patch.object(sources, "_capture_source", side_effect=AssertionError("dirty buffers ran native research")):
            dirty_reply = self.call("goals.list", {"documentId": "main"}, revision=dirty)
            self.assertEqual(dirty_reply["status"], "stale", dirty_reply)
        self.assertTrue(self.status()["result"]["buffersDirty"])
        original = self.source.read_bytes()
        self.source.write_bytes(original + b"-- host edit\n")
        self.source.write_bytes(original)
        clean = self.workspace.notify_buffers(dirty=False)
        self.assertNotEqual(dirty, self.rev)
        self.assertNotEqual(clean, dirty)
        stale = self.call("goals.inspect", self.select(listed))
        self.assertEqual(stale["status"], "stale", stale)
        self.rev = self.status()["currentRevision"]
        self.assertEqual(self.status()["workspace"], baseline["workspace"])
        self.assertEqual(self.get(listed["recordId"])["result"]["freshness"], "stale")
        self.assertEqual(self.call("goals.inspect", self.select(listed))["error"]["code"], "listing-stale")
        fresh = self.listed()
        (self.project / "notes.txt").write_bytes(b"changed unrelated client source\n")
        edited_client = self.status()
        self.assertNotEqual(edited_client["workspace"]["clientSourceId"], baseline["workspace"]["clientSourceId"])
        self.assertIs(edited_client["result"]["dependencyMatchesPin"], True)
        self.assertEqual(self.get(fresh["recordId"])["result"]["freshness"], "stale")
        self.rev = edited_client["currentRevision"]
        (self.library / "notes.txt").write_bytes(b"changed unrelated dependency source\n")
        changed = self.status()
        self.assertIs(changed["result"]["dependencyMatchesPin"], False)
        self.assertEqual(changed["result"]["dependencyPins"], baseline["result"]["dependencyPins"])
        self.assertNotEqual(changed["workspace"]["dependencySourceId"], baseline["workspace"]["dependencySourceId"])
        self.assertEqual(changed["workspace"]["dependencyResolutionId"], baseline["workspace"]["dependencyResolutionId"])
        self.assertEqual(changed["workspace"]["dependencyBundleId"], baseline["workspace"]["dependencyBundleId"])
        with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
            self.assertEqual(self.call("goals.list", {"documentId": "main"})["status"], "stale")
            self.rev = changed["currentRevision"]
            self.error(self.call("goals.list", {"documentId": "main"}), "dependency-changed")
            self.assert_no_interaction(popen)
        history = self.get(fresh["recordId"])["result"]
        self.assertEqual(history["freshness"], "stale")
        self.assertIs(history["dependencyMatchesPin"], False)
        self.assert_offline(history["artifact"])


@unittest.skipUnless(os.name == "posix", "deterministic native pipe fixture requires POSIX")
class SourceResearchTests(_WorkspaceFixtures, unittest.TestCase):
    def test_versioned_status_six_subjects_composition_and_default_store(self):
        self.assertIsInstance(self.workspace, research.ResearchWorkspace)
        status = self.status()
        self.assertEqual(set(status), RESPONSE_FIELDS)
        self.assertEqual(status["apiVersion"], 2)
        self.assertEqual(set(status["workspace"]), SUBJECT_FIELDS)
        for digest in status["workspace"].values():
            self.assertRegex(digest, r"^sha256:[a-f0-9]{64}$")
        result = status["result"]
        self.assertEqual(result["documentIds"], ["main"])
        self.assertFalse(result["buffersDirty"])
        self.assertTrue(result["compilerAvailable"])
        self.assertFalse(result["catalogConfigured"])
        self.assertEqual(result["includes"], ["."])
        self.assertIs(result["safe"], True)
        self.assertEqual(result["limits"], {"timeoutSeconds": 30, "maxOutputBytes": 4_194_304,
                                           "maxRecords": 64, "maxStoredBytes": 67_108_864})
        self.assertEqual(set(result["dependencyPins"]), PIN_FIELDS)
        self.assertEqual(result["dependencyPins"], {"dependencySourceId": self.components["snapshot.json"]["sourceId"],
            "dependencyResolutionId": self.components["resolution.json"]["resolutionId"], "dependencyBundleId": self.manifest["bundleId"]})
        self.assertIs(result["dependencyMatchesPin"], True)
        composition = {"policy": "one-dependency-source-copy-v1", "clientIncludes": ["."],
                       "dependencyIncludes": ["src"], "safe": True}
        expected_id = "sha256:" + core.digest_value({"format": "agda-evidence/source-research-composition-v2", "composition": composition})
        self.assertEqual(result["composition"], composition)
        self.assertEqual(source_research.composition_identity(composition), expected_id)
        self.assertEqual(status["workspace"]["compositionId"], expected_id)
        self.assertEqual(status["workspace"]["clientSourceId"], core.build_snapshot(self.project)[0]["sourceId"])
        different = self.status(workspace=self.make_workspace(safe=False))
        self.assertNotEqual(different["workspace"]["compositionId"], expected_id)

    def test_full_source_roundtrip_retains_native_query_failure_and_original_leaf(self):
        self.exercise_roundtrip()

    def test_host_configuration_is_explicit_verified_and_failed_attestation_is_allowed(self):
        required = dict(dependency_root=self.library, dependency_bundle=self.bundle, dependency_includes=("src",),
                        agda_binary=str(self.binary))
        for missing in ("dependency_root", "dependency_bundle", "dependency_includes"):
            with self.subTest(missing=missing), self.assertRaises(TypeError):
                source_research.SourceResearchWorkspace(self.project, {"main": "Main.agda"},
                    **{key: value for key, value in required.items() if key != missing})
        for options in ({"dependency_root": self.project}, {"dependency_root": self.home},
                        {"dependency_includes": ()}, {"dependency_includes": ("../src",)},
                        {"dependency_includes": ("missing",)}):
            with self.subTest(options=options), self.assertRaises(core.EvidenceError):
                self.make_workspace(**options)
        (self.library / "notes.txt").write_bytes(b"initial mismatch must fail, never auto-pin\n")
        with self.assertRaises(core.EvidenceError):
            self.make_workspace()
        rebound_bundle = self.second_bundle()
        rebound = self.make_workspace(dependency_bundle=rebound_bundle)
        rebound_status = self.status(workspace=rebound)
        self.assertIs(rebound_status["result"]["dependencyMatchesPin"], True)
        self.assertNotEqual(rebound_status["result"]["dependencyPins"]["dependencyBundleId"], self.manifest["bundleId"])
        failed_bundle = self.second_bundle(failed=True)
        _, components = core.load_verified_bundle(failed_bundle)
        self.assertNotEqual(components["attestation.json"]["outcome"]["status"], "passed")
        self.assertNotIn("index-ref.json", components)
        workspace = self.make_workspace(dependency_bundle=failed_bundle)
        revision = self.status(workspace=workspace)["currentRevision"]
        listing = self.listed(workspace=workspace, revision=revision)
        self.assert_offline(self.get(listing["recordId"], workspace=workspace)["result"]["artifact"])

    def test_request_boundary_versions_paths_flags_uploads_and_boolean_goals(self):
        valid = self.request("goals.list", {"documentId": "main"})
        invalid = [None, [], {}, {**valid, "extra": True}, {**valid, "revision": None},
                   {**valid, "args": []}, {**valid, "op": "notify_buffers"},
                   {**valid, "args": {"documentId": "../Main.agda"}}]
        invalid += [{key: value for key, value in valid.items() if key != field} for field in valid]
        invalid += [{**valid, "apiVersion": value} for value in (None, True, False, 1, 3, "2", 2.0)]
        for field in ("projectRoot", "dependencyRoot", "dependencyBundle", "dependencyIncludes", "agdaBinary",
                      "includes", "safe", "catalog", "path", "flags", "artifact", "listing", "dirty", "uploads"):
            invalid.append({**valid, "args": {"documentId": "main", field: "/host/secret"}})
        for value in (True, False, -1, "0", 0.0, None):
            invalid.append(self.request("goals.inspect", {"listingId": "unknown", "goalId": value}))
        invalid.append(self.request("goals.inspect", {"listingId": {"observation": "forged"}, "goalId": 0}))
        for field in ("requestId", "revision", "op"):
            invalid.append({**valid, field: {"path": "/host/secret"}})
            invalid.append({**valid, field: "bad\ncontrol"})
            invalid.append({**valid, field: "\ud800"})
        with patch.object(self.workspace, "_observe", side_effect=AssertionError("invalid request probed inputs")) as probe:
            for request in invalid:
                with self.subTest(request=request):
                    response = self.workspace.handle(request)
                    self.error(response, "invalid-request")
                    self.assertEqual(response["apiVersion"], 2)
                    self.assertNotIn("/host/secret", json.dumps(response))
                    json.dumps(response, ensure_ascii=False).encode("utf-8")
            probe.assert_not_called()

    def test_unknown_cross_session_and_non_leaf_selection_fail_before_probes(self):
        listing = self.listed()
        inspection = self.call("goals.inspect", self.select(listing))
        other = self.make_workspace()
        with patch.object(self.workspace, "_observe", side_effect=AssertionError("unknown record probed inputs")), \
             patch.object(other, "_observe", side_effect=AssertionError("cross-session record probed inputs")), \
             patch("subprocess.Popen", side_effect=AssertionError("unknown selection launched a process")):
            for unavailable in ("not-a-record", listing["result"]["sourceObservationId"], listing["result"]["observationId"],
                                str(self.home / "uploaded-listing.json")):
                self.error(self.get(unavailable), "record-unavailable")
                self.error(self.call("goals.inspect", {"listingId": unavailable, "goalId": 0}), "record-unavailable")
            self.error(self.get(listing["recordId"], workspace=other), "record-unavailable")
            self.error(self.call("goals.inspect", self.select(listing), workspace=other), "record-unavailable")
            self.error(self.call("goals.inspect", {"listingId": inspection["recordId"], "goalId": 0}), "invalid-request")
            self.error(self.call("goals.inspect", self.select(listing, goalId=99)), "invalid-request")
        self.configure(blocked=True)
        blocked = self.call("goals.list", {"documentId": "main"})
        self.assertEqual(blocked["status"], "ok", blocked)
        self.assertEqual(blocked["result"]["outcome"]["status"], "load-blocked")
        with patch.object(self.workspace, "_observe", side_effect=AssertionError("blocked listing probed inputs")):
            self.error(self.call("goals.inspect", {"listingId": blocked["recordId"], "goalId": 0}), "invalid-request")

    def test_notified_edit_revert_client_tuple_and_unrelated_dependency_known_staleness(self):
        self.exercise_dirty_and_dependency_change()
        with self.assertRaises(core.EvidenceError):
            self.workspace.notify_buffers(dirty="false")

    def test_same_source_resolution_valid_new_bundle_invalidates_exact_frozen_bundle(self):
        listing = self.listed()
        before = self.status()
        replacement = self.second_bundle()
        manifest, components = core.load_verified_bundle(replacement)
        self.assertEqual(components["snapshot.json"]["sourceId"], self.components["snapshot.json"]["sourceId"])
        self.assertEqual(components["resolution.json"]["resolutionId"], self.components["resolution.json"]["resolutionId"])
        self.assertNotEqual(manifest["bundleId"], self.manifest["bundleId"])
        with replaced_bundle(self.bundle, replacement):
            current = self.status()
            self.assertEqual(current["result"]["dependencyPins"], before["result"]["dependencyPins"])
            self.assertEqual(current["workspace"]["dependencyBundleId"], manifest["bundleId"])
            self.assertIs(current["result"]["dependencyMatchesPin"], False)
            self.assertNotEqual(current["currentRevision"], self.rev)
            self.rev = current["currentRevision"]
            with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
                self.error(self.call("goals.list", {"documentId": "main"}), "dependency-changed")
                self.assert_no_interaction(popen)
            self.assertEqual(self.get(listing["recordId"])["result"]["freshness"], "stale")
            rebound = self.make_workspace()
            self.assertIs(self.status(workspace=rebound)["result"]["dependencyMatchesPin"], True)
        restored = self.status()
        self.assertEqual(restored["result"]["dependencyPins"], before["result"]["dependencyPins"])
        self.assertIs(restored["result"]["dependencyMatchesPin"], True)
        self.assertEqual(self.get(listing["recordId"])["result"]["freshness"], "stale")

    def test_native_registry_version_executable_and_dependency_manifest_mismatches_are_known(self):
        listing = self.listed()
        baseline = self.status()
        manifest_path = self.library / "sourceLib.agda-lib"
        manifest_bytes = manifest_path.read_bytes()
        for change in ("registry", "version", "compiler bytes", "dependency manifest"):
            with self.subTest(change=change):
                try:
                    if change == "registry":
                        (self.app / "libraries").write_text("/different/library.agda-lib\n", encoding="utf-8")
                    elif change == "version":
                        self.version.write_text("Agda version 2.6.3-changed-fixture\n", encoding="utf-8")
                    elif change == "compiler bytes":
                        self.binary.write_bytes(self.binary_bytes + b"\n# changed executable bytes\n")
                    else:
                        manifest_path.write_bytes(manifest_bytes + b"-- different native root manifest\n")
                    current = self.status()
                    self.assertIs(current["result"]["dependencyMatchesPin"], False)
                    self.assertNotEqual(current["workspace"]["dependencyResolutionId"], baseline["workspace"]["dependencyResolutionId"])
                    self.assertEqual(current["result"]["dependencyPins"], baseline["result"]["dependencyPins"])
                    self.rev = current["currentRevision"]
                    with self.assertRaises(core.EvidenceError):
                        self.make_workspace()  # Initial resolution mismatch is never silently rebound.
                    with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
                        self.error(self.call("goals.list", {"documentId": "main"}), "dependency-changed")
                        self.assert_no_interaction(popen)
                    history = self.get(listing["recordId"])["result"]
                    self.assertEqual(history["freshness"], "stale")
                    self.assertIs(history["dependencyMatchesPin"], False)
                finally:
                    (self.app / "libraries").unlink(missing_ok=True)
                    self.version.write_bytes(self.version_bytes)
                    self.binary.write_bytes(self.binary_bytes)
                    manifest_path.write_bytes(manifest_bytes)
                self.rev = self.status()["currentRevision"]

    def test_unavailable_client_dependency_or_bundle_keeps_null_revision_offline_history(self):
        listing = self.listed()
        original = self.get(listing["recordId"])["result"]["artifact"]
        for path in (self.project, self.library, self.bundle):
            with self.subTest(missing=path.name), hidden(path):
                self.error(self.call("workspace.status"), "freshness-unavailable")
                self.error(self.get(listing["recordId"], revision=self.rev), "freshness-unavailable")
                historical = self.get(listing["recordId"], revision=None)
                self.assertEqual(historical["status"], "ok", historical)
                self.assertEqual(historical["result"]["freshness"], "unknown")
                self.assertIsNone(historical["result"]["dependencyMatchesPin"])
                self.assertEqual(historical["result"]["artifact"], original)
                self.assert_offline(original)
                self.error(self.get("unknown"), "record-unavailable")
            self.rev = self.status()["currentRevision"]
        diagnostics = self.bundle / "diagnostics.json"
        saved = diagnostics.read_bytes()
        try:
            diagnostics.write_bytes(saved + b"corrupt component")
            self.error(self.get(listing["recordId"], revision=self.rev), "freshness-unavailable")
            history = self.get(listing["recordId"], revision=None)["result"]
            self.assertEqual(history["freshness"], "unknown")
            self.assertIsNone(history["dependencyMatchesPin"])
            self.assertEqual(history["artifact"], original)
        finally:
            diagnostics.write_bytes(saved)

    def test_source_record_store_is_canonical_detached_and_fifo_count_and_byte_bounded(self):
        captured = []
        real_capture = sources._capture_source
        def capture(*args, **options):
            value = real_capture(*args, **options)
            captured.append(value)
            return value
        with patch.object(sources, "_capture_source", side_effect=capture):
            listing = self.listed()
        record_id = listing["recordId"]
        original = deepcopy(self.get(record_id)["result"]["artifact"])
        self.assertEqual(self.workspace._records[record_id]["payload"], core.canonical_json_bytes(original))
        captured[0]["observation"]["result"]["goals"].clear()
        listing["result"]["outcome"]["goals"].clear()
        fetched = self.get(record_id)
        fetched["result"]["artifact"]["dependency"]["evidence"]["components"].clear()
        fetched["workspace"].clear()
        self.assertEqual(self.get(record_id)["result"]["artifact"], original)
        self.assertEqual(set(self.status()["workspace"]), SUBJECT_FIELDS)
        size = len(core.canonical_json_bytes(original))
        for limits in ({"max_records": 2}, {"max_records": 20, "max_stored_bytes": size * 2 + 256}):
            with self.subTest(limits=limits):
                workspace = self.make_workspace(**limits)
                revision = self.status(workspace=workspace)["currentRevision"]
                first = self.listed(workspace=workspace, revision=revision)
                second = self.listed(workspace=workspace, revision=revision)
                self.get(first["recordId"], workspace=workspace)
                third = self.listed(workspace=workspace, revision=revision)
                with patch.object(workspace, "_observe", side_effect=AssertionError("evicted record probed inputs")):
                    self.error(self.get(first["recordId"], workspace=workspace), "record-unavailable")
                    self.error(self.call("goals.inspect", self.select(first), workspace=workspace, revision=revision), "record-unavailable")
                for retained in (second, third):
                    self.assertEqual(self.get(retained["recordId"], workspace=workspace)["status"], "ok")
                if "max_stored_bytes" in limits:
                    oversized = self.call("candidate.check", self.select(third, expression="x" * 65536), workspace=workspace, revision=revision)
                    self.error(oversized, "store-capacity")
                    self.assertIsNone(oversized["recordId"])
                    self.assertEqual(self.get(second["recordId"], workspace=workspace)["status"], "ok")
                    self.assertEqual(self.get(third["recordId"], workspace=workspace)["status"], "ok")
        tiny = self.make_workspace(max_stored_bytes=1024)
        revision = self.status(workspace=tiny)["currentRevision"]
        self.error(self.call("goals.list", {"documentId": "main"}, workspace=tiny, revision=revision), "store-capacity")

    def test_dependency_search_uses_actual_source_index_and_never_implies_scope(self):
        listing = self.listed()
        before = {root: tree_bytes(root) for root in self.original_trees}
        actual = core.build_declaration_index(self.library)
        with patch.object(sources, "_capture_source", side_effect=AssertionError("lexical search ran native research")):
            response = self.call("library.search", self.select(listing, exact="Library.identity", scope="dependency"))
            self.assertEqual(response["status"], "ok", response)
            hit, = response["result"]["entries"]
            self.assertEqual(hit["origin"], "dependency")
            self.assertEqual(hit["path"], "src/Library.agda")
            self.assertEqual(hit["evidence"]["sourceId"], actual["sourceId"])
            self.assertEqual(hit["evidence"]["indexId"], actual["indexId"])
            self.assertEqual(hit["evidence"]["bundleId"], self.manifest["bundleId"])
            self.assertEqual(hit["evidence"]["resolutionId"], self.components["resolution.json"]["resolutionId"])
            self.assertEqual(hit["scopeStatus"], "not-established")
            self.assertEqual(hit["candidateUsability"], "not-tested")
            self.assertIs(response["result"]["contextualRanking"], False)
            self.assertIsNone(response["recordId"])
            self.assertEqual(self.call("library.search", self.select(listing, exact="Library.identity", scope="project"))["result"]["entries"], [])
            all_hits = self.call("library.search", self.select(listing, prefix="Library", scope="all"))
            self.assertEqual(all_hits["status"], "ok", all_hits)
            self.assertTrue(all(hit["origin"] == "dependency" for hit in all_hits["result"]["entries"]))
            self.error(self.call("library.search", self.select(listing, prefix="Library", scope="catalog")), "catalog-unavailable")
        for scope in ("project", "dependency"):
            with patch.object(self.workspace, "_observe", side_effect=AssertionError("invalid filter probed inputs")):
                self.error(self.call("library.search", self.select(listing, prefix="Library", scope=scope, libraries=["alpha"])), "invalid-request")
        self.assert_pristine(before)

    def test_all_search_combines_project_dependency_and_separate_catalog_provenance(self):
        replacement = self.second_bundle()
        index_path = replacement.parent / "index.json"
        core.write_declaration_index(index_path, core.build_declaration_index(self.library))
        indexed_bundle = replacement.parent / "indexed-bundle"
        core.capture_bundle(self.library, indexed_bundle, [sys.executable, "-c", "pass"],
                            agda_binary=str(self.binary), index_reference=index_path)
        catalog_path = replacement.parent / "catalog.json"
        catalog.create_catalog(catalog_path, [("archived", indexed_bundle)])
        workspace = self.make_workspace(catalog=catalog_path)
        revision = self.status(workspace=workspace)["currentRevision"]
        listing = self.listed(workspace=workspace, revision=revision)
        response = self.call("library.search", self.select(listing, prefix="", scope="all"), workspace=workspace, revision=revision)
        self.error(response, "invalid-request")
        response = self.call("library.search", self.select(listing, exact="Library.identity", scope="all"), workspace=workspace, revision=revision)
        self.assertEqual(response["status"], "ok", response)
        self.assertEqual({hit["origin"] for hit in response["result"]["entries"]}, {"dependency", "catalog"})
        self.assertEqual(response["result"]["checkedCatalogEntries"], ["archived"])
        project = self.call("library.search", self.select(listing, exact="Main.identityproof", scope="all"), workspace=workspace, revision=revision)
        self.assertEqual([hit["origin"] for hit in project["result"]["entries"]], ["project"])
        for hit in response["result"]["entries"] + project["result"]["entries"]:
            self.assertEqual(hit["scopeStatus"], "not-established")
            self.assertEqual(hit["candidateUsability"], "not-tested")
        catalog_hit = next(hit for hit in response["result"]["entries"] if hit["origin"] == "catalog")
        self.assertEqual(catalog_hit["evidence"]["entry"], "archived")
        self.assertNotEqual(catalog_hit["evidence"]["bundleId"], self.manifest["bundleId"])
        self.assertEqual(self.status(workspace=workspace)["result"]["dependencyPins"]["dependencyBundleId"], self.manifest["bundleId"])

    def test_success_failed_work_and_store_failure_all_reobserve_after_work(self):
        real_capture = sources._capture_source
        notes = self.project / "notes.txt"
        original = notes.read_bytes()
        for mode in ("returned", "failed work", "failed store"):
            with self.subTest(mode=mode):
                notes.write_bytes(original)
                self.rev = self.status()["currentRevision"]
                def work(*args, **options):
                    if mode == "failed work":
                        notes.write_bytes(b"changed during failed work\n")
                        raise RuntimeError(str(self.home / "secret"))
                    value = real_capture(*args, **options)
                    if mode == "returned":
                        notes.write_bytes(b"changed just after successful native work\n")
                    return value
                def failed_store(*args, **options):
                    notes.write_bytes(b"changed during failed store\n")
                    raise research.RequestError("store-capacity", str(self.home / "secret"))
                with patch.object(sources, "_capture_source", side_effect=work):
                    if mode == "failed store":
                        with patch.object(self.workspace, "_remember", side_effect=failed_store):
                            response = self.call("goals.list", {"documentId": "main"})
                    else:
                        response = self.call("goals.list", {"documentId": "main"})
                self.assertEqual(response["status"], "stale", response)
                self.assertNotEqual(response["currentRevision"], self.rev)
                self.assertNotIn(str(self.home), json.dumps(response))
                if mode == "returned":
                    retained = self.get(response["recordId"])["result"]
                    self.assertEqual(retained["freshness"], "stale")
                    self.assert_offline(retained["artifact"])
                else:
                    self.assertIsNone(response["recordId"])
        notes.write_bytes(original)

    def test_failed_source_capture_after_unnotified_revert_conservatively_invalidates_history(self):
        listing = self.listed()
        before = self.status()
        notes = self.project / "notes.txt"
        original = notes.read_bytes()
        def reverted_failure(*args, **options):
            notes.write_bytes(original + b"brief edit\n")
            notes.write_bytes(original)
            raise sources.SourceEvidenceError(str(self.home / "secret"))
        with patch.object(sources, "_capture_source", side_effect=reverted_failure):
            response = self.call("goals.list", {"documentId": "main"})
        # Conservative generation invalidation can surface as workspace-changed
        # stale instead of evidence-invalid error. Neither may reactivate history.
        self.assertIn(response["status"], {"error", "stale"}, response)
        self.assertIn(response["error"]["code"], {"evidence-invalid", "workspace-changed"})
        self.assertIsNone(response["recordId"])
        self.assertNotIn(str(self.home), json.dumps(response))
        self.assertNotEqual(response["currentRevision"], before["currentRevision"])
        self.assertEqual(self.status()["workspace"], before["workspace"])
        self.assertEqual(self.get(listing["recordId"])["result"]["freshness"], "stale")
        self.rev = self.status()["currentRevision"]
        self.listed()  # Failure must also release the operation lock.

    def test_fresh_list_capture_guard_prevents_interaction_after_client_or_bundle_race(self):
        real_capture = sources._capture_source
        replacement = self.second_bundle()
        notes = self.project / "notes.txt"
        original = notes.read_bytes()
        for mutation in ("client", "bundle"):
            with self.subTest(mutation=mutation):
                self.rev = self.status()["currentRevision"]
                def raced_capture(*args, **options):
                    if mutation == "client":
                        notes.write_bytes(original + b"changed after requested preflight\n")
                        return real_capture(*args, **options)
                    with replaced_bundle(self.bundle, replacement):
                        return real_capture(*args, **options)
                try:
                    with patch.object(sources, "_capture_source", side_effect=raced_capture), \
                         patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
                        response = self.call("goals.list", {"documentId": "main"})
                        self.assertIn(response["status"], {"error", "stale"}, response)
                        self.assertIsNone(response["recordId"])
                        self.assert_no_interaction(popen)
                finally:
                    notes.write_bytes(original)

    def test_valid_mismatched_returned_envelope_is_only_historical_never_active(self):
        real_capture = sources._capture_source
        notes = self.project / "notes.txt"
        original = notes.read_bytes()
        def other_subject(*args, **options):
            notes.write_bytes(original + b"other complete source subject\n")
            try:
                # Deliberately return a genuine independently captured envelope,
                # not fabricated/rehashed evidence and not the request's subject.
                return real_capture(self.project, "Main.agda", dependency_bundle=self.bundle,
                    dependency_root=self.library, dependency_includes=("src",), agda_binary=str(self.binary),
                    includes=(), safe=True, listing=None, goal_id=None, expression=None,
                    timeout_seconds=30, max_output_bytes=4_194_304)
            finally:
                notes.write_bytes(original)
        with patch.object(sources, "_capture_source", side_effect=other_subject):
            response = self.call("goals.list", {"documentId": "main"})
        self.assertEqual(response["status"], "stale", response)
        self.assertIsNotNone(response["recordId"])
        record = self.get(response["recordId"])["result"]
        self.assertEqual(record["freshness"], "stale")
        self.assertNotEqual(record["artifact"]["clientSnapshot"]["sourceId"], self.status()["workspace"]["clientSourceId"])
        self.assert_offline(record["artifact"])
        self.rev = self.status()["currentRevision"]
        self.assertEqual(self.call("goals.inspect", self.select(response))["status"], "stale")

    def test_event_controlled_busy_lock_allows_status_and_host_notifications(self):
        entered, release = threading.Event(), threading.Event()
        replies = []
        def pending(*args, **options):
            entered.set()
            if not release.wait(10):
                raise AssertionError("test worker was not released")
            raise RuntimeError("fixture worker failure")
        with patch.object(sources, "_capture_source", side_effect=pending):
            thread = threading.Thread(target=lambda: replies.append(self.call("goals.list", {"documentId": "main"})))
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.error(self.call("goals.list", {"documentId": "main"}), "workspace-busy")
                self.assertEqual(self.status()["status"], "ok")
                self.workspace.notify_buffers(dirty=True)
                self.workspace.notify_buffers(dirty=False)
            finally:
                release.set()
                thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["status"], "stale", replies)
        self.rev = self.status()["currentRevision"]
        self.listed()

    def test_event_controlled_concurrent_status_publications_keep_subjects_and_pin_boolean_coherent(self):
        # Pause at the reply boundary, not for an arbitrary sleep. A concurrent
        # reader must never publish one observation's pin admission with another
        # observation's workspace subjects, whichever lock strategy is used.
        entered, release, attempting = threading.Event(), threading.Event(), threading.Event()
        replies, failures = {}, []
        real_response = self.workspace._response
        def gated_response(request, status, **options):
            if request.get("requestId") == "first-reader" and status == "ok":
                entered.set()
                if not release.wait(10):
                    raise AssertionError("first reader was not released")
            return real_response(request, status, **options)
        def reader(label):
            try:
                if label == "second-reader":
                    attempting.set()
                request = {**self.request("workspace.status"), "requestId": label}
                replies[label] = self.workspace.handle(request)
            except BaseException as error:
                failures.append(error)
        notes = self.library / "notes.txt"
        original = notes.read_bytes()
        with patch.object(self.workspace, "_response", side_effect=gated_response):
            first = threading.Thread(target=reader, args=("first-reader",))
            second = threading.Thread(target=reader, args=("second-reader",))
            first.start()
            try:
                self.assertTrue(entered.wait(5))
                notes.write_bytes(original + b"concurrent dependency edit\n")
                second.start()
                self.assertTrue(attempting.wait(5))
            finally:
                release.set()
                first.join(10)
                if second.ident is not None:
                    second.join(10)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(set(replies), {"first-reader", "second-reader"})
        for reply in replies.values():
            self.assertEqual(reply["status"], "ok", reply)
            pins = reply["result"]["dependencyPins"]
            agrees = all(reply["workspace"][key] == value for key, value in pins.items())
            self.assertIs(reply["result"]["dependencyMatchesPin"], agrees)
        self.assertIs(replies["first-reader"]["result"]["dependencyMatchesPin"], True)
        self.assertIs(replies["second-reader"]["result"]["dependencyMatchesPin"], False)
        self.assertEqual(self.status()["workspace"], replies["second-reader"]["workspace"])

    def test_v1_workspace_request_and_pair_of_subjects_are_unchanged(self):
        workspace = research.ResearchWorkspace(self.project, {"main": "Main.agda"}, agda_binary=str(self.binary))
        request = {"requestId": "v1", "op": "workspace.status", "revision": None, "args": {}}
        status = workspace.handle(request)
        self.assertEqual(status["status"], "ok", status)
        self.assertEqual(status["apiVersion"], 1)
        self.assertEqual(set(status["workspace"]), {"sourceId", "resolutionId"})
        self.assertEqual(status["result"]["limits"]["maxStoredBytes"], 33_554_432)
        self.error(workspace.handle({**request, "apiVersion": 2}), "invalid-request")
        self.error(self.workspace.handle(request), "invalid-request")

    def test_v2_schemas_cover_runtime_status_artifacts_search_stale_and_unknown(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("optional jsonschema package is not installed; runtime tests still run")
        request_paths = list((ROOT / "schemas").glob("*research-request-v2.schema.json"))
        response_paths = list((ROOT / "schemas").glob("*research-response-v2.schema.json"))
        self.assertEqual(len(request_paths), 1, "exactly one v2 research request schema is required")
        self.assertEqual(len(response_paths), 1, "exactly one v2 research response schema is required")
        request_schema = json.loads(request_paths[0].read_text(encoding="utf-8"))
        response_schema = json.loads(response_paths[0].read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(request_schema)
        Draft202012Validator.check_schema(response_schema)
        requests, responses = Draft202012Validator(request_schema), Draft202012Validator(response_schema)
        listing = self.listed()
        cases = [self.request("workspace.status"), self.request("record.get", {"recordId": listing["recordId"]}),
                 self.request("goals.inspect", self.select(listing)),
                 self.request("candidate.check", self.select(listing, expression=EXPRESSION)),
                 self.request("library.search", self.select(listing, exact="Library.identity", scope="dependency"))]
        for request in cases:
            requests.validate(request)
            responses.validate(self.workspace.handle(request))
        responses.validate(listing)
        for value in (True, False, 1, "2"):
            bad = {**cases[0], "apiVersion": value}
            self.assertFalse(requests.is_valid(bad))
            responses.validate(self.workspace.handle(bad))
        self.workspace.notify_buffers(dirty=False)
        responses.validate(self.call("goals.inspect", self.select(listing)))
        with hidden(self.bundle):
            responses.validate(self.get(listing["recordId"], revision=None))


@unittest.skipUnless(os.name == "posix" and shutil.which("agda"), "optional native checks require POSIX and installed Agda")
class NativeSourceResearchTests(_WorkspaceFixtures, unittest.TestCase):
    real = True

    def test_native_safe_import_list_inspect_trial_success_failure_and_offline_exact_artifacts(self):
        listed, inspected, checked, failed = self.exercise_roundtrip()
        self.assertEqual(len(listed["result"]["outcome"]["goals"]), 1)
        selected = inspected["result"]["outcome"]["selected"]
        self.assertEqual(selected["type"], "Nat")
        self.assertTrue(any(entry["reifiedName"] == "n" and entry["binding"] == "Nat" and entry["inScope"]
                            for entry in selected["entries"]))
        self.assertEqual(checked["result"]["outcome"]["assurance"], "contextual-elaboration-only")
        self.assertEqual(failed["result"]["outcome"]["status"], "query-error")
        self.assertEqual(self.components["attestation.json"]["outcome"]["status"], "passed")
        self.assertNotIn("index-ref.json", self.components)

    def test_native_dirty_revert_client_edit_and_unrelated_dependency_edit_have_known_staleness(self):
        self.exercise_dirty_and_dependency_change()

    def test_native_imports_and_include_roots_are_not_automatically_repaired(self):
        original = self.source.read_bytes()
        for missing_import in (True, False):
            with self.subTest(missing_import=missing_import):
                self.source.write_bytes(original)
                if missing_import:
                    self.source.write_text(CLIENT.replace("import Library", "import MissingLibrary"), encoding="utf-8")
                    workspace = self.workspace
                else:
                    workspace = self.make_workspace(dependency_includes=(".",))
                revision = self.status(workspace=workspace)["currentRevision"]
                before = {root: tree_bytes(root) for root in self.original_trees}
                response = self.call("goals.list", {"documentId": "main"}, workspace=workspace, revision=revision)
                self.assertEqual(response["status"], "ok", response)
                self.assertEqual(response["result"]["outcome"]["status"], "load-error", response)
                record = self.get(response["recordId"], workspace=workspace)["result"]
                self.assertEqual(record["freshness"], "current")
                self.assert_offline(record["artifact"])
                self.assert_pristine(before)
        self.source.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
