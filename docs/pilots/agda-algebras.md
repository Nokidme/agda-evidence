# agda-algebras pilot

This pilot validates `agda-evidence` against the **Type-check library** lane of `ualib/agda-algebras`. It does not replace or serialize the repository’s broader seven-job `All checks` aggregate.

## Pinned target and native gate

The initial target is `ualib/agda-algebras` commit `c7617677f0e4233939660aa42e7fafb2f68e95e0` on `master`, observed on 30 October 2026. Its supported 3.0 toolchain is Nix-only: `flake.lock` and `flake.nix` pin an unreleased Agda 2.9.0-line compiler and a patched standard-library 2.3.

The source CI’s typecheck job runs these commands in order:

```sh
nix flake check
nix develop --command make check
```

`make check` regenerates `src/Everything.agda` for the canonical library and `src/EverythingLegacy.agda` for the frozen Legacy tree, then checks both with the project’s configured RTS settings. The generated aggregators, `.agda` project registry, and `_build` interfaces are not source input and are ignored by the project.

## Why the Nix probe is separate

A generic capture probes `agda` before it stages and runs the supplied command. That is accurate for an ordinary host toolchain but insufficient for `nix develop`, where the pinned executable and project-local registry are created only inside the flake environment.

The manual workflow therefore has two phases:

1. It runs `agda-evidence probe-nix-resolution` inside `nix develop`. The probe observes the actual Agda binary/version, normalized project-local registry, Nix version, and `flake.nix`/`flake.lock` digests. It writes a semantically verified `resolution.json` outside the checkout.
2. It removes the probe-created `.agda` directory, then runs ordinary `agda-evidence capture` with `--resolution-file` and the exact native command sequence in a new staged project copy. The staged command invokes `nix develop` itself, so its shell hook creates a registry for the staged copy rather than inheriting the original checkout’s wrapper.

The adapter normalizes the stage/checkout path in registry identity data and unwraps the generated project launcher to the underlying Nix-store Agda executable. Thus two clean checkouts of identical flake inputs can compare their `resolutionId` without disclosing or depending on their checkout path.

## Claim and limits

A green pilot attests that the explicit two-command Type-check library sequence exited successfully in a cold isolated copy of the pinned source. It records a **partial** Nix resolution observation; it does not archive the Nix store closure, prove offline replayability, capture private Cachix configuration, or make claims about the separate link, barrel, span-class, docstring, landing-stat, or site/offline CI lanes.

The workflow never runs `make check` from an already-entered Nix shell in the original checkout. Doing so could pass the original checkout’s `AGDA_DIR` and wrapper into the staged copy, which would weaken the isolation claim.

## Sources

- [agda-algebras README](https://github.com/ualib/agda-algebras/blob/c7617677f0e4233939660aa42e7fafb2f68e95e0/README.md)
- [agda-algebras CI workflow](https://github.com/ualib/agda-algebras/blob/c7617677f0e4233939660aa42e7fafb2f68e95e0/.github/workflows/ci.yml)
- [agda-algebras Makefile](https://github.com/ualib/agda-algebras/blob/c7617677f0e4233939660aa42e7fafb2f68e95e0/Makefile)
- [agda-algebras flake](https://github.com/ualib/agda-algebras/blob/c7617677f0e4233939660aa42e7fafb2f68e95e0/flake.nix)
