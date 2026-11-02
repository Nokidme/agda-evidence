"""Command-line interface for the agda-evidence reference implementation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .catalog import CatalogValidationError, create_catalog, query_catalog, verify_catalog
from .checker import CheckerEvidenceError, infer_type, load_observation, write_observation
from .client import client_summary, infer_client, load_client_observation, write_client_observation
from .goals import load_goal_observation, observe_goals, write_goal_observation
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


class _Once(argparse.Action):
    """Reject repeated single-valued client selectors instead of last-value wins."""

    def __call__(self, parser: argparse.ArgumentParser, namespace: argparse.Namespace,
                 values: object, option_string: str | None = None) -> None:
        marker = f"_explicit_{self.dest}"
        if getattr(namespace, marker, False):
            parser.error(f"{option_string} may be supplied only once")
        setattr(namespace, marker, True)
        setattr(namespace, self.dest, values)


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

    catalog = subparsers.add_parser("catalog", help="pin and search an explicit local set of indexed bundles")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_create = catalog_commands.add_parser("create", help="write a new local config with source/resolution pins")
    catalog_create.add_argument("--output", type=Path, required=True, help="new local catalog JSON file")
    catalog_create.add_argument("--entry", action="append", required=True, metavar="NAME=BUNDLE")
    catalog_verify = catalog_commands.add_parser("verify", help="verify every catalog entry and its identity pins")
    catalog_verify.add_argument("catalog", type=Path)
    catalog_query = catalog_commands.add_parser("query", help="query all verified entries with evidence provenance")
    catalog_query.add_argument("catalog", type=Path)
    catalog_filters = catalog_query.add_mutually_exclusive_group()
    catalog_filters.add_argument("--exact", help="exact qualified candidate name")
    catalog_filters.add_argument("--prefix", help="qualified candidate name prefix")
    catalog_query.add_argument("--kind", action="append", choices=sorted(DECLARATION_KINDS))
    catalog_query.add_argument("--library", action="append", help="catalog label to search; repeat to select several")

    checker = subparsers.add_parser("checker", help="record or verify isolated native-Agda expression types")
    checker_commands = checker.add_subparsers(dest="checker_command", required=True)
    checker_infer = checker_commands.add_parser("infer", help="load a snapshot-staged module and infer an explicit expression")
    checker_infer.add_argument("--project-root", type=Path, required=True)
    checker_infer.add_argument("--file", required=True, help="snapshot-relative .agda or .lagda.md source path")
    checker_infer.add_argument("--expression", required=True, help="expression interpreted in the loaded module's top-level scope")
    checker_infer.add_argument("--output", type=Path, required=True, help="new observation JSON outside project/evidence")
    checker_infer.add_argument("--agda-bin", default="agda", help="native Agda executable, not a shell command")
    checker_infer.add_argument("--include", action="append", default=[], help="explicit project-relative include directory")
    checker_infer.add_argument("--safe", action="store_true", help="add Agda --safe to the recorded command")
    checker_infer.add_argument("--timeout-seconds", type=int, default=60)
    checker_infer.add_argument("--max-output-bytes", type=int, default=4_194_304)
    checker_infer.add_argument("--bundle", type=Path, help="optional verified enhanced bundle to pin live source/resolution")
    checker_verify = checker_commands.add_parser("verify", help="verify saved observation without running Agda")
    checker_verify.add_argument("observation", type=Path)

    client = subparsers.add_parser("client", help="infer in an unchanged client with one pinned source library")
    client_commands = client.add_subparsers(dest="client_command", required=True)
    client_infer = client_commands.add_parser("infer", help="compose explicit client/library source copies and query the client")
    for flag, value_type in (("--project-root", Path), ("--library-root", Path), ("--library-bundle", Path), ("--output", Path)):
        client_infer.add_argument(flag, type=value_type, required=True, action=_Once)
    for flag in ("--file", "--expression", "--candidate-path", "--candidate-qualified-name"):
        client_infer.add_argument(flag, required=True, action=_Once)
    client_infer.add_argument("--candidate-line", type=int, required=True, action=_Once)
    client_infer.add_argument("--candidate-kind", choices=sorted(DECLARATION_KINDS), required=True, action=_Once)
    client_infer.add_argument("--library-include", action="append", required=True, help="explicit library-relative include root")
    client_infer.add_argument("--include", action="append", default=[], help="additional client-relative include root")
    client_infer.add_argument("--agda-bin", default="agda", action=_Once)
    client_infer.add_argument("--safe", action="store_true")
    client_infer.add_argument("--timeout-seconds", type=int, default=60, action=_Once)
    client_infer.add_argument("--max-output-bytes", type=int, default=4_194_304, action=_Once)
    client_verify = client_commands.add_parser("verify", help="verify client envelope and embedded evidence without Agda")
    client_verify.add_argument("observation", type=Path)

    goals = subparsers.add_parser("goals", help="record read-only unfinished goals and selected local contexts")
    goal_commands = goals.add_subparsers(dest="goals_command", required=True)
    goal_list = goal_commands.add_parser("list", help="load a source copy and record interaction points without querying them")
    goal_list.add_argument("--file", required=True, action=_Once)
    goal_list.add_argument("--include", action="append", default=[])
    goal_list.add_argument("--safe", action="store_true")
    goal_inspect = goal_commands.add_parser("inspect", help="query one explicit goal under a prior listing's source/policy pins")
    goal_inspect.add_argument("--listing", type=Path, required=True, action=_Once)
    goal_inspect.add_argument("--goal-id", type=int, required=True, action=_Once)
    for command in (goal_list, goal_inspect):
        command.add_argument("--project-root", type=Path, required=True, action=_Once)
        command.add_argument("--output", type=Path, required=True, action=_Once)
        command.add_argument("--agda-bin", default="agda", action=_Once)
        command.add_argument("--timeout-seconds", type=int, default=60, action=_Once)
        command.add_argument("--max-output-bytes", type=int, default=4_194_304, action=_Once)
    goal_verify = goal_commands.add_parser("verify", help="verify a saved goal observation without Agda")
    goal_verify.add_argument("observation", type=Path)

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


def _catalog(arguments: argparse.Namespace) -> int:
    if arguments.catalog_command == "create":
        references = []
        for value in arguments.entry:
            name, delimiter, path = value.partition("=")
            if not delimiter or not name or not path:
                raise EvidenceError("--entry must use NAME=BUNDLE with non-empty values")
            references.append((name, Path(path)))
        result = create_catalog(arguments.output, references)
    elif arguments.catalog_command == "verify":
        result = verify_catalog(arguments.catalog)
    else:
        result = query_catalog(
            arguments.catalog, exact=arguments.exact, prefix=arguments.prefix,
            kinds=arguments.kind or (), libraries=arguments.library or (),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _checker(arguments: argparse.Namespace) -> int:
    if arguments.checker_command == "verify":
        observation = load_observation(arguments.observation)
        print(json.dumps({"observationId": observation["observationId"], "result": observation["result"]}, ensure_ascii=False, indent=2))
        return 0
    output = arguments.output
    if output.exists() or output.is_symlink():
        raise EvidenceError(f"type observation output already exists: {output}")
    if output.resolve().is_relative_to(arguments.project_root.resolve()):
        raise EvidenceError("type observation output must be outside the project root")
    if arguments.bundle and output.resolve().is_relative_to(arguments.bundle.resolve()):
        raise EvidenceError("type observation output must be outside its basis bundle")
    observation = infer_type(
        arguments.project_root, arguments.file, arguments.expression,
        agda_binary=arguments.agda_bin, includes=arguments.include, safe=arguments.safe,
        timeout_seconds=arguments.timeout_seconds, max_output_bytes=arguments.max_output_bytes,
        bundle=arguments.bundle,
    )
    write_observation(output, observation)
    print(json.dumps({"observationId": observation["observationId"], "sourceId": observation["snapshot"]["sourceId"],
                      "resolutionId": observation["resolution"]["resolutionId"], "result": observation["result"]},
                     ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if observation["result"]["status"] == "inferred" else 1


def _client(arguments: argparse.Namespace) -> int:
    if arguments.client_command == "verify":
        observation = load_client_observation(arguments.observation)
        print(json.dumps(client_summary(observation), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    output = arguments.output
    if output.exists() or output.is_symlink():
        raise EvidenceError(f"client observation output already exists: {output}")
    for root in (arguments.project_root, arguments.library_root, arguments.library_bundle):
        if output.resolve().is_relative_to(root.resolve()):
            raise EvidenceError("client observation output must be outside client, library and evidence roots")
    observation = infer_client(
        arguments.project_root, arguments.file, arguments.expression,
        library_bundle=arguments.library_bundle, library_root=arguments.library_root,
        library_includes=arguments.library_include,
        candidate={"path": arguments.candidate_path, "line": arguments.candidate_line,
                   "qualifiedName": arguments.candidate_qualified_name, "kind": arguments.candidate_kind},
        agda_binary=arguments.agda_bin, includes=arguments.include, safe=arguments.safe,
        timeout_seconds=arguments.timeout_seconds, max_output_bytes=arguments.max_output_bytes,
    )
    write_client_observation(output, observation)
    print(json.dumps(client_summary(observation), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if observation["typeObservation"]["result"]["status"] == "inferred" else 1


def _goals(arguments: argparse.Namespace) -> int:
    if arguments.goals_command == "verify":
        value = load_goal_observation(arguments.observation)
    else:
        output = arguments.output
        if output.exists() or output.is_symlink():
            raise EvidenceError(f"goal observation output already exists: {output}")
        if output.resolve().is_relative_to(arguments.project_root.resolve()):
            raise EvidenceError("goal observation output must be outside the project root")
        listing = load_goal_observation(arguments.listing) if arguments.goals_command == "inspect" else None
        value = observe_goals(
            arguments.project_root, listing["query"]["file"] if listing else arguments.file,
            agda_binary=arguments.agda_bin,
            includes=listing["query"]["includes"] if listing else arguments.include,
            safe=listing["query"]["safe"] if listing else arguments.safe,
            listing=listing, goal_id=arguments.goal_id if listing else None,
            timeout_seconds=arguments.timeout_seconds, max_output_bytes=arguments.max_output_bytes,
        )
        write_goal_observation(output, value)
    print(json.dumps({"observationId": value["observationId"], "sourceId": value["snapshot"]["sourceId"],
                      "resolutionId": value["resolution"]["resolutionId"], "result": value["result"]},
                     ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if arguments.goals_command == "verify" or value["result"]["status"] in {"listed", "inspected"} else 1


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
        if arguments.subcommand == "catalog":
            return _catalog(arguments)
        if arguments.subcommand == "checker":
            return _checker(arguments)
        if arguments.subcommand == "client":
            return _client(arguments)
        if arguments.subcommand == "goals":
            return _goals(arguments)
        if arguments.subcommand == "aggregate" and arguments.aggregate_command == "create":
            return _aggregate_create(arguments)
        if arguments.subcommand == "aggregate" and arguments.aggregate_command == "verify":
            return _aggregate_verify(arguments)
        if arguments.subcommand == "verify":
            return _verify(arguments)
        parser.error(f"unknown subcommand: {arguments.subcommand}")
    except (CatalogValidationError, CheckerEvidenceError) as error:
        print(f"agda-evidence: {error}", file=sys.stderr)
        return 1
    except EvidenceError as error:
        print(f"agda-evidence: {error}", file=sys.stderr)
        return 2
    return 2
