from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from agda_evidence import core


class BundleLoadingTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> Path:
        project = root / "project"
        project.mkdir()
        (project / "Main.agda").write_text("module Main where\nvalue : Set\n", encoding="utf-8")
        index = root / "index.json"
        core.write_declaration_index(index, core.build_declaration_index(project))
        bundle = root / "bundle"
        core.capture_bundle(project, bundle, [sys.executable, "-c", "print('fixture')"],
                            agda_binary="agda-unavailable-test", index_reference=index)
        return bundle

    @staticmethod
    def rehash_component(bundle: Path, name: str, payload: object) -> None:
        (bundle / name).write_bytes(core.canonical_json_bytes(payload) + b"\n")
        manifest_path = bundle / "bundle.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["components"][name] = f"sha256:{core.digest_value(payload)}"
        manifest["bundleId"] = f"sha256:{core.digest_value({'format': manifest['format'], 'components': manifest['components']})}"
        manifest_path.write_bytes(core.canonical_json_bytes(manifest) + b"\n")

    def test_loader_returns_same_payloads_it_verified_without_a_provenance_reread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.make_bundle(Path(directory))
            read_json = core._read_json
            reads: list[str] = []

            def read_and_replace(path: Path) -> object:
                reads.append(path.name)
                value = read_json(path)
                if path.name == "attestation.json":
                    path.write_text('{"scope":"unverified replacement"}\n', encoding="utf-8")
                return value

            with patch.object(core, "_read_json", side_effect=read_and_replace):
                manifest, payloads = core.load_verified_bundle(bundle)
            self.assertEqual(payloads["attestation.json"]["scope"], "explicit-project-check")
            self.assertEqual(set(reads), {"bundle.json", *manifest["components"]})
            self.assertEqual(len(reads), len(set(reads)))
            self.assertTrue(core.verify_bundle(bundle))

    def test_nonobject_manifest_and_ambiguous_or_invalid_json_fail_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            for text in ('[]', '{"format":1,"format":2}', '{"format":NaN}'):
                with self.subTest(text=text):
                    (bundle / "bundle.json").write_text(text, encoding="utf-8")
                    self.assertTrue(core.verify_bundle(bundle))
                    with self.assertRaises(core.EvidenceError):
                        core.load_verified_bundle(bundle)
            (bundle / "bundle.json").write_bytes(b"\xff")
            self.assertTrue(core.verify_bundle(bundle))

    def test_malformed_candidate_kind_is_a_validation_error_even_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.make_bundle(Path(directory))
            reference = json.loads((bundle / "index-ref.json").read_text())
            reference["index"]["entries"][0]["kind"] = []
            self.rehash_component(bundle, "index-ref.json", reference)
            problems = core.verify_bundle(bundle)
            self.assertTrue(any("supported lexical candidate kind" in item for item in problems))

    def test_discovery_rejects_symlinked_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.make_bundle(root)
            source = bundle / "index-ref.json"
            target = root / "saved-index-ref.json"
            source.rename(target)
            source.symlink_to(target)
            with self.assertRaisesRegex(core.EvidenceError, "symlinked component"):
                core.declaration_index_from_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
