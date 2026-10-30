from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agda_evidence import core


class NixResolutionTests(unittest.TestCase):
    @staticmethod
    def write_executable(path: Path, body: str) -> None:
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def make_project(self, parent: Path, name: str, target_agda: Path, fake_bin: Path) -> Path:
        project = parent / name
        project.mkdir()
        (project / "flake.nix").write_text('{ description = "fixture"; }\n', encoding="utf-8")
        (project / "flake.lock").write_text('{"version":7,"root":"root","nodes":{"root":{"inputs":{}}}}\n', encoding="utf-8")
        (project / "fixture.agda-lib").write_text("name: fixture\ndepend: standard-library-2.3\ninclude: src\n", encoding="utf-8")
        (project / "src").mkdir()
        (project / "src" / "Fixture.agda").write_text("module Fixture where\n", encoding="utf-8")
        (project / "check.py").write_text("print('checked')\n", encoding="utf-8")
        agda_dir = project / ".agda"
        (agda_dir / "bin").mkdir(parents=True)
        (agda_dir / "libraries").write_text(
            f"/nix/store/patched-stdlib/standard-library.agda-lib\n{project}/fixture.agda-lib\n",
            encoding="utf-8",
        )
        (agda_dir / "defaults").write_text("standard-library\n", encoding="utf-8")
        self.write_executable(
            agda_dir / "bin" / "agda",
            f'#!/bin/sh\nexec "{target_agda}" "$@"\n',
        )
        return project

    def write_fake_nix(self, path: Path, system: str = "x86_64-linux") -> None:
        self.write_executable(
            path,
            "#!/bin/sh\n"
            "if [ \"${1:-}\" = \"--version\" ]; then\n"
            "  echo 'nix (Nix) 2.28.6'\n"
            "elif [ \"${1:-}\" = \"eval\" ]; then\n"
            f"  echo '{system}'\n"
            "else\n"
            "  exit 2\n"
            "fi\n",
        )

    def test_nix_probe_normalizes_checkout_specific_wrapper_and_registry_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            target_agda = fake_bin / "nix-store-agda"
            self.write_executable(
                target_agda,
                "#!/bin/sh\ncase \"${1:-}\" in\n  --version) echo 'Agda version 2.9.0-fixture' ;;\n  --print-agda-app-dir) echo \"${AGDA_DIR:?}\" ;;\n  *) exit 2 ;;\nesac\n",
            )
            self.write_fake_nix(fake_bin / "nix")
            first = self.make_project(temporary, "first-checkout", target_agda, fake_bin)
            second = self.make_project(temporary, "second-checkout", target_agda, fake_bin)

            with patch.dict(os.environ, {"PATH": f"{first / '.agda/bin'}:{fake_bin}", "AGDA_DIR": str(first / ".agda")}, clear=False):
                first_resolution = core.build_nix_resolution(first)
            with patch.dict(os.environ, {"PATH": f"{second / '.agda/bin'}:{fake_bin}", "AGDA_DIR": str(second / ".agda")}, clear=False):
                second_resolution = core.build_nix_resolution(second)

            self.assertEqual(first_resolution["resolutionId"], second_resolution["resolutionId"])
            self.assertEqual(first_resolution["agda"]["binarySha256"], f"sha256:{core.sha256_file(target_agda)}")
            self.assertEqual(first_resolution["agda"]["launcher"], "project-local-nix-wrapper-unwrapped")
            self.assertEqual(first_resolution["nix"]["adapter"], core.NIX_PROBE_ADAPTER)
            self.assertEqual(first_resolution["nix"]["system"]["stdout"], "x86_64-linux")
            self.assertIn("resolutionSha256", first_resolution["registry"]["registries"][0])

    def test_verified_resolution_handoff_is_bound_into_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            target_agda = fake_bin / "nix-store-agda"
            self.write_executable(target_agda, "#!/bin/sh\necho 'Agda version 2.9.0-fixture'\n")
            self.write_fake_nix(fake_bin / "nix")
            project = self.make_project(temporary, "project", target_agda, fake_bin)
            with patch.dict(os.environ, {"PATH": f"{project / '.agda/bin'}:{fake_bin}", "AGDA_DIR": str(project / ".agda")}, clear=False):
                resolution = core.build_nix_resolution(project)
            observation = temporary / "resolution.json"
            core.write_resolution_observation(observation, resolution)
            verified = core.load_resolution_observation(observation)

            # The generated Nix registry is not source input; the real staged Nix
            # command recreates it inside the disposable project copy.
            for child in sorted((project / ".agda").rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            (project / ".agda").rmdir()
            output = temporary / "bundle"
            core.capture_bundle(project, output, [sys.executable, "check.py"], resolution_observation=verified)
            self.assertEqual(core.verify_bundle(output), [])
            attestation = core._read_json(output / "attestation.json")
            self.assertEqual(attestation["subjects"]["resolutionId"], resolution["resolutionId"])

            (project / "flake.lock").write_text('{"changed":true}\n', encoding="utf-8")
            stale_output = temporary / "stale-bundle"
            with self.assertRaisesRegex(core.EvidenceError, "does not match flake.lock"):
                core.capture_bundle(project, stale_output, [sys.executable, "check.py"], resolution_observation=verified)
            self.assertFalse(stale_output.exists())

    def test_nix_system_changes_resolution_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            target_agda = fake_bin / "nix-store-agda"
            self.write_executable(target_agda, "#!/bin/sh\necho 'Agda version 2.9.0-fixture'\n")
            project = self.make_project(temporary, "project", target_agda, fake_bin)
            with patch.dict(os.environ, {"PATH": f"{project / '.agda/bin'}:{fake_bin}", "AGDA_DIR": str(project / ".agda")}, clear=False):
                self.write_fake_nix(fake_bin / "nix", "x86_64-linux")
                linux = core.build_nix_resolution(project)
                self.write_fake_nix(fake_bin / "nix", "aarch64-darwin")
                darwin = core.build_nix_resolution(project)
            self.assertNotEqual(linux["resolutionId"], darwin["resolutionId"])

    def test_resolution_handoff_rejects_a_stale_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = temporary / "project"
            project.mkdir()
            (project / "sample.agda-lib").write_text("name: sample\ninclude: src\n", encoding="utf-8")
            (project / "src").mkdir()
            resolution = core.build_resolution(project, "agda-not-installed-for-test")
            resolution["resolutionId"] = "sha256:" + "0" * 64
            observation = temporary / "resolution.json"
            observation.write_bytes(core.canonical_json_bytes(resolution) + b"\n")
            with self.assertRaisesRegex(core.EvidenceError, "does not match"):
                core.load_resolution_observation(observation)


if __name__ == "__main__":
    unittest.main()
