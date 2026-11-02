#!/usr/bin/env python3
"""Finite native-Agda pilot; writes evidence only under a new external directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agda_evidence.client import (
    client_summary, infer_client, load_client_observation, select_candidate,
    write_client_observation,
)
from agda_evidence.core import (
    build_declaration_index, build_snapshot, capture_bundle, load_verified_bundle,
    write_declaration_index,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agda-bin", default="agda")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or args.output.is_symlink() or output.is_relative_to(ROOT):
        parser.error("pilot output must be a new directory outside the repository")
    output.mkdir(parents=True)
    library = ROOT / "examples/client-query/library"
    client = ROOT / "examples/client-query/client"
    before = (build_snapshot(library)[0]["sourceId"], build_snapshot(client)[0]["sourceId"])
    index = build_declaration_index(library)
    write_declaration_index(output / "library.index.json", index)
    entries = [entry for entry in index["entries"] if entry["qualifiedName"] == "Example.identity" and entry["kind"] == "signature"]
    if len(entries) != 1:
        raise SystemExit("expected one recorded Example.identity signature")
    selection = {key: entries[0][key] for key in ("path", "line", "qualifiedName", "kind")}
    select_candidate(index, selection)
    capture_bundle(
        library, output / "library.evidence",
        [args.agda_bin, "--no-libraries", "--ignore-interfaces", "--safe", "-i", "src", "src/Example.agda"],
        agda_binary=args.agda_bin, scope="safe example library typecheck", index_reference=output / "library.index.json",
    )
    manifest, payloads = load_verified_bundle(output / "library.evidence")
    if payloads["attestation.json"]["outcome"]["status"] != "passed":
        raise SystemExit("example library typecheck did not pass")
    summaries = {}
    for label, file, expression, expected in (
        ("imported", "Main.agda", "Example.identity", "inferred"),
        ("alias", "Main.agda", "importedIdentity", "inferred"),
        ("no-import", "NoImport.agda", "Example.identity", "query-error"),
        ("private", "Main.agda", "Example.secret", "query-error"),
        ("homonym", "Homonym.agda", "identity", "inferred"),
    ):
        value = infer_client(
            client, file, expression, library_root=library,
            library_bundle=output / "library.evidence", library_includes=("src",),
            candidate=selection, agda_binary=args.agda_bin, safe=True,
        )
        path = output / f"{label}.client.json"
        write_client_observation(path, value)
        checked = load_client_observation(path)
        result = checked["typeObservation"]["result"]
        if result["status"] != expected:
            raise SystemExit(f"unexpected {label} result: {result}")
        if expected == "inferred" and result["type"] != "Nat → Nat":
            raise SystemExit(f"unexpected {label} displayed type: {result}")
        summaries[label] = client_summary(checked)
        print(f"{label}: {result}", flush=True)
    after = (build_snapshot(library)[0]["sourceId"], build_snapshot(client)[0]["sourceId"])
    if before != after or list(library.rglob("*.agdai")) or list(client.rglob("*.agdai")):
        raise SystemExit("pilot altered original source inputs or generated interfaces there")
    summary = {
        "libraryBundleId": manifest["bundleId"],
        "libraryCheckId": payloads["attestation.json"]["attestationId"],
        "compiler": payloads["resolution.json"]["agda"],
        "cases": summaries,
        "selectionRelation": "lexical-context-only",
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Native client pilot passed; all five saved envelopes verified locally.", flush=True)


if __name__ == "__main__":
    main()
