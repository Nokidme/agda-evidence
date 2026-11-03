# agda-evidence

`agda-evidence` creates a portable evidence bundle for an **explicit** Agda project check. A bundle captures the exact project source tree, visible Agda/library configuration, the command that ran, bounded process output, and content-addressed component digests.

It is intentionally small and local. It does not choose a build command, fetch or solve dependencies, replace Agda’s package system, provide an interactive proving server, or claim that a passed check proves informal mathematical intent.

## Status

The published bounded alpha is [`v0.1.0a1`](https://github.com/Nokidme/agda-evidence/releases/tag/v0.1.0a1); the main branch now contains unreleased `0.1.0a2.dev0` development. Neither is a stable API. The core has no runtime dependencies beyond Python 3.11+. See the [alpha support and distribution contract](docs/alpha-release.md) for the release's exact tested scope and procedure.

A passed bundle means only that the **recorded explicit command** exited successfully in an isolated copy of the recorded project source. It does not claim a full dependency closure, offline replayability, all-project coverage, or structured Agda diagnostics.

The v1 profile distinguishes three comparison values: `sourceId` for the captured source tree, `resolutionId` for the visible partial resolution context, and `attestationId` for the time-specific command outcome. `bundleId` remains the identifier of the complete immutable artifact, so separate captures can have distinct bundle IDs even when their source and resolution IDs match.

## Install

For development:

```sh
python -m pip install -e .
```

Or run directly from a checkout:

```sh
PYTHONPATH=src python -m agda_evidence --help
```

Built wheel and source distributions include all versioned JSON schemas as `agda_evidence.schemas` resources; the source archive also retains documentation and examples. The alpha CI checks both installations outside the checkout. Agda itself must be installed separately; native interaction adapters require POSIX and an explicitly supported source/dependency profile. Do not infer compiler/platform support from the wheel's `py3-none-any` tag.

## Capture a project check

Pass the intended project command after `--`. The command is executed without a shell in a temporary copy of the project, so generated files do not modify the working tree.

```sh
agda-evidence capture \
  --project-root /path/to/project \
  --output /tmp/project.evidence \
  --scope "whole-library check" \
  -- make check
```

The output directory must be new or empty and must be outside the project root. If the project needs a particular Agda executable, record it explicitly:

```sh
agda-evidence capture \
  --project-root /path/to/project \
  --output /tmp/project.evidence \
  --agda-bin /path/to/agda \
  -- agda Everything.agda
```

The reference CLI records that Agda was unavailable when it cannot run the configured binary. It can still capture an explicit command that does not require the binary, which is useful for testing the bundle contract but does not create a meaningful Agda attestation.

For a project whose supported Agda environment exists only inside a pinned Nix flake, first run `probe-nix-resolution` *inside* `nix develop`, save its output outside the project, and pass it back via `capture --resolution-file`. The check command must still invoke its project’s native Nix command from the staged copy. The [agda-algebras pilot](docs/pilots/agda-algebras.md) and [formal-ledger pilot](docs/pilots/formal-ledger.md) are maintained examples.

## Aggregate independent lanes

For multiple independently captured green lanes from the **same** source tree, create a closed aggregate. It physically includes each child bundle and rejects failed lanes, mixed source identities, duplicated evidence, and external references:

```sh
agda-evidence aggregate create \
  --output /tmp/project.aggregate \
  --lane typecheck=/tmp/project-typecheck.evidence \
  --lane docs=/tmp/project-docs.evidence

agda-evidence aggregate verify /tmp/project.aggregate
```

An aggregate says only that every included child command passed for the shared `sourceId`; it does not prove that those lanes are a project’s complete CI matrix. See the [aggregate format guide](docs/aggregate.md).

## Discover source-bound declaration candidates

Build a deterministic lexical index from snapshot-visible `.agda` and fenced literate Agda source, attach it to a capture, and query that verified bundle:

```sh
agda-evidence index build --project-root ./library --output /tmp/library.index.json
agda-evidence capture --project-root ./library --output /tmp/library.evidence \
  --index-reference /tmp/library.index.json -- make check
agda-evidence index query /tmp/library.evidence --prefix Data.Nat
```

The index is deliberately lexical: it finds documented source-text candidates, not typechecked, resolved, exported, or complete declarations. Capture rejects an index that is stale or does not exactly match the captured source scan. See the [declaration-index guide](docs/declaration-index.md).

## Search an explicit set of libraries

A local catalog names indexed evidence bundles and pins each entry's source and partial resolution identities. Queries verify every entry before returning candidates with independent bundle, index, and check provenance:

```sh
agda-evidence catalog create --output /work/catalog.json \
  --entry stdlib=/work/stdlib.evidence --entry research=/work/research.evidence
agda-evidence catalog verify /work/catalog.json
agda-evidence catalog query /work/catalog.json --prefix Data.Nat
```

Duplicate candidate names stay separate. A catalog may include different sources or failed checks; it is not a green aggregate, installed Agda environment, compatibility claim, or scope resolver. Paths are local references, not preserved contents. See the [local catalog guide](docs/local-catalog.md).

## Ask Agda for an expression's type

The native POSIX checker adapter loads an isolated snapshot copy and infers an explicit expression in that module's top-level scope. It does not insert holes or edit the original source:

```sh
agda-evidence checker infer --project-root examples/type-query \
  --file Main.agda --expression identity --safe --output /tmp/identity.type.json
agda-evidence checker verify /tmp/identity.type.json
```

An optional `--bundle` pins the current source and visible resolution to earlier verified evidence. This first adapter disables library files, uses explicit project-relative include roots, and requires a clean load. Failed queries save diagnostic observations rather than types. Saved observation verification is local and does not rerun Agda. Inferred display text does not prove a lexical candidate's declaration origin or importability elsewhere. See the [checker guide](docs/checker.md).

## Try a discovered expression in an existing client

`client infer` composes unchanged client and library source copies, pins one selected indexed library bundle against its checkout and native compiler context, and queries an explicit expression in the existing client module. It adds no import and guesses no qualification. The complete selected evidence and nested checker observation are saved in one independently verifiable envelope.

The [client guide](docs/client.md) provides selection/import/query commands. A reusable native pilot demonstrates successful explicit imports and aliases, failed missing-import/private-name queries, and a local-homonym success that must **not** be interpreted as selected-candidate resolution:

```sh
python scripts/client-pilot.py --agda-bin /usr/bin/agda --output /tmp/native-client-pilot
agda-evidence client verify /tmp/native-client-pilot/imported.client.json
```

This supports one direct source-library pair, not dependency solving, Nix activation, an export graph, or a general expression-to-declaration identity claim.

## Inspect unfinished proof goals

List unfinished goals, then inspect one explicit ID against that saved listing's source, compiler and policy pins:

```sh
agda-evidence goals list --project-root examples/goal-query --file Main.agda \
  --safe --output /tmp/goals.list.json
agda-evidence goals inspect --project-root examples/goal-query \
  --listing /tmp/goals.list.json --goal-id 1 --output /tmp/goal-context.json
agda-evidence goals verify /tmp/goal-context.json
```

The result retains displayed type, structured local bindings, and goal-related constraint/boundary text. It never fills holes or declares the proof complete. Unfinished loads may have `checked: false`; a separate conservative policy blocks unrelated warnings/errors without weakening clean-only type inference. See the [goal inspection guide](docs/goals.md).

## Try a proposed expression without filling the goal

```sh
agda-evidence goals check --project-root examples/goal-query \
  --listing /tmp/goals.list.json --goal-id 0 --expression 'n' \
  --output /tmp/candidate-n.json
agda-evidence goals verify-check /tmp/candidate-n.json
```

Agda checks against the selected goal's contextual expected type, then the adapter verifies that the restored goal summary is unchanged. The positive status is **`elaborated`**, not proof completion or candidate-local obligation freedom: Agda discards speculative checking state before those diagnostics are collected. No expression is inserted and every trial gets a fresh isolated session. See the [candidate guide](docs/candidates.md), including a native unused-meta counterexample to stronger claims.

## Connect an existing research editor

The optional Python `ResearchWorkspace` facade joins host-configured document IDs, goal selection, project/catalog lexical discovery, explicit candidate trials and complete evidence retrieval. Requests carry an editor revision; dirty buffers, source/compiler changes and late results are not promoted as current. A bounded session store retains current or historical exact artifacts without allowing client-supplied host paths or compiler commands.

See the [research API guide](docs/research-api.md) and `scripts/research-pilot.py`. This is a library integration contract, not a replacement editor or a claim that a live AgdaLab deployment has already been modified. The host must provide authorization, revision materialization and execution isolation.

## Use an explicit source dependency in unfinished client work

The unreleased `source list/inspect/check/verify` family composes unchanged client sources with **one complete pinned native source dependency**, without requiring a lexical candidate selection or declaration index. A separate source envelope binds original source/environment subjects, the exact dependency bundle, declared include roots and the unchanged inner goal/candidate records. Saved selections inherit their complete composition pins; native work never adds imports or fills holes.

See the [source dependency guide](docs/sources.md) and the finite `scripts/sources-pilot.py` stdlib example. This does not activate Nix, resolve transitive dependencies, preserve a replayable closure or automatically upgrade the existing `ResearchWorkspace` runtime profile. Candidate success still means contextual elaboration only.

For an explicitly opted-in editor host, [`SourceResearchWorkspace` API version 2](docs/source-research-api.md) adds dependency source/resolution/bundle and composition freshness to research revisions, lexical dependency search and complete source-envelope history. Observable changed dependencies mark history stale; missing required evidence marks it unknown. Frozen pins are never refreshed by a client request, and the ordinary v1 facade remains unchanged. `scripts/source-research-pilot.py` exercises the source-aware session independently of any app deployment.

## Verify a bundle

```sh
agda-evidence verify /tmp/project.evidence
```

Verification recomputes every component digest and the bundle identifier. It does not rerun the check. A future replay command will be a separate feature because it must state which environment and dependency guarantees it makes.

## Bundle contents

| File | Meaning |
| --- | --- |
| `bundle.json` | Version, immutable artifact identifier, and component-digest map. |
| `snapshot.json` | Content-addressed regular source/configuration files and stable `sourceId`. |
| `resolution.json` | Visible partial resolution evidence and stable `resolutionId`. |
| `attestation.json` | Explicit command, outcome, source/resolution subjects, and time-specific `attestationId`. |
| `diagnostics.json` | Bounded process stdout/stderr; v0.1 does not claim a structured Agda parser. |
| `index-ref.json` | Optional source-bound lexical declaration index (or byte-integrity-compatible legacy opaque reference). |

Read the [v1 schema notes](docs/schema.md) before publishing a bundle. Bundle contents can include source, command arguments, and tool output; inspect them before sharing.

## Development

```sh
python -m unittest discover -s tests -v
```

The first validation target is a common contract across `agda-stdlib`, `agda-algebras`, and the Cardano formal ledger. The [agda-stdlib pilot](docs/pilots/agda-stdlib.md) transcribes a full-library gate, while the two Nix pilots preserve their projects’ native root-level commands. The core uses adapters only where project-specific conventions cannot fit the generic contract.

## License

Apache-2.0. See [LICENSE](LICENSE).
