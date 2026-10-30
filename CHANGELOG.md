# Changelog

## 0.1.0a0 — unreleased

- Defines the `agda-evidence/bundle-v1` manifest schema.
- Adds a dependency-light reference CLI for snapshotting a project, recording visible Agda configuration, running an explicit command in an isolated copy, and verifying component digests.
- Adds deterministic fixtures and CI for passing and failing checks.
- Adds stable `sourceId` and `resolutionId` values alongside a time-specific `attestationId`, while retaining `bundleId` as the immutable complete-artifact identifier.
- Adds semantic identity verification, timestamp-order checks, and legacy-v1 integrity compatibility tests.
- Adds a manual-only, upstream-pinned `agda-stdlib` pilot workflow and pilot documentation.

This is a pre-alpha reference implementation. It does not resolve or fetch dependencies, parse all Agda diagnostics, prove a dependency closure, or guarantee offline replay.
