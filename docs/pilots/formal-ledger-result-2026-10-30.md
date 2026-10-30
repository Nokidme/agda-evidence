# Cardano formal-ledger pilot result — 30 October 2026

The initial formal-ledger pilot completed successfully in [GitHub Actions run 41107525351](https://github.com/Nokidme/agda-evidence/actions/runs/41107525351). It pinned `IntersectMBO/formal-ledger-specifications` to commit `7d4956e92bfa7cc472dca79c6eaf496677c24ea5`.

The workflow first observed the locked flake’s Agda resolution in `nix develop`, removed any local probe state, and then ran the upstream protected Agda gate from an isolated staged source copy:

```sh
nix build --no-write-lock-file -o outputs .#formal-ledger
```

The uploaded bundle was downloaded and independently verified with `agda-evidence verify`. Its composite command exited with status `passed` and exit code `0`.

```text
sourceId:      sha256:de97813ea428c4534c41dbd2bf8640bfbcf9ad32de325658277d5e104945b324
resolutionId:  sha256:96727190fb0d9e8819d5c2bf75ffc37e75253a62fdfab3f39ddf45c304567caf
attestationId: sha256:55a7ca1ff0be006c37ec6433df2997decf054e669e07245d3d6408966d29d265
bundleId:      sha256:41d11f02b175eeb4b01d8087e0a80e69eedb470e43395ef0ea7b7237e961acdb
```

The source snapshot contains 404 regular files. Its Nix resolution observation records `x86_64-linux`, Nix `2.35.4`, and Agda `2.8.0` with these flake-input file identities:

```text
flake.nix:  sha256:50452a23d8bbefa81a2990cba9a4678980ea5c8eb5b1eedebd78116711d5d2b2
flake.lock: sha256:e8fbb9af4a463caadca4c7ef90cbcf9214ca0c0f97212dd76cb478874602f478
```

This result attests only the recorded `formal-ledger-agda` derivation: it typechecks the top-level Ledger specification and invokes the project’s completeness check for interfaces under `src/Ledger`. It does not attest Haskell extraction, documentation generation, property-catalog drift checking, artifact publication, Cardano-ledger conformance, a preserved Nix-store closure, offline replayability, signatures, or the informal meaning of the specification. The uploaded bundle remains available as an Actions artifact for 30 days under the linked run.
