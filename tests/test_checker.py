"""Native checker contract tests; the fake executable speaks Agda's wire protocol."""

from __future__ import annotations

import copy
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

from agda_evidence import checker, core


# Each test selects a mode in the script source, not through checker internals.
# All traffic is real pipe I/O, including the initial prompt without a newline.
FAKE_AGDA = r'''
import json
import os
from pathlib import Path
import sys
import time

MODE = __MODE__
LOG = Path(__LOG__)
APP_DIR = __APP_DIR__


def log(**record):
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def send(data):
    if MODE == "fragmented":
        # Byte-sized writes split both JSON tokens and UTF-8 code points.
        for byte in data:
            sys.stdout.buffer.write(bytes([byte]))
            sys.stdout.buffer.flush()
            time.sleep(0.001)
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def response(kind, **fields):
    send((json.dumps(dict(kind=kind, **fields), ensure_ascii=False) + "\n").encode("utf-8"))


def prompt():
    send(b"JSON> ")


log(argv=sys.argv[1:], cwd=os.getcwd())
if "--version" in sys.argv:
    print("Agda version 2.6.4-fake")
    sys.exit(0)
if "--print-agda-app-dir" in sys.argv:
    print(APP_DIR)
    sys.exit(0)
if "--interaction-json" not in sys.argv:
    sys.exit(2)
if MODE == "timeout-startup":
    time.sleep(30)
prompt()
for command in sys.stdin:
    log(command=command.rstrip("\n"))
    if "Cmd_load" in command:
        if MODE == "load-error":
            response("DisplayInfo", info={"kind": "Error", "message": os.getcwd() + "/Main.agda: bad load"})
            prompt()
            continue
        if MODE == "malformed":
            send(b'{"kind": not-json}\n')
            prompt()
            continue
        # A generated interface must stay in the temporary staged project.
        Path("fake.agdai").write_bytes(b"not a source input")
        response("Status", status={"checked": MODE != "unchecked"})
        summary = dict(kind="AllGoalsWarnings", visibleGoals=[], invisibleGoals=[], warnings=[], errors=[])
        points = []
        if MODE == "goals":
            summary["visibleGoals"] = [{"id": 0}]
            points = [{"id": 0}]
        if MODE == "invisible-goals":
            summary["invisibleGoals"] = [{"id": 1}]
        if MODE == "warnings":
            summary["warnings"] = [{"message": "unsafe fixture"}]
        response("DisplayInfo", info=summary)
        response("InteractionPoints", interactionPoints=points)
        prompt()
        if MODE == "stall-infer-input":
            time.sleep(30)
    elif "Cmd_infer_toplevel" in command:
        if MODE == "query-error":
            sys.stderr.write("fake query diagnostic λ\n")
            sys.stderr.flush()
            response("DisplayInfo", info={"kind": "Error", "message": "unknown name λ"})
            prompt()
            sys.exit(0)  # Zero OS exit does not mean a successful type inference.
        if MODE == "eof":
            sys.exit(0)
        if MODE == "timeout-infer":
            time.sleep(30)
        if MODE == "stdout-limit":
            send(b"x" * 4096)
            time.sleep(30)
        if MODE == "stderr-limit":
            sys.stderr.buffer.write(b"x" * 4096)
            sys.stderr.buffer.flush()
            time.sleep(30)
        if MODE == "combined-limit":
            send(b"x" * 600)
            sys.stderr.buffer.write(b"y" * 600)
            sys.stderr.buffer.flush()
            time.sleep(30)
        response("DisplayInfo", info={"kind": "InferredType", "expr": "ℕ → ℕ"})
        prompt()
    else:
        sys.exit(3)
'''


