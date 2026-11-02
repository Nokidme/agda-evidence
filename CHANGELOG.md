# Changelog

## 0.1.0a0 — unreleased

- Defines the `agda-evidence/bundle-v1` manifest schema.
- Adds a dependency-light reference CLI for snapshotting a project, recording visible Agda configuration, running an explicit command in an isolated copy, and verifying component digests.
- Adds deterministic fixtures and CI for passing and failing checks.
- Adds stable `sourceId` and `resolutionId` values alongside a time-specific `attestationId`, while retaining `bundleId` as the immutable complete-artifact identifier.
- Adds semantic identity verification, timestamp-order checks, and legacy-v1 integrity compatibility tests.
- Adds a manual-only, upstream-pinned `agda-stdlib` pilot workflow and pilot documentation.
- Adds a Nix-environment resolution probe plus verified resolution-file handoff for flake-defined Agda toolchains.
- Binds newly probed Nix resolution identities to the evaluated Nix platform as well as the flake-file digests.
- Adds a manual-only, upstream-pinned `agda-algebras` Type-check library pilot workflow and documentation.
- Adds a manual-only, upstream-pinned Cardano `formal-ledger-agda` pilot workflow and documentation.
- Adds a closed aggregate-v1 envelope for independently verified green lanes from one captured source tree.
- Adds source-bound lexical declaration-index build and evidence-query commands, including stale-index rejection at capture time.
- Adds explicit local discovery catalogs with source/resolution pins, all-or-nothing validation, and per-result check/index provenance across independent libraries.
- Reuses verified in-memory payloads for discovery, rejects ambiguous JSON keys, and handles malformed declaration kinds as validation errors.
- Adds isolated native-Agda top-level type observations with prompt-aware bounded sessions, clean-load gating, optional source/resolution pins, and offline response/result verification.

This is a pre-alpha reference implementation. It does not resolve or fetch dependencies, parse all Agda diagnostics, prove a dependency closure, or guarantee offline replay.
