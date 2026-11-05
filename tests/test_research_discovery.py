"""Discovery cache tests at the editor facade's revision boundary.

The shared mixin supplies fixtures/helpers only. Accepted listings come from an
explicitly fake JSON protocol over real pipes, never from an installed Agda.
Lexical search results remain evidence of candidate heads, not usable proofs.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agda_evidence import catalog, core, research, source_research, sources
from agda_evidence._discovery import _LexicalMemo
from test_source_research import _WorkspaceFixtures, hidden


def workspace_memo(workspace):
    memos = [value for value in vars(workspace).values() if isinstance(value, _LexicalMemo)]
    if len(memos) != 1:
        raise AssertionError("each workspace must own exactly one lexical memo")
    return memos[0]


class _DiscoveryChecks:
    """Shared assertions, deliberately not an inherited existing test class."""
    def search(self, listing, *, workspace=None, revision=None, **filters):
        options = {} if revision is None else {"revision": revision}
        return self.call("library.search", self.select(listing, **filters), workspace=workspace, **options)

    def assert_memo_empty(self, workspace=None):
        memo = workspace_memo(self.workspace if workspace is None else workspace)
        self.assertEqual(len(memo._entries), 0)
        self.assertEqual(memo._stored_bytes, 0)
        self.assertEqual(memo._generation, (self.workspace if workspace is None else workspace)._generation)

    def warm(self):
        listing = self.listed()
        response = self.search(listing, prefix="Main", scope="project")
        self.assertEqual(response["status"], "ok", response)
        self.assertTrue(workspace_memo(self.workspace)._entries)
        return listing, response

    def run_blocked_search(self, listing, *, patch_target, replacement, entered, release, scope="project"):
        replies, errors = [], []
        def work():
            try:
                replies.append(self.search(listing, prefix="Main", scope=scope))
            except BaseException as error:
                errors.append(error)
        with patch_target(replacement):
            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered.wait(10), "search did not reach the race barrier")
                generation = self.workspace._generation
                dirty = self.workspace.notify_buffers(dirty=True)
                self.assertEqual(self.workspace._generation, generation + 1)
                self.assert_memo_empty()
                clean = self.workspace.notify_buffers(dirty=False)
                self.assertNotEqual(dirty, clean)
                self.assertEqual(self.workspace._generation, generation + 2)
                self.assert_memo_empty()
            finally:
                release.set()
                worker.join(20)
        self.assertFalse(worker.is_alive(), "search failed to finish after releasing the barrier")
        self.assertEqual(errors, [])
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["status"], "stale", replies[0])
        self.assertEqual(replies[0]["error"]["code"], "workspace-changed", replies[0])
        self.assert_memo_empty()
        self.rev = self.status()["currentRevision"]
        obsolete = self.search(listing, prefix="Main", scope="project")
        self.assertEqual(obsolete["status"], "stale", obsolete)
        self.assertEqual(obsolete["error"]["code"], "listing-stale", obsolete)
        self.assert_memo_empty()
        fresh = self.listed()
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            current = self.search(fresh, prefix="Main", scope="project")
        self.assertEqual(current["status"], "ok", current)
        scan.assert_called_once()

    def test_project_warm_results_match_uncached_index_without_changing_wire_or_scope(self):
        listing = self.listed()
        canonical = core.build_declaration_index(self.project)
        expected = core.query_declaration_index(canonical, prefix="Main")
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            first = self.search(listing, prefix="Main", scope="project")
            second = self.search(listing, prefix="Main", scope="project")
        scan.assert_called_once()
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ok", first)
        self.assertEqual(first["apiVersion"], self.version_number)
        self.assertIsNone(first["recordId"])
        self.assertEqual(set(first["result"]), {"entries", "totalMatches", "truncated", "checkedCatalogEntries", "contextualRanking", "context"})
        self.assertEqual(first["result"]["context"], {"listingId": listing["recordId"], "goalId": 0})
        self.assertIs(first["result"]["contextualRanking"], False)
        self.assertEqual(first["result"]["checkedCatalogEntries"], [])
        self.assertEqual(first["result"]["totalMatches"], len(expected))
        self.assertFalse(first["result"]["truncated"])
        for hit, raw in zip(first["result"]["entries"], expected):
            self.assertEqual({key: hit[key] for key in raw}, raw)
            self.assertEqual(hit["origin"], "project")
            self.assertEqual(hit["evidence"], {"sourceId": canonical["sourceId"], "indexId": canonical["indexId"]})
            self.assertEqual(hit["scopeStatus"], "not-established")
            self.assertEqual(hit["candidateUsability"], "not-tested")
        detached = deepcopy(second)
        first["result"]["entries"][0]["qualifiedName"] = "Caller.Forged"
        first["result"]["entries"][0]["evidence"].clear()
        first["result"]["entries"].clear()
        self.assertEqual(self.search(listing, prefix="Main", scope="project"), detached)

    def test_other_workspace_has_its_own_memo_and_does_not_borrow_warm_entries(self):
        listing, _ = self.warm()
        other = self.make_workspace()
        revision = self.status(workspace=other)["currentRevision"]
        other_listing = self.listed(workspace=other, revision=revision)
        self.assertIsNot(workspace_memo(other), workspace_memo(self.workspace))
        self.assert_memo_empty(other)
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            own = self.search(listing, prefix="Main", scope="project")
            second = self.search(other_listing, workspace=other, revision=revision, prefix="Main", scope="project")
        scan.assert_called_once()
        self.assertEqual(own["result"]["entries"], second["result"]["entries"])
        other.notify_buffers(dirty=False)
        self.assert_memo_empty(other)
        self.assertTrue(workspace_memo(self.workspace)._entries)

    def test_notify_during_scanner_clears_each_generation_and_does_not_reinsert_old_work(self):
        listing = self.listed()
        entered, release = threading.Event(), threading.Event()
        scanner = core._lexical_candidates_for_file
        def blocked(*args):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("scanner release timed out")
            return scanner(*args)
        self.run_blocked_search(listing, patch_target=lambda fn: patch.object(core, "_lexical_candidates_for_file", side_effect=fn),
                                replacement=blocked, entered=entered, release=release)

    def test_notify_before_search_begins_uses_generation_captured_at_admission(self):
        listing = self.listed()
        entered, release = threading.Event(), threading.Event()
        admitted = self.workspace._generation
        search = self.workspace._search
        generations = []
        def blocked(*args, **options):
            generations.append(options.get("_generation"))
            entered.set()
            if not release.wait(10):
                raise RuntimeError("search release timed out")
            return search(*args, **options)
        self.run_blocked_search(listing, patch_target=lambda fn: patch.object(self.workspace, "_search", side_effect=fn),
                                replacement=blocked, entered=entered, release=release)
        self.assertEqual(generations, [admitted])

    def test_observed_source_change_and_revert_clear_cache_without_reactivating_history(self):
        listing, _ = self.warm()
        original = (self.project / "notes.txt").read_bytes()
        generation = self.workspace._generation
        (self.project / "notes.txt").write_bytes(original + b"unnotified edit\n")
        changed = self.status()
        self.assertGreater(self.workspace._generation, generation)
        self.assert_memo_empty()
        (self.project / "notes.txt").write_bytes(original)
        restored = self.status()
        self.assertNotEqual(changed["currentRevision"], restored["currentRevision"])
        self.assert_memo_empty()
        self.rev = restored["currentRevision"]
        stale = self.search(listing, prefix="Main", scope="project")
        self.assertEqual(stale["error"]["code"], "listing-stale", stale)
        fresh = self.listed()
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            response = self.search(fresh, prefix="Main", scope="project")
        self.assertEqual(response["status"], "ok", response)
        scan.assert_called_once()

    def test_observation_failure_clears_and_restoration_never_reactivates_old_generation(self):
        listing, _ = self.warm()
        generation = self.workspace._generation
        with hidden(self.project):
            response = self.call("workspace.status")
            self.error(response, "freshness-unavailable")
            self.assertGreater(self.workspace._generation, generation)
            self.assert_memo_empty()
        self.rev = self.status()["currentRevision"]
        self.assert_memo_empty()
        old = self.search(listing, prefix="Main", scope="project")
        self.assertEqual(old["error"]["code"], "listing-stale", old)
        fresh = self.listed()
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            response = self.search(fresh, prefix="Main", scope="project")
        self.assertEqual(response["status"], "ok", response)
        scan.assert_called_once()

    def test_central_generation_advance_invalidates_memo_and_old_build_cannot_repopulate(self):
        self.warm()
        admitted = self.workspace._generation
        snapshot = core.build_snapshot(self.project)[0]
        with self.workspace._state:
            self.workspace._advance_generation_locked()
        self.assertEqual(self.workspace._generation, admitted + 1)
        self.assert_memo_empty()
        obsolete = self.workspace._build_discovery_index(self.project, snapshot, generation=admitted,
                                                         _builder=core._build_declaration_index)
        self.assertEqual(obsolete, core.build_declaration_index(self.project, snapshot))
        self.assert_memo_empty()
        fresh = self.workspace._build_discovery_index(self.project, snapshot, generation=self.workspace._generation,
                                                      _builder=core._build_declaration_index)
        self.assertEqual(fresh, obsolete)
        self.assertTrue(workspace_memo(self.workspace)._entries)


@unittest.skipUnless(os.name == "posix", "fake native pipe fixture requires POSIX")
class ResearchDiscoveryTests(_DiscoveryChecks, _WorkspaceFixtures, unittest.TestCase):
    version_number = 1

    def make_workspace(self, **options):
        return research.ResearchWorkspace(self.project, {"main": "Main.agda"}, agda_binary=str(self.binary), **options)

    def request(self, *args, **options):
        request = super().request(*args, **options)
        del request["apiVersion"]
        return request

    def test_observed_compiler_change_clears_v1_cache_on_change_and_revert(self):
        listing, _ = self.warm()
        original = self.binary.read_bytes()
        self.binary.write_bytes(original + b"\n# compiler identity changed\n")
        changed = self.status()
        self.assert_memo_empty()
        self.binary.write_bytes(original)
        restored = self.status()
        self.assertNotEqual(changed["currentRevision"], restored["currentRevision"])
        self.assert_memo_empty()
        self.rev = restored["currentRevision"]
        self.assertEqual(self.search(listing, prefix="Main", scope="project")["error"]["code"], "listing-stale")


@unittest.skipUnless(os.name == "posix", "fake native pipe fixture requires POSIX")
class SourceResearchDiscoveryTests(_DiscoveryChecks, _WorkspaceFixtures, unittest.TestCase):
    version_number = 2

    def test_project_and_dependency_warm_indexes_preserve_full_distinct_provenance(self):
        listing = self.listed()
        indexes = {"project": core.build_declaration_index(self.project), "dependency": core.build_declaration_index(self.library)}
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan, \
             patch.object(source_research, "observe_source_goals", side_effect=AssertionError("search ran native research")):
            first = self.search(listing, prefix="L", scope="all")
            warm = self.search(listing, prefix="L", scope="all")
            project = self.search(listing, exact="Main.identityproof", scope="project")
            dependency = self.search(listing, exact="Library.identity", scope="dependency")
        self.assertEqual(scan.call_count, 2)
        self.assertEqual(first, warm)
        self.assertEqual(first["status"], "ok", first)
        self.assertEqual(project["status"], "ok", project)
        self.assertEqual(dependency["status"], "ok", dependency)
        for response in (project, dependency):
            hit, = response["result"]["entries"]
            index = indexes[hit["origin"]]
            self.assertEqual(hit["evidence"]["sourceId"], index["sourceId"])
            self.assertEqual(hit["evidence"]["indexId"], index["indexId"])
            raw, = core.query_declaration_index(index, exact=hit["qualifiedName"])
            self.assertEqual({key: hit[key] for key in raw}, raw)
            self.assertEqual(hit["scopeStatus"], "not-established")
            self.assertEqual(hit["candidateUsability"], "not-tested")
        hit = dependency["result"]["entries"][0]
        attestation = self.components["attestation.json"]
        self.assertEqual(hit["evidence"], {
            "sourceId": indexes["dependency"]["sourceId"], "indexId": indexes["dependency"]["indexId"],
            "bundleId": self.manifest["bundleId"], "resolutionId": self.components["resolution.json"]["resolutionId"],
            "attestationId": attestation["attestationId"],
            **{key: attestation[key] for key in ("command", "scope", "outcome")},
        })
        expected = deepcopy(dependency)
        hit["evidence"]["command"].clear()
        hit["evidence"]["outcome"].clear()
        hit["qualifiedName"] = "Forged.Dependency"
        self.assertEqual(self.search(listing, exact="Library.identity", scope="dependency"), expected)

    def test_same_relative_project_dependency_path_with_different_bytes_does_not_alias(self):
        # Reuse the same relative spelling while retaining separately bound trees.
        path = self.project / "src" / "Library.agda"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"module ClientOnly where\nclientHead : Set\n")
        self.rev = self.status()["currentRevision"]
        listing = self.listed()
        indexes = {"project": core.build_declaration_index(self.project), "dependency": core.build_declaration_index(self.library)}
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            project = self.search(listing, prefix="ClientOnly", scope="project")
            dependency = self.search(listing, prefix="Library", scope="dependency")
            self.assertEqual(self.search(listing, prefix="ClientOnly", scope="project"), project)
            self.assertEqual(self.search(listing, prefix="Library", scope="dependency"), dependency)
        self.assertEqual(scan.call_count, 3)
        self.assertEqual(project["status"], "ok", project)
        self.assertEqual(dependency["status"], "ok", dependency)
        for origin, response, prefix in (("project", project, "ClientOnly"), ("dependency", dependency, "Library")):
            expected = core.query_declaration_index(indexes[origin], prefix=prefix)
            self.assertEqual([{key: hit[key] for key in raw} for hit, raw in zip(response["result"]["entries"], expected)], expected)
            self.assertEqual({hit["path"] for hit in response["result"]["entries"]}, {"src/Library.agda"})
            self.assertEqual({hit["origin"] for hit in response["result"]["entries"]}, {origin})
        self.assertNotEqual(project["result"]["entries"][0]["sourceSha256"], dependency["result"]["entries"][0]["sourceSha256"])

    def test_warm_search_skips_only_scanner_not_two_pass_observations_or_fresh_root_reads(self):
        listing = self.listed()
        read_bytes = Path.read_bytes
        reads = []
        def read(path):
            reads.append(path)
            return read_bytes(path)
        with patch.object(self.workspace, "_observe", wraps=self.workspace._observe) as observe, \
             patch.object(source_research, "build_snapshot", wraps=source_research.build_snapshot) as observed_snapshots, \
             patch.object(source_research, "build_resolution", wraps=source_research.build_resolution) as native, \
             patch.object(source_research, "_load_source_evidence", wraps=source_research._load_source_evidence) as load, \
             patch.object(research, "build_snapshot", wraps=research.build_snapshot) as discovery_snapshots, \
             patch.object(core, "sha256_file", wraps=core.sha256_file) as hashes, \
             patch.object(Path, "read_bytes", read), \
             patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            cold = self.search(listing, prefix="Library", scope="all")
            self.assertEqual(cold["status"], "ok", cold)
            self.assertEqual(observe.call_count, 2)
            self.assertEqual(observed_snapshots.call_count, 8)
            self.assertEqual(native.call_count, 8)
            self.assertEqual(load.call_count, 4)
            warm = self.search(listing, prefix="Library", scope="all")
        self.assertEqual(cold, warm)
        self.assertEqual(observe.call_count, 4)
        self.assertEqual(observed_snapshots.call_count, 16)
        self.assertEqual(native.call_count, 16)
        self.assertEqual(load.call_count, 8)
        self.assertEqual(discovery_snapshots.call_count, 4)
        self.assertEqual(scan.call_count, 2)
        self.assertEqual(Counter(reads), Counter({self.source: 2, self.library / "src" / "Library.agda": 2}))
        counted = Counter(call.args[0] for call in hashes.call_args_list)
        self.assertEqual(counted[self.source], 12)
        self.assertEqual(counted[self.library / "src" / "Library.agda"], 12)
        self.assertEqual(counted[self.project / "notes.txt"], 10)
        self.assertEqual(counted[self.library / "notes.txt"], 10)

    def test_notify_between_project_and_dependency_builds_pins_whole_search_generation(self):
        listing = self.listed()
        admitted = self.workspace._generation
        entered, release = threading.Event(), threading.Event()
        builder = self.workspace._build_discovery_index
        builds = []
        def blocked(root, snapshot, **options):
            builds.append((root, options["generation"]))
            result = builder(root, snapshot, **options)
            if root == self.project:
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("between-index release timed out")
            return result
        self.run_blocked_search(listing, patch_target=lambda fn: patch.object(self.workspace, "_build_discovery_index", side_effect=fn),
                                replacement=blocked, entered=entered, release=release, scope="all")
        self.assertEqual(builds, [(self.project, admitted), (self.library, admitted)])

    def test_dependency_notes_change_and_revert_clear_warm_memo_keep_frozen_pin(self):
        listing, _ = self.warm()
        path = self.library / "notes.txt"
        original = path.read_bytes()
        path.write_bytes(original + b"dependency edit\n")
        changed = self.status()
        self.assertFalse(changed["result"]["dependencyMatchesPin"])
        self.assert_memo_empty()
        self.rev = changed["currentRevision"]
        self.error(self.search(listing, prefix="Library", scope="dependency"), "dependency-changed")
        path.write_bytes(original)
        restored = self.status()
        self.assertTrue(restored["result"]["dependencyMatchesPin"])
        self.assert_memo_empty()
        self.rev = restored["currentRevision"]
        self.assertEqual(self.search(listing, prefix="Main", scope="project")["error"]["code"], "listing-stale")
        fresh = self.listed()
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            response = self.search(fresh, prefix="Library", scope="dependency")
        self.assertEqual(response["status"], "ok", response)
        scan.assert_called_once()

    def test_observed_compiler_change_and_revert_clear_v2_cache_without_reactivating_listing(self):
        listing, _ = self.warm()
        self.version.write_bytes(b"Agda version 2.6.3-discovery-changed\n")
        changed = self.status()
        self.assertFalse(changed["result"]["dependencyMatchesPin"])
        self.assert_memo_empty()
        self.version.write_bytes(self.version_bytes)
        restored = self.status()
        self.assertTrue(restored["result"]["dependencyMatchesPin"])
        self.assertNotEqual(changed["currentRevision"], restored["currentRevision"])
        self.assert_memo_empty()
        self.rev = restored["currentRevision"]
        self.assertEqual(self.search(listing, prefix="Main", scope="project")["error"]["code"], "listing-stale")

    def test_no_envelope_source_failure_invalidates_discovery_cache_even_after_revert(self):
        listing, _ = self.warm()
        generation = self.workspace._generation
        def fail(*args, **options):
            original = self.source.read_bytes()
            self.source.write_bytes(original + b"-- transient edit\n")
            self.source.write_bytes(original)
            raise sources.SourceEvidenceError("failed source validation")
        with patch.object(source_research, "observe_source_goals", side_effect=fail):
            response = self.call("goals.list", {"documentId": "main"})
        self.assertIn(response["status"], {"error", "stale"}, response)
        self.assertIn(response["error"]["code"], {"evidence-invalid", "workspace-changed"}, response)
        self.assertGreater(self.workspace._generation, generation)
        self.assert_memo_empty()
        self.rev = self.status()["currentRevision"]
        self.assertEqual(self.search(listing, prefix="Main", scope="project")["error"]["code"], "listing-stale")

    def test_warm_live_search_does_not_hide_filtered_out_catalog_corruption(self):
        temporary = tempfile.TemporaryDirectory(prefix="discovery-catalog-", dir=self.home)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        index = root / "library.index.json"
        core.write_declaration_index(index, core.build_declaration_index(self.library))
        bundles = []
        for name in ("selected", "filtered"):
            bundle = root / name
            core.capture_bundle(self.library, bundle, [sys.executable, "-c", "print('" + name + "')"],
                                agda_binary=str(self.binary), index_reference=index)
            bundles.append((name, bundle))
        path = root / "catalog.json"
        catalog.create_catalog(path, bundles)
        workspace = self.make_workspace(catalog=path)
        revision = self.status(workspace=workspace)["currentRevision"]
        listing = self.listed(workspace=workspace, revision=revision)
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            response = self.search(listing, workspace=workspace, revision=revision,
                                   exact="Library.identity", scope="all", libraries=["selected"])
            self.assertEqual(response["status"], "ok", response)
            self.assertEqual(response["result"]["checkedCatalogEntries"], ["filtered", "selected"])
            self.assertEqual({hit["origin"] for hit in response["result"]["entries"]}, {"dependency", "catalog"})
            scanned = scan.call_count
            self.assertEqual(scanned, 2)
            diagnostics = root / "filtered" / "diagnostics.json"
            diagnostics.write_bytes(diagnostics.read_bytes() + b"corruption")
            rejected = self.search(listing, workspace=workspace, revision=revision,
                                   exact="Library.identity", scope="all", libraries=["selected"])
            self.error(rejected, "catalog-invalid")
            self.assertIsNone(rejected["result"])
            self.assertEqual(scan.call_count, scanned, "only live lexical scans should be memoized")
        self.assertNotIn(str(root), str(rejected))


if __name__ == "__main__":
    unittest.main()
