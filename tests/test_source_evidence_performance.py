"""Structural performance contracts, with no wall-clock or real-Agda dependency.

A disk load has one generic verification, followed by the stricter source-copy
profile. Two-pass observations must still read and hash fresh inputs twice.
The imported mixin supplies only fixtures/helpers, not another test class.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from agda_evidence import core, sources, source_research
from test_source_research import _WorkspaceFixtures


@unittest.skipUnless(os.name == "posix", "fake native pipe fixture requires POSIX")
class SourceEvidencePerformanceTests(_WorkspaceFixtures, unittest.TestCase):
    """Use genuine captures and a deliberately fake JSON protocol over pipes."""

    def evidence(self):
        return deepcopy({"manifest": self.manifest, "components": self.components})

    @staticmethod
    def rehash(evidence):
        """Repair generic bindings, leaving source-only policy violations intact."""
        manifest, payloads = evidence["manifest"], evidence["components"]
        snapshot, resolution = payloads["snapshot.json"], payloads["resolution.json"]
        attestation = payloads["attestation.json"]
        snapshot["sourceId"] = snapshot["sourceDigest"] = core.derive_source_id(snapshot)
        resolution["resolutionId"] = core.derive_resolution_id(resolution)
        attestation["subjects"]["sourceId"] = snapshot["sourceId"]
        attestation["subjects"]["resolutionId"] = resolution["resolutionId"]
        attestation["diagnosticsDigest"] = core.derive_diagnostics_digest(payloads["diagnostics.json"])
        attestation["attestationId"] = core.derive_attestation_id(attestation)
        manifest["components"] = {
            name: f"sha256:{core.digest_value(value)}" for name, value in payloads.items()
        }
        manifest["bundleId"] = f"sha256:{core.digest_value({'format': manifest['format'], 'components': manifest['components']})}"
        return evidence

    def write_evidence(self, evidence, *, preserve_metadata=False):
        objects = {"bundle.json": evidence["manifest"], **evidence["components"]}
        for name, value in objects.items():
            path = self.bundle / name
            before = path.stat()
            data = core.canonical_json_bytes(value) + b"\n"
            if preserve_metadata:
                self.assertEqual(len(data), before.st_size, name)
            path.write_bytes(data)
            if preserve_metadata:
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                after = path.stat()
                self.assertEqual((after.st_ino, after.st_size, after.st_mtime_ns),
                                 (before.st_ino, before.st_size, before.st_mtime_ns), name)

    def changed_valid_evidence(self):
        evidence = self.evidence()
        attestation = evidence["components"]["attestation.json"]
        self.assertEqual(attestation["scope"], "explicit-project-check")
        attestation["scope"] = "explicit-project-checK"
        self.rehash(evidence)
        self.assertEqual(core._verify_bundle_payloads(evidence["manifest"], evidence["components"]), [])
        self.assertNotEqual(evidence["manifest"]["bundleId"], self.manifest["bundleId"])
        return evidence

    def overwrite_component_same_metadata(self):
        path = self.bundle / "attestation.json"
        before = path.stat()
        original = path.read_bytes()
        self.assertIn(b"explicit-project-check", original)
        replacement = original.replace(b"explicit-project-check", b"explicit-project-checK", 1)
        self.assertEqual(len(replacement), len(original))
        self.assertNotEqual(replacement, original)
        path.write_bytes(replacement)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = path.stat()
        self.assertEqual((after.st_ino, after.st_size, after.st_mtime_ns),
                         (before.st_ino, before.st_size, before.st_mtime_ns))

    def test_disk_loader_verifies_once_and_returns_exact_checked_objects(self):
        with patch.object(core, "_read_json", wraps=core._read_json) as read, \
             patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as verify, \
             patch.object(sources, "_require_source_evidence_profile", wraps=sources._require_source_evidence_profile) as profile, \
             patch.object(sources, "_source_evidence", side_effect=AssertionError("disk evidence was generically rechecked")):
            manifest, payloads = sources._load_source_evidence(self.bundle)
        verify.assert_called_once()
        profile.assert_called_once()
        self.assertIs(manifest, verify.call_args.args[0])
        self.assertIs(payloads, verify.call_args.args[1])
        self.assertIs(manifest, profile.call_args.args[0])
        self.assertIs(payloads, profile.call_args.args[1])
        self.assertEqual(Counter(Path(call.args[0]).name for call in read.call_args_list),
                         Counter({"bundle.json": 1, **{name: 1 for name in manifest["components"]}}))
        self.assertNotIn("index-ref.json", payloads)
        self.assertEqual((manifest, payloads), (self.manifest, self.components))

    def test_workspace_initialization_uses_one_load_and_two_fresh_observation_loads(self):
        with patch.object(source_research, "_load_source_evidence", wraps=source_research._load_source_evidence) as load, \
             patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as verify, \
             patch.object(sources, "_source_evidence", side_effect=AssertionError("trusted disk payloads were reverified")):
            workspace = self.make_workspace()
        self.assertEqual(load.call_count, 3)
        self.assertEqual(verify.call_count, 3)
        self.assertEqual(workspace._expectedDependency["dependencyBundleId"], self.manifest["bundleId"])
        self.assertEqual(workspace._dependency_evidence, self.evidence())
        self.assertIsNot(workspace._dependency_evidence["manifest"], verify.call_args_list[0].args[0])

    def test_observe_keeps_two_generic_verifications_and_four_native_resolutions(self):
        loaded = []
        original_load = source_research._load_source_evidence

        def load(path):
            value = original_load(path)
            loaded.append(value)
            return value

        with patch.object(source_research, "_load_source_evidence", side_effect=load) as loader, \
             patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as verify, \
             patch.object(source_research, "build_resolution", wraps=source_research.build_resolution) as native, \
             patch.object(source_research, "build_snapshot", wraps=source_research.build_snapshot) as snapshot, \
             patch.object(sources, "_source_evidence", side_effect=AssertionError("duplicate generic verification")):
            subjects, client, observed = self.workspace._observe()
        self.assertEqual(loader.call_count, 2)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(native.call_count, 4)
        self.assertEqual(snapshot.call_count, 4)
        self.assertEqual([call.args[0] for call in native.call_args_list],
                         [self.project, self.library, self.project, self.library])
        for index, (manifest, payloads) in enumerate(loaded):
            self.assertIs(manifest, verify.call_args_list[index].args[0])
            self.assertIs(payloads, verify.call_args_list[index].args[1])
        self.assertIsNot(loaded[0][0], loaded[1][0])
        self.assertIsNot(loaded[0][1], loaded[1][1])
        self.assertIs(observed["evidence"]["manifest"], loaded[0][0])
        self.assertIs(observed["evidence"]["components"], loaded[0][1])
        self.assertEqual(subjects["clientSourceId"], client["sourceId"])
        self.assertIs(observed["dependencyMatchesPin"], True)

    def test_source_capture_loads_once_but_still_fully_validates_embedded_envelope(self):
        with patch.object(sources, "_load_source_evidence", wraps=sources._load_source_evidence) as load, \
             patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as disk_verify, \
             patch.object(sources, "_verify_bundle_payloads", wraps=sources._verify_bundle_payloads) as embedded_verify, \
             patch.object(sources, "_source_evidence", wraps=sources._source_evidence) as embedded:
            value = sources.observe_source_goals(self.project, "Main.agda", dependency_bundle=self.bundle,
                dependency_root=self.library, dependency_includes=("src",), agda_binary=str(self.binary), safe=True)
        load.assert_called_once_with(self.bundle)
        disk_verify.assert_called_once()
        embedded_verify.assert_called_once()
        embedded.assert_called_once()
        evidence = value["dependency"]["evidence"]
        self.assertIs(evidence["manifest"], disk_verify.call_args.args[0])
        self.assertIs(evidence["components"], disk_verify.call_args.args[1])
        self.assertIs(evidence["manifest"], embedded_verify.call_args.args[0])
        self.assertIs(evidence["components"], embedded_verify.call_args.args[1])
        self.assertEqual(value["observation"]["result"]["status"], "listed")

    def test_post_parse_disk_edit_does_not_replace_checked_objects_and_next_load_rejects(self):
        original_read = core._read_json

        def read_then_edit(path):
            value = original_read(path)
            if path.name == "attestation.json":
                self.overwrite_component_same_metadata()
            return value

        with patch.object(core, "_read_json", side_effect=read_then_edit) as read, \
             patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as verify:
            manifest, payloads = sources._load_source_evidence(self.bundle)
        verify.assert_called_once()
        self.assertIs(manifest, verify.call_args.args[0])
        self.assertIs(payloads, verify.call_args.args[1])
        self.assertEqual(payloads["attestation.json"], self.components["attestation.json"])
        self.assertEqual(Counter(Path(call.args[0]).name for call in read.call_args_list)["attestation.json"], 1)
        with self.assertRaisesRegex(core.EvidenceError, "digest mismatch"):
            sources._load_source_evidence(self.bundle)
        self.assertEqual(payloads["attestation.json"]["scope"], "explicit-project-check")

    def test_observe_rejects_same_length_component_edit_between_fresh_loads(self):
        original_load = source_research._load_source_evidence
        loaded = []

        def load_then_edit(path):
            value = original_load(path)
            loaded.append(value)
            if len(loaded) == 1:
                self.overwrite_component_same_metadata()
            return value

        with patch.object(source_research, "_load_source_evidence", side_effect=load_then_edit) as load, \
             patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as verify:
            with self.assertRaisesRegex(core.EvidenceError, "digest mismatch"):
                self.workspace._observe()
        self.assertEqual(load.call_count, 2)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(loaded[0][1]["attestation.json"]["scope"], "explicit-project-check")
        self.assertEqual(self.workspace._dependency_evidence, self.evidence())

    def test_observe_rejects_valid_rehashed_bundle_change_even_with_restored_metadata(self):
        replacement = self.changed_valid_evidence()
        original_load = source_research._load_source_evidence
        loaded = []

        def load_then_replace(path):
            value = original_load(path)
            loaded.append(value)
            if len(loaded) == 1:
                self.write_evidence(replacement, preserve_metadata=True)
            return value

        with patch.object(source_research, "_load_source_evidence", side_effect=load_then_replace) as load, \
             patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as verify, \
             patch.object(source_research, "build_resolution", wraps=source_research.build_resolution) as native:
            with self.assertRaisesRegex(sources.SourceEvidenceError, "Inputs changed during source observation"):
                self.workspace._observe()
        self.assertEqual(load.call_count, 2)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(native.call_count, 4)
        self.assertEqual(loaded[0][0]["bundleId"], self.manifest["bundleId"])
        self.assertEqual(loaded[1][0]["bundleId"], replacement["manifest"]["bundleId"])
        self.assertEqual(self.workspace._dependency_evidence, self.evidence())

    def test_status_reloads_same_path_and_reports_valid_bundle_as_not_matching_frozen_pin(self):
        replacement = self.changed_valid_evidence()
        with patch.object(source_research, "_load_source_evidence", wraps=source_research._load_source_evidence) as load, \
             patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as verify:
            before = self.status()
            self.assertEqual(load.call_count, 2)
            self.assertEqual(verify.call_count, 2)
            self.write_evidence(replacement, preserve_metadata=True)
            after = self.status()
        self.assertEqual(load.call_count, 4)
        self.assertEqual(verify.call_count, 4)
        self.assertIs(before["result"]["dependencyMatchesPin"], True)
        self.assertIs(after["result"]["dependencyMatchesPin"], False)
        self.assertEqual(after["result"]["dependencyPins"], before["result"]["dependencyPins"])
        self.assertEqual(after["workspace"]["dependencyBundleId"], replacement["manifest"]["bundleId"])
        for field in ("dependencySourceId", "dependencyResolutionId", "clientSourceId", "clientResolutionId"):
            self.assertEqual(after["workspace"][field], before["workspace"][field])
        self.assertNotEqual(after["currentRevision"], before["currentRevision"])
        self.assertEqual(self.workspace._dependency_evidence, self.evidence())

    def test_unknown_embedded_shape_and_component_names_are_checked_before_generic_verification(self):
        invalid = []
        extra_field = self.evidence()
        extra_field["trusted"] = True
        invalid.append(extra_field)
        missing = self.evidence()
        del missing["components"]["diagnostics.json"]
        invalid.append(missing)
        undeclared = self.evidence()
        undeclared["components"]["extra.json"] = {}
        invalid.append(undeclared)
        for name in ("", ".", "..", "bundle.json", "../escape.json", "dir/file.json", "dir\\file.json"):
            unsafe = self.evidence()
            unsafe["components"][name] = {}
            unsafe["manifest"]["components"][name] = f"sha256:{core.digest_value({})}"
            invalid.append(unsafe)
        with patch.object(sources, "_verify_bundle_payloads", side_effect=AssertionError("shape checks were skipped")) as verify:
            for evidence in invalid:
                with self.subTest(fields=list(evidence), names=list(evidence["components"])), self.assertRaises(core.EvidenceError):
                    sources._source_evidence(evidence)
        verify.assert_not_called()

    def test_previously_loaded_mutable_objects_are_not_trusted_by_embedded_or_public_validator(self):
        value = sources.observe_source_goals(self.project, "Main.agda", dependency_bundle=self.bundle,
            dependency_root=self.library, dependency_includes=("src",), agda_binary=str(self.binary), safe=True)
        original = deepcopy(value)
        evidence = value["dependency"]["evidence"]
        evidence["components"]["diagnostics.json"]["unverifiedMutation"] = True
        value["sourceObservationId"] = sources.source_observation_id(value)
        with patch("subprocess.Popen", side_effect=AssertionError("offline validation launched a compiler")), \
             patch.object(sources, "_verify_bundle_payloads", wraps=sources._verify_bundle_payloads) as verify:
            with self.assertRaisesRegex(core.EvidenceError, "invalid embedded dependency evidence.*digest mismatch"):
                sources._source_evidence(evidence)
            with self.assertRaisesRegex(sources.SourceEvidenceError, "invalid embedded dependency evidence.*digest mismatch"):
                sources.validate_source_observation(value)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(original["dependency"]["evidence"], self.evidence())
        self.assertEqual(self.workspace._dependency_evidence, self.evidence())

    def test_strict_profile_preserves_identifier_diagnostics_and_exact_subject_set(self):
        fields = [("manifest", "bundleId", "dependency bundleId"),
                  ("snapshot.json", "sourceId", "dependency sourceId"),
                  ("resolution.json", "resolutionId", "dependency resolutionId"),
                  ("attestation.json", "attestationId", "dependency attestationId"),
                  ("attestation.json", "diagnosticsDigest", "dependency diagnostics digest")]
        with patch.object(core, "_verify_bundle_payloads", side_effect=AssertionError("profile repeated generic verification")), \
             patch.object(sources, "_verify_bundle_payloads", side_effect=AssertionError("profile repeated embedded verification")):
            for filename, field, diagnostic in fields:
                evidence = self.evidence()
                target = evidence["manifest"] if filename == "manifest" else evidence["components"][filename]
                target[field] = "sha256:" + "A" * 64
                with self.subTest(field=field), self.assertRaisesRegex(core.EvidenceError, diagnostic):
                    sources._require_source_evidence_profile(evidence["manifest"], evidence["components"])
        evidence = self.evidence()
        evidence["components"]["attestation.json"]["subjects"]["extraId"] = self.manifest["bundleId"]
        self.rehash(evidence)
        self.assertEqual(core._verify_bundle_payloads(evidence["manifest"], evidence["components"]), [])
        with patch.object(sources, "_verify_bundle_payloads", wraps=sources._verify_bundle_payloads) as verify:
            with self.assertRaisesRegex(core.EvidenceError, "complete enhanced source/resolution subjects"):
                sources._source_evidence(evidence)
        verify.assert_called_once()

    def test_strict_native_profile_rejects_generically_valid_non_source_resolutions(self):
        for mutation, diagnostic in (("nix", "partial native resolution"),
                                     ("unavailable", "available native compiler"),
                                     ("missing compiler digest", "compiler digest"),
                                     ("library mismatch", "root library manifests"),
                                     ("nonpartial", "partial native resolution")):
            evidence = self.evidence()
            resolution = evidence["components"]["resolution.json"]
            if mutation == "nix":
                resolution["nix"] = {"adapter": core.NIX_PROBE_ADAPTER, "version": {}, "flake": {
                    "flakeNixSha256": "sha256:" + "1" * 64, "flakeLockSha256": "sha256:" + "2" * 64}}
            elif mutation == "unavailable":
                resolution["agda"] = {"requested": "fixture-unavailable", "available": False, "reason": "fixture"}
            elif mutation == "missing compiler digest":
                resolution["agda"].pop("binarySha256")
            elif mutation == "library mismatch":
                resolution["projectLibraryFiles"] = []
            else:
                resolution["resolutionStatus"] = "complete"
            self.rehash(evidence)
            with self.subTest(mutation=mutation):
                self.assertEqual(core._verify_bundle_payloads(evidence["manifest"], evidence["components"]), [])
                with patch.object(core, "_verify_bundle_payloads", side_effect=AssertionError("profile reverified generic bindings")):
                    with self.assertRaisesRegex(core.EvidenceError, diagnostic):
                        sources._require_source_evidence_profile(evidence["manifest"], evidence["components"])
                self.write_evidence(evidence)
                with patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as verify:
                    with self.assertRaisesRegex(core.EvidenceError, diagnostic):
                        sources._load_source_evidence(self.bundle)
                verify.assert_called_once()

    def test_strict_snapshot_profile_rejects_rehashed_noncanonical_or_unsafe_records(self):
        for mutation, diagnostic in (("ordering", "exact and canonically ordered"),
                                     ("extra record field", "exact and canonically ordered"),
                                     ("parent path", "unsafe source path"),
                                     ("control path", "unsafe source path"),
                                     ("tree algorithm", "unsupported format or tree algorithm")):
            evidence = self.evidence()
            snapshot = evidence["components"]["snapshot.json"]
            if mutation == "ordering":
                snapshot["files"].reverse()
            elif mutation == "extra record field":
                snapshot["files"][0]["unverified"] = True
            elif mutation in {"parent path", "control path"}:
                record = next(item for item in snapshot["files"] if item["path"] == "src/Library.agda")
                record["path"] = "src/../Library.agda" if mutation == "parent path" else "src/Library\n.agda"
                snapshot["files"].sort(key=lambda item: item["path"])
            else:
                snapshot["treeAlgorithm"] = "fixture-other-tree"
            self.rehash(evidence)
            with self.subTest(mutation=mutation):
                self.assertEqual(core._verify_bundle_payloads(evidence["manifest"], evidence["components"]), [])
                with patch.object(core, "_verify_bundle_payloads", side_effect=AssertionError("profile reverified generic bindings")):
                    with self.assertRaisesRegex(core.EvidenceError, diagnostic):
                        sources._require_source_evidence_profile(evidence["manifest"], evidence["components"])
                self.write_evidence(evidence)
                with patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as verify:
                    with self.assertRaisesRegex(core.EvidenceError, diagnostic):
                        sources._load_source_evidence(self.bundle)
                verify.assert_called_once()

    def test_failed_explicit_attestation_remains_acceptable_source_evidence(self):
        bundle = self.second_bundle(failed=True)
        with patch.object(core, "_verify_bundle_payloads", wraps=core._verify_bundle_payloads) as verify:
            manifest, payloads = sources._load_source_evidence(bundle)
        verify.assert_called_once()
        self.assertNotEqual(payloads["attestation.json"]["outcome"]["status"], "passed")
        self.assertNotIn("index-ref.json", payloads)
        with patch.object(core, "_verify_bundle_payloads", side_effect=AssertionError("profile repeated generic verification")), \
             patch.object(sources, "_verify_bundle_payloads", side_effect=AssertionError("profile repeated embedded verification")):
            sources._require_source_evidence_profile(manifest, payloads)
        workspace = self.make_workspace(dependency_bundle=bundle)
        self.assertIs(self.status(workspace=workspace)["result"]["dependencyMatchesPin"], True)
        self.assertEqual(workspace._dependency_evidence["components"]["attestation.json"], payloads["attestation.json"])


if __name__ == "__main__":
    unittest.main()
