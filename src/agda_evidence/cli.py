"""Command-line interface for the agda-evidence reference implementation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .core import (
    EvidenceError,
    build_nix_resolution,
    capture_bundle,
    load_resolution_observation,
    verify_bundle,
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
    parser.add_argument("--index-reference", type=Path, help="optional JSON declaration-index reference")
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


def _verify(arguments: argparse.Namespace) -> int:
    problems = verify_bundle(arguments.bundle)
    if problems:
        print("Evidence bundle verification failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print("Evidence bundle verification passed.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.subcommand == "capture":
            return _capture(arguments)
        if arguments.subcommand == "probe-nix-resolution":
            return _probe_nix_resolution(arguments)
        if arguments.subcommand == "verify":
            return _verify(arguments)
        parser.error(f"unknown subcommand: {arguments.subcommand}")
    except EvidenceError as error:
        print(f"agda-evidence: {error}", file=sys.stderr)
        return 2
    return 2
