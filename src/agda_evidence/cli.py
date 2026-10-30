"""Command-line interface for the agda-evidence reference implementation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .core import (
    DECLARATION_KINDS,
    EvidenceError,
    build_declaration_index,
    build_nix_resolution,
    capture_bundle,
    create_aggregate,
    declaration_index_from_bundle,
    load_resolution_observation,
    query_declaration_index,
    verify_aggregate,
    verify_bundle,
    write_declaration_index,
    write_resolution_observation,
)


def _capture_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "capture",
        help="capture an explicit project check in an isolated project copy",
    )
    parser.add_argument("--project-root", type=Path, required=True, help="directory to snapshot")
    parser.add_argument("--output", type=Path, required=True, help="new or empty bundle directory outside the project")
    parser.add_argument("--agda-bin", default="agda", help="Agda executable to inspect (default: agda)")
    parser.add_argument("--scope", default="explicit-project-check", help="human-readable scope for the supplied command")
    parser.add_argument("--timeout-seconds", type=int, default=600, help="maximum runtime for the supplied command")
    parser.add_argument("--max-output-bytes", type=int, default=262_144, help="maximum retained bytes per output stream")
    parser.add_argument(
        "--index-reference",
        type=Path,
        help="optional source-bound declaration index built by 'index build'",
    )
    parser.add_argument(
        "--resolution-file",
        type=Path,
        help="previously verified resolution JSON captured in the target toolchain environment",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="command to run, supplied after '--'; for example: -- make check",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agda-evidence",
        description="Create portable evidence bundles for explicit Agda project checks.",
    )
    parser.add_argument("--version", action="version", version=f"agda-evidence {__version__}")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    _capture_parser(subparsers)

    nix_probe = subparsers.add_parser(
        "probe-nix-resolution",
        help="record Agda resolution from an already activated nix develop environment",
    )
    nix_probe.add_argument("--project-root", type=Path, required=True, help="flake project root")
    nix_probe.add_argument("--output", type=Path, required=True, help="new JSON resolution observation file")
    nix_probe.add_argument("--nix-bin", default="nix", help="Nix executable to inspect (default: nix)")
    nix_probe.add_argument("--agda-bin", default="agda", help="Agda executable to inspect (default: agda)")

    index = subparsers.add_parser(
        "index",
        help="build or query source-bound lexical declaration-discovery indexes",
    )
    index_subparsers = index.add_subparsers(dest="index_command", required=True)
    index_build = index_subparsers.add_parser(
        "build",
        help="scan snapshot-visible Agda source for lexical declaration candidates",
    )
    index_build.add_argument("--project-root", type=Path, required=True, help="project directory to scan")
    index_build.add_argument("--output", type=Path, required=True, help="new JSON index output outside the project")
    index_query = index_subparsers.add_parser(
        "query",
        help="query the verified source-bound lexical index in an evidence bundle",
    )
    index_query.add_argument("bundle", type=Path, help="directory containing a bundle with index-ref.json")
    index_filter = index_query.add_mutually_exclusive_group()
    index_filter.add_argument("--exact", help="return candidates with this exact qualified name")
    index_filter.add_argument("--prefix", help="return candidates whose qualified name has this prefix")
    index_query.add_argument(
        "--kind",
        action="append",
        choices=sorted(DECLARATION_KINDS),
        help="candidate kind to retain; repeat to select several kinds",
    )

    aggregate = subparsers.add_parser(
        "aggregate",
        help="create or verify a closed aggregate of independently verified green bundles",
    )
    aggregate_subparsers = aggregate.add_subparsers(dest="aggregate_command", required=True)
    aggregate_create = aggregate_subparsers.add_parser(
        "create",
        help="copy passed enhanced bundles into a closed aggregate envelope",
    )
    aggregate_create.add_argument("--output", type=Path, required=True, help="new or empty aggregate directory")
    aggregate_create.add_argument(
        "--lane",
        action="append",
        required=True,
        metavar="NAME=BUNDLE",
        help="safe lane name and existing child bundle directory; repeat for each lane",
    )
    aggregate_verify = aggregate_subparsers.add_parser(
        "verify",
        help="verify a closed aggregate and every included child bundle",
    )
    aggregate_verify.add_argument("aggregate", type=Path, help="directory containing aggregate.json")

    verify = subparsers.add_parser("verify", help="verify component and bundle identifiers")
    verify.add_argument("bundle", type=Path, help="directory containing bundle.json")
    return parser


def _capture(arguments: argparse.Namespace) -> int:
    command = list(arguments.command)
    if command[:1] == ["--"]:
        command = command[1:]
    resolution = load_resolution_observation(arguments.resolution_file) if arguments.resolution_file else None
    bundle = capture_bundle(
        arguments.project_root,
        arguments.output,
        command,
        agda_binary=arguments.agda_bin,
        scope=arguments.scope,
        timeout_seconds=arguments.timeout_seconds,
        max_output_bytes=arguments.max_output_bytes,
        index_reference=arguments.index_reference,
        resolution_observation=resolution,
    )
    outcome_path = arguments.output / "attestation.json"
    attestation = json.loads(outcome_path.read_text(encoding="utf-8"))
    snapshot = json.loads((arguments.output / "snapshot.json").read_text(encoding="utf-8"))
    resolution = json.loads((arguments.output / "resolution.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "bundleId": bundle["bundleId"],
                "sourceId": snapshot["sourceId"],
                "resolutionId": resolution["resolutionId"],
                "attestationId": attestation["attestationId"],
                "outcome": attestation["outcome"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _probe_nix_resolution(arguments: argparse.Namespace) -> int:
    resolution = build_nix_resolution(
        arguments.project_root,
        nix_binary=arguments.nix_bin,
        agda_binary=arguments.agda_bin,
    )
    write_resolution_observation(arguments.output, resolution)
    print(json.dumps({"resolutionId": resolution["resolutionId"], "output": str(arguments.output)}, indent=2, sort_keys=True))
    return 0


def _index_build(arguments: argparse.Namespace) -> int:
    root = arguments.project_root.resolve()
    output = arguments.output.resolve()
    if output.is_relative_to(root):
        raise EvidenceError("declaration index output must be outside the project root")
    index = build_declaration_index(root)
    write_declaration_index(output, index)
    print(
        json.dumps(
            {
                "indexId": index["indexId"],
                "sourceId": index["sourceId"],
                "entryCount": len(index["entries"]),
                "output": str(output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _index_query(arguments: argparse.Namespace) -> int:
    index = declaration_index_from_bundle(arguments.bundle)
    entries = query_declaration_index(
        index,
        exact=arguments.exact,
        prefix=arguments.prefix,
        kinds=arguments.kind or (),
    )
    print(
        json.dumps(
            {
                "indexId": index["indexId"],
                "sourceId": index["sourceId"],
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _verify(arguments: argparse.Namespace) -> int:
    problems = verify_bundle(arguments.bundle)
    if problems:
        print("Evidence bundle verification failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print("Evidence bundle verification passed.")
    return 0


def _parse_lane_specification(value: str) -> tuple[str, Path]:
    name, delimiter, raw_path = value.partition("=")
    if not delimiter or not name or not raw_path:
        raise EvidenceError("--lane must use NAME=BUNDLE with non-empty values")
    return name, Path(raw_path)


def _aggregate_create(arguments: argparse.Namespace) -> int:
    aggregate = create_aggregate(
        arguments.output,
        [_parse_lane_specification(value) for value in arguments.lane],
    )
    print(
        json.dumps(
            {
                "aggregateId": aggregate["aggregateId"],
                "sourceId": aggregate["sourceId"],
                "lanes": {
                    name: aggregate["lanes"][name]["bundleId"]
                    for name in sorted(aggregate["lanes"])
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _aggregate_verify(arguments: argparse.Namespace) -> int:
    problems = verify_aggregate(arguments.aggregate)
    if problems:
        print("Evidence aggregate verification failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print("Evidence aggregate verification passed.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.subcommand == "capture":
            return _capture(arguments)
        if arguments.subcommand == "probe-nix-resolution":
            return _probe_nix_resolution(arguments)
        if arguments.subcommand == "index" and arguments.index_command == "build":
            return _index_build(arguments)
        if arguments.subcommand == "index" and arguments.index_command == "query":
            return _index_query(arguments)
        if arguments.subcommand == "aggregate" and arguments.aggregate_command == "create":
            return _aggregate_create(arguments)
        if arguments.subcommand == "aggregate" and arguments.aggregate_command == "verify":
            return _aggregate_verify(arguments)
        if arguments.subcommand == "verify":
            return _verify(arguments)
        parser.error(f"unknown subcommand: {arguments.subcommand}")
    except EvidenceError as error:
        print(f"agda-evidence: {error}", file=sys.stderr)
        return 2
    return 2
