from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class EvidenceCliTests(unittest.TestCase):
    def make_project(self, temporary: Path, check_exit: int = 0) -> Path:
        project = temporary / "sample-project"
        project.mkdir()
        (project / "sample.agda-lib").write_text(
            "name: sample\ninclude: src\ndepend: standard-library\nflags: --safe\n",
            encoding="utf-8",
        )
        (project / "src").mkdir()
        (project / "src" / "Main.agda").write_text("module Main where\n", encoding="utf-8")
        (project / "check.py").write_text(
            f"import sys\nprint('sample check')\nsys.exit({check_exit})\n", encoding="utf-8"
        )
        return project

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "agda_evidence", *arguments],
            cwd=ROOT,
            env={"PYTHONPATH": str(SRC)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_capture_and_verify_passed_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            output = temporary / "bundle"
            result = self.run_cli(
                "capture",
                "--project-root", str(project),
                "--output", str(output),
                "--scope", "sample check",
                "--",
                sys.executable,
                "check.py",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            reported = json.loads(result.stdout)
            self.assertTrue(reported["bundleId"].startswith("sha256:"))
            self.assertEqual(reported["outcome"]["status"], "passed")

            bundle = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(bundle["format"], "agda-evidence/bundle-v1")
            snapshot = json.loads((output / "snapshot.json").read_text(encoding="utf-8"))
            self.assertIn("src/Main.agda", [item["path"] for item in snapshot["files"]])
            self.assertEqual(self.run_cli("verify", str(output)).returncode, 0)

    def test_failed_check_is_attested_without_losing_the_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary, check_exit=7)
            output = temporary / "bundle"
            result = self.run_cli(
                "capture", "--project-root", str(project), "--output", str(output), "--", sys.executable, "check.py"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            attestation = json.loads((output / "attestation.json").read_text(encoding="utf-8"))
            self.assertEqual(attestation["outcome"]["status"], "failed")
            self.assertEqual(attestation["outcome"]["exitCode"], 7)
            self.assertEqual(self.run_cli("verify", str(output)).returncode, 0)

    def test_verify_rejects_tampered_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            output = temporary / "bundle"
            captured = self.run_cli(
                "capture", "--project-root", str(project), "--output", str(output), "--", sys.executable, "check.py"
            )
            self.assertEqual(captured.returncode, 0, captured.stderr)
            (output / "snapshot.json").write_text("{}\n", encoding="utf-8")
            verified = self.run_cli("verify", str(output))
            self.assertEqual(verified.returncode, 1)
            self.assertIn("digest mismatch", verified.stderr)

    def test_capture_refuses_an_output_inside_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            result = self.run_cli(
                "capture",
                "--project-root", str(project),
                "--output", str(project / "bundle"),
                "--",
                sys.executable,
                "check.py",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("outside the project root", result.stderr)


if __name__ == "__main__":
    unittest.main()
