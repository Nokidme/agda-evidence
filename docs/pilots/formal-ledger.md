# Cardano formal-ledger pilot

This pilot validates `agda-evidence` against the protected primary Agda gate in [`IntersectMBO/formal-ledger-specifications`](https://github.com/IntersectMBO/formal-ledger-specifications). The initial target is commit `7d4956e92bfa7cc472dca79c6eaf496677c24ea5` on `master`, observed on 30 October 2026.

## Recorded gate

The upstream [`formal-ledger-agda` CI job](https://github.com/IntersectMBO/formal-ledger-specifications/blob/7d4956e92bfa7cc472dca79c6eaf496677c24ea5/.github/workflows/ci.yml) uses Nix and executes:

```sh
nix build -o outputs
```

The default flake package is `formal-ledger`. The pilot runs the explicit equivalent below from its isolated staged copy, with lock-file writes disabled:

```sh
nix build --no-write-lock-file -o outputs .#formal-ledger
```

That derivation invokes Agda on `src/Ledger.lagda.md`. Its repository check script then requires a current interface file for every matching Agda source in `src/Ledger`.[1] The scope recorded in each bundle is therefore:

> `formal-ledger-agda: full Ledger specification typecheck at <commit>`

It is not a single-module development check. The upstream contribution guide documents `nix develop --command agda <module>` as a faster local iteration aid, but that command is not the protected CI status.[2]

## Flake-backed resolution and isolated execution

The project’s flake pins Nix inputs and provides the custom Agda environment. The root library descriptor declares `src` and `src-lib-exts` plus five direct library dependencies.[3] [4]

The workflow follows the maintained Nix-pilot procedure:

1. It clones the selected commit, detaches it, and refuses known generated state (`.agda`, `_build`, `dist`, `.shake`, `result`, and `outputs`).
2. From the clean source root, it runs `probe-nix-resolution` inside `nix develop`. The observation records the Nix and Agda version results, evaluated Nix platform, normalized visible registry, and digests for `flake.nix` and `flake.lock`.
3. It removes any probe-created local `.agda` directory, snapshots the clean project, and runs the exact Nix build from the new staged source copy. The `outputs` link is created only inside that disposable copy.
4. It verifies the uploaded evidence bundle and requires its recorded outcome to be `passed`.

The upstream CI configures public IOG and Nix caches. The pilot mirrors that availability configuration, but the cache is not an immutable dependency archive and is not the source of the bundle’s toolchain identity. The flake files and the actual resolution observation are.[3]

## What this does not claim

A green pilot says only that the recorded formal-ledger Nix derivation passed for the captured source snapshot and flake observation. It does not establish offline replayability or preserve the Nix store closure.

It also does not cover the upstream `hs` Haskell extraction job, MkDocs generation, artifact-branch publication, the independent property-catalog drift check, or nightly conformance testing against the separate `cardano-ledger` repository. Those are separate commands and will need separate bundles or a future explicit aggregate manifest.[5] [6]

## Initial result

The first pinned run passed on 30 October 2026. Its independently verified identifiers, toolchain observations, and exact claim are recorded in [the initial result](formal-ledger-result-2026-10-30.md).

## Sources

[1]: https://github.com/IntersectMBO/formal-ledger-specifications/blob/7d4956e92bfa7cc472dca79c6eaf496677c24ea5/build-tools/scripts/checkTypeChecked.sh "Formal-ledger completeness check"
[2]: https://github.com/IntersectMBO/formal-ledger-specifications/blob/7d4956e92bfa7cc472dca79c6eaf496677c24ea5/CONTRIBUTING.md "Formal-ledger contributor guide"
[3]: https://github.com/IntersectMBO/formal-ledger-specifications/blob/7d4956e92bfa7cc472dca79c6eaf496677c24ea5/flake.nix "Formal-ledger Nix flake"
[4]: https://github.com/IntersectMBO/formal-ledger-specifications/blob/7d4956e92bfa7cc472dca79c6eaf496677c24ea5/formal-ledger.agda-lib "Formal-ledger library descriptor"
[5]: https://github.com/IntersectMBO/formal-ledger-specifications/blob/7d4956e92bfa7cc472dca79c6eaf496677c24ea5/.github/workflows/ci.yml "Formal-ledger CI workflow"
[6]: https://github.com/IntersectMBO/formal-ledger-specifications/blob/7d4956e92bfa7cc472dca79c6eaf496677c24ea5/.github/workflows/properties-check.yml "Formal-ledger properties check"
