"""Independent offline wrapper contracts; synthetic evidence, no native processes."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from agda_evidence import candidates, checker, client, core, goals, sources

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evidence-accounting.py"
STAMP = "2000-01-01T00:00:00Z"


def load_script():
    spec = importlib.util.spec_from_file_location("evidence_accounting_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bind_snapshot(snapshot):
    snapshot["capturedAt"] = STAMP
    snapshot["sourceId"] = snapshot["sourceDigest"] = core.derive_source_id(snapshot)
    return snapshot


class EvidenceAccountingTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process launched")))
        self.enterContext(patch("socket.socket", side_effect=AssertionError("network used")))
        self.tool = load_script()
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        project = self.root / "project"
        project.mkdir()
        (project / "Main.agda").write_text("module Main where\n-- λ → 隠\n", encoding="utf-8")
        self.snapshot = bind_snapshot(core.build_snapshot(project)[0])
        with patch.object(core.shutil, "which", return_value=None):
            self.resolution = core.build_resolution(project, "accounting-fixture-unavailable")
        self.resolution["capturedAt"] = STAMP
        self.value = self.observation()
        checker.validate_observation(self.value)

    def observation(self, *, goal=False, snapshot=None, resolution=None, listing=None):
        snapshot = deepcopy(snapshot or self.snapshot)
        resolution = deepcopy(resolution or self.resolution)
        file = next(r for r in snapshot["files"] if r["path"].endswith("Main.agda"))
        includes = [".", "client", "library"] if file["path"].startswith("client/") else ["."]
        query = dict(file=file["path"], sourceSha256=file["sha256"], includes=includes,
                     safe=False, rewrite="Simplified")
        query.update(operation="inspect" if listing else "list", goalId=0 if listing else None,
                     loadPolicy=goals.LOAD_POLICY) if goal else query.update(expression="λ x → x")
        value = dict(format=goals.GOAL_FORMAT if goal else checker.OBSERVATION_FORMAT,
                     observationId="", snapshot=snapshot, resolution=resolution, query=query,
                     execution=dict(argv=checker._argv("$AGDA", includes, False, anchor="$PROJECT_ROOT"),
                                    mode="isolated-project-copy", timeoutSeconds=1, maxOutputBytes=1024,
                                    startedAt=STAMP, finishedAt=STAMP), transcript=[],
                     transport=dict(status="execution-error", message="synthetic unavailable λ",
                                    stderr="", stdoutBytes=0), result={})
        value["listing" if goal else "basis"] = listing
        value["result"] = goals.goal_result(value) if goal else checker.response_result([], value["transport"])
        value["observationId"] = checker.observation_id(value)
        return value

    def envelopes(self):
        """Manual compiler metadata is evidence only, never an executable fixture."""
        native = deepcopy(self.resolution)
        native["agda"] = dict(requested="synthetic", available=True, binarySha256="sha256:" + "1" * 64,
                              version={"available": True, "stdout": "synthetic-version"})
        native["resolutionId"] = core.derive_resolution_id(native)
        library = self.root / "library"
        library.mkdir()
        (library / "Lib.agda").write_text("module Lib where\nidentity : Set → Set\nidentity x = x\n", encoding="utf-8")
        snapshot = bind_snapshot(core.build_snapshot(library)[0])
        index = core.build_declaration_index(library)
        diagnostics = {"format": core.DIAGNOSTICS_FORMAT, "stdout": {"text": "λ failure"}}
        attestation = dict(format=core.ATTESTATION_FORMAT, recordedAt=STAMP, scope="explicit-project-check",
                           command=["synthetic-not-executed"], workingDirectory="$PROJECT_ROOT", execution={},
                           outcome=dict(status="failed", exitCode=1, startedAt=STAMP, finishedAt=STAMP),
                           subjects=dict(sourceId=snapshot["sourceId"], resolutionId=native["resolutionId"]),
                           diagnosticsDigest=core.derive_diagnostics_digest(diagnostics))
        attestation["attestationId"] = core.derive_attestation_id(attestation)
        components = {"snapshot.json": snapshot, "resolution.json": native,
                      "attestation.json": attestation, "diagnostics.json": diagnostics,
                      "index-ref.json": dict(format=core.INDEX_REFERENCE_FORMAT, sourcePathReference="synthetic-index",
                                             inputSha256="sha256:" + core.digest_value(index), index=index)}
        manifest = dict(format=core.BUNDLE_FORMAT, components={k: "sha256:" + core.digest_value(v) for k, v in components.items()})
        manifest.update(bundleId="sha256:" + core.digest_value(manifest), createdAt=STAMP)
        evidence = dict(manifest=manifest, components=components)
        self.assertEqual(core._verify_bundle_payloads(manifest, components), [])
        workspace = bind_snapshot({**deepcopy(self.snapshot), "files": client.composed_records(self.snapshot, snapshot)})
        inner = self.observation(snapshot=workspace, resolution=native)
        candidate = next(e for e in index["entries"] if e["qualifiedName"] == "Lib.identity")
        outer = dict(format=client.CLIENT_FORMAT, clientObservationId="", clientSnapshot=self.snapshot,
                     library=dict(evidence=evidence, nativeResolution=native, candidate=candidate),
                     composition=dict(policy=client.COMPOSITION_POLICY, clientIncludes=["."], libraryIncludes=["."]),
                     typeObservation=inner)
        outer["clientObservationId"] = client.client_observation_id(outer)
        client.validate_client_observation(outer)
        listing = self.observation(goal=True, snapshot=workspace, resolution=native)
        point = dict(id=0, range=[dict(start=dict(pos=1, line=1, col=1), end=dict(pos=2, line=1, col=2))])
        listing["transport"].update(status="completed", message=None)
        summary = dict(kind="AllGoalsWarnings", visibleGoals=[dict(kind="OfType", constraintObj=point, type="Set")],
                       invisibleGoals=[], warnings=[], errors=[])
        listing["transcript"] = [dict(phase="startup", request=None, responses=[], complete=True),
            dict(phase="load", request=checker._request("$PROJECT_ROOT/client/Main.agda", "load", ""),
                 responses=[dict(kind="DisplayInfo", info=summary), dict(kind="InteractionPoints", interactionPoints=[point])], complete=True)]
        listing["result"] = goals.goal_result(listing)
        listing["observationId"] = goals.goal_observation_id(listing)
        source = dict(format=sources.SOURCE_FORMAT, sourceObservationId="", clientSnapshot=self.snapshot,
                      clientResolution=native, dependency=dict(evidence=evidence, nativeResolution=native),
                      composition=dict(policy=sources.SOURCE_POLICY, clientIncludes=["."], dependencyIncludes=["."]),
                      observation=listing, listing=None)
        source["sourceObservationId"] = sources.source_observation_id(source)
        sources.validate_source_observation(source)
        selected = deepcopy(source)
        selected["listing"] = deepcopy(source)
        selected["observation"] = self.observation(goal=True, snapshot=workspace, resolution=native, listing=deepcopy(listing))
        selected["sourceObservationId"] = sources.source_observation_id(selected)
        sources.validate_source_observation(selected)
        candidate_observation = deepcopy(selected["observation"])
        candidate_observation["format"] = candidates.CANDIDATE_FORMAT
        candidate_observation["query"].update(operation="check", expression="λ x → x", candidatePolicy=candidates.CANDIDATE_POLICY)
        candidate_observation["result"] = candidates.candidate_result(candidate_observation)
        candidate_observation["observationId"] = goals.goal_observation_id(candidate_observation)
        candidates.validate_candidate_observation(candidate_observation)
        return outer, selected, candidate_observation

    def account(self, value, raw=None):
        return self.tool.account_artifact(value, input_bytes=raw if raw is not None else core.canonical_json_bytes(value))

    def cli(self, raw=None, extra=(), output=None, inputs=None):
        source = self.root / "input.json"
        if raw is not None:
            source.write_bytes(raw)
        output = output or self.root / "report.json"
        args = [part for path in (inputs or [source]) for part in ("--artifact", str(path))]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as stderr:
            try:
                code = self.tool.main([*args, "--output", str(output), *extra])
            except SystemExit as error:
                code = error.code
        return code, stderr.getvalue(), output

    def test_unicode_raw_binding_sections_and_failure_are_exact(self):
        before = deepcopy(self.value)
        raw = json.dumps(self.value, ensure_ascii=False, indent=2).encode() + b"\n"
        report = self.account(self.value, raw)
        self.assertEqual((report["inputBytes"], report["inputSha256"]), (len(raw), "sha256:" + hashlib.sha256(raw).hexdigest()))
        self.assertEqual(report["canonicalPayloadBytes"], len(core.canonical_json_bytes(self.value)))
        self.assertEqual(report["sectionValueBytes"], {k: len(core.canonical_json_bytes(v)) for k, v in self.value.items()})
        self.assertEqual((report["artifactFormat"], report["artifactId"], report["nativeStatus"]),
                         (checker.OBSERVATION_FORMAT, self.value["observationId"], "execution-error"))
        self.assertEqual(report["nativeResult"], self.value["result"])
        self.assertEqual(self.value, before)

    def test_all_formats_source_content_and_embedded_listings(self):
        outer, source, candidate = self.envelopes()
        for value in (self.observation(goal=True), candidate, outer, source):
            with self.subTest(format=value["format"]):
                report = self.account(value)
                self.assertEqual(report["artifactFormat"], value["format"])
                self.assertEqual(report["canonicalPayloadBytes"], len(core.canonical_json_bytes(value)))
        for value, key in ((outer, "typeObservation"), (source, "observation")):
            report = self.account(value)
            snapshots = {"client": value["clientSnapshot"], "workspace": value[key]["snapshot"],
                         "dependency": value["library" if key == "typeObservation" else "dependency"]["evidence"]["components"]["snapshot.json"]}
            self.assertEqual(report["snapshotFileCounts"], {k: len(s["files"]) for k, s in snapshots.items()})
            self.assertEqual(report["sourceContentBytes"], {k: sum(f["size"] for f in s["files"]) for k, s in snapshots.items()})
        report = self.account(source)
        self.assertEqual(report["embeddedSourceListingBytes"], len(core.canonical_json_bytes(source["listing"])))
        self.assertEqual(report["embeddedNativeListingBytes"], len(core.canonical_json_bytes(source["observation"]["listing"])))

    def test_byte_binding_mismatch_rejected(self):
        changed = deepcopy(self.value)
        changed["transport"]["message"] = "different"
        with self.assertRaises(self.tool.AccountingError):
            self.account(self.value, core.canonical_json_bytes(changed))

    def test_same_id_and_rehashed_semantic_tampering_rejected(self):
        for rehash in (False, True):
            for field in ("result", "source"):
                changed = deepcopy(self.value)
                if field == "result":
                    changed["result"] = dict(status="inferred", type="Set")
                else:
                    changed["query"]["sourceSha256"] = "sha256:" + "0" * 64
                if rehash:
                    changed["observationId"] = checker.observation_id(changed)
                with self.subTest(rehash=rehash, field=field), self.assertRaises(self.tool.AccountingError):
                    self.account(changed)

    def test_rehashed_embedded_evidence_tamper_rejected(self):
        outer, source, _ = self.envelopes()
        for value, key, id_key, identify in ((outer, "library", "clientObservationId", client.client_observation_id),
                                            (source, "dependency", "sourceObservationId", sources.source_observation_id)):
            changed = deepcopy(value)
            changed[key]["evidence"]["components"]["diagnostics.json"]["unbound"] = True
            changed[id_key] = identify(changed)
            with self.assertRaises(self.tool.AccountingError):
                self.account(changed)

    def test_fifo_differential_randomized(self):
        rng = random.Random(731)
        for _ in range(120):
            sizes, cap, count = [rng.randint(1, 18) for _ in range(rng.randint(0, 25))], rng.randint(1, 30), rng.randint(1, 5)
            expected, events = [], []
            for index, size in enumerate(sizes):
                evicted = []
                if size <= cap:
                    while len(expected) >= count or sum(sizes[i] for i in expected) + size > cap:
                        evicted.append(expected.pop(0))
                    expected.append(index)
                events.append(dict(inputIndex=index, payloadBytes=size, accepted=size <= cap, evictedInputIndexes=evicted,
                                   retainedInputIndexes=expected.copy(), storedBytes=sum(sizes[i] for i in expected)))
            actual = self.tool.simulate_history(sizes, max_records=count, max_stored_bytes=cap)
            self.assertEqual(actual["events"], events)
            self.assertEqual((actual["retainedInputIndexes"], actual["storedBytes"]), (expected, sum(sizes[i] for i in expected)))

    def test_oversize_arrival_does_not_evict_and_exact_limit_is_accepted(self):
        result = self.tool.simulate_history([2, 3, 6, 5], max_records=2, max_stored_bytes=5)
        self.assertEqual(result["events"][2], dict(inputIndex=2, payloadBytes=6, accepted=False,
                         evictedInputIndexes=[], retainedInputIndexes=[0, 1], storedBytes=5))
        self.assertEqual(result["events"][3]["evictedInputIndexes"], [0, 1])
        self.assertEqual(result["retainedInputIndexes"], [3])

    def test_fifo_rejects_nonpositive_and_boolean_sizes_or_limits(self):
        for sizes in ([True], [False], [-1], [0], [1.0], ["1"], (1,), None):
            with self.subTest(sizes=sizes), self.assertRaises(self.tool.ConfigurationError):
                self.tool.simulate_history(sizes)
        for name in ("max_records", "max_stored_bytes"):
            for value in (True, False, 0, -1, 1.0, "1"):
                with self.subTest(name=name, value=value), self.assertRaises(self.tool.ConfigurationError):
                    self.tool.simulate_history([1], **{name: value})

    def test_cli_success_is_diagnostic_and_preserves_sources(self):
        raw = core.canonical_json_bytes(self.value) + b"\n"
        code, error, output = self.cli(raw, inputs=[self.root / "input.json"] * 2, extra=["--max-records", "1"])
        self.assertEqual(code, 0, error)
        report = json.loads(output.read_bytes())
        self.assertEqual(report["format"], "evidence-accounting-diagnostic-v1")
        self.assertIn("not", report["scope"].lower())
        for word in ("process-memory", "freshness", "native-conformance"):
            self.assertIn(word, report["scope"])
        self.assertEqual(report["history"]["retainedInputIndexes"], [1])
        self.assertEqual(report["records"][0]["inputSha256"], report["records"][1]["inputSha256"])
        self.assertEqual((self.root / "input.json").read_bytes(), raw)

    def test_cli_strict_json_and_unknown_formats_are_controlled_errors(self):
        for raw in (b'{"format":1,"format":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
                    b'{"x":1e9999}', b'{"format":"unknown"}', b'[]', b'null', b'\xff', b'{'):
            with self.subTest(raw=raw):
                code, _, output = self.cli(raw)
                self.assertEqual(code, 1)
                self.assertFalse(output.exists())

    def test_cli_existing_output_and_exact_input_alias_never_overwrite(self):
        raw = core.canonical_json_bytes(self.value)
        output = self.root / "existing.json"
        output.write_bytes(b"keep")
        for destination in (output, self.root / "input.json"):
            code, _, _ = self.cli(raw, output=destination)
            self.assertEqual(code, 2)
        self.assertEqual(output.read_bytes(), b"keep")
        self.assertEqual((self.root / "input.json").read_bytes(), raw)

    def test_cli_symlink_and_hardlink_output_aliases_rejected(self):
        source = self.root / "input.json"
        source.write_bytes(core.canonical_json_bytes(self.value))
        for name, create in (("symlink", lambda p: p.symlink_to(source)), ("hardlink", lambda p: os.link(source, p))):
            link = self.root / name
            try:
                create(link)
            except (OSError, NotImplementedError):
                continue  # Some Windows/filesystem configurations do not permit links.
            with self.subTest(kind=name):
                self.assertEqual(self.cli(output=link)[0], 2)
                self.assertEqual(link.read_bytes(), source.read_bytes())
                if name == "symlink":
                    self.assertEqual(self.cli(inputs=[link])[0], 2)

    def test_cli_nonregular_missing_input_and_bad_limits_are_configuration_errors(self):
        for inputs in ([self.root], [self.root / "missing"]):
            self.assertEqual(self.cli(inputs=inputs)[0], 2)
        for extra in (["--max-records", "0"], ["--max-stored-bytes", "-1"], ["--max-input-bytes", "0"],
                      ["--max-input-bytes", "67108865"]):
            self.assertEqual(self.cli(core.canonical_json_bytes(self.value), extra=extra)[0], 2)
        self.assertEqual(self.cli(core.canonical_json_bytes(self.value), inputs=[self.root / "input.json"] * 65)[0], 2)

    def test_cli_input_size_bound_rejects_before_accounting(self):
        with patch.object(self.tool, "account_artifact", side_effect=AssertionError("oversize was parsed")):
            code, _, output = self.cli(b" " * 33, extra=["--max-input-bytes", "32"])
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())

    def test_cli_tampering_is_exit_one_not_native_success(self):
        changed = deepcopy(self.value)
        changed["result"] = dict(status="inferred", type="Set")
        changed["observationId"] = checker.observation_id(changed)
        self.assertEqual(self.cli(core.canonical_json_bytes(changed))[0], 1)

    def test_cli_reads_are_bounded_not_read_all(self):
        raw = core.canonical_json_bytes(self.value)
        reads, original = [], os.fdopen

        class Probe:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def __getattr__(self, name):
                return getattr(self.stream, name)
            def read(self, size=-1):
                if size < 0:
                    raise AssertionError("unbounded input read")
                reads.append(size)
                return self.stream.read(size)

        with patch.object(self.tool.os, "fdopen", side_effect=lambda *args: Probe(original(*args))):
            code, error, _ = self.cli(raw, extra=["--max-input-bytes", str(len(raw))])
        self.assertEqual(code, 0, error)
        self.assertEqual(reads, [len(raw) + 1])

    def test_cli_aggregate_input_limit_without_large_allocations(self):
        raw = core.canonical_json_bytes(self.value)
        # Scale only the ceiling, keeping real regular-file reads and validators.
        with patch.object(self.tool, "MAX_TOTAL_BYTES", len(raw) * 2 - 1), \
             patch.object(self.tool, "account_artifact", wraps=self.tool.account_artifact) as account:
            code, _, output = self.cli(raw, inputs=[self.root / "input.json"] * 2,
                                       extra=["--max-input-bytes", str(len(raw))])
        self.assertEqual(code, 2)
        self.assertEqual(account.call_count, 1)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
