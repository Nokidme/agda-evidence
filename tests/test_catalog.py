from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agda_evidence import catalog, cli, core


class CatalogTests(unittest.TestCase):
    """Local discovery is source-bound lexical evidence, not an Agda environment."""

    @classmethod
    def setUpClass(cls) -> None:
        # Capture each independent source/resolution once; each test gets private
        # copies. Neither the fixtures nor their check command require Agda.
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.fixture_root = Path(temporary.name)
        cls.agda_binary = str(cls.fixture_root / "not-an-agda-executable")
        (cls.fixture_root / "empty-registry").mkdir()
        for name in ("alpha", "zeta"):
            project = cls.fixture_root / f"{name}-project"
            project.mkdir()
            (project / "sample.agda-lib").write_text(
                f"name: {name}\ninclude: src\n", encoding="utf-8"
            )
            (project / "src").mkdir()
            (project / "src" / "Shared.agda").write_text(
                f"-- independently indexed {name} source\n"
                "module Shared.API where\n"
                "record Z : Set where\n"
                "data A : Set where\n"
                "postulate axiom : Set\n"
                "value : Set\n",
                encoding="utf-8",
            )
            (project / "check.py").write_text(
                "import sys\nprint('catalog fixture')\nsys.exit(int(sys.argv[1]))\n",
                encoding="utf-8",
            )
            index = cls.fixture_root / f"{name}.index.json"
            # The lexical index is genuinely built before capture, not injected
            # into a synthetic bundle after the fact.
            core.write_declaration_index(index, core.build_declaration_index(project))
            cls.capture(project, cls.fixture_root / name, index)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "working"
        shutil.copytree(self.fixture_root, self.root)
        self.alpha = self.root / "alpha"
        self.zeta = self.root / "zeta"
        self.path = self.root / "config" / "catalog.json"

    @classmethod
    def capture(
        cls, project: Path, output: Path, index: Path | None,
        *, exit_code: int = 0, scope: str = "catalog fixture check",
    ) -> dict:
        with patch.dict(os.environ, {"AGDA_DIR": str(cls.fixture_root / "empty-registry")}):
            return core.capture_bundle(
                project, output, [sys.executable, "check.py", str(exit_code)],
                agda_binary=cls.agda_binary, index_reference=index, scope=scope,
            )

    @staticmethod
    def read_json(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def write_json(path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(core.canonical_json_bytes(value) + b"\n")

    def refresh_manifest(self, bundle: Path) -> None:
        """Rehash storage only, so semantic-invalid fixtures reach validation."""
        manifest = self.read_json(bundle / "bundle.json")
        manifest["components"] = {
            name: f"sha256:{core.digest_value(self.read_json(bundle / name))}"
            for name in manifest["components"]
        }
        identity = {"format": manifest["format"], "components": manifest["components"]}
        manifest["bundleId"] = f"sha256:{core.digest_value(identity)}"
        self.write_json(bundle / "bundle.json", manifest)

    def pins(self, bundle: Path) -> dict:
        return {
            "sourceId": self.read_json(bundle / "snapshot.json")["sourceId"],
            "resolutionId": self.read_json(bundle / "resolution.json")["resolutionId"],
        }

    def provenance(self, name: str, bundle: Path) -> dict:
        manifest = self.read_json(bundle / "bundle.json")
        attestation = self.read_json(bundle / "attestation.json")
        reference = self.read_json(bundle / "index-ref.json")
        return {
            "entry": name,
            "bundleId": manifest["bundleId"],
            **self.pins(bundle),
            "attestationId": attestation["attestationId"],
            "indexId": reference["index"]["indexId"],
            "scope": attestation["scope"],
            "command": attestation["command"],
            "outcome": attestation["outcome"],
        }

    def create_pair(self, path: Path | None = None) -> dict:
        # Intentionally pass reverse order; neither reference order nor the
        # scanner's physical line order should determine query order.
        return catalog.create_catalog(
            path or self.path, [("zeta", self.zeta), ("alpha", self.alpha)]
        )

    def copy_bundle(self, label: str) -> Path:
        return Path(shutil.copytree(self.zeta, self.root / label))

    @staticmethod
    def run_cli(*arguments: str) -> tuple[int, str, str]:
        # Exercise the real CLI dispatcher and its returned process exit code
        # without adding a subprocess to a read-only verification/query test.
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = cli.main(list(arguments))
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_cli_error(self, code: int, *arguments: str) -> str:
        actual, stdout, stderr = self.run_cli(*arguments)
        self.assertEqual(actual, code, stderr)
        self.assertEqual(stdout, "", "a failed catalog operation must not emit partial JSON")
        self.assertIn("agda-evidence:", stderr)
        self.assertNotIn("Traceback", stderr)
        return stderr

    def assert_invalid_bundle(self, bundle: Path, reason: str) -> None:
        output = self.root / "rejected" / "catalog.json"
        with self.assertRaisesRegex(catalog.CatalogValidationError, reason):
            catalog.create_catalog(output, [("bad", bundle)])
        self.assertFalse(output.exists())
        self.assertFalse(output.parent.exists(), "validation must precede writing")

        # Bypass create only to test reading an invalid reference. Keep alpha
        # valid and selected, with the invalid entry deliberately filtered out.
        value = {
            "format": catalog.CATALOG_FORMAT,
            "entries": {
                "alpha": {"bundle": os.path.relpath(self.alpha, self.path.parent),
                          "expected": self.pins(self.alpha)},
                "zeta": {"bundle": os.path.relpath(bundle, self.path.parent),
                         "expected": self.pins(self.zeta)},
            },
        }
        self.write_json(self.path, value)
        with self.assertRaisesRegex(catalog.CatalogValidationError, reason):
            catalog.verify_catalog(self.path)
        with self.assertRaisesRegex(catalog.CatalogValidationError, reason):
            catalog.query_catalog(self.path, exact="Shared.API.value", libraries=("alpha",))
        for command, filters in (("verify", ()), ("query", ("--library", "alpha"))):
            stderr = self.assert_cli_error(1, "catalog", command, str(self.path), *filters)
            self.assertRegex(stderr, reason)

    def test_create_and_verify_preserve_independent_colliding_provenance(self) -> None:
        value = self.create_pair()
        self.assertEqual(value["format"], catalog.CATALOG_FORMAT)
        self.assertEqual(list(value["entries"]), ["alpha", "zeta"])
        for name, bundle in (("alpha", self.alpha), ("zeta", self.zeta)):
            reference = value["entries"][name]
            self.assertEqual(set(reference), {"bundle", "expected"})
            self.assertFalse(Path(reference["bundle"]).is_absolute())
            self.assertEqual(reference["expected"], self.pins(bundle))
            self.assertEqual(set(reference["expected"]), {"sourceId", "resolutionId"})
            self.assertEqual(core.verify_bundle(bundle), [])
        for field in ("sourceId", "resolutionId"):
            self.assertNotEqual(self.pins(self.alpha)[field], self.pins(self.zeta)[field])

        # Capture has finished before installing these guards. Verification and
        # discovery must never invoke a checker, resolver, or other subprocess.
        with patch("subprocess.run", side_effect=AssertionError("unexpected subprocess")), \
             patch("subprocess.Popen", side_effect=AssertionError("unexpected process")):
            verified = catalog.verify_catalog(self.path)
            queried = catalog.query_catalog(self.path, exact="Shared.API.value")
        expected = [self.provenance("alpha", self.alpha), self.provenance("zeta", self.zeta)]
        self.assertEqual(verified, {"format": catalog.CATALOG_VERIFY_FORMAT, "entries": expected})
        self.assertEqual([entry["evidence"] for entry in queried["entries"]], expected)
        self.assertNotEqual(expected[0]["indexId"], expected[1]["indexId"])
        self.assertNotEqual(expected[0]["bundleId"], expected[1]["bundleId"])

    def test_query_filters_candidate_shape_and_deterministic_order(self) -> None:
        self.create_pair()
        result = catalog.query_catalog(self.path)
        self.assertEqual(set(result), {"format", "checkedEntries", "entries"})
        self.assertEqual(result["format"], catalog.CATALOG_QUERY_FORMAT)
        self.assertEqual(result["checkedEntries"], ["alpha", "zeta"])
        expected_heads = [
            ("Shared.API", "module"), ("Shared.API.A", "data"),
            ("Shared.API.Z", "record"), ("Shared.API.axiom", "postulate"),
            ("Shared.API.value", "signature"),
        ]
        self.assertEqual(
            [(entry["qualifiedName"], entry["kind"], entry["evidence"]["entry"])
             for entry in result["entries"]],
            [(name, kind, library) for name, kind in expected_heads for library in ("alpha", "zeta")],
        )
        for entry in result["entries"]:
            self.assertEqual(
                set(entry), {"qualifiedName", "kind", "path", "line", "sourceSha256", "evidence"}
            )
            bundle = self.root / entry["evidence"]["entry"]
            candidates = self.read_json(bundle / "index-ref.json")["index"]["entries"]
            self.assertIn({key: value for key, value in entry.items() if key != "evidence"}, candidates)
            self.assertEqual(entry["evidence"], self.provenance(entry["evidence"]["entry"], bundle))

        exact = catalog.query_catalog(self.path, exact="Shared.API.value")
        self.assertEqual(len(exact["entries"]), 2, "colliding names must not be deduplicated")
        filtered = catalog.query_catalog(
            self.path, prefix="Shared.API.", kinds=("signature", "data"), libraries=("zeta",)
        )
        self.assertEqual(filtered["checkedEntries"], ["alpha", "zeta"])
        self.assertEqual([entry["qualifiedName"] for entry in filtered["entries"]],
                         ["Shared.API.A", "Shared.API.value"])
        self.assertEqual({entry["evidence"]["entry"] for entry in filtered["entries"]}, {"zeta"})
        self.assertEqual(
            catalog.query_catalog(self.path, libraries=("zeta", "alpha"), kinds=("record", "module")),
            catalog.query_catalog(self.path, libraries=("alpha", "zeta"), kinds=("module", "record")),
        )
        code, stdout, stderr = self.run_cli(
            "catalog", "query", str(self.path), "--prefix", "Shared.API.",
            "--kind", "signature", "--kind", "data", "--library", "zeta",
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout), filtered)

    def test_zero_matches_and_invalid_filters_are_not_silent_success(self) -> None:
        self.create_pair()
        for filters in ({"exact": "Missing.name"}, {"prefix": "Missing."},
                        {"exact": "Shared.API.value", "kinds": ("record",)}):
            with self.subTest(filters=filters):
                result = catalog.query_catalog(self.path, **filters)
                self.assertEqual(result["entries"], [])
                self.assertEqual(result["checkedEntries"], ["alpha", "zeta"])
        code, stdout, stderr = self.run_cli("catalog", "query", str(self.path), "--exact", "Missing")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["entries"], [])
        with self.assertRaisesRegex(catalog.CatalogConfigError, "unknown catalog entries"):
            catalog.query_catalog(self.path, libraries=("missing",))
        self.assert_cli_error(2, "catalog", "query", str(self.path), "--library", "missing")
        with self.assertRaisesRegex(core.EvidenceError, "unsupported.*kinds"):
            catalog.query_catalog(self.path, kinds=("not-a-kind",))
        with self.assertRaisesRegex(core.EvidenceError, "at most one"):
            catalog.query_catalog(self.path, exact="Shared.API", prefix="Shared")

    def test_create_never_overwrites_existing_files_or_dangling_symlinks(self) -> None:
        self.create_pair()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(catalog.CatalogConfigError, "already exists"):
            self.create_pair()
        self.assert_cli_error(2, "catalog", "create", "--output", str(self.path),
                              "--entry", f"alpha={self.alpha}")
        self.assertEqual(self.path.read_bytes(), before)
        link = self.root / "dangling.json"
        link.symlink_to(self.root / "absent.json")
        with self.assertRaisesRegex(catalog.CatalogConfigError, "already exists"):
            catalog.create_catalog(link, [("alpha", self.alpha)])
        self.assertTrue(link.is_symlink())
        self.assertFalse(link.exists())

    def test_duplicate_names_and_bundle_aliases_are_refused(self) -> None:
        output = self.root / "new" / "catalog.json"
        with self.assertRaisesRegex(catalog.CatalogConfigError, "duplicate catalog entry name"):
            catalog.create_catalog(output, [("alpha", self.alpha), ("alpha", self.zeta)])
        self.assert_cli_error(2, "catalog", "create", "--output", str(output),
                              "--entry", f"alpha={self.alpha}", "--entry", f"alpha={self.zeta}")
        copied = self.copy_bundle("same-bundle-different-path")
        with self.assertRaisesRegex(catalog.CatalogValidationError, "alias the same bundleId"):
            catalog.create_catalog(output, [("one", self.zeta), ("two", copied)])
        self.assert_cli_error(1, "catalog", "create", "--output", str(output),
                              "--entry", f"one={self.zeta}", "--entry", f"two={copied}")
        self.assertFalse(output.parent.exists())

        value = self.create_pair()
        value["entries"]["alpha"] = deepcopy(value["entries"]["zeta"])
        self.write_json(self.path, value)
        with self.assertRaisesRegex(catalog.CatalogValidationError, "alias the same bundleId"):
            catalog.verify_catalog(self.path)
        self.assert_cli_error(1, "catalog", "query", str(self.path), "--library", "alpha")

    def test_catalog_relative_references_do_not_depend_on_the_working_directory(self) -> None:
        value = self.create_pair()
        expected = catalog.query_catalog(self.path, exact="Shared.API.value")
        elsewhere = self.root / "unrelated-cwd"
        elsewhere.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(elsewhere)
            relative_catalog = Path(os.path.relpath(self.path, elsewhere))
            self.assertEqual(catalog.query_catalog(relative_catalog, exact="Shared.API.value"), expected)
            self.assertEqual(len(catalog.verify_catalog(relative_catalog)["entries"]), 2)
            code, stdout, stderr = self.run_cli("catalog", "verify", str(relative_catalog))
            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout), catalog.verify_catalog(self.path))
            other = self.root / "other-config" / "catalog.json"
            code, stdout, stderr = self.run_cli(
                "catalog", "create", "--output", str(other),
                "--entry", f"alpha={os.path.relpath(self.alpha, elsewhere)}",
            )
            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout)["entries"]["alpha"]["expected"], self.pins(self.alpha))
            self.assertEqual(len(catalog.verify_catalog(other)["entries"]), 1)
        finally:
            os.chdir(previous)
        self.assertEqual(self.read_json(self.path), value)

    def test_create_preserves_physical_bundle_through_symlink_parent_and_dotdot(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        alias_root = self.root / "aliases"
        alias_root.mkdir()
        alias = alias_root / "link"
        alias.symlink_to(nested, target_is_directory=True)
        # Filesystem resolution: aliases/link/../alpha -> working/alpha.
        # Lexical normalization would incorrectly select aliases/alpha instead.
        reference = alias / ".." / "alpha"
        output = alias_root / "catalog.json"
        created = catalog.create_catalog(output, [("alpha", reference)])
        written_path = output.parent / created["entries"]["alpha"]["bundle"]
        self.assertEqual(written_path.resolve(), self.alpha.resolve())
        self.assertEqual(catalog.verify_catalog(output)["entries"], [self.provenance("alpha", self.alpha)])

    def test_each_pin_mismatch_fails_even_when_its_entry_is_filtered_out(self) -> None:
        original = self.create_pair()
        for field in ("sourceId", "resolutionId"):
            with self.subTest(field=field):
                value = deepcopy(original)
                value["entries"]["zeta"]["expected"][field] = "sha256:" + "0" * 64
                self.write_json(self.path, value)
                reason = f"{field} pin mismatch"
                with self.assertRaisesRegex(catalog.CatalogValidationError, reason):
                    catalog.verify_catalog(self.path)
                with self.assertRaisesRegex(catalog.CatalogValidationError, reason):
                    catalog.query_catalog(self.path, exact="Shared.API.value", libraries=("alpha",))
                for command, filters in (("verify", ()),
                                         ("query", ("--exact", "Shared.API.value", "--library", "alpha"))):
                    stderr = self.assert_cli_error(1, "catalog", command, str(self.path), *filters)
                    self.assertIn(reason, stderr)

    def test_bad_catalog_configuration_is_exit_two_not_evidence_failure(self) -> None:
        valid = {
            "format": catalog.CATALOG_FORMAT,
            "entries": {"alpha": {"bundle": "../alpha", "expected": self.pins(self.alpha)}},
        }
        cases = []
        for location in ("root", "entry", "expected"):
            value = deepcopy(valid)
            target = value if location == "root" else value["entries"]["alpha"]
            if location == "expected":
                target = target["expected"]
            target["unknown"] = True
            cases.append((f"unknown-{location}", core.canonical_json_bytes(value)))
        for name in ("../escape", "Uppercase", "has space", "a" * 64):
            value = deepcopy(valid)
            value["entries"] = {name: value["entries"]["alpha"]}
            cases.append((f"name-{name}", core.canonical_json_bytes(value)))
        for path in ("https://example.invalid/bundle", "file:///tmp/bundle", "//host/bundle", "bad\npath"):
            value = deepcopy(valid)
            value["entries"]["alpha"]["bundle"] = path
            cases.append((f"path-{path}", core.canonical_json_bytes(value)))
        for field in ("sourceId", "resolutionId"):
            for bad_id in ("sha256:short", "sha256:" + "A" * 64, 7):
                value = deepcopy(valid)
                value["entries"]["alpha"]["expected"][field] = bad_id
                cases.append((f"id-{field}-{bad_id}", core.canonical_json_bytes(value)))
        cases.extend([
            ("empty", core.canonical_json_bytes({"format": catalog.CATALOG_FORMAT, "entries": {}})),
            ("wrong-shape", b"[]"), ("syntax", b"{not JSON"), ("utf8", b"\xff"),
            ("duplicate-root", b'{"format":"x","format":"y","entries":{}}'),
            ("duplicate-entry", ('{"format":' + json.dumps(catalog.CATALOG_FORMAT) +
                                 ',"entries":{"alpha":{},"alpha":{}}}').encode()),
            ("duplicate-pin", ('{"format":' + json.dumps(catalog.CATALOG_FORMAT) +
                               ',"entries":{"alpha":{"bundle":"../alpha","expected":'
                               '{"sourceId":"x","sourceId":"y","resolutionId":"z"}}}}').encode()),
        ])
        for label, raw in cases:
            with self.subTest(label=label):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_bytes(raw)
                with self.assertRaises(catalog.CatalogConfigError):
                    catalog.verify_catalog(self.path)
                for command in ("verify", "query"):
                    self.assert_cli_error(2, "catalog", command, str(self.path))

    def test_unindexed_opaque_legacy_and_partial_profiles_are_not_searchable(self) -> None:
        unindexed = self.root / "unindexed"
        self.capture(self.root / "zeta-project", unindexed, None)
        self.assertEqual(core.verify_bundle(unindexed), [])
        self.assert_invalid_bundle(unindexed, "does not contain a declaration index")

        for profile in ("opaque", "legacy", "partial"):
            with self.subTest(profile=profile):
                bundle = self.copy_bundle(profile)
                if profile in {"opaque", "legacy"}:
                    reference = self.read_json(bundle / "index-ref.json")
                    reference.pop("index")
                    reference["content"] = {"external": "old opaque metadata"}
                    self.write_json(bundle / "index-ref.json", reference)
                if profile == "legacy":
                    for filename, fields in (
                        ("snapshot.json", ("sourceId",)),
                        ("resolution.json", ("resolutionId",)),
                        ("attestation.json", ("subjects", "diagnosticsDigest", "attestationId")),
                    ):
                        payload = self.read_json(bundle / filename)
                        for field in fields:
                            payload.pop(field)
                        self.write_json(bundle / filename, payload)
                elif profile == "partial":
                    payload = self.read_json(bundle / "attestation.json")
                    payload.pop("attestationId")
                    self.write_json(bundle / "attestation.json", payload)
                self.refresh_manifest(bundle)
                if profile != "partial":
                    self.assertEqual(core.verify_bundle(bundle), [], "old bundles retain byte-integrity compatibility")
                reason = "partial enhanced identity profile" if profile == "partial" else "legacy opaque"
                self.assert_invalid_bundle(bundle, reason)

    def test_corruption_and_missing_components_fail_without_partial_results(self) -> None:
        for damage in ("corrupt", "missing"):
            with self.subTest(damage=damage):
                bundle = self.copy_bundle(damage)
                if damage == "corrupt":
                    payload = self.read_json(bundle / "snapshot.json")
                    payload["rootName"] = "tampered without rehashing"
                    self.write_json(bundle / "snapshot.json", payload)
                    reason = "digest mismatch for snapshot.json"
                else:
                    (bundle / "diagnostics.json").unlink()
                    reason = "missing component: diagnostics.json"
                self.assert_invalid_bundle(bundle, reason)

    def test_malformed_bundle_data_is_a_controlled_validation_error(self) -> None:
        for damage in ("manifest-array", "components-array", "invalid-json", "duplicate-json",
                       "component-scalar", "bad-index-line", "index-source-mismatch"):
            with self.subTest(damage=damage):
                bundle = self.copy_bundle(damage)
                if damage == "manifest-array":
                    self.write_json(bundle / "bundle.json", [])
                    reason = "bundle.json must be an object"
                elif damage == "components-array":
                    manifest = self.read_json(bundle / "bundle.json")
                    manifest["components"] = []
                    self.write_json(bundle / "bundle.json", manifest)
                    reason = "components object"
                elif damage == "invalid-json":
                    (bundle / "resolution.json").write_text("{broken", encoding="utf-8")
                    reason = "cannot read JSON"
                elif damage == "duplicate-json":
                    (bundle / "diagnostics.json").write_text('{"x":1,"x":2}', encoding="utf-8")
                    reason = "duplicate JSON key"
                elif damage == "component-scalar":
                    self.write_json(bundle / "attestation.json", None)
                    self.refresh_manifest(bundle)
                    reason = "attestation.json must be an object"
                else:
                    reference = self.read_json(bundle / "index-ref.json")
                    entry = reference["index"]["entries"][0]
                    if damage == "bad-index-line":
                        entry["line"] = True
                        reason = "line must be a positive integer"
                    else:
                        entry["sourceSha256"] = "sha256:" + "0" * 64
                        reference["index"]["indexId"] = core.derive_declaration_index_id(reference["index"])
                        reason = "does not match snapshot source digest"
                    self.write_json(bundle / "index-ref.json", reference)
                    self.refresh_manifest(bundle)
                self.assert_invalid_bundle(bundle, reason)

    def test_symlinked_manifest_component_and_bundle_root_are_rejected(self) -> None:
        for target in ("bundle.json", "index-ref.json", "root"):
            with self.subTest(target=target):
                bundle = self.copy_bundle("symlink-" + target)
                if target == "root":
                    link = self.root / "bundle-link"
                    link.symlink_to(bundle, target_is_directory=True)
                    bundle = link
                    reason = "bundle directory must be a regular directory"
                else:
                    component = bundle / target
                    component.unlink()
                    component.symlink_to(self.zeta / target)
                    reason = "bundle.json must be a regular file" if target == "bundle.json" else "symlinked component"
                self.assert_invalid_bundle(bundle, reason)

    def test_failed_wip_capture_is_searchable_with_its_actual_outcome_disclosed(self) -> None:
        failed = self.root / "failed-wip"
        self.capture(self.root / "zeta-project", failed, self.root / "zeta.index.json",
                     exit_code=7, scope="WIP explicit fixture check; not all-project CI")
        catalog.create_catalog(self.path, [("wip", failed)])
        expected = self.provenance("wip", failed)
        self.assertEqual(expected["outcome"]["status"], "failed")
        self.assertEqual(expected["outcome"]["exitCode"], 7)
        self.assertEqual(expected["command"], [sys.executable, "check.py", "7"])
        self.assertIn("WIP", expected["scope"])
        self.assertEqual(catalog.verify_catalog(self.path)["entries"], [expected])
        result = catalog.query_catalog(self.path, exact="Shared.API.value")
        self.assertEqual([entry["evidence"] for entry in result["entries"]], [expected])
        code, stdout, stderr = self.run_cli("catalog", "query", str(self.path), "--exact", "Shared.API.value")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout), result)

    def test_recapture_with_same_pins_exposes_new_bundle_attestation_and_outcome(self) -> None:
        value = self.create_pair()
        old = self.provenance("zeta", self.zeta)
        source_before = (self.root / "zeta-project" / "check.py").read_bytes()
        shutil.rmtree(self.zeta)
        # Vary only argv, never the source: the catalog pins source/resolution,
        # not a particular bundle, attestation, timestamp, or successful outcome.
        self.capture(self.root / "zeta-project", self.zeta, self.root / "zeta.index.json", exit_code=9)
        self.assertEqual((self.root / "zeta-project" / "check.py").read_bytes(), source_before)
        current = self.provenance("zeta", self.zeta)
        self.assertEqual(value["entries"]["zeta"]["expected"], self.pins(self.zeta))
        for field in ("sourceId", "resolutionId", "indexId"):
            self.assertEqual(current[field], old[field])
        for field in ("bundleId", "attestationId"):
            self.assertNotEqual(current[field], old[field])
        self.assertEqual(current["outcome"]["status"], "failed")
        self.assertEqual(current["outcome"]["exitCode"], 9)
        self.assertEqual(current["command"], [sys.executable, "check.py", "9"])
        verified = catalog.verify_catalog(self.path)
        self.assertEqual(verified["entries"][1], current)
        result = catalog.query_catalog(self.path, exact="Shared.API.value", libraries=("zeta",))
        self.assertEqual(result["checkedEntries"], ["alpha", "zeta"])
        self.assertEqual([entry["evidence"] for entry in result["entries"]], [current])
        for command, expected in (("verify", verified), ("query", catalog.query_catalog(self.path))):
            code, stdout, stderr = self.run_cli("catalog", command, str(self.path))
            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout), expected)
        self.assertEqual(self.read_json(self.path), value, "recapture must not silently rewrite the pins")

    def test_timeout_and_execution_error_remain_disclosed_searchable_evidence(self) -> None:
        commands = {
            "timed-out": [sys.executable, "-c", "import time; time.sleep(10)"],
            "execution-error": [str(self.root / "missing-checker")],
        }
        for status, command in commands.items():
            with self.subTest(status=status):
                bundle = self.root / status
                core.capture_bundle(
                    self.root / "zeta-project", bundle, command,
                    agda_binary=self.agda_binary, timeout_seconds=1,
                    index_reference=self.root / "zeta.index.json",
                )
                output = self.root / f"{status}.catalog.json"
                catalog.create_catalog(output, [("wip", bundle)])
                result = catalog.query_catalog(output, exact="Shared.API.value")
                outcome = result["entries"][0]["evidence"]["outcome"]
                self.assertEqual(outcome["status"], status)
                self.assertIsNone(outcome["exitCode"])
                if status == "execution-error":
                    self.assertTrue(outcome["executionError"])


if __name__ == "__main__":
    unittest.main()
