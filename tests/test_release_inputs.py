from __future__ import annotations

import base64
from contextlib import redirect_stderr, redirect_stdout
import copy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
import warnings
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_inputs", ROOT / "scripts/check-release-inputs.py")
release_inputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_inputs)

VERSION = "0.1.0a2"
REPOSITORY = "Nokidme/agda-evidence"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
RUN_ID = 123456
REPOSITORY_ID = 1439873902
JOB_NAMES = {
    "test (3.11)", "test (3.12)", "distributions",
    "installed-package (ubuntu-24.04, 3.11)", "installed-package (ubuntu-24.04, 3.12)",
    "installed-package (windows-latest, 3.11)", "installed-package (windows-latest, 3.12)",
    "native-installed-package",
}


def ci_fixture():
    return {
        "id": RUN_ID, "repository": {"full_name": REPOSITORY, "id": REPOSITORY_ID},
        "head_repository": {"full_name": REPOSITORY, "id": REPOSITORY_ID}, "head_sha": COMMIT,
        "path": ".github/workflows/ci.yml", "event": "push",
        "status": "completed", "conclusion": "success", "workflow_id": 987654,
    }


def jobs_fixture():
    return {"total_count": 8, "jobs": [
        {"id": index + 1, "name": name, "run_id": RUN_ID,
         "status": "completed", "conclusion": "success"}
        for index, name in enumerate(sorted(JOB_NAMES))
    ]}


def artifacts_fixture():
    return {"total_count": 1, "artifacts": [{
        "id": 13449093118, "name": "alpha-distributions-" + COMMIT,
        "size_in_bytes": 399671, "expired": False,
        "workflow_run": {"id": RUN_ID, "repository_id": REPOSITORY_ID,
                         "head_repository_id": REPOSITORY_ID, "head_branch": "main", "head_sha": COMMIT},
    }]}


def metadata(version=VERSION, extra=""):
    return (f"Metadata-Version: 2.4\nName: agda-evidence\nVersion: {version}\n"
            f"Requires-Python: >=3.11\n{extra}\nSynthetic package description.\n").encode()


ENTRY_POINTS = b"[console_scripts]\nagda-evidence = agda_evidence.cli:main\n"


