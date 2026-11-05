"""Lexical memoization may save scanning, never source validation or identity.

All projects are local temporary inputs. These tests exercise lexical candidates,
not Agda parsing, scope resolution, elaboration, or proof completion.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agda_evidence import core, research
from agda_evidence._discovery import _LexicalMemo


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class LexicalMemoTests(unittest.TestCase):
    def setUp(self):
        self.memo = _LexicalMemo()
        self.memo.invalidate(7)
        self.data = b"module Example where\nvalue : Set\n"

    def scan(self, path="Example.agda", data=None, *, generation=7, memo=None):
        data = self.data if data is None else data
        return (self.memo if memo is None else memo).scan(path, data, digest(data), generation=generation)

    def assert_empty(self, memo=None):
        memo = self.memo if memo is None else memo
        self.assertEqual(len(memo._entries), 0)
        self.assertEqual(memo._stored_bytes, 0)

    def test_warm_scan_is_exact_detached_and_empty_fragments_are_hits(self):
        scanner = core._lexical_candidates_for_file
        owned = []
        def scan(*args):
            value = scanner(*args)
            owned.append(value)
            return value
        with patch.object(core, "_lexical_candidates_for_file", side_effect=scan) as counted:
            first = self.scan()
            expected = deepcopy(first)
            owned[0][0]["qualifiedName"] = "Scanner.Mutated"
            owned[0].clear()
            first[0]["qualifiedName"] = "Caller.Mutated"
            first.clear()
            second = self.scan()
            self.assertEqual(second, expected)
            second[0]["path"] = "other.agda"
            self.assertEqual(self.scan(), expected)
            self.assertEqual(counted.call_count, 1)
            self.assertEqual(self.scan("Empty.agda", b""), [])
            self.assertEqual(self.scan("Empty.agda", b""), [])
            self.assertEqual(counted.call_count, 2)
        self.assertEqual(len(self.memo._entries), 2)
        self.assertGreater(self.memo._stored_bytes, len(core.canonical_json_bytes(expected)))

    def test_exact_paths_unicode_normalization_and_content_do_not_alias(self):
        composed, decomposed = "Caf\u00e9.agda", "Cafe\u0301.agda"
        self.assertNotEqual(composed, decomposed)
        other = b"module Different where\nother : Set\n"
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            first = self.scan(composed)
            second = self.scan(decomposed)
            changed = self.scan(composed, other)
            self.assertEqual(self.scan(composed), first)
            self.assertEqual(self.scan(decomposed), second)
            self.assertEqual(self.scan(composed, other), changed)
        self.assertEqual(scan.call_count, 3)
        self.assertEqual({item["path"] for item in first}, {composed})
        self.assertEqual({item["path"] for item in second}, {decomposed})
        self.assertNotEqual(first, changed)
        self.assertEqual(len(self.memo._entries), 3)

    def test_scanner_policy_formats_and_generation_are_cache_keys(self):
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            self.scan()
            for suffix in ("-test-one", "-test-two"):
                with self.subTest(format=suffix), patch.object(core, "LEXICAL_DISCOVERY_FORMAT", core.LEXICAL_DISCOVERY_FORMAT + suffix):
                    self.scan()
                    self.scan()
            self.assertEqual(scan.call_count, 3)
            self.memo.invalidate(8)
            self.assert_empty()
            self.assertEqual(self.memo._generation, 8)
            fresh = self.scan(generation=8)
            self.assertEqual(self.scan(generation=8), fresh)
            self.assertEqual(scan.call_count, 4)

    def test_strict_utf8_validation_precedes_even_a_claimed_warm_hash_hit(self):
        old_sha = digest(self.data)
        self.scan()
        with patch.object(core, "_lexical_candidates_for_file", side_effect=AssertionError("invalid UTF-8 reached scanner")):
            with self.assertRaises(core.EvidenceError):
                self.memo.scan("Example.agda", b"\xff", old_sha, generation=7)
        # The memo trusts the builder's byte/digest binding, but never decoding.
        self.assertEqual(len(self.memo._entries), 1)
        self.assertEqual(self.scan()[0]["qualifiedName"], "Example")

    def test_scanner_failure_and_invalid_fragments_never_become_accepted_hits(self):
        canonical = core._lexical_candidates_for_file("Example.agda", self.data.decode(), digest(self.data))
        invalid = []
        for field, value in (("line", True), ("kind", "not-a-kind"),
                             ("path", "../Other.agda"), ("sourceSha256", "sha256:invalid")):
            fragment = deepcopy(canonical)
            fragment[0][field] = value
            invalid.append(fragment)
        invalid.extend([canonical + [deepcopy(canonical[-1])],
                        [{**canonical[0], "extra": "not permitted"}]])
        for fragment in invalid:
            with self.subTest(fragment=fragment):
                with patch.object(core, "_lexical_candidates_for_file", return_value=fragment) as scan:
                    for _ in range(2):
                        # Bypass must preserve downstream whole-index diagnostics;
                        # malformed scanner output must not become a cache hit.
                        returned = self.scan()
                        self.assertEqual(returned, fragment)
                        with self.assertRaises(core.EvidenceError):
                            core._normalised_declaration_entries(sorted(returned, key=core._index_entry_sort_key))
                        self.assert_empty()
                    self.assertEqual(scan.call_count, 2)
                self.assert_empty()
        with patch.object(core, "_lexical_candidates_for_file", side_effect=RuntimeError("failed scanner")) as scan:
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    self.scan()
            self.assertEqual(scan.call_count, 2)
        self.assert_empty()
        self.assertEqual(self.scan(), canonical)

    def test_limits_require_positive_integer_file_and_byte_budgets(self):
        for field in ("max_files", "max_bytes"):
            for value in (0, -1, True, False, 1.5, None, "2"):
                with self.subTest(field=field, value=value), self.assertRaises((ValueError, TypeError, core.EvidenceError)):
                    _LexicalMemo(**{field: value})
        memo = _LexicalMemo(max_files=1, max_bytes=1)
        memo.invalidate(7)
        self.assertEqual(self.scan(memo=memo)[0]["qualifiedName"], "Example")
        self.assert_empty(memo)

    def test_count_budget_evicts_and_rescans_without_changing_candidates(self):
        memo = _LexicalMemo(max_files=2, max_bytes=100000)
        memo.invalidate(7)
        expected = {}
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            for name in ("One.agda", "Two.agda", "Three.agda"):
                expected[name] = self.scan(name, memo=memo)
                self.assertLessEqual(len(memo._entries), 2)
                self.assertLessEqual(memo._stored_bytes, 100000)
            self.assertEqual(scan.call_count, 3)
            self.assertEqual(self.scan("Three.agda", memo=memo), expected["Three.agda"])
            self.assertEqual(scan.call_count, 3)
            self.assertEqual(self.scan("One.agda", memo=memo), expected["One.agda"])
            self.assertEqual(scan.call_count, 4)
        self.assertEqual(len(memo._entries), 2)

    def test_byte_budget_counts_keys_evicts_and_oversized_fragments_bypass(self):
        probe = _LexicalMemo(max_files=10, max_bytes=100000)
        probe.invalidate(7)
        self.scan("One.agda", memo=probe)
        one_size = probe._stored_bytes
        payload_size = len(core.canonical_json_bytes(self.scan("One.agda", memo=probe)))
        self.assertGreater(one_size, payload_size, "key storage must also count toward the budget")
        memo = _LexicalMemo(max_files=10, max_bytes=one_size)
        memo.invalidate(7)
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            first = self.scan("One.agda", memo=memo)
            second = self.scan("Two.agda", memo=memo)
            self.assertEqual(len(memo._entries), 1)
            self.assertLessEqual(memo._stored_bytes, one_size)
            self.assertEqual(self.scan("Two.agda", memo=memo), second)
            self.assertEqual(scan.call_count, 2)
            self.assertEqual(self.scan("One.agda", memo=memo), first)
            self.assertEqual(scan.call_count, 3)
            before = (deepcopy(memo._entries), memo._stored_bytes)
            oversized = ("huge" + "x" * 4000 + " : Set\n").encode()
            expected = self.scan("Huge.agda", oversized, memo=memo)
            self.assertEqual(self.scan("Huge.agda", oversized, memo=memo), expected)
            self.assertEqual(scan.call_count, 5)
            self.assertEqual((memo._entries, memo._stored_bytes), before)
        # Even an empty fragment can have an oversized exact path key.
        tiny = _LexicalMemo(max_files=10, max_bytes=2)
        tiny.invalidate(7)
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            self.assertEqual(self.scan("Empty.agda", b"", memo=tiny), [])
            self.assertEqual(self.scan("Empty.agda", b"", memo=tiny), [])
        self.assertEqual(scan.call_count, 2)
        self.assert_empty(tiny)

    def test_invalidation_during_scan_is_nonblocking_and_old_work_cannot_reinsert(self):
        entered, release, invalidated = threading.Event(), threading.Event(), threading.Event()
        scanner = core._lexical_candidates_for_file
        results, errors = [], []
        def blocked(*args):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test scanner release timed out")
            return scanner(*args)
        def work():
            try:
                results.append(self.scan())
            except BaseException as error:
                errors.append(error)
        def invalidate():
            self.memo.invalidate(8)
            invalidated.set()
        with patch.object(core, "_lexical_candidates_for_file", side_effect=blocked):
            worker = threading.Thread(target=work, daemon=True)
            notifier = threading.Thread(target=invalidate, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered.wait(10))
                notifier.start()
                self.assertTrue(invalidated.wait(5), "scanner must run outside the memo lock")
                self.assert_empty()
            finally:
                release.set()
                worker.join(10)
                if notifier.ident is not None:
                    notifier.join(10)
        self.assertFalse(worker.is_alive())
        self.assertFalse(notifier.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0][0]["qualifiedName"], "Example")
        self.assert_empty()
        with patch.object(core, "_lexical_candidates_for_file", wraps=scanner) as scan:
            self.scan(generation=7)
            self.assert_empty()
            self.scan(generation=8)
            self.scan(generation=8)
        self.assertEqual(scan.call_count, 2)


class DiscoveryBuilderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lexical-discovery-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.project = self.home / "project"
        self.project.mkdir()
        self.source = self.project / "Main.agda"
        self.original = b"module Main where\nvalue : Set\n"
        self.source.write_bytes(self.original)
        self.notes = self.project / "notes.txt"
        self.notes.write_bytes(b"notes before\n")
        self.snapshot = core.build_snapshot(self.project)[0]
        self.memo = _LexicalMemo()
        self.memo.invalidate(3)

    def cached(self, snapshot=None):
        return core._build_declaration_index(self.project, self.snapshot if snapshot is None else snapshot,
            _candidate_scanner=lambda path, data, sha: self.memo.scan(path, data, sha, generation=3))

    def test_cached_index_matches_canonical_bytes_ids_unicode_and_physical_line_policy(self):
        files = {
            "Main.agda": b"module Main where\r\nvalue : Set\rdata Thing : Set where\r\n  hidden : Set\r",
            "BOM.agda": "\ufeffmodule BOM where\r\nvisible : Set\n".encode(),
            "Empty.agda": b"",
            "Caf\u00e9.agda": "module Caf\u00e9 where\n\u00e9 : Set\n".encode(),
            "Cafe\u0301.agda": "module Cafe\u0301 where\ne\u0301 : Set\n".encode(),
            "Story.lagda.md": (
                "prose : Set\r\n```python\r\npythonOnly : Set\r\n```\r\n"
                "~~~Agda2\r\nmodule Story where\r\ninside : Set\r\n  indented : Set\r\n~~~\r\n"
                "outside : Set\r\n```agda\r\ndata Second : Set where\r\n```\r\n").encode(),
        }
        for path, data in files.items():
            (self.project / path).write_bytes(data)
        snapshot = core.build_snapshot(self.project)[0]
        canonical = core.build_declaration_index(self.project, snapshot)
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            first = self.cached(snapshot)
            second = self.cached(snapshot)
        self.assertEqual(scan.call_count, len(files))
        self.assertEqual(first, canonical)
        self.assertEqual(second, canonical)
        self.assertEqual(core.canonical_json_bytes(first), core.canonical_json_bytes(canonical))
        self.assertEqual(first["indexId"], core.derive_declaration_index_id(first))
        self.assertEqual(first["sourceId"], snapshot["sourceId"])
        heads = {(entry["path"], entry["qualifiedName"], entry["kind"], entry["line"]) for entry in first["entries"]}
        self.assertEqual(heads, {
            ("Main.agda", "Main", "module", 1), ("Main.agda", "Main.value", "signature", 2),
            ("Main.agda", "Main.Thing", "data", 3), ("BOM.agda", "visible", "signature", 2),
            ("Caf\u00e9.agda", "Caf\u00e9", "module", 1), ("Caf\u00e9.agda", "Caf\u00e9.\u00e9", "signature", 2),
            ("Cafe\u0301.agda", "Cafe\u0301", "module", 1), ("Cafe\u0301.agda", "Cafe\u0301.e\u0301", "signature", 2),
            ("Story.lagda.md", "Story", "module", 6), ("Story.lagda.md", "Story.inside", "signature", 7),
            ("Story.lagda.md", "Story.Second", "data", 12),
        })
        for entry in first["entries"]:
            self.assertEqual(entry["sourceSha256"], digest(files[entry["path"]]))
        first["entries"].clear()
        self.assertEqual(self.cached(snapshot), canonical)

    def test_default_and_memo_scanners_receive_universal_newlines_without_stripping_bom(self):
        data = b"\xef\xbb\xbfmodule Main where\r\nvalue : Set\rother : Set\n"
        self.source.write_bytes(data)
        snapshot = core.build_snapshot(self.project)[0]
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            public = core.build_declaration_index(self.project, snapshot)
            cached = self.cached(snapshot)
        self.assertEqual(public, cached)
        self.assertEqual(scan.call_count, 2)
        for call in scan.call_args_list:
            self.assertEqual(call.args, ("Main.agda", "\ufeffmodule Main where\nvalue : Set\nother : Set\n", digest(data)))

    def test_warm_builder_rehashes_and_reads_exact_bytes_before_callback(self):
        canonical = self.cached()
        read_bytes = Path.read_bytes
        reads = []
        def read(path):
            reads.append(path)
            return read_bytes(path)
        with patch.object(core, "sha256_file", wraps=core.sha256_file) as sha, \
             patch.object(Path, "read_bytes", read), \
             patch.object(core, "_lexical_candidates_for_file", side_effect=AssertionError("warm cache rescanned")):
            self.assertEqual(self.cached(), canonical)
        self.assertEqual([call.args[0] for call in sha.call_args_list], [self.source])
        self.assertEqual(reads, [self.source])

    def test_warm_old_hash_never_accepts_changed_or_invalid_utf8_bytes(self):
        self.cached()
        for replacement in (b"module Evil where\n", b"\xff" * len(self.original)):
            with self.subTest(replacement=replacement):
                self.source.write_bytes(replacement)
                with patch.object(core, "_lexical_candidates_for_file", side_effect=AssertionError("mismatch scanned")):
                    with self.assertRaises(core.EvidenceError):
                        self.cached()
                self.source.write_bytes(self.original)
                self.assertEqual(self.cached(), core.build_declaration_index(self.project, self.snapshot))
        invalid_snapshot_data = b"\xff\r\n"
        self.source.write_bytes(invalid_snapshot_data)
        invalid_snapshot = core.build_snapshot(self.project)[0]
        with self.assertRaisesRegex(core.EvidenceError, "UTF-8"):
            self.cached(invalid_snapshot)

    def test_public_hash_then_read_race_rejects_before_scanner(self):
        original_sha = core.sha256_file
        changed = False
        def hash_then_edit(path):
            nonlocal changed
            value = original_sha(path)
            if path == self.source and not changed:
                changed = True
                self.source.write_bytes(b"module Evil where\nvalue : Set\n")
            return value
        with patch.object(core, "sha256_file", side_effect=hash_then_edit), \
             patch.object(core, "_lexical_candidates_for_file", side_effect=AssertionError("raced bytes were scanned")) as scan:
            with self.assertRaises(core.EvidenceError):
                core.build_declaration_index(self.project, self.snapshot)
        self.assertTrue(changed)
        scan.assert_not_called()
        self.source.write_bytes(self.original)
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            restored = core.build_declaration_index(self.project, self.snapshot)
        scan.assert_called_once()
        self.assertEqual(restored["entries"][0]["qualifiedName"], "Main")

    def test_private_hash_then_read_race_never_caches_under_old_digest(self):
        original_sha = core.sha256_file
        def hash_then_edit(path):
            value = original_sha(path)
            if path == self.source:
                self.source.write_bytes(b"module Evil where\nvalue : Set\n")
            return value
        with patch.object(core, "sha256_file", side_effect=hash_then_edit), \
             patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            with self.assertRaises(core.EvidenceError):
                self.cached()
        scan.assert_not_called()
        self.assertEqual(len(self.memo._entries), 0)
        self.source.write_bytes(self.original)
        with patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            restored = self.cached()
            self.assertEqual(self.cached(), restored)
        scan.assert_called_once()
        self.assertEqual(restored, core.build_declaration_index(self.project, self.snapshot))

    def test_invalid_fragment_bypasses_memo_and_actual_builder_preserves_global_diagnostics(self):
        first = self.project / "AFirst.agda"
        first.write_bytes(b"module First where\nfirst : Set\n")
        snapshot = core.build_snapshot(self.project)[0]
        original_scan = core._lexical_candidates_for_file
        for field, value, message in (
            ("line", True, r"declaration index entries\[2\]\.line must be a positive integer"),
            ("kind", "invalid-kind", r"declaration index entries\[2\]\.kind is not a supported"),
            ("extra", "invalid-field", r"declaration index entries\[2\] must contain exactly"),
        ):
            with self.subTest(field=field):
                self.memo.invalidate(3)
                def invalid_scan(path, text, sha):
                    fragment = original_scan(path, text, sha)
                    if path == "Main.agda":
                        fragment[0][field] = value
                    return fragment
                with patch.object(core, "_lexical_candidates_for_file", side_effect=invalid_scan) as scan, \
                     patch.object(core, "derive_declaration_index_id", wraps=core.derive_declaration_index_id) as derive:
                    for _ in range(2):
                        with self.assertRaisesRegex(core.EvidenceError, message):
                            self.cached(snapshot)
                        # Only the valid first file is retained. Malformed Main
                        # candidates reach the aggregate validator every time.
                        self.assertEqual(len(self.memo._entries), 1)
                    self.assertEqual(Counter(call.args[0] for call in scan.call_args_list),
                                     Counter({"AFirst.agda": 1, "Main.agda": 2}))
                    self.assertEqual(derive.call_count, 2)
                    for call in derive.call_args_list:
                        self.assertEqual(call.args[0]["entries"][2][field], value)

    def test_missing_symlinked_and_invalid_snapshot_sources_reject_on_warm_path(self):
        self.cached()
        self.source.unlink()
        with self.assertRaises(core.EvidenceError):
            self.cached()
        target = self.home / "outside.agda"
        target.write_bytes(self.original)
        self.source.symlink_to(target)
        with self.assertRaises(core.EvidenceError):
            self.cached()
        self.source.unlink()
        self.source.write_bytes(self.original)
        forged = deepcopy(self.snapshot)
        forged["sourceId"] = "sha256:" + "0" * 64
        with self.assertRaises(core.EvidenceError):
            self.cached(forged)

    def test_workspace_guard_rebuilds_whole_snapshot_despite_warm_unchanged_agda(self):
        workspace = research.ResearchWorkspace(self.project, {"main": "Main.agda"}, agda_binary="unused-discovery-test")
        def build(snapshot):
            return workspace._build_discovery_index(self.project, snapshot, generation=workspace._generation,
                                                     _builder=core._build_declaration_index)
        expected = core.build_declaration_index(self.project, self.snapshot)
        with patch.object(research, "build_snapshot", wraps=research.build_snapshot) as snapshots, \
             patch.object(core, "sha256_file", wraps=core.sha256_file) as hashes, \
             patch.object(core, "_lexical_candidates_for_file", wraps=core._lexical_candidates_for_file) as scan:
            self.assertEqual(build(self.snapshot), expected)
            self.assertEqual(build(self.snapshot), expected)
        self.assertEqual(snapshots.call_count, 2)
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(sum(call.args[0] == self.notes for call in hashes.call_args_list), 2)
        before = self.notes.stat()
        replacement = b"notes AFTER!\n"
        self.assertEqual(len(replacement), before.st_size)
        self.notes.write_bytes(replacement)
        os.utime(self.notes, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.notes.stat().st_mtime_ns, before.st_mtime_ns)
        with patch.object(core, "_lexical_candidates_for_file", side_effect=AssertionError("stale whole root reached scanner")):
            with self.assertRaises(core.EvidenceError):
                build(self.snapshot)
        fresh = core.build_snapshot(self.project)[0]
        self.assertNotEqual(fresh["sourceId"], self.snapshot["sourceId"])
        self.assertEqual(build(fresh), core.build_declaration_index(self.project, fresh))

    def test_workspace_guard_detects_addition_deletion_symlink_and_invalid_source_id(self):
        workspace = research.ResearchWorkspace(self.project, {"main": "Main.agda"}, agda_binary="unused-discovery-test")
        def build(snapshot=self.snapshot):
            return workspace._build_discovery_index(self.project, snapshot, generation=workspace._generation,
                                                     _builder=core._build_declaration_index)
        build()
        added = self.project / "Added.agda"
        added.write_bytes(b"module Added where\n")
        with self.assertRaises(core.EvidenceError):
            build()
        added.unlink()
        self.notes.unlink()
        with self.assertRaises(core.EvidenceError):
            build()
        self.notes.write_bytes(b"notes before\n")
        self.source.unlink()
        self.source.symlink_to(self.notes)
        with self.assertRaises(core.EvidenceError):
            build()
        self.source.unlink()
        self.source.write_bytes(self.original)
        invalid = deepcopy(self.snapshot)
        invalid["sourceId"] = "sha256:" + "0" * 64
        with self.assertRaises(core.EvidenceError):
            build(invalid)


if __name__ == "__main__":
    unittest.main()
