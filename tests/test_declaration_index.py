from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agda_evidence import core


class DeclarationIndexTests(unittest.TestCase):
    def make_project(self, temporary: Path, name: str = "project") -> Path:
        project = temporary / name
        project.mkdir()
        (project / "sample.agda-lib").write_text("name: sample\ninclude: src\n", encoding="utf-8")
        source = project / "src"
        source.mkdir()
        (source / "Alpha.agda").write_text(
            "module Demo.Alpha where\n"
            "\n"
            "data Thing : Set where\n"
            "\n"
            "record Holder : Set where\n"
            "\n"
            "postulate axiom : Set\n"
            "primitive primThing : Set\n"
            "value : Set\n"
            "  indented : Set\n"
            "\n"
            "-- ignored : Set\n",
            encoding="utf-8",
        )
        (source / "Literate.lagda.md").write_text(
            "# Literate source\n"
            "\n"
            "```agda\n"
            "module Demo.Literate where\n"
            "data MarkdownThing : Set where\n"
            "markdownValue : Set\n"
            "```\n"
            "\n"
            "outside : Set\n",
            encoding="utf-8",
        )
        (project / "check.py").write_text("print('checked')\n", encoding="utf-8")
        return project

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

    @staticmethod
    def capture_times() -> list[str]:
        return [
            "2026-10-30T20:00:00Z",
            "2026-10-30T20:00:01Z",
            "2026-10-30T20:00:02Z",
            "2026-10-30T20:00:03Z",
            "2026-10-30T20:00:04Z",
        ]

    def capture(self, project: Path, output: Path, index_reference: Path | None = None) -> dict[str, object]:
        with patch("agda_evidence.core.utc_now", side_effect=self.capture_times()):
            return core.capture_bundle(
                project,
                output,
                [sys.executable, "check.py"],
                agda_binary="agda-not-installed-for-index-test",
                index_reference=index_reference,
            )

    def test_build_is_checkout_independent_and_scans_only_documented_lexical_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            first = self.make_project(temporary, "first")
            second = temporary / "second"
            shutil.copytree(first, second)

            first_index = core.build_declaration_index(first)
            second_index = core.build_declaration_index(second)
            self.assertEqual(first_index, second_index)
            self.assertEqual(first_index["sourceId"], core.build_snapshot(first)[0]["sourceId"])

            records = {(entry["qualifiedName"], entry["kind"]): entry for entry in first_index["entries"]}
            expected = {
                ("Demo.Alpha", "module"),
                ("Demo.Alpha.Thing", "data"),
                ("Demo.Alpha.Holder", "record"),
                ("Demo.Alpha.axiom", "postulate"),
                ("Demo.Alpha.primThing", "primitive"),
                ("Demo.Alpha.value", "signature"),
                ("Demo.Literate", "module"),
                ("Demo.Literate.MarkdownThing", "data"),
                ("Demo.Literate.markdownValue", "signature"),
            }
            self.assertEqual(set(records), expected)
            self.assertEqual(records[("Demo.Literate", "module")]["line"], 4)
            self.assertNotIn(("Demo.Alpha.indented", "signature"), records)
            self.assertNotIn(("outside", "signature"), records)

            signatures = core.query_declaration_index(first_index, prefix="Demo.Alpha", kinds=("signature",))
            self.assertEqual([entry["qualifiedName"] for entry in signatures], ["Demo.Alpha.value"])

    def test_capture_binds_index_without_changing_source_resolution_or_attestation_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            index_path = temporary / "project.index.json"
            index = core.build_declaration_index(project)
            core.write_declaration_index(index_path, index)
            unindexed = temporary / "unindexed"
            indexed = temporary / "indexed"
            unindexed_bundle = self.capture(project, unindexed)
            indexed_bundle = self.capture(project, indexed, index_path)

            for component_name, field in (
                ("snapshot.json", "sourceId"),
                ("resolution.json", "resolutionId"),
                ("attestation.json", "attestationId"),
            ):
                self.assertEqual(
                    self.component(unindexed, component_name)[field],
                    self.component(indexed, component_name)[field],
                )
            self.assertNotEqual(unindexed_bundle["bundleId"], indexed_bundle["bundleId"])
            self.assertEqual(core.verify_bundle(indexed), [])
            self.assertEqual(core.declaration_index_from_bundle(indexed), index)
            queried = core.query_declaration_index(core.declaration_index_from_bundle(indexed), exact="Demo.Literate.markdownValue")
            self.assertEqual(len(queried), 1)
            self.assertEqual(queried[0]["line"], 6)

    def test_capture_rejects_stale_or_noncanonical_indexes_before_running_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            index_path = temporary / "project.index.json"
            index = core.build_declaration_index(project)
            core.write_declaration_index(index_path, index)
            (project / "src" / "Alpha.agda").write_text("module Demo.Changed where\n", encoding="utf-8")
            output = temporary / "stale-bundle"
            with self.assertRaisesRegex(core.EvidenceError, "sourceId does not match"):
                core.capture_bundle(
                    project,
                    output,
                    [sys.executable, "check.py"],
                    agda_binary="agda-not-installed-for-index-test",
                    index_reference=index_path,
                )
            self.assertFalse(output.exists())

            fresh_index = core.build_declaration_index(project)
            fresh_index["entries"][0]["qualifiedName"] = "Forged.Name"
            fresh_index["indexId"] = core.derive_declaration_index_id(fresh_index)
            forged_path = temporary / "forged.index.json"
            core.write_declaration_index(forged_path, fresh_index)
            with self.assertRaisesRegex(core.EvidenceError, "does not match the current project's lexical source scan"):
                core.capture_bundle(
                    project,
                    temporary / "forged-bundle",
                    [sys.executable, "check.py"],
                    agda_binary="agda-not-installed-for-index-test",
                    index_reference=forged_path,
                )

    def test_verifier_rejects_snapshot_mismatched_index_after_component_and_manifest_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            index_path = temporary / "project.index.json"
            core.write_declaration_index(index_path, core.build_declaration_index(project))
            bundle = temporary / "bundle"
            self.capture(project, bundle, index_path)

            reference = self.component(bundle, "index-ref.json")
            reference["index"]["entries"][0]["sourceSha256"] = "sha256:" + "0" * 64
            reference["index"]["indexId"] = core.derive_declaration_index_id(reference["index"])
            self.write_component(bundle, "index-ref.json", reference)
            self.refresh_manifest(bundle)
            self.assertIn(
                "declaration index entry does not match snapshot source digest",
                core.verify_bundle(bundle)[0],
            )

    def test_verifier_keeps_legacy_opaque_index_reference_byte_integrity_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            project = self.make_project(temporary)
            bundle = temporary / "bundle"
            self.capture(project, bundle)
            legacy = {
                "format": core.INDEX_REFERENCE_FORMAT,
                "sourcePathReference": "path-sha256:" + "0" * 64,
                "inputSha256": "sha256:" + "1" * 64,
                "content": {"external": "legacy metadata"},
            }
            self.write_component(bundle, "index-ref.json", legacy)
            manifest = self.component(bundle, "bundle.json")
            manifest["components"]["index-ref.json"] = f"sha256:{core.digest_value(legacy)}"
            identity = {"format": core.BUNDLE_FORMAT, "components": manifest["components"]}
            manifest["bundleId"] = f"sha256:{core.digest_value(identity)}"
            self.write_component(bundle, "bundle.json", manifest)
            self.assertEqual(core.verify_bundle(bundle), [])
            with self.assertRaisesRegex(core.EvidenceError, "legacy opaque"):
                core.declaration_index_from_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