class DistributionFixture:
    """Tiny distributions built without setuptools, imports, installs or Agda."""

    def __init__(self, base: Path, version=VERSION):
        self.version = version
        self.root = base / "repository"
        self.dist = base / "dist"
        self.root.mkdir()
        self.dist.mkdir()
        self.source = {
            "pyproject.toml": b'[project]\nname = "agda-evidence"\nrequires-python = ">=3.11"\n',
            "MANIFEST.in": b"include LICENSE README.md CHANGELOG.md CONTRIBUTING.md\n",
            "LICENSE": b"Fixture license\n", "README.md": b"Fixture readme\n",
            "CHANGELOG.md": b"Fixture changes\n", "CONTRIBUTING.md": b"Fixture contributions\n",
            "src/agda_evidence/__init__.py": f'__version__ = "{version}"\n'.encode(),
            "src/agda_evidence/__main__.py": b"# Never executed by these tests.\n",
            "src/agda_evidence/cli.py": b"def main():\n    pass\n",
            "schemas/__init__.py": b"# Canonical schema package.\n",
            "docs/nested/guide.md": b"Declared documentation\n",
            "examples/Main.agda": b"module Main where\n",
            "examples/example.agda-lib": b"name: example\ninclude: .\n",
            "scripts/example.py": b"# Declared release script.\n",
            "tests/test_example.py": b"# Declared test source.\n",
            ".github/workflows/ci.yml": b"name: CI\non: push\njobs: {}\n",
        }
        self.source.update({f"schemas/fixture-{index}.schema.json":
                            json.dumps({"$id": f"fixture-{index}"}).encode() for index in range(13)})
        for name, data in self.source.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.wheel_prefix = f"agda_evidence-{version}.dist-info/"
        self.tar_prefix = f"agda_evidence-{version}/"
        self.wheel_path = self.dist / f"agda_evidence-{version}-py3-none-any.whl"
        self.tar_path = self.dist / f"agda_evidence-{version}.tar.gz"
        self.wheel_files = {}
        for name, data in self.source.items():
            if name.startswith("src/agda_evidence/"):
                self.wheel_files[name.removeprefix("src/")] = data
            elif name.startswith("schemas/"):
                self.wheel_files["agda_evidence/" + name] = data
        self.wheel_files.update({self.wheel_prefix + name: data for name, data in {
            "METADATA": metadata(version),
            "WHEEL": b"Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            "top_level.txt": b"agda_evidence\n", "entry_points.txt": ENTRY_POINTS,
            "licenses/LICENSE": self.source["LICENSE"],
        }.items()})
        egg = "src/agda_evidence.egg-info/"
        auto = {
            "PKG-INFO": metadata(version), "setup.cfg": b"[egg_info]\ntag_build = \ntag_date = 0\n",
            egg + "PKG-INFO": metadata(version), egg + "dependency_links.txt": b"\n",
            egg + "entry_points.txt": ENTRY_POINTS, egg + "top_level.txt": b"agda_evidence\n",
        }
        sources = set(self.source) | {name for name in auto if name.startswith(egg)} | {egg + "SOURCES.txt"}
        auto[egg + "SOURCES.txt"] = ("\n".join(sorted(sources)) + "\n").encode()
        self.tar_files = {self.tar_prefix + name: data for name, data in (self.source | auto).items()}
        self.write_wheel()
        self.write_tar()
        self.write_checksums()

    def write_wheel(self, *, extra_members=(), regenerate_record=True, directories=()):
        if regenerate_record:
            record_name = self.wheel_prefix + "RECORD"
            self.wheel_files.pop(record_name, None)
            output = io.StringIO(newline="")
            writer = csv.writer(output, lineterminator="\n")
            for name, data in sorted(self.wheel_files.items()):
                digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
                writer.writerow([name, "sha256=" + digest, str(len(data))])
            writer.writerow([record_name, "", ""])
            self.wheel_files[record_name] = output.getvalue().encode()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in self.wheel_files.items():
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    archive.writestr(info, data)
                for name in directories:
                    archive.writestr(name, b"")
                for name, data, mode in extra_members:
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = mode << 16
                    archive.writestr(info, data)
        self.write_checksums()

    def write_tar(self, *, extra_members=(), directory_trailing_slash=False):
        with tarfile.open(self.tar_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            dirs = set()
            for name in self.tar_files:
                parts = name.split("/")
                dirs.update("/".join(parts[:index]) for index in range(1, len(parts)))
            for name in sorted(dirs):
                info = tarfile.TarInfo(name + ("/" if directory_trailing_slash else ""))
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            for name, data in self.tar_files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            for name, data, kind in extra_members:
                info = tarfile.TarInfo(name)
                info.type = kind
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    info.linkname = "/outside/credential"
                if kind == tarfile.REGTYPE:
                    info.size = len(data)
                archive.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
        self.write_checksums()

    def write_checksums(self):
        if self.wheel_path.exists() and self.tar_path.exists():
            (self.dist / "SHA256SUMS").write_text("".join(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                for path in (self.wheel_path, self.tar_path)), encoding="ascii")

    def validate(self):
        return release_inputs.validate_distributions(self.dist, self.root, self.version)


class CIRunValidationTests(unittest.TestCase):
    def validate(self, run=None, jobs=None, artifacts=None, **changes):
        args = dict(repository=REPOSITORY, commit=COMMIT, run_id=RUN_ID)
        args.update(changes)
        return release_inputs.validate_ci_run(ci_fixture() if run is None else run,
                                             jobs_fixture() if jobs is None else jobs,
                                             artifacts_fixture() if artifacts is None else artifacts, **args)

    def test_exact_success_and_json_ready_report(self):
        report = self.validate()
        self.assertEqual(report["format"], "release-input-validation-v1")
        self.assertEqual(report["source_sha"], COMMIT)
        self.assertEqual(report["run_id"], RUN_ID)
        self.assertEqual(report["job_count"], 8)
        self.assertEqual(set(report["job_names"]), JOB_NAMES)
        self.assertEqual(report["repository_id"], REPOSITORY_ID)
        self.assertEqual(report["artifact"]["name"], "alpha-distributions-" + COMMIT)
        self.assertIs(report["artifact"]["expired"], False)
        self.assertIn("not an evidence certificate", report["scope"])
        json.dumps(report)

    def test_workflow_id_is_irrelevant(self):
        for value in (None, True, "unrelated", 0):
            run = ci_fixture()
            run["workflow_id"] = value
            self.validate(run)

    def test_reject_wrong_run_fields_and_boolean_id(self):
        changes = [
            ("id", RUN_ID + 1), ("id", str(RUN_ID)), ("id", True), ("id", 0), ("id", -1),
            ("head_sha", "f" * 40), ("head_sha", COMMIT.upper()), ("head_sha", COMMIT[:-1]),
            ("head_sha", True), ("path", ".github/workflows/native-conformance.yml"),
            ("path", ".github/workflows/ci.yml@main"), ("event", "workflow_dispatch"),
            ("event", "pull_request"), ("status", "in_progress"), ("status", True),
            ("conclusion", "failure"), ("conclusion", "skipped"), ("conclusion", None),
        ]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                run = ci_fixture()
                run[key] = value
                with self.assertRaises(release_inputs.ReleaseInputError):
                    self.validate(run)

    def test_reject_wrong_or_missing_repositories(self):
        for key in ("repository", "head_repository"):
            for value in ({"full_name": "attacker/agda-evidence"}, {"full_name": REPOSITORY.upper()}, None, {}, True):
                with self.subTest(key=key, value=value):
                    run = ci_fixture()
                    run[key] = value
                    with self.assertRaises(release_inputs.ReleaseInputError):
                        self.validate(run)

    def test_repository_ids_must_be_identical_positive_integers(self):
        for key in ("repository", "head_repository"):
            for value in (None, True, 0, -1, str(REPOSITORY_ID), REPOSITORY_ID + 1):
                run = ci_fixture()
                run[key]["id"] = value
                with self.subTest(key=key, value=value), self.assertRaises(release_inputs.ReleaseInputError):
                    self.validate(run)

    def test_missing_fields_and_api_errors_are_not_bypassed(self):
        for key in ci_fixture().keys() - {"workflow_id"}:
            run = ci_fixture()
            del run[key]
            with self.subTest(key=key), self.assertRaises(release_inputs.ReleaseInputError):
                self.validate(run)
        for key in ("message", "error", "errors"):
            run = ci_fixture()
            run[key] = "API failed"
            with self.subTest(key=key), self.assertRaises(release_inputs.ReleaseInputError):
                self.validate(run)

    def test_invalid_expected_inputs(self):
        for changes in ({"run_id": True}, {"run_id": 0}, {"run_id": "123456"},
                        {"commit": COMMIT.upper()}, {"commit": "a" * 39},
                        {"repository": "https://github.com/" + REPOSITORY}):
            with self.subTest(changes=changes), self.assertRaises(release_inputs.ReleaseInputError):
                self.validate(**changes)

    def test_reject_partial_missing_duplicate_or_unexpected_jobs(self):
        cases = []
        jobs = jobs_fixture()
        jobs["jobs"].pop()
        cases.append(jobs)
        jobs = jobs_fixture()
        jobs["total_count"] = 7
        cases.append(jobs)
        jobs = jobs_fixture()
        jobs["total_count"] = True
        cases.append(jobs)
        jobs = jobs_fixture()
        jobs["jobs"][1] = copy.deepcopy(jobs["jobs"][0])
        cases.append(jobs)
        jobs = jobs_fixture()
        jobs["jobs"][0]["name"] = "unexpected-ci-job"
        cases.append(jobs)
        cases += [{"total_count": 8}, {"total_count": 8, "jobs": {}}, {"message": "error"}]
        for jobs in cases:
            with self.subTest(jobs=jobs), self.assertRaises(release_inputs.ReleaseInputError):
                self.validate(jobs=jobs)

    def test_every_job_must_succeed_and_match_exact_integer_run(self):
        for index in range(8):
            for key, value in (("status", "queued"), ("status", "in_progress"),
                               ("conclusion", "failure"), ("conclusion", "skipped"),
                               ("conclusion", "cancelled"), ("conclusion", None),
                               ("run_id", RUN_ID + 1), ("run_id", str(RUN_ID)), ("run_id", True)):
                jobs = jobs_fixture()
                jobs["jobs"][index][key] = value
                with self.subTest(index=index, key=key, value=value), self.assertRaises(release_inputs.ReleaseInputError):
                    self.validate(jobs=jobs)
        jobs = jobs_fixture()
        del jobs["jobs"][0]["run_id"]
        with self.assertRaises(release_inputs.ReleaseInputError):
            self.validate(jobs=jobs)

    def test_artifact_cardinality_name_size_id_expiration_and_workflow_pins(self):
        cases = [{"total_count": 0, "artifacts": []}, {"total_count": True, "artifacts": []},
                 {"total_count": 1, "artifacts": []}, {"total_count": 2, "artifacts": []},
                 {"total_count": 1}, {"message": "Not Found"}]
        artifacts = artifacts_fixture()
        artifacts["artifacts"].append(copy.deepcopy(artifacts["artifacts"][0]))
        cases.append(artifacts)
        for artifacts in cases:
            with self.subTest(artifacts=artifacts), self.assertRaises(release_inputs.ReleaseInputError):
                self.validate(artifacts=artifacts)
        for key, value in (("name", "alpha-distributions-" + "f" * 40),
                           ("name", "alpha-distributions-" + COMMIT + "-extra"),
                           ("expired", True), ("expired", 0), ("expired", None),
                           ("id", True), ("id", 0), ("id", -1), ("id", "13449093118"),
                           ("size_in_bytes", True), ("size_in_bytes", 0),
                           ("size_in_bytes", -1), ("size_in_bytes", "399671"),
                           ("workflow_run", None)):
            artifacts = artifacts_fixture()
            artifacts["artifacts"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(release_inputs.ReleaseInputError):
                self.validate(artifacts=artifacts)
        for key, value in (("id", RUN_ID + 1), ("id", True), ("id", str(RUN_ID)),
                           ("repository_id", REPOSITORY_ID + 1), ("repository_id", True),
                           ("head_repository_id", REPOSITORY_ID + 1), ("head_repository_id", True),
                           ("head_sha", "f" * 40), ("head_sha", COMMIT.upper())):
            artifacts = artifacts_fixture()
            artifacts["artifacts"][0]["workflow_run"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(release_inputs.ReleaseInputError):
                self.validate(artifacts=artifacts)
        for key in artifacts_fixture()["artifacts"][0]:
            artifacts = artifacts_fixture()
            del artifacts["artifacts"][0][key]
            with self.subTest(missing=key), self.assertRaises(release_inputs.ReleaseInputError):
                self.validate(artifacts=artifacts)

    def test_json_reader_rejects_duplicate_keys_and_nonobjects(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "metadata.json"
            for text in ('{"id":1,"id":2}', '{"repository":{"full_name":"a","full_name":"b"}}',
                         "[]", "null", "not JSON"):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(release_inputs.ReleaseInputError):
                    release_inputs.load_ci_metadata(path)

    def test_ci_cli_requires_jobs_and_artifacts_and_returns_json_or_exit_two(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_path, jobs_path = root / "run.json", root / "jobs.json"
            artifact_path = root / "artifacts.json"
            run_path.write_text(json.dumps(ci_fixture()))
            jobs_path.write_text(json.dumps(jobs_fixture()))
            artifact_path.write_text(json.dumps(artifacts_fixture()))
            args = ["ci-run", "--metadata", str(run_path), "--repository", REPOSITORY,
                    "--commit", COMMIT, "--run-id", str(RUN_ID)]
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                release_inputs.main(args)
            self.assertEqual(caught.exception.code, 2)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                release_inputs.main(args + ["--jobs", str(jobs_path)])
            self.assertEqual(caught.exception.code, 2)
            args += ["--jobs", str(jobs_path), "--artifacts", str(artifact_path)]
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(release_inputs.main(args), 0)
            self.assertEqual(json.loads(output.getvalue())["job_count"], 8)
            jobs_path.write_text('{"message":"Not Found"}')
            output, error = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                self.assertEqual(release_inputs.main(args), 2)
            self.assertEqual(output.getvalue(), "")
            self.assertNotIn("Traceback", error.getvalue())


class DistributionValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = DistributionFixture(Path(self.temporary.name))

    def reject(self, text=None):
        if text is None:
            with self.assertRaises(release_inputs.ReleaseInputError):
                self.fixture.validate()
        else:
            with self.assertRaisesRegex(release_inputs.ReleaseInputError, text):
                self.fixture.validate()

    def test_success_reports_exact_filenames_digests_and_counts(self):
        report = self.fixture.validate()
        self.assertEqual(report["expected_version"], VERSION)
        self.assertEqual(report["module_count"], 3)
        self.assertEqual(report["schema_count"], 13)
        self.assertEqual(report["schema_module_count"], 1)
        self.assertEqual(report["canonical_source_file_count"], len(self.fixture.source))
        self.assertEqual({a["filename"] for a in report["artifacts"]},
                         {self.fixture.wheel_path.name, self.fixture.tar_path.name})
        for artifact in report["artifacts"]:
            self.assertEqual(artifact["sha256"], hashlib.sha256(
                (self.fixture.dist / artifact["filename"]).read_bytes()).hexdigest())
        json.dumps(report)

    def test_development_version_can_be_validated_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DistributionFixture(Path(temporary), "0.1.0a2.dev0")
            self.assertEqual(fixture.validate()["expected_version"], "0.1.0a2.dev0")

    def test_tar_directory_trailing_slashes_are_allowed(self):
        self.fixture.write_tar(directory_trailing_slash=True)
        self.fixture.validate()

    def test_legacy_setuptools_license_location_is_allowed(self):
        prefix = self.fixture.wheel_prefix
        self.fixture.wheel_files[prefix + "LICENSE"] = self.fixture.wheel_files.pop(prefix + "licenses/LICENSE")
        self.fixture.write_wheel()
        self.fixture.validate()

    def test_release_directory_has_exactly_three_regular_entries(self):
        for name in ("report.json", "extra.whl", "old.tar.gz", ".credential"):
            path = self.fixture.dist / name
            path.write_bytes(b"unexpected")
            with self.subTest(name=name):
                self.reject("exactly")
            path.unlink()
        path = self.fixture.dist / "SHA256SUMS"
        path.unlink()
        self.reject("exactly")

    def test_symlinked_artifact_or_checksum_file_is_rejected(self):
        for path in (self.fixture.wheel_path, self.fixture.tar_path, self.fixture.dist / "SHA256SUMS"):
            data = path.read_bytes()
            target = self.fixture.root.parent / "target"
            target.write_bytes(data)
            path.unlink()
            path.symlink_to(target)
            with self.subTest(name=path.name):
                self.reject("regular file")
            path.unlink()
            path.write_bytes(data)

    def test_wrong_artifact_filename_or_expected_version_is_rejected(self):
        renamed = self.fixture.wheel_path.with_name("agda_evidence-0.1.0a1-py3-none-any.whl")
        self.fixture.wheel_path.rename(renamed)
        self.reject("canonical wheel")
        renamed.rename(self.fixture.wheel_path)
        with self.assertRaises(release_inputs.ReleaseInputError):
            release_inputs.validate_distributions(self.fixture.dist, self.fixture.root, "0.1.0a1")
        for version in ("../0.1.0a2", "0.1.0a2/extra", "0.1.0a2\n", True):
            with self.subTest(version=version), self.assertRaises(release_inputs.ReleaseInputError):
                release_inputs.validate_distributions(self.fixture.dist, self.fixture.root, version)

    def test_checksums_reject_extra_duplicate_wrong_truncated_and_unsafe_entries(self):
        path = self.fixture.dist / "SHA256SUMS"
        original = path.read_text()
        lines = original.splitlines()
        digest, name = lines[0].split()
        cases = ["", lines[0] + "\n", original + lines[0] + "\n", lines[0] + "\n" + lines[0] + "\n",
                 original.replace(digest, digest[:-1]), original.replace(digest, digest.upper()),
                 original.replace(digest, "0" * 64), original.replace(name, "../" + name),
                 original.replace(name, "https://example.invalid/" + name),
                 original.replace(name, "*" + name), original.replace(name, "unexpected.whl"),
                 original.replace(name, name + " extra"), original.replace(name, name + "é")]
        for text in cases:
            path.write_text(text)
            with self.subTest(text=text):
                self.reject()
        path.write_text(original)
        self.fixture.validate()

    def test_standard_checksum_whitespace_is_accepted(self):
        path = self.fixture.dist / "SHA256SUMS"
        path.write_text(path.read_text().replace("  ", "\t"))
        self.fixture.validate()

    def test_tampered_archive_rejected_before_archive_read(self):
        with self.fixture.wheel_path.open("ab") as stream:
            stream.write(b"tamper")
        self.reject("digest mismatch")

    def test_wheel_requires_canonical_modules_schema_and_distinfo(self):
        for name in ("agda_evidence/__init__.py", "agda_evidence/cli.py",
                     "agda_evidence/schemas/__init__.py", "agda_evidence/schemas/fixture-0.schema.json",
                     self.fixture.wheel_prefix + "METADATA"):
            data = self.fixture.wheel_files.pop(name)
            self.fixture.write_wheel()
            with self.subTest(name=name):
                self.reject("missing members")
            self.fixture.wheel_files[name] = data
        self.fixture.write_wheel()
        old = self.fixture.wheel_prefix + "METADATA"
        self.fixture.wheel_files["agda_evidence-0.1.0a1.dist-info/METADATA"] = self.fixture.wheel_files.pop(old)
        self.fixture.write_wheel()
        self.reject()

    def test_wheel_metadata_is_unambiguous_and_has_no_runtime_dependencies(self):
        name = self.fixture.wheel_prefix + "METADATA"
        for data in (metadata("0.1.0a1"), metadata(extra="Requires-Dist: requests\n"),
                     metadata(extra="Requires-Dist:\n"), metadata(extra="Name: agda-evidence\n"),
                     metadata(extra=f"vErSiOn: {VERSION}\n"), metadata(extra="Requires-Python: >=3.11\n"),
                     metadata(extra="Dynamic: Requires-Dist\n"),
                     metadata().replace(b"Name: agda-evidence", b"Name: wrong-package"),
                     metadata().replace(b">=3.11", b">=3.10")):
            self.fixture.wheel_files[name] = data
            self.fixture.write_wheel()
            with self.subTest(data=data):
                self.reject()

    def test_wheel_runtime_schema_and_license_bytes_match_repository(self):
        for name in ("agda_evidence/cli.py", "agda_evidence/__init__.py",
                     "agda_evidence/schemas/fixture-0.schema.json", self.fixture.wheel_prefix + "licenses/LICENSE"):
            original = self.fixture.wheel_files[name]
            self.fixture.wheel_files[name] += b"changed"
            self.fixture.write_wheel()
            with self.subTest(name=name):
                self.reject("bytes differ")
            self.fixture.wheel_files[name] = original

    def test_wheel_record_entrypoints_and_pure_tag_are_checked(self):
        prefix = self.fixture.wheel_prefix
        cases = [(prefix + "RECORD", b"malformed\n", False),
                 (prefix + "entry_points.txt", b"[console_scripts]\nother = evil:main\n", True),
                 (prefix + "WHEEL", b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: py3-none-any\n", True),
                 (prefix + "top_level.txt", b"agda_evidence\nother_package\n", True)]
        for name, data, regenerate in cases:
            original = self.fixture.wheel_files[name]
            self.fixture.wheel_files[name] = data
            self.fixture.write_wheel(regenerate_record=regenerate)
            with self.subTest(name=name):
                self.reject()
            self.fixture.wheel_files[name] = original

    def test_wheel_rejects_unexpected_private_and_unsafe_paths(self):
        for name in ("../escape.py", "/absolute.py", "agda_evidence/../escape.py",
                     "agda_evidence//empty.py", "agda_evidence/./alias.py", "agda_evidence\\escape.py",
                     "agda_evidence/control\x01.py", "agda_evidence/__pycache__/x.pyc",
                     "agda_evidence/.env", "agda_evidence/vm/private.py", "agda_evidence/raw.evidence",
                     "unrelated_package/__init__.py", "agda_evidence/unexpected.py"):
            self.fixture.write_wheel(extra_members=[(name, b"private", stat.S_IFREG | 0o644)])
            with self.subTest(name=name):
                self.reject()

    def test_duplicate_wheel_names_symlinks_and_special_modes_rejected(self):
        for name, mode in (("agda_evidence/cli.py", stat.S_IFREG | 0o644),
                           ("agda_evidence/link", stat.S_IFLNK | 0o777),
                           ("agda_evidence/fifo", stat.S_IFIFO | 0o644)):
            self.fixture.write_wheel(extra_members=[(name, b"target", mode)])
            with self.subTest(name=name):
                self.reject()

    def test_zip_nul_bearing_original_filename_is_not_silently_normalized(self):
        data = self.fixture.wheel_path.read_bytes()
        data = data.replace(b"agda_evidence/cli.py", b"agda_evidence/cli.\x00y")
        self.fixture.wheel_path.write_bytes(data)
        self.fixture.write_checksums()
        self.reject("noncanonical wheel member filename")

    def test_sdist_missing_or_changed_declared_source_is_rejected(self):
        for relative in ("src/agda_evidence/cli.py", "schemas/fixture-0.schema.json", "schemas/__init__.py",
                         "pyproject.toml", "docs/nested/guide.md", "scripts/example.py", "tests/test_example.py",
                         "examples/Main.agda", "examples/example.agda-lib", ".github/workflows/ci.yml"):
            name = self.fixture.tar_prefix + relative
            original = self.fixture.tar_files.pop(name)
            self.fixture.write_tar()
            with self.subTest(name=name, kind="missing"):
                self.reject("missing members")
            self.fixture.tar_files[name] = original + b"changed"
            self.fixture.write_tar()
            with self.subTest(name=name, kind="changed"):
                self.reject("bytes differ")
            self.fixture.tar_files[name] = original

    def test_sdist_metadata_rejects_runtime_dependencies_and_duplicate_headers(self):
        for relative in ("PKG-INFO", "src/agda_evidence.egg-info/PKG-INFO"):
            name = self.fixture.tar_prefix + relative
            original = self.fixture.tar_files[name]
            for data in (metadata("0.1.0a1"), metadata(extra="Requires-Dist: requests\n"),
                         metadata(extra=f"Version: {VERSION}\n")):
                self.fixture.tar_files[name] = data
                self.fixture.write_tar()
                with self.subTest(name=name, data=data):
                    self.reject()
            self.fixture.tar_files[name] = original

    def test_sdist_rejects_unsafe_unexpected_duplicate_links_and_special_files(self):
        prefix = self.fixture.tar_prefix
        cases = [(name, tarfile.REGTYPE) for name in (
            "../escape", "/absolute", prefix + "../escape", prefix + "src//empty.py",
            prefix + "src\\escape.py", prefix + "secret\x7f", prefix + ".git/config",
            prefix + ".env", prefix + "src/agda_evidence/__pycache__/x.pyc",
            prefix + "examples/Main.agdai", prefix + "cloud/private.py", prefix + "raw.evidence",
            prefix + ".github/secrets/token", prefix + ".github/workflows/.private.yml",
            prefix + ".github/workflows/unexpected.yml", prefix + ".github/workflows/extra.yaml",
            prefix + "src/agda_evidence/cli.py", "another-root/README.md")]
        cases += [(prefix + "link", kind) for kind in
                  (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE,
                   tarfile.GNUTYPE_SPARSE, tarfile.CONTTYPE)]
        for name, kind in cases:
            self.fixture.write_tar(extra_members=[(name, b"private", kind)])
            with self.subTest(name=name, kind=kind):
                self.reject()

    def test_repository_inventory_is_dynamic_and_excludes_local_caches(self):
        for name in ("tests/__pycache__/ignored.py", "scripts/.private/ignored.py",
                     "examples/cloud/ignored.agda"):
            path = self.fixture.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not a declared source")
        self.fixture.validate()
        path = self.fixture.root / "scripts/new_release_check.py"
        path.write_bytes(b"# Newly added canonical script\n")
        self.reject("missing members")

    def test_repository_version_schema_count_and_symlink_sources_are_checked(self):
        init = self.fixture.root / "src/agda_evidence/__init__.py"
        original = init.read_bytes()
        for data in (b'__version__ = "0.1.0a1"\n', original + original,
                     b'__version__ = compute_version()\n'):
            init.write_bytes(data)
            with self.subTest(data=data):
                self.reject("__version__")
        init.write_bytes(original)
        schema = self.fixture.root / "schemas/fixture-0.schema.json"
        data = schema.read_bytes()
        schema.unlink()
        self.reject("exactly 13")
        schema.write_bytes(data)
        target = self.fixture.root.parent / "source-target"
        target.write_bytes(data)
        schema.unlink()
        schema.symlink_to(target)
        self.reject("symlink")

    def test_invalid_archives_raise_controlled_value_error(self):
        for path in (self.fixture.wheel_path, self.fixture.tar_path):
            original = path.read_bytes()
            path.write_bytes(b"not an archive")
            self.fixture.write_checksums()
            with self.subTest(path=path):
                self.reject("cannot validate")
            path.write_bytes(original)
            self.fixture.write_checksums()
        self.assertTrue(issubclass(release_inputs.ReleaseInputError, ValueError))

    def test_distributions_cli_json_and_error_exit_two(self):
        args = ["distributions", "--dist-dir", str(self.fixture.dist),
                "--repository-root", str(self.fixture.root), "--expected-version", VERSION]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(release_inputs.main(args), 0)
        self.assertEqual(json.loads(output.getvalue())["kind"], "distributions")
        (self.fixture.dist / "report.json").write_bytes(b"{}")
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            self.assertEqual(release_inputs.main(args), 2)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn("Traceback", error.getvalue())


if __name__ == "__main__":
    unittest.main()
