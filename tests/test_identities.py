from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from agda_evidence import core


class EvidenceIdentityTests(unittest.TestCase):
    def make_project(self, temporary: Path) -> Path:
        project = temporary / "sample-project"
        project.mkdir()
        (project / "sample.agda-lib").write_text(
            "name: sample\ninclude: src\ndepend: standard-library\nflags: --safe\n",
            encoding="utf-8",
        )
        (project / "src").mkdir()
        (project / "src" / "Main.agda").write_text("module Main where\n", encoding="utf-8")
        (project / "check.py").write_text("print('sample check')\n", encoding="utf-8")
        return project

    @staticmethod
    def capture_times(minute: int) -> list[str]:
        return [
            f"2026-10-30T12:{minute:02d}:00Z",
            f"2026-10-30T12:{minute:02d}:01Z",
            f"2026-10-30T12:{minute:02d}:02Z",
            f"2026-10-30T12:{minute:02d}:03Z",
            f"2026-10-30T12:{minute:02d}:04Z",
        ]

    def capture(self, project: Path, output: Path, minute: int) -> dict[str, object]:
        with patch("agda_evidence.core.utc_now", side_effect=self.capture_times(minute)):
            return core.capture_bundle(
                project,
                output,
                [sys.executable, "check.py"],
                agda_binary="agda-not-installed-for-test",
            )

    @staticmethod
    def component(bundle: Path, name: str) -> dict[str, object]:
        return json.loads((bundle / name).read_text(encoding="utf-8"))

    @staticmethod
    def write_component(bundle: Path, name: str, payload: dict[str, object]) -> None:
        (bundle / name).write_bytes(core.canonical_json_bytes(payload) + b"\n")

    def refresh_manifest(self, bundle: Path) -> None:
        manifest = self.component(bundle, "bundle.json")
        components = {
            name: f"sha256:{core.digest_value(self.component(bundle, name))}"
            for name in manifest["components"]
        }
        identity = {"format": core.BUNDLE_FORMAT, "components": components}
        manifest["components"] = components
        manifest["bundleId"] = f"sha256:{core.digest_value(identity)}"
        self.write_component(bundle, "bundle.json", manifest)

    def test_same_source_and_resolution_have_stable_ids_across_capture_times(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            first_directory = temporary / "first"
            second_directory = temporary / "second"
            first_bundle = self.capture(project, first_directory, minute=0)
            second_bundle = self.capture(project, second_directory, minute=1)

            first_snapshot = self.component(first_directory, "snapshot.json")
            second_snapshot = self.component(second_directory, "snapshot.json")
            first_resolution = self.component(first_directory, "resolution.json")
            second_resolution = self.component(second_directory, "resolution.json")
            first_attestation = self.component(first_directory, "attestation.json")
            second_attestation = self.component(second_directory, "attestation.json")

            self.assertEqual(first_snapshot["sourceDigest"], first_snapshot["sourceId"])
            self.assertEqual(first_snapshot["sourceId"], second_snapshot["sourceId"])
            self.assertEqual(first_resolution["resolutionId"], second_resolution["resolutionId"])
            self.assertEqual(first_attestation["diagnosticsDigest"], second_attestation["diagnosticsDigest"])
            self.assertNotEqual(first_attestation["attestationId"], second_attestation["attestationId"])
            self.assertNotEqual(first_bundle["bundleId"], second_bundle["bundleId"])
            self.assertEqual(core.verify_bundle(first_directory), [])
            self.assertEqual(core.verify_bundle(second_directory), [])

    def test_source_change_changes_source_and_attestation_but_not_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            first_directory = temporary / "first"
            second_directory = temporary / "second"
            self.capture(project, first_directory, minute=0)
            (project / "src" / "Main.agda").write_text("module Main where\npostulate X : Set\n", encoding="utf-8")
            self.capture(project, second_directory, minute=1)

            first_snapshot = self.component(first_directory, "snapshot.json")
            second_snapshot = self.component(second_directory, "snapshot.json")
            first_resolution = self.component(first_directory, "resolution.json")
            second_resolution = self.component(second_directory, "resolution.json")
            first_attestation = self.component(first_directory, "attestation.json")
            second_attestation = self.component(second_directory, "attestation.json")

            self.assertNotEqual(first_snapshot["sourceId"], second_snapshot["sourceId"])
            self.assertEqual(first_resolution["resolutionId"], second_resolution["resolutionId"])
            self.assertNotEqual(first_attestation["attestationId"], second_attestation["attestationId"])

    def test_registry_change_changes_resolution_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            agda_directory = temporary / "agda-config"
            agda_directory.mkdir()
            registry = agda_directory / "libraries"
            first_directory = temporary / "first"
            second_directory = temporary / "second"
            with patch.dict(os.environ, {"AGDA_DIR": str(agda_directory)}, clear=False):
                registry.write_text("/example/first.agda-lib\n", encoding="utf-8")
                self.capture(project, first_directory, minute=0)
                registry.write_text("/example/second.agda-lib\n", encoding="utf-8")
                self.capture(project, second_directory, minute=1)

            first_snapshot = self.component(first_directory, "snapshot.json")
            second_snapshot = self.component(second_directory, "snapshot.json")
            first_resolution = self.component(first_directory, "resolution.json")
            second_resolution = self.component(second_directory, "resolution.json")
            self.assertEqual(first_snapshot["sourceId"], second_snapshot["sourceId"])
            self.assertNotEqual(first_resolution["resolutionId"], second_resolution["resolutionId"])

    def test_verifier_rejects_semantically_incorrect_source_id_after_rehashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            bundle = temporary / "bundle"
            self.capture(project, bundle, minute=0)
            snapshot = self.component(bundle, "snapshot.json")
            snapshot["sourceId"] = "sha256:" + "0" * 64
            self.write_component(bundle, "snapshot.json", snapshot)
            self.refresh_manifest(bundle)

            problems = core.verify_bundle(bundle)
            self.assertIn("snapshot.sourceId does not match the recorded file tree", problems)

    def test_verifier_accepts_a_complete_legacy_profile_but_rejects_a_partial_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            bundle = temporary / "bundle"
            self.capture(project, bundle, minute=0)
            snapshot = self.component(bundle, "snapshot.json")
            resolution = self.component(bundle, "resolution.json")
            attestation = self.component(bundle, "attestation.json")
            snapshot.pop("sourceId")
            resolution.pop("resolutionId")
            attestation.pop("subjects")
            attestation.pop("diagnosticsDigest")
            attestation.pop("attestationId")
            self.write_component(bundle, "snapshot.json", snapshot)
            self.write_component(bundle, "resolution.json", resolution)
            self.write_component(bundle, "attestation.json", attestation)
            self.refresh_manifest(bundle)
            self.assertEqual(core.verify_bundle(bundle), [])

            snapshot["sourceId"] = snapshot["sourceDigest"]
            self.write_component(bundle, "snapshot.json", snapshot)
            self.refresh_manifest(bundle)
            self.assertIn("partial enhanced identity profile", core.verify_bundle(bundle)[0])


if __name__ == "__main__":
    unittest.main()
