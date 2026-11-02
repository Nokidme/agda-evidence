"""Pinned client/library composition contracts, with native pipe-I/O fixtures.

The fake compiler is local to each test and its metadata is captured from the
same actual library checkout used by infer_client.  Real Agda tests are optional;
none of these tests fetch dependencies or alter production implementation files.
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
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from agda_evidence import checker, cli, client, core


# Not imported from another test module: every native executable, registry,
# metadata file and command log belongs to this test's temporary directory.
FAKE_AGDA = r'''
import json
import os
from pathlib import Path
import sys

MODE = __MODE__
LOG = Path(__LOG__)
APP_DIR = __APP_DIR__
VERSION = Path(__VERSION__)


def log(**value):
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def response(kind, **value):
    print(json.dumps(dict(kind=kind, **value), ensure_ascii=False), flush=True)


def prompt():
    sys.stdout.write("JSON> ")
    sys.stdout.flush()


log(argv=sys.argv[1:], cwd=os.getcwd())
if "--version" in sys.argv:
    print(VERSION.read_text(encoding="utf-8").strip())
    sys.exit(0)
if "--print-agda-app-dir" in sys.argv:
    print(APP_DIR)
    sys.exit(0)
if "--interaction-json" not in sys.argv:
    sys.exit(2)
prompt()
for command in sys.stdin:
    log(command=command.rstrip("\n"))
    if "Cmd_load" in command:
        if MODE == "load-error":
            response("DisplayInfo", info={"kind": "Error", "message": os.getcwd() + "/client/Main.agda: load failed"})
        elif MODE == "malformed":
            print('{"kind": not-json}', flush=True)
        else:
            Path("generated.agdai").write_bytes(b"only in the checker copy")
            response("Status", status={"checked": True})
            response("DisplayInfo", info=dict(kind="AllGoalsWarnings", visibleGoals=[], invisibleGoals=[], warnings=[], errors=[]))
            response("InteractionPoints", interactionPoints=[])
        prompt()
    elif "Cmd_infer_toplevel" in command:
        if MODE == "query-error":
            sys.stderr.write("fixture query diagnostic λ\n")
            sys.stderr.flush()
            response("DisplayInfo", info={"kind": "Error", "message": "unknown name λ"})
            prompt()
            sys.exit(0)
        response("DisplayInfo", info={"kind": "InferredType", "expr": "Nat → Nat"})
        prompt()
    else:
        sys.exit(3)
'''


class _ClientFixtures:
    """Shared helpers only; no inherited unittest test methods."""

    def make_trees(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="client-contract-")
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.project = self.temporary / "client checkout λ"
        self.library = self.temporary / "library checkout λ"
        self.project.mkdir()
        (self.project / "src").mkdir()
        (self.library / "src").mkdir(parents=True)
        self.source = self.project / "Main.agda"
        self.source.write_text("module Main where\nimport Example\n", encoding="utf-8")
        (self.library / "example.agda-lib").write_text(
            "name: example\ninclude: src\n", encoding="utf-8"
        )
        (self.library / "src" / "Example.agda").write_text(
            "module Example where\nopen import Agda.Builtin.Nat\n"
            "identity : Nat → Nat\nidentity x = x\n"
            "private\n  secret : Nat → Nat\n  secret x = x\n", encoding="utf-8"
        )
        for root in (self.project, self.library):
            (root / "notes.txt").write_text(root.name + "\n", encoding="utf-8")
            (root / "existing.agdai").write_bytes(b"original interface must survive")
        self.app_dir = self.temporary / "agda-config"
        self.app_dir.mkdir()
        environment = patch.dict(os.environ, {"AGDA_DIR": str(self.app_dir)})
        environment.start()
        self.addCleanup(environment.stop)
        self.bundle = self.temporary / "evidence"

    def capture(self, name: str = "evidence", *, failed: bool = False, real: bool = False) -> Path:
        index = core.build_declaration_index(self.library)
        index_path = self.temporary / f"{name}.index.json"
        core.write_declaration_index(index_path, index)
        bundle = self.temporary / name
        command = ([str(self.binary), "--safe", "--no-libraries", "--ignore-interfaces",
                    "-i", "src", "src/Example.agda"] if real else
                   [sys.executable, "-c", "import sys; print('fixture capture'); sys.exit(" + ("7" if failed else "0") + ")"])
        core.capture_bundle(self.library, bundle, command, agda_binary=str(self.binary), index_reference=index_path)
        self.assertEqual(core.verify_bundle(bundle), [])
        self.index = index
        self.candidate = {key: value for key, value in next(
            entry for entry in index["entries"] if entry["qualifiedName"] == "Example.identity"
        ).items() if key != "sourceSha256"}
        return bundle

    def infer(self, expression: str = "Example.identity", **options) -> dict:
        arguments = dict(library_bundle=self.bundle, library_root=self.library,
                         library_includes=("src",), candidate=self.candidate,
                         agda_binary=str(self.binary), safe=True, timeout_seconds=15)
        arguments.update(options)
        return client.infer_client(self.project, "Main.agda", expression, **arguments)

    @staticmethod
    def tree_bytes(root: Path) -> dict[str, bytes]:
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*") if path.is_file()}

    @staticmethod
    def read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def save_json(path: Path, value: dict) -> None:
        path.write_bytes(core.canonical_json_bytes(value) + b"\n")

    def refresh_bundle(self, bundle: Path) -> None:
        manifest = self.read_json(bundle / "bundle.json")
        manifest["components"] = {name: "sha256:" + core.digest_value(self.read_json(bundle / name))
                                  for name in manifest["components"]}
        manifest["bundleId"] = "sha256:" + core.digest_value(
            {"format": manifest["format"], "components": manifest["components"]}
        )
        self.save_json(bundle / "bundle.json", manifest)

    def replace_resolution(self, bundle: Path, mutate) -> None:
        resolution = self.read_json(bundle / "resolution.json")
        mutate(resolution)
        resolution["resolutionId"] = core.derive_resolution_id(resolution)
        attestation = self.read_json(bundle / "attestation.json")
        attestation["subjects"]["resolutionId"] = resolution["resolutionId"]
        attestation["attestationId"] = core.derive_attestation_id(attestation)
        self.save_json(bundle / "resolution.json", resolution)
        self.save_json(bundle / "attestation.json", attestation)
        self.refresh_bundle(bundle)

    @staticmethod
    def anchored_argv(includes: list[str], safe: bool = True) -> list[str]:
        argv = ["$AGDA", "--interaction-json", "--no-libraries", "--ignore-interfaces"]
        if safe:
            argv.append("--safe")
        for directory in includes:
            argv.extend(["-i", "$PROJECT_ROOT" if directory == "." else "$PROJECT_ROOT/" + directory])
        return argv

    def assert_selection_only(self, observation: dict) -> None:
        summary = client.client_summary(observation)
        self.assertEqual(summary["selectionRelation"], "lexical-context-only")
        self.assertEqual(summary["selection"], observation["library"]["candidate"])
        # No claim that the query resolved the lexical entry is permitted.
        self.assertEqual(set(summary), {"clientObservationId", "clientSourceId", "librarySourceId",
            "workspaceSourceId", "libraryResolutionId", "workspaceResolutionId", "selection",
            "selectionRelation", "result"})
        self.assertEqual(set(observation["library"]["candidate"]),
                         {"path", "line", "qualifiedName", "kind", "sourceSha256"})


@unittest.skipUnless(os.name == "posix", "native fake Agda sessions require POSIX")
class ClientTests(_ClientFixtures, unittest.TestCase):
    def setUp(self) -> None:
        self.make_trees()
        self.binary = self.temporary / "fake agda λ;not-shell"
        self.log = self.temporary / "native.jsonl"
        self.version = self.temporary / "compiler-version.txt"
        self.version.write_text("Agda version 2.6.4-fixture\n", encoding="utf-8")
        self.make_fake()
        self.bundle = self.capture()
        self.log.unlink(missing_ok=True)

    def make_fake(self, mode: str = "clean") -> None:
        source = (FAKE_AGDA.replace("__MODE__", repr(mode))
                  .replace("__LOG__", repr(str(self.log)))
                  .replace("__APP_DIR__", repr(str(self.app_dir)))
                  .replace("__VERSION__", repr(str(self.version))))
        self.binary.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
        self.binary.chmod(0o755)
        self.log.unlink(missing_ok=True)

    def records(self) -> list[dict]:
        return ([json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
                if self.log.exists() else [])

    def assert_no_interaction(self) -> None:
        self.assertFalse(any("--interaction-json" in record.get("argv", []) for record in self.records()))
        self.assertFalse(any("command" in record for record in self.records()))

    def cli_args(self, output: Path) -> list[str]:
        return ["client", "infer", "--project-root", str(self.project), "--library-root", str(self.library),
                "--library-bundle", str(self.bundle), "--library-include", "src", "--file", "Main.agda",
                "--expression", "Example.identity", "--output", str(output), "--agda-bin", str(self.binary),
                "--candidate-path", self.candidate["path"], "--candidate-line", str(self.candidate["line"]),
                "--candidate-qualified-name", self.candidate["qualifiedName"],
                "--candidate-kind", self.candidate["kind"], "--safe"]

    @staticmethod
    def run_cli(arguments: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                status = cli.main(arguments)
            except SystemExit as error:
                status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    def test_exact_prefixed_union_full_evidence_candidate_and_isolation(self) -> None:
        before = {root: self.tree_bytes(root) for root in (self.project, self.library, self.bundle)}
        with patch("agda_evidence.checker.subprocess.Popen", wraps=subprocess.Popen) as popen:
            observation = self.infer(includes=("src", ".", "src"), library_includes=("src", "src"))
        inner = observation["typeObservation"]
        library = observation["library"]
        manifest, payloads = core.load_verified_bundle(self.bundle)
        self.assertEqual(library["evidence"], {"manifest": manifest, "components": payloads})
        self.assertEqual(library["nativeResolution"]["resolutionId"], payloads["resolution.json"]["resolutionId"])
        self.assertTrue(payloads["resolution.json"]["agda"]["available"])
        self.assertEqual(payloads["resolution.json"]["agda"]["binarySha256"], "sha256:" + core.sha256_file(self.binary))
        root_manifest = next(record for record in payloads["snapshot.json"]["files"] if record["path"] == "example.agda-lib")
        self.assertEqual(payloads["resolution.json"]["projectLibraryFiles"][0]["sha256"], root_manifest["sha256"])
        selected = next(entry for entry in self.index["entries"] if all(entry[key] == value for key, value in self.candidate.items()))
        self.assertEqual(library["candidate"], selected)
        self.assertNotIn("sourceSha256", self.candidate)
        expected = sorted([{**record, "path": prefix + "/" + record["path"]}
                           for prefix, snapshot in (("client", observation["clientSnapshot"]),
                                                    ("library", payloads["snapshot.json"]))
                           for record in snapshot["files"]], key=lambda record: record["path"])
        self.assertEqual(inner["snapshot"]["files"], expected)
        ids = {observation["clientSnapshot"]["sourceId"], payloads["snapshot.json"]["sourceId"], inner["snapshot"]["sourceId"]}
        self.assertEqual(len(ids), 3)
        self.assertEqual(observation["composition"], {"policy": "one-library-source-copy-v1",
                                                     "clientIncludes": [".", "src"], "libraryIncludes": ["src"]})
        self.assertEqual(inner["query"]["includes"], [".", "client", "client/src", "library/src"])
        self.assertEqual(inner["query"]["file"], "client/Main.agda")
        self.assertEqual(inner["query"]["expression"], "Example.identity")
        self.assertEqual(inner["execution"]["argv"], self.anchored_argv(inner["query"]["includes"]))
        self.assertIsNone(inner["basis"])
        self.assertEqual(inner["result"], {"status": "inferred", "type": "Nat → Nat"})
        interactions = [call for call in popen.call_args_list if "--interaction-json" in call.args[0]]
        self.assertEqual(len(interactions), 1)
        launch = interactions[0]
        self.assertFalse(launch.kwargs.get("shell", False))
        stage = Path(launch.kwargs["cwd"])
        self.assertNotIn(stage, (self.project, self.library))
        self.assertFalse(stage.exists())
        includes = launch.args[0]
        self.assertEqual([includes[i + 1] for i, value in enumerate(includes) if value == "-i"],
                         [str(stage / root) for root in inner["query"]["includes"]])
        self.assertEqual({root: self.tree_bytes(root) for root in before}, before)
        self.assertEqual(client.validate_client_observation(observation), observation)
        self.assertEqual(observation["clientObservationId"], client.client_observation_id(observation))
        self.assert_selection_only(observation)

    def test_duplicate_qualified_names_preserve_exact_path_and_line(self) -> None:
        source = self.library / "src" / "Example.agda"
        source.write_text(source.read_text(encoding="utf-8") + "identity : Nat → Nat\n", encoding="utf-8")
        (self.library / "src" / "Alternate.agda").write_text(
            "module Example where\n\nidentity : Set\n", encoding="utf-8")
        bundle = self.capture("duplicates")
        entries = core.query_declaration_index(self.index, exact="Example.identity")
        self.assertEqual(len(entries), 3)
        self.assertEqual(len({(entry["path"], entry["line"]) for entry in entries}), 3)
        for entry in entries:
            with self.subTest(path=entry["path"], line=entry["line"]):
                selection = {key: value for key, value in entry.items() if key != "sourceSha256"}
                observation = self.infer(library_bundle=bundle, candidate=selection)
                self.assertEqual(observation["library"]["candidate"], entry)
        invalid = dict(self.candidate, line=999)
        self.log.unlink(missing_ok=True)
        with self.assertRaisesRegex(client.ClientEvidenceError, "exactly one"):
            self.infer(library_bundle=bundle, candidate=invalid)
        self.assert_no_interaction()
        with self.assertRaises(core.EvidenceError):
            self.infer(candidate=dict(self.candidate, sourceSha256=entries[0]["sourceSha256"]))

    def test_unrelated_library_edit_breaks_source_pin_before_metadata_or_interaction(self) -> None:
        (self.library / "notes.txt").write_text("unrelated source-tree edit\n", encoding="utf-8")
        with patch("subprocess.Popen", side_effect=AssertionError("source mismatch launched a process")):
            with self.assertRaisesRegex(client.ClientEvidenceError, "source pin mismatch"):
                self.infer()
        self.assertEqual(self.records(), [])

    def test_registry_and_compiler_metadata_changes_break_resolution_pin(self) -> None:
        binary = self.binary.read_bytes()
        version = self.version.read_bytes()
        registry = self.app_dir / "libraries"
        for change in ("registry", "version", "binary"):
            with self.subTest(change=change):
                registry.unlink(missing_ok=True)
                self.binary.write_bytes(binary)
                self.version.write_bytes(version)
                if change == "registry":
                    registry.write_text("/unrelated/library.agda-lib\n", encoding="utf-8")
                elif change == "version":
                    self.version.write_text("Agda version changed-with-identical-binary\n", encoding="utf-8")
                else:
                    self.binary.write_bytes(binary + b"\n# changed compiler bytes\n")
                self.log.unlink(missing_ok=True)
                with self.assertRaisesRegex(client.ClientEvidenceError, "resolution pin mismatch"):
                    self.infer()
                self.assertTrue(any("--version" in record.get("argv", []) for record in self.records()))
                self.assert_no_interaction()

    def test_malformed_legacy_opaque_missing_nix_and_unpinned_evidence_rejected(self) -> None:
        cases = ("malformed", "legacy", "opaque", "missing-index", "missing-component", "nix",
                 "unavailable", "missing-digest", "unbound-agda-lib")
        for case in cases:
            with self.subTest(case=case):
                bundle = self.temporary / ("bad-" + case)
                shutil.copytree(self.bundle, bundle)
                if case == "malformed":
                    (bundle / "bundle.json").write_text('{"format":1,"format":2}\n', encoding="utf-8")
                elif case in {"legacy", "missing-index"}:
                    manifest = self.read_json(bundle / "bundle.json")
                    del manifest["components"]["index-ref.json"]
                    (bundle / "index-ref.json").unlink()
                    self.save_json(bundle / "bundle.json", manifest)
                    if case == "legacy":
                        for filename, fields in (("snapshot.json", ("sourceId",)), ("resolution.json", ("resolutionId",)),
                                                 ("attestation.json", ("subjects", "diagnosticsDigest", "attestationId"))):
                            payload = self.read_json(bundle / filename)
                            for field in fields:
                                payload.pop(field)
                            self.save_json(bundle / filename, payload)
                    self.refresh_bundle(bundle)
                    self.assertEqual(core.verify_bundle(bundle), [])
                elif case == "opaque":
                    reference = self.read_json(bundle / "index-ref.json")
                    reference.pop("index")
                    reference["content"] = {"opaque": "legacy reference"}
                    self.save_json(bundle / "index-ref.json", reference)
                    self.refresh_bundle(bundle)
                    self.assertEqual(core.verify_bundle(bundle), [])
                elif case == "missing-component":
                    (bundle / "diagnostics.json").unlink()
                else:
                    def mutate(resolution):
                        if case == "nix":
                            resolution["nix"] = {"adapter": core.NIX_PROBE_ADAPTER, "version": {}, "flake": {
                                "flakeNixSha256": "sha256:" + "1" * 64, "flakeLockSha256": "sha256:" + "2" * 64}}
                        elif case == "unavailable":
                            resolution["agda"] = {"requested": resolution["agda"]["requested"], "available": False, "reason": "not-found"}
                        elif case == "missing-digest":
                            resolution["agda"].pop("binarySha256")
                        else:
                            resolution["projectLibraryFiles"] = []
                    self.replace_resolution(bundle, mutate)
                    self.assertEqual(core.verify_bundle(bundle), [])
                self.log.unlink(missing_ok=True)
                with patch("subprocess.Popen", side_effect=AssertionError("invalid evidence launched a process")):
                    with self.assertRaises(client.ClientEvidenceError):
                        self.infer(library_bundle=bundle)
                self.assertEqual(self.records(), [])

    def test_failed_library_capture_is_embedded_unchanged_not_promoted_to_green(self) -> None:
        failed = self.capture("failed-evidence", failed=True)
        before = self.tree_bytes(failed)
        observation = self.infer(library_bundle=failed)
        recorded = self.read_json(failed / "attestation.json")
        self.assertEqual(recorded["outcome"]["status"], "failed")
        self.assertEqual(recorded["outcome"]["exitCode"], 7)
        self.assertEqual(observation["library"]["evidence"]["components"]["attestation.json"], recorded)
        self.assertEqual(observation["typeObservation"]["result"]["status"], "inferred")
        self.assertEqual(self.tree_bytes(failed), before)
        self.assert_selection_only(observation)

    def test_embedded_provenance_uses_same_verified_payload_instances_without_reread(self) -> None:
        read_json = core._read_json
        loaded = {}
        reads = []
        def read_and_replace(path):
            value = read_json(path)
            if path.parent == self.bundle:
                reads.append(path.name)
                loaded[path.name] = value
                if path.name == "attestation.json":
                    path.write_text('{"scope":"unverified replacement"}\n', encoding="utf-8")
            return value
        with patch.object(core, "_read_json", side_effect=read_and_replace):
            observation = self.infer()
        evidence = observation["library"]["evidence"]
        self.assertIs(evidence["manifest"], loaded["bundle.json"])
        for name, payload in evidence["components"].items():
            self.assertIs(payload, loaded[name])
        self.assertEqual(len(reads), len(set(reads)))
        self.assertEqual(set(reads), {"bundle.json", *evidence["components"]})
        self.assertEqual(evidence["components"]["attestation.json"]["scope"], "explicit-project-check")
        self.assertTrue(core.verify_bundle(self.bundle))
        with patch("subprocess.Popen", side_effect=AssertionError("offline verifier launched a process")):
            self.assertEqual(client.validate_client_observation(observation), observation)

    def test_rehashing_only_outer_id_cannot_hide_inner_or_evidence_tampering(self) -> None:
        original = self.infer()
        mutations = {
            "inner result": lambda o: o["typeObservation"]["result"].update(type="Set"),
            "client source": lambda o: o["clientSnapshot"]["files"][0].update(sha256="sha256:" + "0" * 64),
            "compiler": lambda o: o["library"]["nativeResolution"]["agda"]["version"].update(stdout="different version"),
            "candidate": lambda o: o["library"]["candidate"].update(sourceSha256="sha256:" + "0" * 64),
            "composition": lambda o: o["composition"].update(libraryIncludes=["."]),
            "evidence": lambda o: o["library"]["evidence"]["components"]["diagnostics.json"]["stdout"].update(text="forged"),
            "outer extra field": lambda o: o.update(candidateResolution="claimed"),
            "unknown schema": lambda o: o.update(format="agda-evidence/client-observation-v999"),
        }
        path = self.temporary / "tampered.json"
        for label, mutate in mutations.items():
            with self.subTest(binding=label):
                changed = copy.deepcopy(original)
                mutate(changed)
                changed["clientObservationId"] = client.client_observation_id(changed)
                self.save_json(path, changed)
                with patch("subprocess.Popen", side_effect=AssertionError("offline verifier launched a process")):
                    with self.assertRaises(client.ClientEvidenceError):
                        client.validate_client_observation(changed)
                    with self.assertRaises(client.ClientEvidenceError):
                        client.load_client_observation(path)

    def test_rehashed_inner_still_obeys_union_compiler_include_candidate_and_composition_bindings(self) -> None:
        original = self.infer()
        def source_union(o):
            snapshot = o["typeObservation"]["snapshot"]
            next(record for record in snapshot["files"] if record["path"] == "library/notes.txt")["sha256"] = "sha256:" + "0" * 64
            snapshot["sourceId"] = snapshot["sourceDigest"] = core.derive_source_id(snapshot)
        def compiler(o):
            resolution = o["typeObservation"]["resolution"]
            resolution["agda"]["version"]["stdout"] = "another compiler version"
            resolution["resolutionId"] = core.derive_resolution_id(resolution)
        def includes(o):
            inner = o["typeObservation"]
            inner["query"]["includes"] = [".", "client"]
            inner["execution"]["argv"] = self.anchored_argv(inner["query"]["includes"])
        def legacy_argv(o):
            inner = o["typeObservation"]
            argv = ["$AGDA", "--interaction-json", "--no-libraries", "--ignore-interfaces", "--safe"]
            for root in inner["query"]["includes"]:
                argv.extend(["-i", root])
            inner["execution"]["argv"] = argv
        mutations = {"prefixed source union": source_union, "workspace compiler": compiler,
                     "workspace include roots": includes, "legacy unanchored argv": legacy_argv,
                     "candidate path": lambda o: o["library"]["candidate"].update(path="src/Missing.agda"),
                     "candidate line": lambda o: o["library"]["candidate"].update(line=999),
                     "candidate qualified name": lambda o: o["library"]["candidate"].update(qualifiedName="Other.identity"),
                     "candidate kind": lambda o: o["library"]["candidate"].update(kind="module"),
                     "candidate digest": lambda o: o["library"]["candidate"].update(sourceSha256="sha256:" + "0" * 64),
                     "composition policy": lambda o: o["composition"].update(policy="unrestricted"),
                     "client includes": lambda o: o["composition"].update(clientIncludes=[".", "src"])}
        for label, mutate in mutations.items():
            with self.subTest(binding=label):
                changed = copy.deepcopy(original)
                mutate(changed)
                changed["typeObservation"]["observationId"] = checker.observation_id(changed["typeObservation"])
                changed["clientObservationId"] = client.client_observation_id(changed)
                with self.assertRaises(client.ClientEvidenceError):
                    client.validate_client_observation(changed)

    def test_success_and_failed_inner_observations_roundtrip_and_verify_without_processes(self) -> None:
        for mode, expected in (("clean", "inferred"), ("load-error", "load-error"),
                               ("query-error", "query-error"), ("malformed", "protocol-error")):
            with self.subTest(mode=mode):
                self.make_fake(mode)
                bundle = self.capture("roundtrip-" + mode)
                observation = self.infer(library_bundle=bundle)
                inner = observation["typeObservation"]
                self.assertEqual(inner["result"]["status"], expected)
                self.assertEqual(len(inner["transcript"]), 2 if mode in {"load-error", "malformed"} else 3)
                if mode == "query-error":
                    self.assertIn("fixture query diagnostic λ", inner["transport"]["stderr"])
                    self.assertEqual(inner["transcript"][2]["responses"][0]["info"]["kind"], "Error")
                path = self.temporary / (mode + ".json")
                client.write_client_observation(path, observation)
                saved = path.read_bytes()
                self.log.unlink(missing_ok=True)
                with patch("subprocess.Popen", side_effect=AssertionError("verification launched a process")):
                    self.assertEqual(client.load_client_observation(path), observation)
                    self.assertEqual(client.validate_client_observation(observation), observation)
                    status, stdout, stderr = self.run_cli(["client", "verify", str(path)])
                self.assertEqual(status, 0, stderr)
                self.assertEqual(json.loads(stdout)["result"]["status"], expected)
                self.assertEqual(self.records(), [])
                with self.assertRaises(core.EvidenceError):
                    client.write_client_observation(path, observation)
                self.assertEqual(path.read_bytes(), saved)
                link = self.temporary / (mode + "-link.json")
                link.symlink_to(path)
                with self.assertRaises(client.ClientEvidenceError):
                    client.load_client_observation(link)
        # Failed inference is still written by the CLI, with exit 1, not discarded.
        self.make_fake("query-error")
        self.bundle = self.capture("cli-failed-evidence")
        path = self.temporary / "cli-failed.json"
        status, stdout, stderr = self.run_cli(self.cli_args(path))
        self.assertEqual(status, 1, stderr)
        self.assertEqual(json.loads(stdout)["result"]["status"], "query-error")
        self.assertEqual(client.load_client_observation(path)["typeObservation"]["result"]["status"], "query-error")

    def test_cli_protects_both_source_roots_evidence_and_existing_outputs(self) -> None:
        existing = self.temporary / "existing.json"
        existing.write_bytes(b"keep output\n")
        link = self.temporary / "output-link.json"
        link.symlink_to(existing)
        root_link = self.temporary / "library-link"
        root_link.symlink_to(self.library, target_is_directory=True)
        before = {root: self.tree_bytes(root) for root in (self.project, self.library, self.bundle)}
        for output in (self.project / "out.json", self.library / "out.json", self.bundle / "out.json",
                       existing, link, root_link / "out.json"):
            with self.subTest(output=str(output)):
                with patch("subprocess.Popen", side_effect=AssertionError("unsafe output launched a process")):
                    status, _, stderr = self.run_cli(self.cli_args(output))
                self.assertEqual(status, 2, stderr)
                self.assertTrue("outside" in stderr or "already exists" in stderr, stderr)
                if output not in (existing, link):
                    self.assertFalse(output.exists())
        self.assertEqual(existing.read_bytes(), b"keep output\n")
        self.assertEqual({root: self.tree_bytes(root) for root in before}, before)

    def test_repeated_single_cli_selectors_and_invalid_composition_inputs_reject(self) -> None:
        output = self.temporary / "not-written.json"
        arguments = self.cli_args(output)
        singles = ("--project-root", "--library-root", "--library-bundle", "--output", "--file", "--expression",
                   "--candidate-path", "--candidate-line", "--candidate-qualified-name", "--candidate-kind", "--agda-bin")
        for flag in singles:
            with self.subTest(flag=flag):
                value = arguments[arguments.index(flag) + 1]
                with patch("subprocess.Popen", side_effect=AssertionError("repeated selector launched a process")):
                    status, _, stderr = self.run_cli(arguments + [flag, value])
                self.assertEqual(status, 2, stderr)
                self.assertIn("only once", stderr)
                self.assertFalse(output.exists())
        for options in ({"library_includes": ()}, {"library_includes": ("../src",)},
                        {"library_root": self.project}, {"library_root": self.project / "src"}):
            with self.subTest(options=options):
                with patch("subprocess.Popen", side_effect=AssertionError("invalid composition launched a process")):
                    with self.assertRaises(core.EvidenceError):
                        self.infer(**options)

    def test_expected_source_and_compiler_preflight_guards_reject_before_interaction(self) -> None:
        infer_type = checker.infer_type
        for mutation in ("workspace", "compiler"):
            with self.subTest(mutation=mutation):
                self.version.write_text("Agda version 2.6.4-fixture\n", encoding="utf-8")
                self.log.unlink(missing_ok=True)
                def mutate_then_infer(root, file, expression, **options):
                    self.assertIn("_expected_source_id", options)
                    self.assertIn("_expected_agda", options)
                    if mutation == "workspace":
                        (root / "library" / "notes.txt").write_text("changed before inner capture\n", encoding="utf-8")
                    else:
                        self.version.write_text("Agda version changed before inner capture\n", encoding="utf-8")
                    with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
                        try:
                            # Return only a genuine observation, or propagate the original exception.
                            return infer_type(root, file, expression, **options)
                        finally:
                            self.assertFalse(any("--interaction-json" in call.args[0] for call in popen.call_args_list))
                            if mutation == "workspace":
                                popen.assert_not_called()
                with patch.object(client, "infer_type", side_effect=mutate_then_infer):
                    with self.assertRaisesRegex(checker.CheckerEvidenceError, "composition (source|compiler) pin mismatch"):
                        self.infer()
                self.assert_no_interaction()

    def test_copy_mutations_additions_and_removals_of_unrelated_files_are_detected(self) -> None:
        copy_snapshot = client._copy_snapshot
        notes = self.library / "notes.txt"
        original_notes = notes.read_bytes()
        for location, action in (("destination", "addition"), ("destination", "removal"),
                                 ("source", "addition"), ("source", "removal")):
            with self.subTest(location=location, action=action):
                notes.write_bytes(original_notes)
                (self.library / "added.txt").unlink(missing_ok=True)
                self.log.unlink(missing_ok=True)
                def mutate_copy(root, files, target):
                    if root == self.library and location == "source":
                        if action == "addition":
                            (root / "added.txt").write_text("added after capture\n", encoding="utf-8")
                        else:
                            (root / "notes.txt").unlink()
                    copy_snapshot(root, files, target)
                    if root == self.library and location == "destination":
                        if action == "addition":
                            (target / "added.txt").write_text("added during copy\n", encoding="utf-8")
                        else:
                            (target / "notes.txt").unlink()
                with patch.object(client, "_copy_snapshot", side_effect=mutate_copy):
                    with self.assertRaises(core.EvidenceError):
                        self.infer()
                self.assert_no_interaction()


@unittest.skipIf(shutil.which("agda") is None, "optional installed Agda is unavailable")
@unittest.skipUnless(os.name == "posix", "native Agda requires POSIX")
class RealAgdaClientTests(_ClientFixtures, unittest.TestCase):
    def setUp(self) -> None:
        self.make_trees()
        self.binary = Path(shutil.which("agda"))
        self.source.write_text("module Main where\nopen import Agda.Builtin.Nat\nimport Example\n", encoding="utf-8")
        self.bundle = self.capture(real=True)
        attestation = self.read_json(self.bundle / "attestation.json")
        self.assertEqual(attestation["outcome"]["status"], "passed",
                         self.read_json(self.bundle / "diagnostics.json"))

    def test_safe_import_private_visibility_missing_import_and_explicit_library_include(self) -> None:
        original = self.source.read_text(encoding="utf-8")
        cases = ((original, "Example.identity", ("src",), "inferred"),
                 (original, "Example.secret", ("src",), "query-error"),
                 ("module Main where\n", "Example.identity", ("src",), "query-error"),
                 (original, "Example.identity", (".",), "load-error"))
        for text, expression, roots, expected in cases:
            with self.subTest(expression=expression, includes=roots, imported="import Example" in text):
                self.source.write_text(text, encoding="utf-8")
                before = {root: self.tree_bytes(root) for root in (self.project, self.library, self.bundle)}
                observation = self.infer(expression, library_includes=roots)
                inner = observation["typeObservation"]
                self.assertEqual(inner["result"]["status"], expected, inner["transcript"])
                self.assertEqual(inner["result"]["type"], "Nat → Nat" if expected == "inferred" else None)
                self.assertEqual(inner["execution"]["argv"], self.anchored_argv(inner["query"]["includes"]))
                self.assertEqual({root: self.tree_bytes(root) for root in before}, before)
                self.assertEqual(client.validate_client_observation(observation), observation)
                self.assert_selection_only(observation)

    def test_renaming_reexport_alias_and_unimported_client_homonym_are_lexical_context_only(self) -> None:
        sources = (("module Main where\nopen import Agda.Builtin.Nat\nopen import Example renaming (identity to renamed)\n", "renamed"),
                   ("module Main where\nopen import Agda.Builtin.Nat\nmodule Alias where\n  open import Example public\n", "Alias.identity"),
                   ("module Main where\nopen import Agda.Builtin.Nat\nidentity : Nat → Nat\nidentity x = x\n", "identity"))
        for text, expression in sources:
            with self.subTest(expression=expression):
                self.source.write_text(text, encoding="utf-8")
                before = {root: self.tree_bytes(root) for root in (self.project, self.library, self.bundle)}
                observation = self.infer(expression)
                self.assertEqual(observation["typeObservation"]["result"], {"status": "inferred", "type": "Nat → Nat"},
                                 observation["typeObservation"]["transcript"])
                self.assertEqual(observation["library"]["candidate"]["qualifiedName"], "Example.identity")
                self.assertEqual(observation["typeObservation"]["query"]["expression"], expression)
                self.assertEqual({root: self.tree_bytes(root) for root in before}, before)
                self.assert_selection_only(observation)
                if expression == "identity":
                    self.assertNotIn("import Example", self.source.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
