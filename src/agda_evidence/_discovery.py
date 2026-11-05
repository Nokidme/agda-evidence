"""Private, bounded lexical fragments; never cached evidence or freshness claims."""

from __future__ import annotations

from collections import OrderedDict
import json
import threading
from typing import Any

from . import core


class _LexicalMemo:
    """Memoize only candidates obtained from snapshot-approved source bytes.

    The caller verifies bytes and pins a generation for its entire build/request.
    No state callback is made under this memo's lock: workspace lock order is
    state then memo, while scanning and validation happen outside either lock.
    """

    def __init__(self, max_files: int = 4096, max_bytes: int = 16_777_216) -> None:
        for name, value in (("max_files", max_files), ("max_bytes", max_bytes)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self._max_files = max_files
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._generation = 0
        self._entries: OrderedDict[tuple[int, str, str, str], bytes] = OrderedDict()
        self._stored_bytes = 0

    def invalidate(self, generation: int) -> None:
        with self._lock:
            self._generation = generation
            self._entries.clear()
            self._stored_bytes = 0

    @staticmethod
    def _thaw(payload: bytes) -> list[dict[str, Any]]:
        # Canonical JSON sorts object keys; restore the scanner's field order as
        # well as returning wholly detached dictionaries for every cache hit.
        return [
            {field: record[field] for field in ("qualifiedName", "kind", "path", "line", "sourceSha256")}
            for record in json.loads(payload)
        ]

    def scan(
        self, path: str, data: bytes, source_sha256: str, *, generation: int,
    ) -> list[dict[str, Any]]:
        # A hit must still enforce strict decoding of the currently read bytes.
        core._decode_indexed_source(path, data)
        key = (generation, path, source_sha256, core.LEXICAL_DISCOVERY_FORMAT)
        with self._lock:
            payload = self._entries.get(key) if generation == self._generation else None
        if payload is not None:
            return self._thaw(payload)

        # Resolve the scanner dynamically, and never invoke it under the lock.
        candidates = core._scan_indexed_source_bytes(path, data, source_sha256)
        if not isinstance(candidates, list):
            return candidates
        try:
            normalized = core._normalised_declaration_entries(candidates)
            if any(record["path"] != path or record["sourceSha256"] != source_sha256 for record in normalized):
                return candidates
            payload = core.canonical_json_bytes(normalized)
            stored_size = len(payload) + len(core.canonical_json_bytes(key))
        except (core.EvidenceError, KeyError, TypeError, ValueError, OverflowError):
            # The whole index retains its original validation and diagnostic
            # positions, including candidates malformed by an injected scanner.
            return candidates
        if stored_size > self._max_bytes:
            return candidates

        with self._lock:
            # A notification may have advanced the epoch while scanning. Old
            # work may complete, but must never repopulate the new generation.
            if generation == self._generation and key not in self._entries:
                while self._entries and (
                    len(self._entries) >= self._max_files or self._stored_bytes + stored_size > self._max_bytes
                ):
                    removed_key, removed_payload = self._entries.popitem(last=False)
                    self._stored_bytes -= len(removed_payload) + len(core.canonical_json_bytes(removed_key))
                self._entries[key] = payload
                self._stored_bytes += stored_size
        return self._thaw(payload)
