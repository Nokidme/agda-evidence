from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agda_evidence import core


class AggregateTests(unittest.TestCase):
    @staticmethod
    def make_project(temporary: Path, name: str, check_exit: int = 0) -> Path:
        project = temporary / name
        project.mkdir()
        (project / "sample.agda-lib").write_text("name: sample\ninclude: src\n", encoding="utf-8")
        (project / "src").mkdir()
        (project / "src" / "Main.agda").write_text("module Main where\n", encoding="utf-8")
        (project / "check.py").write_text(
            f"import sys\nprint('aggregate fixture')\nsys.exit({check_exit})\n", encoding="utf-8"
        )
        return project

    @staticmethod
    def capture(project: Path, output: Path, scope: str) -> None:
        core.capture_bundle(
            project,
            output,
            [sys.executable, "check.py"],
            agda_binary="agda-not-installed-for-aggregate-test",
            scope=scope,
        )

    @staticmethod
    def write_aggregate(path: Path, aggregate: dict[str, object]) -> None:
        (path / "aggregate.json").write_bytes(core.canonical_json_bytes(aggregate) + b"\n")

    def test_closed_aggregate_verifies_and_has_a_stable_lane_selection_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary, "project")
            typecheck = temporary / "typecheck"
            documentation = temporary / "documentation"
            self.capture(project, typecheck, "typecheck lane")
            self.capture(project, documentation, "documentation lane")

            first = core.create_aggregate(
                temporary / "first.aggregate",
                [("typecheck", typecheck), ("documentation", documentation)],
            )
            second = core.create_aggregate(
                temporary / "second.aggregate",
                [("documentation", documentation), ("typecheck", typecheck)],
            )
            self.assertEqual(first["aggregateId"], second["aggregateId"])
            self.assertEqual(core.verify_aggregate(temporary / "first.aggregate"), [])
            self.assertEqual(core.verify_aggregate(temporary / "second.aggregate"), [])
            self.assertEqual(
                {entry.name for entry in (temporary / "first.aggregate" / "lanes").iterdir()},
                {"typecheck", "documentation"},
            )
            self.assertEqual(
                {entry.name for entry in (temporary / "first.aggregate" / "lanes" / "typecheck").iterdir()},
                {"bundle.json", "snapshot.json", "resolution.json", "attestation.json", "diagnostics.json"},
            )

    def test_aggregate_rejects_children_from_different_source_trees_and_failed_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            first_project = self.make_project(temporary, "first-project")
            second_project = self.make_project(temporary, "second-project")
            (second_project / "src" / "Main.agda").write_text(
                "module Main where\npostulate changed : Set\n", encoding="utf-8"
            )
            first_bundle = temporary / "first"
            second_bundle = temporary / "second"
            self.capture(first_project, first_bundle, "first")
            self.capture(second_project, second_bundle, "second")
            with self.assertRaisesRegex(core.EvidenceError, "one identical sourceId"):
                core.create_aggregate(temporary / "different.aggregate", [("first", first_bundle), ("second", second_bundle)])

            failing_project = self.make_project(temporary, "failing-project", check_exit=9)
            failed_bundle = temporary / "failed"
            self.capture(failing_project, failed_bundle, "failed")
            with self.assertRaisesRegex(core.EvidenceError, "must report passed"):
                core.create_aggregate(temporary / "failed.aggregate", [("failed", failed_bundle)])

    def test_aggregate_verifier_rejects_relabelled_or_open_child_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary, "project")
            bundle = temporary / "bundle"
            self.capture(project, bundle, "typecheck")
            aggregate_path = temporary / "aggregate"
            core.create_aggregate(aggregate_path, [("typecheck", bundle)])

            aggregate = json.loads((aggregate_path / "aggregate.json").read_text(encoding="utf-8"))
            aggregate["lanes"]["typecheck"]["bundleId"] = "sha256:" + "0" * 64
            aggregate["aggregateId"] = core.derive_aggregate_id(aggregate)
            self.write_aggregate(aggregate_path, aggregate)
            self.assertIn(
                "aggregate lane typecheck does not match its included child bundle",
                core.verify_aggregate(aggregate_path),
            )

            # Restore a correct closed envelope, then introduce a file not named
            # by the child bundle's manifest.
            core.create_aggregate(temporary / "restored", [("typecheck", bundle)])
            (temporary / "restored" / "lanes" / "typecheck" / "extra.json").write_text("{}\n", encoding="utf-8")
            self.assertIn("not a closed child bundle", core.verify_aggregate(temporary / "restored")[0])

            core.create_aggregate(temporary / "root-extra", [("typecheck", bundle)])
            (temporary / "root-extra" / "notes.txt").write_text("not part of aggregate v1\n", encoding="utf-8")
            self.assertIn("aggregate directory is not closed", core.verify_aggregate(temporary / "root-extra")[0])

    def test_aggregate_rejects_duplicate_child_evidence_under_two_lane_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary, "project")
            bundle = temporary / "bundle"
            self.capture(project, bundle, "typecheck")
            with self.assertRaisesRegex(core.EvidenceError, "same bundle twice"):
                core.create_aggregate(temporary / "aggregate", [("first", bundle), ("second", bundle)])

            output_file = temporary / "not-a-directory"
            output_file.write_text("not a directory\n", encoding="utf-8")
            with self.assertRaisesRegex(core.EvidenceError, "not a directory"):
                core.create_aggregate(output_file, [("typecheck", bundle)])

            aggregate = temporary / "regular.aggregate"
            core.create_aggregate(aggregate, [("typecheck", bundle)])
            aggregate_link = temporary / "aggregate-link"
            aggregate_link.symlink_to(aggregate, target_is_directory=True)
            self.assertEqual(core.verify_aggregate(aggregate_link), ["aggregate directory must not be a symlink"])


if __name__ == "__main__":
    unittest.main()
