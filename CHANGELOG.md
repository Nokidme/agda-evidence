# Changelog

## 0.1.0a1 — alpha candidate

- Distributes all ten canonical versioned JSON schemas as `agda_evidence.schemas` resources in both wheel and source archive, preserving relative schema references.
- Includes contract/pilot documentation, source examples, tests and reusable scripts in source distributions.
- Derives package metadata and CLI version from the single package version constant.
- Adds external fresh-environment wheel/source installation checks and an installed-artifact CI matrix, separate from editable source tests.
- Distinguishes native Windows drive paths from URI schemes in local catalogs, rejects network/UNC references, and retains local absolute references across different Windows drives.
- Documents exact Python/platform/compiler observation levels and explicitly unsupported runtime profiles; no stronger evidence claims or format changes.

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
- Adds one-library client expression observations with exact lexical selection context, pinned source composition, complete embedded evidence, and offline cross-binding checks.
- Anchors newly executed checker include paths to the staged workspace while retaining the original relative-argv v1 verification profile; client envelopes require anchored argv.
- Adds bounded read-only unfinished-goal listings and prior-listing-pinned combined type/context observations, with a separate diagnostic policy and no proof edits.
- Adds non-filling, source-pinned candidate elaboration trials with exact restored-goal postflight checks; positive results deliberately do not certify candidate-local residual freedom or proof completion.
- Adds a host-owned research workspace API with document/record IDs, project/catalog lexical search, selected goal/trial evidence, editor generation and live-input freshness guards, and bounded immutable session history; no editor deployment or public server is implied.

This history records the pre-alpha reference implementation. Neither the pre-alpha nor the bounded alpha resolves or fetches dependencies, parses all Agda diagnostics, proves a dependency closure, or guarantees offline replay.
