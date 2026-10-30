# Changelog

## 0.1.0a0 — unreleased

- Defines the `agda-evidence/bundle-v1` manifest schema.
- Adds a dependency-light reference CLI for snapshotting a project, recording visible Agda configuration, running an explicit command in an isolated copy, and verifying component digests.
- Adds deterministic fixtures and CI for passing and failing checks.

This is a pre-alpha reference implementation. It does not resolve or fetch dependencies, parse all Agda diagnostics, prove a dependency closure, or guarantee offline replay.
