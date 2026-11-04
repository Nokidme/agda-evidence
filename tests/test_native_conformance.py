"""Finite native-runner contracts; only the full integration needs real Agda.

The report is a sidecar, not a new certificate schema. Offline validation below
uses the existing public v1 loaders, after all native work has finished.
"""
from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agda_evidence import candidates, core, goals, sources

SCRIPT = ROOT / "scripts" / "native-conformance.py"
REPORT_FORMAT = "agda-evidence/native-conformance-report-v1"


def load_runner():
    # The hyphenated, repository-local script intentionally is not a package API.
    spec = importlib.util.spec_from_file_location("native_conformance_test_runner", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import the native conformance script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def saved_report(output: Path) -> dict:
    reports = []
    for path in output.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("format") == REPORT_FORMAT:
            reports.append(value)
    if len(reports) != 1:
        raise AssertionError(f"expected one retained report, found {len(reports)} in {output}")
    return reports[0]


def source_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()
            and path.suffix in {".agda", ".agdai", ".agda-lib"}}


class NativeConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-conformance-tests-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.output = self.home / "report"

    def run_report(self, **options):
        arguments = {"agda_binary": "agda-conformance-intentionally-absent",
                     "expected_version": "2.6.3", "output": self.output}
        arguments.update(options)
        return self.runner.run_conformance(**arguments)

    def assert_failed_report(self, report, output=None):
        self.assertEqual(report["format"], REPORT_FORMAT)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(saved_report(output or self.output), report)
        cases = report["cases"]
        self.assertEqual([case["id"] for case in cases], list(self.runner.REQUIRED_CASES))
        self.assertTrue(any(case["status"] == "failed" for case in cases))
        self.assertTrue(all(case["status"] in {"passed", "failed", "not-run"} for case in cases))
        self.assertNotIn("skipped", {case["status"] for case in cases})
        return cases

    def cli(self, *arguments):
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
        return subprocess.run([sys.executable, "-B", str(SCRIPT), *map(str, arguments)],
                              cwd=self.home, env=environment, capture_output=True,
                              text=True, timeout=30, check=False)

    def test_public_defaults_and_mandatory_cases_are_stable(self):
        signature = inspect.signature(self.runner.run_conformance)
        self.assertEqual(signature.parameters["profile"].default, "builtin")
        self.assertIsNone(signature.parameters["dependency_root"].default)
        self.assertEqual(signature.parameters["timeout_seconds"].default, 20)
        cases = self.runner.REQUIRED_CASES
        self.assertIsInstance(cases, tuple)
        self.assertTrue(cases)
        self.assertEqual(len(cases), len(set(cases)))
        self.assertTrue(all(isinstance(case, str) and case for case in cases))
        self.assertIn("compiler-version", cases)
        self.assertEqual(cases, (
            "compiler-version", "dependency-gate", "native-v1", "source-list",
            "source-context", "source-elaborated", "source-wrong-type",
            "source-missing-name", "source-no-import", "source-multiple-goals",
            "source-empty-goals", "source-warning-blocked", "source-fatal-load",
            "lexical-scopes", "catalog-not-mounted", "dirty-generation",
            "dependency-changed", "missing-bundle", "cross-session",
            "offline-verification", "source-integrity",
        ))

    def test_recorded_inner_seconds_reads_native_utc_span_without_mutation(self):
        execution = {"startedAt": "2026-01-02T03:04:05.125Z",
                     "finishedAt": "2026-01-02T03:04:06.625+00:00"}
        native = {"execution": execution}
        envelope = {"observation": native}
        before = copy.deepcopy(envelope)
        self.assertEqual(self.runner.recorded_inner_seconds(native), 1.5)
        self.assertEqual(self.runner.recorded_inner_seconds(envelope), 1.5)
        self.assertEqual(envelope, before)
        zero = {"execution": {"startedAt": execution["startedAt"],
                              "finishedAt": execution["startedAt"]}}
        self.assertEqual(self.runner.recorded_inner_seconds(zero), 0.0)

    def test_recorded_inner_seconds_rejects_missing_invalid_naive_and_reverse_times(self):
        good = {"execution": {"startedAt": "2026-01-01T00:00:00+00:00",
                              "finishedAt": "2026-01-01T00:00:01+00:00"}}
        invalid = [{}, {"execution": {}}, {"execution": None}]
        for field in ("startedAt", "finishedAt"):
            for value in (None, 1, "not a timestamp", "2026-01-01T00:00:00"):
                changed = copy.deepcopy(good)
                changed["execution"][field] = value
                invalid.append(changed)
        invalid.append({"execution": {"startedAt": "2026-01-01T00:00:02Z",
                                      "finishedAt": "2026-01-01T00:00:01Z"}})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises((core.EvidenceError, ValueError)):
                self.runner.recorded_inner_seconds(value)

    def test_existing_output_is_not_overwritten_or_used(self):
        self.output.mkdir()
        marker = self.output / "keep.bin"
        marker.write_bytes(b"preserve\x00all bytes\xff\n")
        before = marker.read_bytes()
        with patch("subprocess.run", side_effect=AssertionError("configuration launched a process")), \
             patch("subprocess.Popen", side_effect=AssertionError("configuration launched a process")):
            with self.assertRaises(core.EvidenceError):
                self.run_report()
        self.assertEqual(marker.read_bytes(), before)
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_output_must_be_outside_project_and_supplied_dependency(self):
        dependency = self.home / "dependency"
        dependency.mkdir()
        source = dependency / "src" / "Function" / "Base.agda"
        source.parent.mkdir(parents=True)
        source.write_text("module Function.Base where\n", encoding="utf-8")
        before = source_bytes(dependency)
        for output, options in ((ROOT / "must-not-create-conformance-report", {}),
                                (dependency / "must-not-create-report",
                                 {"profile": "stdlib-function", "dependency_root": dependency})):
            with self.subTest(output=output), \
                 patch("subprocess.run", side_effect=AssertionError("unsafe output launched a process")), \
                 patch("subprocess.Popen", side_effect=AssertionError("unsafe output launched a process")):
                with self.assertRaises(core.EvidenceError):
                    self.run_report(output=output, **options)
            self.assertFalse(output.exists())
        self.assertEqual(source_bytes(dependency), before)

    def test_unknown_profile_fails_before_filesystem_or_compiler_access(self):
        with patch.object(Path, "resolve", side_effect=AssertionError("profile probed filesystem")), \
             patch("subprocess.run", side_effect=AssertionError("profile launched a process")), \
             patch("subprocess.Popen", side_effect=AssertionError("profile launched a process")):
            with self.assertRaises(core.EvidenceError):
                self.run_report(profile="unknown-native-profile")
        self.assertFalse(self.output.exists())

    def test_dependency_is_required_only_for_stdlib_profile(self):
        dependency = self.home / "dependency"
        dependency.mkdir()
        for options in ({"profile": "stdlib-function"},
                        {"profile": "builtin", "dependency_root": dependency}):
            with self.subTest(options=options), \
                 patch("subprocess.run", side_effect=AssertionError("invalid dependency launched a process")), \
                 patch("subprocess.Popen", side_effect=AssertionError("invalid dependency launched a process")):
                with self.assertRaises(core.EvidenceError):
                    self.run_report(**options)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(dependency.iterdir()), [])

    def test_timeout_is_a_non_boolean_integer_in_one_to_three_hundred(self):
        for value in (0, -1, 301, True, False, 1.0, 20.5, "20", None):
            with self.subTest(timeout=value), \
                 patch("subprocess.run", side_effect=AssertionError("invalid timeout launched a process")), \
                 patch("subprocess.Popen", side_effect=AssertionError("invalid timeout launched a process")):
                with self.assertRaises(core.EvidenceError):
                    self.run_report(timeout_seconds=value)
            self.assertFalse(self.output.exists())
        for value in (1, 300):
            output = self.home / f"timeout-{value}"
            report = self.run_report(output=output, timeout_seconds=value)
            self.assert_failed_report(report, output)
            self.assertEqual(report["nativeTimeoutSeconds"], value)

    def test_expected_version_requires_exact_numeric_version_configuration(self):
        for value in ("", "v2.6.3", "Agda version 2.6.3", "2.6.3-dev", " 2.6.3", None, True):
            with self.subTest(version=value), \
                 patch("subprocess.run", side_effect=AssertionError("invalid version launched a process")), \
                 patch("subprocess.Popen", side_effect=AssertionError("invalid version launched a process")):
                with self.assertRaises(core.EvidenceError):
                    self.run_report(expected_version=value)
            self.assertFalse(self.output.exists())

    def test_missing_compiler_retains_failed_report_and_all_mandatory_cases(self):
        report = self.run_report()
        cases = self.assert_failed_report(report)
        version_case = next(case for case in cases if case["id"] == "compiler-version")
        self.assertEqual(version_case["status"], "failed")
        self.assertEqual(report["profile"], "builtin")
        self.assertEqual(report["expectedVersion"], "2.6.3")
        self.assertEqual(report["nativeTimeoutSeconds"], 20)
        self.assertEqual(report["records"], {})

    def test_same_version_prefix_with_different_patch_is_not_accepted(self):
        # Only the version subprocess is simulated, never a native typed result.
        response = subprocess.CompletedProcess([sys.executable, "--version"], 0,
                                               "Agda version 2.6.30\n", "")
        with patch("shutil.which", return_value=sys.executable), \
             patch("subprocess.run", return_value=response) as version_probe:
            report = self.run_report(agda_binary=sys.executable, expected_version="2.6.3")
        cases = self.assert_failed_report(report)
        self.assertEqual(next(case for case in cases if case["id"] == "compiler-version")["status"], "failed")
        self.assertEqual(report["actualVersion"], "2.6.30")
        self.assertEqual(report["records"], {})
        calls = [call.args[0] for call in version_probe.call_args_list]
        self.assertEqual(sum("--version" in argv for argv in calls), 1)
        self.assertFalse(any("--interaction-json" in argv for argv in calls))

    def test_cli_requires_explicit_compiler_version_output_and_retains_missing_failure(self):
        for arguments in ((), ("--agda-bin", "absent"),
                          ("--expected-version", "2.6.3", "--output", self.output)):
            with self.subTest(arguments=arguments):
                completed = self.cli(*arguments)
                self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(self.output.exists())
        completed = self.cli("--agda-bin", "agda-conformance-intentionally-absent",
                             "--expected-version", "2.6.3", "--output", self.output)
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assert_failed_report(saved_report(self.output))

    def test_runner_contains_no_network_provisioning_or_warning_suppression(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("git clone", script)
        self.assertNotIn("requests.get", script)
        self.assertNotIn("urlretrieve", script)
        self.assertNotIn("noUnsupportedIndexedMatch", script)
        self.assertIn("--no-libraries", script)
        self.assertIn("--ignore-interfaces", script)
        self.assertIn("--safe", script)
        self.assertIn("monotonic", script)
        # Simulate only a successful version probe and a failing compile gate.
        # No interaction record, typed result, or proof is manufactured here.
        version = subprocess.CompletedProcess([sys.executable, "--version"], 0,
                                              "Agda version 2.6.3\n", "")
        with patch("shutil.which", return_value=sys.executable), \
             patch("subprocess.run", return_value=version), \
             patch.object(self.runner, "capture_bundle", side_effect=core.EvidenceError("compile gate failed")):
            report = self.run_report(agda_binary=sys.executable)
        cases = self.assert_failed_report(report)
        self.assertEqual(cases[0]["status"], "passed")
        self.assertEqual(cases[1]["status"], "failed")
        self.assertTrue(all(case["status"] == "not-run" for case in cases[2:]))
        self.assertEqual(report["records"], {})

    def test_cli_real_version_mismatch_exits_nonzero_with_retained_failure(self):
        binary = shutil.which("agda") or "agda-conformance-intentionally-absent"
        completed = self.cli("--agda-bin", binary,
                             "--expected-version", "99.99.99", "--output", self.output)
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = saved_report(self.output)
        cases = self.assert_failed_report(report)
        self.assertEqual(next(case for case in cases if case["id"] == "compiler-version")["status"], "failed")
        self.assertNotEqual(report["actualVersion"], "99.99.99")
        self.assertEqual(report["records"], {})

    @unittest.skipUnless(os.name == "posix" and shutil.which("agda"),
                         "real native conformance requires POSIX and an installed Agda compiler")
    def test_full_builtin_native_run_and_offline_v1_evidence(self):
        binary = shutil.which("agda")
        probe = subprocess.run([binary, "--version"], capture_output=True, text=True,
                               timeout=20, check=True)
        match = re.fullmatch(r"Agda version ([0-9]+(?:\.[0-9]+)+)", probe.stdout.strip())
        self.assertIsNotNone(match, probe.stdout)
        expected = match.group(1)
        before = source_bytes(ROOT / "examples")
        report = self.run_report(agda_binary=binary, expected_version=expected, timeout_seconds=20)
        self.assertEqual(report["format"], REPORT_FORMAT)
        self.assertEqual(report["status"], "passed", json.dumps(report, ensure_ascii=False, indent=2))
        self.assertEqual(report, saved_report(self.output))
        self.assertEqual(report["profile"], "builtin")
        self.assertEqual(report["expectedVersion"], expected)
        self.assertEqual(report["actualVersion"], expected)
        self.assertEqual(report["nativeTimeoutSeconds"], 20)
        self.assertIs(report["originalSourcesUnchanged"], True)
        self.assertEqual(source_bytes(ROOT / "examples"), before)
        for name in ("client", "dependency", "catalog-source", "plain-client"):
            self.assertEqual(list((self.output / name).rglob("*.agdai")), [])
        self.assertEqual([case["id"] for case in report["cases"]], list(self.runner.REQUIRED_CASES))
        self.assertTrue(all(case["status"] == "passed" for case in report["cases"]))
        self.assertEqual(self.runner.REQUIRED_CASES, tuple(case["id"] for case in report["cases"]))
        self.assertTrue(report["timings"])
        roles = set()
        recorded_spans = []
        for timing in report["timings"]:
            roles.add(timing["role"])
            self.assertTrue(timing["label"])
            self.assertIn(timing["caseId"], self.runner.REQUIRED_CASES)
            self.assertTrue(math.isfinite(timing["elapsedSeconds"]))
            self.assertGreaterEqual(timing["elapsedSeconds"], 0)
            if "innerExecutionSeconds" in timing:
                self.assertEqual(timing["nativeTimeoutSeconds"], 20)
                self.assertTrue(math.isfinite(timing["innerExecutionSeconds"]))
                self.assertGreaterEqual(timing["innerExecutionSeconds"], 0)
                recorded_spans.append(timing["innerExecutionSeconds"])
        self.assertTrue({"case", "host-call", "export"} <= roles)
        self.assertIn("not compiler CPU", report["isolation"]["timingMeaning"])
        # UTC artifact spans and host monotonic spans have different clocks;
        # deliberately assert no strict inequality, CPU time, SLA or 20s total.
        records = report["records"]
        self.assertIsInstance(records, dict)
        self.assertTrue(records)
        native = []
        # Both subprocess APIs are blocked only now: all native work is complete.
        with patch("subprocess.run", side_effect=AssertionError("offline validation launched a process")), \
             patch("subprocess.Popen", side_effect=AssertionError("offline validation launched a process")):
            for metadata in report["bundles"].values():
                manifest_path = self.output / metadata["path"]
                self.assertTrue(manifest_path.resolve().is_relative_to(self.output.resolve()))
                manifest, components = core.load_verified_bundle(manifest_path.parent)
                self.assertEqual(metadata["id"], manifest["bundleId"])
                self.assertEqual(metadata["nativeStatus"], components["attestation.json"]["outcome"]["status"])
            for name, metadata in records.items():
                with self.subTest(record=name):
                    relative = Path(metadata["path"])
                    self.assertFalse(relative.is_absolute())
                    self.assertNotIn("..", relative.parts)
                    path = self.output / relative
                    self.assertTrue(path.resolve().is_relative_to(self.output.resolve()))
                    self.assertIsInstance(metadata["id"], str)
                    self.assertTrue(metadata["kind"])
                    if metadata["kind"] == "bundle":
                        manifest, components = core.load_verified_bundle(path)
                        self.assertEqual(metadata["id"], manifest["bundleId"])
                        self.assertEqual(components["attestation.json"]["outcome"]["status"], "passed")
                        continue
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if value["format"] == sources.SOURCE_FORMAT:
                        self.assertEqual(sources.load_source_observation(path), value)
                        self.assertEqual(sources.validate_source_observation(value), value)
                        inner = value["observation"]
                        if inner["format"] == goals.GOAL_FORMAT:
                            self.assertEqual(goals.validate_goal_observation(inner), inner)
                        else:
                            self.assertEqual(candidates.validate_candidate_observation(inner), inner)
                        if value["listing"] is not None:
                            self.assertEqual(inner["listing"], value["listing"]["observation"])
                        self.assertEqual(metadata["id"], value["sourceObservationId"])
                        summary = sources.source_summary(value)
                        self.assertEqual({field: summary[field] for field in report["dependencyPins"]},
                                         report["dependencyPins"])
                        self.assertEqual(summary["dependencyBundleId"],
                                         report["initialWorkspace"]["dependencyBundleId"])
                        native.append((name, value, inner, metadata))
                    elif value["format"] == goals.GOAL_FORMAT:
                        self.assertEqual(goals.load_goal_observation(path), value)
                        native.append((name, value, value, metadata))
                    elif value["format"] == candidates.CANDIDATE_FORMAT:
                        self.assertEqual(candidates.load_candidate_observation(path), value)
                        native.append((name, value, value, metadata))
                    else:
                        self.fail(f"unexpected native record format: {value['format']}")
        self.assertTrue(native)
        outcomes = {inner["result"]["status"] for _, _, inner, _ in native}
        self.assertTrue({"listed", "inspected", "elaborated", "query-error", "load-blocked", "load-error"} <= outcomes,
                        outcomes)
        by_id = {metadata["id"]: value for _, value, _, metadata in native}
        self.assertCountEqual(recorded_spans,
                              [self.runner.recorded_inner_seconds(value) for _, value, _, _ in native])
        exchanges = json.loads((self.output / "exchanges.json").read_text(encoding="utf-8"))
        failed_trials = [exchange["response"] for exchange in exchanges
                         if exchange["request"]["op"] == "candidate.check"
                         and (exchange["response"].get("result") or {}).get("outcome", {}).get("status") == "query-error"]
        self.assertGreaterEqual(len(failed_trials), 3)
        self.assertTrue(all(response["status"] == "ok" for response in failed_trials))
        for name, value, inner, metadata in native:
            with self.subTest(native=name):
                self.assertEqual(metadata["nativeStatus"], inner["result"]["status"])
                prior = value.get("listing")
                if prior is not None:
                    prior_id = prior.get("sourceObservationId", prior.get("observationId"))
                    self.assertEqual(prior, by_id[prior_id])
                if value["format"] != sources.SOURCE_FORMAT:
                    self.assertEqual(metadata["id"], value["observationId"])
                self.assertEqual(inner["execution"]["timeoutSeconds"], 20)
                self.assertIs(inner["query"]["safe"], True)
                argv = inner["execution"]["argv"]
                self.assertIn("--no-libraries", argv)
                self.assertIn("--ignore-interfaces", argv)
                self.assertIn("--safe", argv)
                self.assertFalse(any("noUnsupported" in flag or flag.startswith("--warning=") for flag in argv))
                seconds = self.runner.recorded_inner_seconds(value)
                self.assertTrue(math.isfinite(seconds))
                self.assertGreaterEqual(seconds, 0)
                if inner["result"]["status"] == "elaborated":
                    self.assertEqual(inner["result"]["assurance"], "contextual-elaboration-only")
                    self.assertIs(inner["result"]["postflightUnchanged"], True)
                if inner["result"]["status"] in {"load-blocked", "load-error"}:
                    infos = [message.get("info", {}) for phase in inner["transcript"]
                             for message in phase["responses"] if message.get("kind") == "DisplayInfo"]
                    if inner["result"]["status"] == "load-blocked":
                        self.assertTrue(any(info.get("kind") == "AllGoalsWarnings" and info.get("warnings")
                                            for info in infos))
                    else:
                        self.assertTrue(any(info.get("kind") == "Error" for info in infos))
                for phase in inner["transcript"]:
                    self.assertNotIn("Cmd_give", phase.get("request") or "")
                    self.assertNotIn("Cmd_refine", phase.get("request") or "")


if __name__ == "__main__":
    unittest.main()