@unittest.skipUnless(os.name == "posix", "native fake sessions currently require POSIX")
class CheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="checker-tests-")
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.project = self.temporary / "project λ"
        self.project.mkdir()
        self.source = self.project / "Main.agda"
        self.source.write_text("module Main where\n", encoding="utf-8")
        (self.project / "src").mkdir()
        self.app_dir = self.temporary / "agda-config"
        self.app_dir.mkdir()
        # Avoid relying on the host's Agda registry, even if Agda is installed.
        environment = patch.dict(os.environ, {"AGDA_DIR": str(self.app_dir)})
        environment.start()
        self.addCleanup(environment.stop)
        self.binary = self.temporary / "fake agda λ;not-a-shell"
        self.log = self.temporary / "commands.jsonl"
        self.make_fake()

    def make_fake(self, mode: str = "clean") -> None:
        source = FAKE_AGDA.replace("__MODE__", repr(mode))
        source = source.replace("__LOG__", repr(str(self.log)))
        source = source.replace("__APP_DIR__", repr(str(self.app_dir)))
        self.binary.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
        self.binary.chmod(0o755)
        self.log.unlink(missing_ok=True)

    def records(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def commands(self) -> list[str]:
        return [record["command"] for record in self.records() if "command" in record]

    def infer(self, expression: str = "identity", **options) -> dict:
        return checker.infer_type(
            self.project, "Main.agda", expression, agda_binary=str(self.binary), **options
        )

    def basis_bundle(self) -> tuple[Path, dict]:
        path = self.temporary / "basis"
        manifest = core.capture_bundle(
            self.project, path, [sys.executable, "-c", "pass"], agda_binary=str(self.binary)
        )
        self.assertEqual(core.verify_bundle(path), [])
        return path, manifest

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "agda_evidence", "checker", *arguments],
            cwd=ROOT, env={**os.environ, "PYTHONPATH": str(SRC)},
            text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=15,
        )

    def cli_infer(self, output: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "infer", "--project-root", str(self.project), "--file", "Main.agda",
            "--expression", "identity", "--output", str(output),
            "--agda-bin", str(self.binary), *extra,
        )

    def assert_failed(self, observation: dict, result: str, transport: str = "completed") -> None:
        self.assertEqual(observation["result"], {"status": result, "type": None})
        self.assertEqual(observation["transport"]["status"], transport)
        self.assertEqual(checker.validate_observation(observation), observation)

    def test_stalled_stdin_write_obeys_total_session_timeout(self) -> None:
        self.make_fake("stall-infer-input")
        observation = self.infer("x" * 1_048_576, timeout_seconds=1)
        self.assert_failed(observation, "timed-out", "timed-out")
        self.assertEqual(len(self.commands()), 1)
        self.assertEqual(observation["transcript"][-1]["phase"], "infer")
        self.assertFalse(observation["transcript"][-1]["complete"])

    def test_clean_load_infer_is_isolated_and_uses_argv_not_shell(self) -> None:
        before = {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        with patch("agda_evidence.checker.subprocess.Popen", wraps=subprocess.Popen) as popen:
            observation = self.infer(includes=("src", ".", "src"), safe=True)
        self.assertEqual(observation["result"], {"status": "inferred", "type": "ℕ → ℕ"})
        self.assertEqual(observation["transport"]["status"], "completed")
        self.assertEqual([p["phase"] for p in observation["transcript"]], ["startup", "load", "infer"])
        self.assertTrue(all(p["complete"] for p in observation["transcript"]))
        self.assertIsNone(observation["transcript"][0]["request"])
        self.assertEqual(observation["query"]["includes"], [".", "src"])
        self.assertEqual(observation["execution"]["argv"], [
            "$AGDA", "--interaction-json", "--no-libraries", "--ignore-interfaces", "--safe", "-i", "$PROJECT_ROOT", "-i", "$PROJECT_ROOT/src"
        ])
        interaction = [call for call in popen.call_args_list if "--interaction-json" in call.args[0]]
        self.assertEqual(len(interaction), 1)
        self.assertIsInstance(interaction[0].args[0], list)
        self.assertFalse(interaction[0].kwargs.get("shell", False))
        self.assertNotEqual(Path(interaction[0].kwargs["cwd"]), self.project)
        self.assertFalse(Path(interaction[0].kwargs["cwd"]).exists())
        self.assertEqual(len(self.commands()), 2)
        self.assertIn("Cmd_load", self.commands()[0])
        self.assertIn("Cmd_infer_toplevel", self.commands()[1])
        self.assertIn("$PROJECT_ROOT/Main.agda", observation["transcript"][1]["request"])
        after = {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(list(self.project.rglob("*.agdai")), [])
        self.assertEqual(observation["observationId"], checker.observation_id(observation))

    def test_legacy_relative_argv_observation_keeps_original_verification_contract(self) -> None:
        observation = self.infer(includes=("src",), safe=True)
        observation["execution"]["argv"] = checker._argv("$AGDA", [".", "src"], True)
        observation["observationId"] = checker.observation_id(observation)
        self.assertEqual(checker.validate_observation(observation), observation)

    def test_fragmented_json_prompt_and_unicode_request(self) -> None:
        self.make_fake("fragmented")
        name = "Λ.agda"
        (self.project / name).write_text("module Λ where\n", encoding="utf-8")
        expression = 'λ x → x "quoted" \\ newline\nnext'
        observation = checker.infer_type(
            self.project, name, expression, agda_binary=str(self.binary), timeout_seconds=5
        )
        self.assertEqual(observation["result"]["type"], "ℕ → ℕ")
        self.assertEqual(observation["query"]["expression"], expression)
        self.assertEqual(len(self.commands()), 2)  # Escaped newline must not create a third command.
        self.assertIn("Λ.agda", self.commands()[0])
        self.assertIn("λ x → x", self.commands()[1])
        self.assertIn(r'\"quoted\"', self.commands()[1])
        self.assertNotIn(r"\u03bb", self.commands()[1])
        self.assertTrue(all(p["complete"] for p in observation["transcript"]))

    def test_load_error_never_sends_infer_and_normalises_diagnostics(self) -> None:
        self.make_fake("load-error")
        observation = self.infer()
        self.assert_failed(observation, "load-error")
        self.assertEqual([p["phase"] for p in observation["transcript"]], ["startup", "load"])
        self.assertEqual(len(self.commands()), 1)
        error = observation["transcript"][1]["responses"][0]["info"]["message"]
        self.assertIn("$PROJECT_ROOT/Main.agda: bad load", error)
        self.assertNotIn(str(self.temporary), error)

    def test_goals_warnings_and_unchecked_loads_reject_without_inference(self) -> None:
        for mode in ("goals", "invisible-goals", "warnings", "unchecked"):
            with self.subTest(mode=mode):
                self.make_fake(mode)
                observation = self.infer()
                self.assert_failed(observation, "load-incomplete")
                self.assertEqual(len(self.commands()), 1)
                self.assertEqual(len(observation["transcript"]), 2)
                self.assertTrue(observation["transcript"][-1]["complete"])

    def test_query_error_is_failure_even_when_fake_exits_zero(self) -> None:
        self.make_fake("query-error")
        observation = self.infer()
        self.assert_failed(observation, "query-error")
        self.assertEqual(len(self.commands()), 2)
        self.assertEqual(observation["transcript"][2]["responses"][0]["info"]["kind"], "Error")
        self.assertTrue(observation["transcript"][2]["complete"])

    def test_eof_and_malformed_json_are_protocol_failures(self) -> None:
        for mode, phase in (("eof", "infer"), ("malformed", "load")):
            with self.subTest(mode=mode):
                self.make_fake(mode)
                observation = self.infer()
                self.assert_failed(observation, "protocol-error", "protocol-error")
                self.assertEqual(observation["transcript"][-1]["phase"], phase)
                self.assertFalse(observation["transcript"][-1]["complete"])
                self.assertTrue(observation["transport"]["message"])
                self.assertEqual(len(self.commands()), 2 if phase == "infer" else 1)

    def test_output_limit_applies_to_stdout_and_stderr(self) -> None:
        for mode in ("stdout-limit", "stderr-limit", "combined-limit"):
            with self.subTest(mode=mode):
                self.make_fake(mode)
                observation = self.infer(max_output_bytes=1024)
                self.assert_failed(observation, "output-limit", "output-limit")
                self.assertEqual(observation["execution"]["maxOutputBytes"], 1024)
                self.assertFalse(observation["transcript"][-1]["complete"])
                self.assertIn("byte limit", observation["transport"]["message"])

    def test_timeout_in_startup_or_infer_produces_a_valid_failed_observation(self) -> None:
        for mode, phase in (("timeout-startup", "startup"), ("timeout-infer", "infer")):
            with self.subTest(mode=mode):
                self.make_fake(mode)
                observation = self.infer(timeout_seconds=1)
                self.assert_failed(observation, "timed-out", "timed-out")
                self.assertEqual(observation["transcript"][-1]["phase"], phase)
                self.assertFalse(observation["transcript"][-1]["complete"])
                self.assertIn("timeout", observation["transport"]["message"])

    def test_saved_success_and_failure_roundtrip_verify_without_running_agda(self) -> None:
        for mode in ("clean", "query-error"):
            with self.subTest(mode=mode):
                self.make_fake(mode)
                observation = self.infer()
                path = self.temporary / f"{mode}.json"
                checker.write_observation(path, observation)
                original_bytes = path.read_bytes()
                with patch("subprocess.Popen", side_effect=AssertionError("verifier launched a process")):
                    self.assertEqual(checker.load_observation(path), observation)
                    self.assertEqual(checker.validate_observation(observation), observation)
                with self.assertRaises(core.EvidenceError):
                    checker.write_observation(path, observation)
                self.assertEqual(path.read_bytes(), original_bytes)

    def test_rehashed_tampering_of_summary_and_bindings_is_rejected(self) -> None:
        original = self.infer()
        # Recompute the outer digest deliberately: verification must check semantics too.
        mutations = {
            "type": lambda o: o["result"].update(type="Set"),
            "file digest": lambda o: o["query"].update(sourceSha256="sha256:" + "0" * 64),
            "request": lambda o: o["query"].update(expression="different expression"),
            "argv": lambda o: o["execution"]["argv"].append("--allow-unsolved-metas"),
            "timestamps": lambda o: o["execution"].update(finishedAt="2000-01-01T00:00:00Z"),
            "timezone": lambda o: o["execution"].update(startedAt="2026-01-01T00:00:00"),
            "basis": lambda o: o.update(basis={
                "bundleId": "sha256:" + "1" * 64, "sourceId": "sha256:" + "0" * 64,
                "resolutionId": o["resolution"]["resolutionId"],
            }),
        }
        path = self.temporary / "tampered.json"
        for label, mutate in mutations.items():
            with self.subTest(field=label):
                changed = copy.deepcopy(original)
                mutate(changed)
                changed["observationId"] = checker.observation_id(changed)
                path.write_text(json.dumps(changed, ensure_ascii=False) + "\n", encoding="utf-8")
                with self.assertRaises(core.EvidenceError):
                    checker.validate_observation(changed)
                with self.assertRaises(checker.CheckerEvidenceError):
                    checker.load_observation(path)
        changed = copy.deepcopy(original)
        changed["transport"]["stderr"] = "tamper without rehash"
        with self.assertRaises(core.EvidenceError):
            checker.validate_observation(changed)

    def test_matching_basis_pins_work_and_source_mismatch_prevents_interaction(self) -> None:
        basis, manifest = self.basis_bundle()
        observation = self.infer(bundle=basis)
        self.assertEqual(observation["basis"], {
            "bundleId": manifest["bundleId"], "sourceId": observation["snapshot"]["sourceId"],
            "resolutionId": observation["resolution"]["resolutionId"],
        })
        self.source.write_text("module Main where\n-- changed source\n", encoding="utf-8")
        self.log.unlink()
        with self.assertRaisesRegex(checker.CheckerEvidenceError, "sourceId.*pin mismatch"):
            self.infer(bundle=basis)
        self.assertTrue(any("--version" in r.get("argv", []) for r in self.records()))
        self.assertFalse(any("--interaction-json" in r.get("argv", []) for r in self.records()))
        self.assertEqual(self.commands(), [])

    def test_resolution_pin_mismatch_prevents_interaction_but_allows_metadata(self) -> None:
        basis, _ = self.basis_bundle()
        # Change only the external registry, leaving the source tree and binary intact.
        (self.app_dir / "libraries").write_text("/different/library.agda-lib\n", encoding="utf-8")
        self.log.unlink()
        with self.assertRaisesRegex(checker.CheckerEvidenceError, "resolutionId.*pin mismatch"):
            self.infer(bundle=basis)
        self.assertTrue(any("--version" in r.get("argv", []) for r in self.records()))
        self.assertFalse(any("--interaction-json" in r.get("argv", []) for r in self.records()))
        self.assertEqual(self.commands(), [])

    def test_cli_exit_codes_preserve_failed_observation_and_diagnostics(self) -> None:
        self.make_fake("query-error")
        failed_path = self.temporary / "failed.json"
        failed = self.cli_infer(failed_path)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertEqual(json.loads(failed.stdout)["result"], {"status": "query-error", "type": None})
        observation = checker.load_observation(failed_path)
        self.assertIn("fake query diagnostic λ", observation["transport"]["stderr"])
        self.assertIn("unknown name λ", json.dumps(observation["transcript"], ensure_ascii=False))
        self.log.unlink()
        verified = self.run_cli("verify", str(failed_path))
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["result"]["status"], "query-error")
        self.assertEqual(self.records(), [])
        self.make_fake()
        inferred = self.cli_infer(self.temporary / "inferred.json")
        self.assertEqual(inferred.returncode, 0, inferred.stderr)
        self.assertEqual(json.loads(inferred.stdout)["result"]["type"], "ℕ → ℕ")
        failed_path.write_text("{}\n", encoding="utf-8")
        self.assertEqual(self.run_cli("verify", str(failed_path)).returncode, 1)

    def test_cli_rejects_invalid_arguments_and_unsafe_output_before_launch(self) -> None:
        basis, _ = self.basis_bundle()
        existing = self.temporary / "existing.json"
        existing.write_text("keep me\n", encoding="utf-8")
        cases = [
            (existing, (), "already exists"),
            (self.project / "observation.json", (), "outside the project"),
            (basis / "observation.json", ("--bundle", str(basis)), "outside its basis"),
            (self.temporary / "bad-timeout.json", ("--timeout-seconds", "0"), "timeout"),
            (self.temporary / "bad-limit.json", ("--max-output-bytes", "512"), "limit"),
            (self.temporary / "bad-file.json", ("--file", "../Main.agda"), "path"),
            (self.temporary / "bad-include.json", ("--include", "../outside"), "include"),
            (self.temporary / "empty-expression.json", ("--expression", " "), "expression"),
        ]
        for output, extra, diagnostic in cases:
            with self.subTest(output=output.name):
                self.log.unlink(missing_ok=True)
                result = self.cli_infer(output, *extra)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual(self.records(), [])
                if output != existing:
                    self.assertFalse(output.exists())
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep me\n")
        missing = self.run_cli("infer", "--project-root", str(self.project))
        self.assertEqual(missing.returncode, 2)
        self.assertIn("required", missing.stderr)


@unittest.skipIf(shutil.which("agda") is None, "optional real Agda executable is unavailable")
@unittest.skipUnless(os.name == "posix", "native checker currently requires POSIX")
class RealAgdaCheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="checker-real-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "project"
        self.project.mkdir()
        self.source = self.project / "Main.agda"
        self.source.write_text(
            "module Main where\n"
            "open import Agda.Builtin.Nat\n"
            "identity : Nat → Nat\nidentity x = x\n"
            "infixl 6 _⊕_\n_⊕_ : Nat → Nat → Nat\nx ⊕ y = x\n",
            encoding="utf-8",
        )

    def test_builtin_identity_unicode_operator_and_subdirectory_include(self) -> None:
        (self.project / "src").mkdir()
        (self.project / "src" / "Helper.agda").write_text(
            "module Helper where\nopen import Agda.Builtin.Nat\n"
            "helper : Nat → Nat\nhelper x = x\n", encoding="utf-8",
        )
        self.source.write_text(self.source.read_text(encoding="utf-8") + "open import Helper\n", encoding="utf-8")
        original = {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob("*.agda")}
        for expression, expected in (("identity", "Nat → Nat"), ("_⊕_", "Nat → Nat → Nat"), ("helper", "Nat → Nat")):
            with self.subTest(expression=expression):
                observation = checker.infer_type(self.project, "Main.agda", expression, includes=("src",), safe=True)
                self.assertEqual(observation["result"], {"status": "inferred", "type": expected}, observation["transcript"])
                self.assertEqual(checker.validate_observation(observation), observation)
        self.assertEqual(original, {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob("*.agda")})
        self.assertEqual(list(self.project.rglob("*.agdai")), [])

    def test_nested_client_file_uses_workspace_anchored_sibling_include(self) -> None:
        (self.project / "client").mkdir()
        (self.project / "library" / "src").mkdir(parents=True)
        (self.project / "library" / "src" / "Helper.agda").write_text(
            "module Helper where\nopen import Agda.Builtin.Nat\nhelper : Nat → Nat\nhelper x = x\n",
            encoding="utf-8",
        )
        nested = self.project / "client" / "Client.agda"
        nested.write_text("module Client where\nopen import Agda.Builtin.Nat\nimport Helper\n", encoding="utf-8")
        observation = checker.infer_type(
            self.project, "client/Client.agda", "Helper.helper", includes=("client", "library/src"), safe=True,
        )
        self.assertEqual(observation["result"], {"status": "inferred", "type": "Nat → Nat"})
        self.assertIn("$PROJECT_ROOT/library/src", observation["execution"]["argv"])
        self.assertEqual(list(self.project.rglob("*.agdai")), [])

    def test_real_load_error_goals_and_missing_name(self) -> None:
        original = self.source.read_text(encoding="utf-8")
        cases = (
            (original, "missingName", "query-error", 3),
            (original + "broken : NotInScope\nbroken = missing\n", "identity", "load-error", 2),
            (original + "unfinished : Nat\nunfinished = ?\n", "identity", "load-incomplete", 2),
        )
        for source, expression, status, phases in cases:
            with self.subTest(status=status):
                self.source.write_text(source, encoding="utf-8")
                observation = checker.infer_type(self.project, "Main.agda", expression)
                self.assertEqual(observation["result"], {"status": status, "type": None}, observation["transcript"])
                self.assertEqual(len(observation["transcript"]), phases)
                self.assertEqual(checker.validate_observation(observation), observation)
                self.assertEqual(self.source.read_text(encoding="utf-8"), source)
                self.assertEqual(list(self.project.rglob("*.agdai")), [])


if __name__ == "__main__":
    unittest.main()
