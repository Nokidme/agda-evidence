"""Editor facade contracts; fake wire evidence is not a claim of kernel checking."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agda_evidence import candidates, catalog, core, goals, research

# Independent of other test modules. Metadata/config/logs remain outside the
# pinned project. Actual capture, transport, staging and validators run normally.
FAKE = r'''
import json
from pathlib import Path
import sys
CONFIG, LOG, APP = map(Path, __PATHS__)
if "--version" in sys.argv:
    print("Agda version 2.6.3-research-fixture")
    sys.exit(0)
if "--print-agda-app-dir" in sys.argv:
    print(APP)
    sys.exit(0)
if "--interaction-json" not in sys.argv:
    sys.exit(2)
config = json.loads(CONFIG.read_text())
point = {"id": 0, "range": [{"start": {"pos": 30, "line": 2, "col": 12},
                                "end": {"pos": 35, "line": 2, "col": 17}}]}
summary = {"kind": "AllGoalsWarnings", "visibleGoals": [
    {"kind": "OfType", "constraintObj": point, "type": "Nat"}],
    "invisibleGoals": [], "warnings": [], "errors": []}
if config.get("blocked"):
    summary["warnings"] = [{"message": "fixture warning"}]
def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)
def display(info):
    emit({"kind": "DisplayInfo", "info": info})
def prompt():
    print("JSON> ", end="", flush=True)
prompt()
for command in sys.stdin:
    with LOG.open("a") as stream:
        stream.write(json.dumps(command) + "\n")
    if "Cmd_load" in command:
        Path("generated.agdai").write_bytes(b"staged only")
        display(summary)
        emit({"kind": "InteractionPoints", "interactionPoints": [point]})
    elif "Cmd_metas AsIs" in command:
        display(summary)
    elif "Cmd_goal_type_context" in command:
        check = "Cmd_goal_type_context_check" in command
        if check and config.get("checkError"):
            display({"kind": "Error", "message": "fixture type mismatch λ"})
        else:
            aux = {"kind": "GoalAndElaboration", "term": "n"} if check else {"kind": "GoalOnly"}
            display({"kind": "GoalSpecific", "interactionPoint": point,
                     "goalInfo": {"kind": "GoalType", "rewrite": "Simplified", "type": "Nat",
                         "typeAux": aux, "entries": [{"originalName": "n", "reifiedName": "n",
                         "binding": "Nat", "inScope": True}], "boundary": [], "outputForms": []}})
    else:
        sys.exit(3)
    prompt()
'''
DEFAULT = object()


@unittest.skipUnless(os.name == "posix", "native interaction adapter requires POSIX")
class ResearchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="research-contract-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.project = self.home / "project λ"
        self.project.mkdir()
        self.source = self.project / "Main.agda"
        self.source.write_text("module Main where\ndata Nat : Set where\n  zero : Nat\n"
                               "local : Nat → Nat\nlocal n = {! !}\n"
                               "other : Nat\nother = {! !}\n", encoding="utf-8")
        (self.project / "notes.txt").write_bytes(b"whole snapshot input\n")
        self.app = self.home / "registry"
        self.app.mkdir()
        environment = patch.dict(os.environ, {"AGDA_DIR": str(self.app)})
        environment.start()
        self.addCleanup(environment.stop)
        self.config, self.log = self.home / "config.json", self.home / "commands.jsonl"
        self.configure()
        self.binary = self.home / "fake agda λ;not-shell"
        self.binary.write_text(f"#!{sys.executable}\n" + FAKE.replace(
            "__PATHS__", repr(tuple(map(str, (self.config, self.log, self.app))))), encoding="utf-8")
        self.binary.chmod(0o755)
        self.workspace = self.make_workspace()
        self.rev = self.status()["currentRevision"]

    def make_workspace(self, **options):
        return research.ResearchWorkspace(self.project, {"main": "Main.agda"},
                                          agda_binary=str(self.binary), **options)

    def configure(self, **options):
        self.config.write_text(json.dumps(options), encoding="utf-8")

    def call(self, op, args=None, *, revision=DEFAULT, workspace=None):
        if revision is DEFAULT:
            revision = None if op in {"workspace.status", "record.get"} else self.rev
        return (workspace or self.workspace).handle({"requestId": "request-λ", "op": op,
                                                   "revision": revision, "args": args or {}})

    def status(self, **options):
        result = self.call("workspace.status", **options)
        self.assertEqual(result["status"], "ok", result)
        return result

    def listed(self, **options):
        result = self.call("goals.list", {"documentId": "main"}, **options)
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["result"]["outcome"]["status"], "listed", result)
        return result

    def select(self, listing, **options):
        return {"listingId": listing["recordId"], "goalId": 0, **options}

    def get(self, record_id, **options):
        return self.call("record.get", {"recordId": record_id}, **options)

    def error(self, response, code):
        self.assertEqual(response["status"], "error", response)
        self.assertEqual(response["error"]["code"], code, response)

    def tree(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes()
                for p in self.project.rglob("*") if p.is_file()}

    def test_public_roundtrip_envelopes_full_artifacts_and_host_policy(self):
        before = self.tree()
        workspace = self.make_workspace(includes=(".",), safe=True, timeout_seconds=7,
                                        max_output_bytes=8192, max_records=8, max_stored_bytes=500000)
        status = self.status(workspace=workspace)
        self.assertEqual(set(status), {"apiVersion", "requestId", "op", "revision", "currentRevision",
                                      "workspace", "status", "recordId", "result", "error"})
        self.assertEqual(status["apiVersion"], 1)
        self.assertEqual(set(status["workspace"]), {"sourceId", "resolutionId"})
        self.assertEqual(status["result"]["documentIds"], ["main"])
        self.assertTrue(status["result"]["compilerAvailable"])
        self.assertFalse(status["result"]["buffersDirty"])
        self.assertFalse(status["result"]["catalogConfigured"])
        self.assertEqual(status["result"]["limits"], {"timeoutSeconds": 7, "maxOutputBytes": 8192,
                                                    "maxRecords": 8, "maxStoredBytes": 500000})
        revision = status["currentRevision"]
        listing = self.listed(workspace=workspace, revision=revision)
        inspected = self.call("goals.inspect", self.select(listing), workspace=workspace, revision=revision)
        checked = self.call("candidate.check", self.select(listing, expression="n"),
                            workspace=workspace, revision=revision)
        for response, kind, outcome in ((listing, "listing", "listed"), (inspected, "inspection", "inspected"),
                                        (checked, "candidate", "elaborated")):
            self.assertEqual(response["status"], "ok", response)
            self.assertIsNone(response["error"])
            self.assertEqual(response["revision"], revision)
            self.assertEqual(response["result"]["outcome"]["status"], outcome)
            record = self.get(response["recordId"], workspace=workspace)["result"]
            artifact = record["artifact"]
            self.assertEqual(record["kind"], kind)
            self.assertEqual(record["documentId"], "main")
            self.assertEqual(record["freshness"], "current")
            self.assertEqual(record["recordRevision"], revision)
            self.assertEqual(artifact["observationId"], response["result"]["observationId"])
            self.assertNotEqual(response["recordId"], artifact["observationId"])
            self.assertTrue(artifact["query"]["safe"])
            self.assertEqual(artifact["resolution"]["resolutionStatus"], "partial")
            self.assertIn("notes.txt", {item["path"] for item in artifact["snapshot"]["files"]})
            self.assertEqual(artifact["execution"]["timeoutSeconds"], 7)
            self.assertEqual(artifact["execution"]["maxOutputBytes"], 8192)
            with patch("subprocess.Popen", side_effect=AssertionError("offline validation spawned Agda")):
                validate = candidates.validate_candidate_observation if kind == "candidate" else goals.validate_goal_observation
                self.assertEqual(validate(artifact), artifact)
        self.assertEqual(checked["result"]["outcome"]["assurance"], "contextual-elaboration-only")
        self.configure(checkError=True)
        rejected = self.call("candidate.check", self.select(listing, expression="λ x → x"),
                             workspace=workspace, revision=revision)
        self.assertEqual(rejected["status"], "ok", rejected)
        self.assertEqual(rejected["result"]["outcome"]["status"], "query-error")
        candidates.validate_candidate_observation(self.get(rejected["recordId"], workspace=workspace)["result"]["artifact"])
        self.assertEqual(self.tree(), before)
        self.assertFalse(list(self.project.rglob("*.agdai")))

    def test_request_boundary_rejects_uploads_host_controls_and_sanitizes_echo(self):
        valid = {"requestId": "req", "op": "goals.list", "revision": self.rev, "args": {"documentId": "main"}}
        cases = [None, [], {}, {**valid, "extra": True}, {k: v for k, v in valid.items() if k != "args"},
                 {**valid, "op": "run"}, {**valid, "args": []}, {**valid, "revision": None},
                 {**valid, "args": {"documentId": "../Main.agda"}}]
        for field in ("projectRoot", "agdaBinary", "includes", "safe", "catalog", "observation", "path", "flags"):
            cases.append({**valid, "args": {**valid["args"], field: "/host/secret"}})
        for field in ("requestId", "op", "revision"):
            for value in ({"secret": "/host/secret"}, ["/host/secret"], "bad\ncontrol", "x" * 5000, "\ud800"):
                cases.append({**valid, field: value})
        with patch.object(research, "build_snapshot", side_effect=AssertionError("invalid request probed inputs")) as probe:
            for request in cases:
                with self.subTest(request_type=type(request).__name__, fields=list(request) if isinstance(request, dict) else None):
                    response = self.workspace.handle(request)
                    self.error(response, "invalid-request")
                    self.assertNotIn("/host/secret", json.dumps(response))
                    json.dumps(response, ensure_ascii=False).encode("utf-8")
            probe.assert_not_called()

    def test_selection_requires_session_record_and_accepted_leaf_listing(self):
        listing = self.listed()
        inspected = self.call("goals.inspect", self.select(listing))
        candidate = self.call("candidate.check", self.select(listing, expression="n"))
        artifact_id = listing["result"]["observationId"]
        other = self.make_workspace()
        with patch.object(research, "build_snapshot", side_effect=AssertionError("unknown record probed inputs")) as probe:
            for record_id in ("unknown", artifact_id, str(self.home / "artifact.json")):
                self.error(self.get(record_id), "record-unavailable")
                self.error(self.call("goals.inspect", {"listingId": record_id, "goalId": 0}), "record-unavailable")
            self.error(self.get(listing["recordId"], workspace=other), "record-unavailable")
            for record_id in (inspected["recordId"], candidate["recordId"]):
                self.error(self.call("goals.inspect", {"listingId": record_id, "goalId": 0}), "invalid-request")
            self.error(self.call("goals.inspect", self.select(listing, goalId=99)), "invalid-request")
            probe.assert_not_called()
        self.configure(blocked=True)
        blocked = self.call("goals.list", {"documentId": "main"})
        self.assertEqual(blocked["status"], "ok")
        self.assertEqual(blocked["result"]["outcome"]["status"], "load-blocked")
        self.error(self.call("goals.inspect", self.select(blocked)), "invalid-request")

    def test_dirty_notifications_even_identical_save_and_revert_invalidate_history(self):
        listing = self.listed()
        original_revision = self.rev
        dirty = self.workspace.notify_buffers(dirty=True)
        self.assertNotEqual(dirty, original_revision)
        self.rev = dirty
        with patch.object(research, "observe_goals") as observe:
            stale = self.call("goals.list", {"documentId": "main"})
            self.assertEqual(stale["status"], "stale")
            observe.assert_not_called()
        self.assertTrue(self.status()["result"]["buffersDirty"])
        self.assertEqual(self.get(listing["recordId"])["result"]["freshness"], "stale")
        self.rev = self.workspace.notify_buffers(dirty=False)
        self.assertNotEqual(self.rev, dirty)
        self.assertFalse(self.status()["result"]["buffersDirty"])
        stale = self.call("goals.inspect", self.select(listing))
        self.assertEqual(stale["error"]["code"], "listing-stale")
        fresh = self.listed()
        self.assertNotEqual(fresh["recordId"], listing["recordId"])
        self.assertEqual(fresh["result"]["observationId"][:7], "sha256:")
        clean = self.workspace.notify_buffers(dirty=False)
        self.assertNotEqual(clean, self.rev)  # A same-content save is still an event.
        self.rev = clean
        self.assertEqual(self.call("goals.inspect", self.select(fresh))["status"], "stale")
        with self.assertRaises(core.EvidenceError):
            self.workspace.notify_buffers(dirty="false")

    def test_whole_snapshot_and_native_resolution_refresh_invalidate_old_revision(self):
        previous = self.status()
        for change in (lambda: (self.project / "unrelated.txt").write_bytes(b"added"),
                       lambda: (self.project / "unrelated.txt").unlink(),
                       lambda: (self.project / "notes.txt").write_bytes(b"edited"),
                       lambda: self.binary.write_bytes(self.binary.read_bytes() + b"\n# changed compiler\n"),
                       lambda: (self.app / "libraries").write_text("/missing-library.agda-lib\n")):
            listing = self.listed()
            change()
            with patch.object(research, "observe_goals") as observe:
                stale = self.call("goals.inspect", self.select(listing))
                self.assertEqual(stale["status"], "stale", stale)
                observe.assert_not_called()
            current = self.status()
            self.assertNotEqual(current["currentRevision"], previous["currentRevision"])
            self.assertNotEqual(current["workspace"], previous["workspace"])
            self.assertEqual(self.get(listing["recordId"])["result"]["freshness"], "stale")
            self.rev = current["currentRevision"]
            previous = current

    def test_after_list_reobserves_success_native_failure_and_all_exceptions(self):
        real_observe = research.observe_goals
        for mode in ("success", "native-error", "evidence-error", "os-error", "unexpected"):
            with self.subTest(mode=mode):
                self.rev = self.status()["currentRevision"]
                self.configure(blocked=mode == "native-error")
                def work(*args, **options):
                    artifact = real_observe(*args, **options) if mode in {"success", "native-error"} else None
                    (self.project / "notes.txt").write_text(mode)
                    if mode not in {"success", "native-error"}:
                        raise {"evidence-error": goals.GoalEvidenceError, "os-error": OSError,
                               "unexpected": RuntimeError}[mode](str(self.home / "secret"))
                    return artifact
                with patch.object(research, "observe_goals", side_effect=work):
                    response = self.call("goals.list", {"documentId": "main"})
                self.assertEqual(response["status"], "stale", response)
                self.assertNotEqual(response["currentRevision"], self.rev)
                self.assertNotIn(str(self.home), json.dumps(response))
                if mode in {"success", "native-error"}:
                    record = self.get(response["recordId"])["result"]
                    self.assertEqual(record["freshness"], "stale")
                    goals.validate_goal_observation(record["artifact"])
                else:
                    self.assertIsNone(response["recordId"])
        self.configure()
        self.rev = self.status()["currentRevision"]
        for exception, code in ((RuntimeError, "internal-error"), (OSError, "workspace-unavailable"),
                                (goals.GoalEvidenceError, "evidence-invalid")):
            with patch.object(research, "observe_goals", side_effect=exception(str(self.home / "secret"))):
                response = self.call("goals.list", {"documentId": "main"})
            self.error(response, code)
            self.assertNotIn(str(self.home), json.dumps(response))
        self.listed()  # Every error path releases the nonblocking operation lock.

    def test_candidate_and_search_recheck_after_work_and_notified_edit_revert(self):
        real_check = research.check_candidate
        for fail in (False, True):
            self.rev = self.status()["currentRevision"]
            listing = self.listed()
            def work(*args, **options):
                artifact = real_check(*args, **options) if not fail else None
                self.binary.write_bytes(self.binary.read_bytes() + b"\n# after candidate\n")
                if fail:
                    raise RuntimeError("secret compiler failure")
                return artifact
            with patch.object(research, "check_candidate", side_effect=work):
                response = self.call("candidate.check", self.select(listing, expression="n"))
            self.assertEqual(response["status"], "stale", response)
            if not fail:
                retained = self.get(response["recordId"])["result"]
                self.assertEqual(retained["freshness"], "stale")
                candidates.validate_candidate_observation(retained["artifact"])
        build_index = research.build_declaration_index
        for fail in (False, True):
            self.rev = self.status()["currentRevision"]
            listing = self.listed()
            def index(*args, **options):
                result = build_index(*args, **options)
                before = self.source.read_bytes()
                self.workspace.notify_buffers(dirty=True)
                self.source.write_bytes(before + b"-- edit\n")
                self.source.write_bytes(before)
                self.workspace.notify_buffers(dirty=False)
                if fail:
                    raise RuntimeError("secret failed lexical index")
                return result
            with patch.object(research, "build_declaration_index", side_effect=index):
                response = self.call("library.search", self.select(listing, prefix="Main", scope="project"))
            self.assertEqual(response["status"], "stale", response)
            self.assertEqual(response["workspace"], listing["workspace"])
            self.assertNotEqual(response["currentRevision"], self.rev)

    def test_nonblocking_busy_allows_status_notifications_and_releases_on_error(self):
        entered, release = threading.Event(), threading.Event()
        replies = []
        def pending(*args, **options):
            entered.set()
            if not release.wait(10):
                raise AssertionError("test worker was not released")
            raise RuntimeError("worker failure")
        with patch.object(research, "observe_goals", side_effect=pending):
            thread = threading.Thread(target=lambda: replies.append(self.call("goals.list", {"documentId": "main"})))
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.error(self.call("goals.list", {"documentId": "main"}), "workspace-busy")
                self.assertEqual(self.status()["status"], "ok")
                self.workspace.notify_buffers(dirty=True)
                self.workspace.notify_buffers(dirty=False)
            finally:
                release.set()
                thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["status"], "stale", replies)
        self.rev = self.status()["currentRevision"]
        self.listed()

    def test_project_search_is_bounded_lexical_discovery_not_candidate_or_scope(self):
        listing = self.listed()
        before = self.tree()
        with patch.object(research, "observe_goals") as observe, patch.object(research, "check_candidate") as check:
            response = self.call("library.search", self.select(listing, prefix="Main", scope="project", limit=1))
            self.assertEqual(response["status"], "ok", response)
            result = response["result"]
            self.assertEqual(len(result["entries"]), 1)
            self.assertTrue(result["truncated"])
            self.assertGreater(result["totalMatches"], 1)
            self.assertIs(result["contextualRanking"], False)
            self.assertEqual(result["context"], self.select(listing))
            self.assertIsNone(response["recordId"])
            exact = self.call("library.search", self.select(listing, exact="Main.local", kinds=["signature"]))
            self.assertEqual([hit["qualifiedName"] for hit in exact["result"]["entries"]], ["Main.local"])
            for hit in result["entries"] + exact["result"]["entries"]:
                self.assertEqual(hit["origin"], "project")
                self.assertEqual(hit["scopeStatus"], "not-established")
                self.assertEqual(hit["candidateUsability"], "not-tested")
                self.assertEqual(hit["evidence"]["sourceId"], response["workspace"]["sourceId"])
                self.assertIn("indexId", hit["evidence"])
            missing = self.call("library.search", self.select(listing, exact="NotPresent"))
            self.assertEqual(missing["result"]["entries"], [])
            self.error(self.call("library.search", self.select(listing, prefix="Main", scope="catalog")), "catalog-unavailable")
            observe.assert_not_called()
            check.assert_not_called()
        self.assertEqual(self.tree(), before)

    def test_host_catalog_validates_all_entries_without_mounting_or_implied_scope(self):
        bundles = []
        for name in ("alpha", "zeta"):
            project = self.home / name
            project.mkdir()
            (project / "Shared.agda").write_text("module Shared where\nvalue : Set\n", encoding="utf-8")
            index = self.home / f"{name}.index.json"
            core.write_declaration_index(index, core.build_declaration_index(project))
            bundle = self.home / f"{name}.bundle"
            core.capture_bundle(project, bundle, [sys.executable, "-c", "pass"],
                                agda_binary=str(self.binary), index_reference=index)
            bundles.append((name, bundle))
        path = self.home / "catalog.json"
        catalog.create_catalog(path, bundles)
        workspace = self.make_workspace(catalog=path)
        self.rev = self.status(workspace=workspace)["currentRevision"]
        listing = self.listed(workspace=workspace)
        before = self.tree()
        response = self.call("library.search", self.select(listing, exact="Shared.value", libraries=["alpha"]), workspace=workspace)
        self.assertEqual(response["status"], "ok", response)
        self.assertEqual(response["result"]["checkedCatalogEntries"], ["alpha", "zeta"])
        hit, = response["result"]["entries"]
        self.assertEqual(hit["origin"], "catalog")
        self.assertEqual(hit["scopeStatus"], "not-established")
        self.assertEqual(hit["candidateUsability"], "not-tested")
        self.assertEqual(hit["evidence"]["entry"], "alpha")
        checked = self.call("candidate.check", self.select(listing, expression="n"), workspace=workspace)
        artifact = self.get(checked["recordId"], workspace=workspace)["result"]["artifact"]
        self.assertEqual(artifact["query"]["expression"], "n")
        self.assertEqual(artifact["query"]["includes"], ["."])
        self.assertNotEqual(artifact["snapshot"]["sourceId"], hit["evidence"]["sourceId"])
        self.assertEqual(self.tree(), before)
        (bundles[1][1] / "diagnostics.json").unlink()  # Filtered-out entries must still verify.
        self.error(self.call("library.search", self.select(listing, exact="Shared.value", libraries=["alpha"]),
                             workspace=workspace), "catalog-invalid")

    def test_search_selector_expression_validation_and_utf8_boundaries(self):
        listing = self.listed()
        base = self.select(listing, prefix="Main")
        invalid = [{k: v for k, v in base.items() if k != "prefix"}, {**base, "exact": "Main"}]
        for field, values in {"prefix": ["", "x" * 257, "bad\n", "\ud800"], "scope": [[], {}, 1, "unknown"],
                              "limit": [0, 101, True, "1"], "kinds": ["signature", ["bogus"], ["module", "module"]],
                              "libraries": [None, [1], ["alpha", "alpha"], ["x"] * 65],
                              "goalId": [True, -1, "0", None]}.items():
            invalid.extend({**base, field: value} for value in values)
        invalid.append({**base, "scope": "project", "libraries": ["alpha"]})
        with patch.object(research, "build_snapshot", side_effect=AssertionError("bad argument probed inputs")) as probe:
            for args in invalid:
                with self.subTest(fields=list(args), value_type=type(args.get("scope")).__name__):
                    self.error(self.call("library.search", args), "invalid-request")
            for expression in (None, [], 7, "", " \n\t", "\ud800", "x" * 65537, "λ" * 32769):
                self.error(self.call("candidate.check", self.select(listing, expression=expression)), "invalid-request")
            probe.assert_not_called()
        for expression in ("λ" * 32768, "x" * 65536):
            response = self.call("candidate.check", self.select(listing, expression=expression))
            self.assertEqual(response["status"], "ok", response)
            self.assertEqual(self.get(response["recordId"])["result"]["artifact"]["query"]["expression"], expression)
        response = self.call("library.search", self.select(listing, prefix="x" * 256, limit=100))
        self.assertEqual(response["status"], "ok", response)

    def test_store_immutable_input_return_values_and_unavailable_current_inputs(self):
        captured = []
        observe = research.observe_goals
        def capture(*args, **options):
            value = observe(*args, **options)
            captured.append(value)
            return value
        with patch.object(research, "observe_goals", side_effect=capture):
            listing = self.listed()
        record_id = listing["recordId"]
        original = deepcopy(self.get(record_id)["result"]["artifact"])
        captured[0]["result"]["goals"].clear()
        listing["result"]["outcome"]["goals"].clear()
        fetched = self.get(record_id)
        fetched["result"]["artifact"]["snapshot"]["files"].clear()
        fetched["workspace"].clear()
        self.assertEqual(self.get(record_id)["result"]["artifact"], original)
        self.assertEqual(len(self.status()["workspace"]), 2)
        self.project.rename(self.home / "temporarily-unavailable")
        historical = self.get(record_id)
        self.assertEqual(historical["status"], "ok", historical)
        self.assertEqual(historical["result"]["freshness"], "unknown")
        self.assertEqual(historical["result"]["artifact"], original)
        goals.validate_goal_observation(historical["result"]["artifact"])
        self.error(self.get("not-a-record"), "record-unavailable")

    def test_fifo_count_byte_budget_and_oversized_record_do_not_corrupt_store(self):
        workspace = self.make_workspace(max_records=2)
        revision = self.status(workspace=workspace)["currentRevision"]
        first = self.listed(workspace=workspace, revision=revision)
        second = self.listed(workspace=workspace, revision=revision)
        self.get(first["recordId"], workspace=workspace)  # Reading must not change FIFO order.
        third = self.listed(workspace=workspace, revision=revision)
        self.error(self.get(first["recordId"], workspace=workspace), "record-unavailable")
        self.assertEqual(self.get(second["recordId"], workspace=workspace)["status"], "ok")
        self.assertEqual(self.get(third["recordId"], workspace=workspace)["status"], "ok")
        artifact = self.get(second["recordId"], workspace=workspace)["result"]["artifact"]
        size = len(core.canonical_json_bytes(artifact))
        workspace = self.make_workspace(max_records=20, max_stored_bytes=size * 2 + 128)
        revision = self.status(workspace=workspace)["currentRevision"]
        first, second, third = [self.listed(workspace=workspace, revision=revision) for _ in range(3)]
        self.error(self.get(first["recordId"], workspace=workspace), "record-unavailable")
        self.assertEqual(self.get(second["recordId"], workspace=workspace)["status"], "ok")
        self.assertEqual(self.get(third["recordId"], workspace=workspace)["status"], "ok")
        failed = self.call("candidate.check", self.select(third, expression="x" * 65536), workspace=workspace, revision=revision)
        self.error(failed, "store-capacity")
        self.assertIsNone(failed["recordId"])
        self.assertEqual(self.get(second["recordId"], workspace=workspace)["status"], "ok")
        self.assertEqual(self.get(third["recordId"], workspace=workspace)["status"], "ok")
        tiny = self.make_workspace(max_stored_bytes=1024)
        self.error(self.call("goals.list", {"documentId": "main"}, workspace=tiny,
                             revision=self.status(workspace=tiny)["currentRevision"]), "store-capacity")

    @unittest.skipUnless(shutil.which("agda"), "optional native Agda smoke; fake tests remain deterministic")
    def test_real_native_temp_copy_success_error_and_offline_artifacts(self):
        native_project = self.home / "real-native"
        shutil.copytree(ROOT / "examples" / "goal-query", native_project)
        workspace = research.ResearchWorkspace(native_project, {"main": "Main.agda"},
                                               agda_binary=shutil.which("agda"), timeout_seconds=20)
        before = {p.relative_to(native_project).as_posix(): p.read_bytes()
                  for p in native_project.rglob("*") if p.is_file()}
        revision = self.status(workspace=workspace)["currentRevision"]
        listing = self.listed(workspace=workspace, revision=revision)
        self.assertEqual(len(listing["result"]["outcome"]["goals"]), 3)
        for expression, expected in (("n", "elaborated"), ("λ x → x", "query-error")):
            response = self.call("candidate.check", self.select(listing, expression=expression),
                                 workspace=workspace, revision=revision)
            self.assertEqual(response["status"], "ok", response)
            self.assertEqual(response["result"]["outcome"]["status"], expected)
            artifact = self.get(response["recordId"], workspace=workspace)["result"]["artifact"]
            candidates.validate_candidate_observation(artifact)
            self.assertEqual(artifact["result"]["assurance"], "contextual-elaboration-only")
        after = {p.relative_to(native_project).as_posix(): p.read_bytes()
                 for p in native_project.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        self.assertFalse(list(native_project.rglob("*.agdai")))


if __name__ == "__main__":
    unittest.main()
