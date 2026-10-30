# agda-stdlib source-index result — 30 October 2026

The source-bound declaration-index pilot completed successfully in [GitHub Actions run 41125759317](https://github.com/Nokidme/agda-evidence/actions/runs/41125759317). It pinned `agda/agda-stdlib` to `565739a4d82b8bb47d2f15cb99178db15ca60e9b`, built Agda `2.8.0` from its pinned upstream tag, created a lexical index outside the checkout, attached that index to the evidence bundle, and ran the same upstream full-library gate recorded by the initial standard-library pilot.

The uploaded artifact was downloaded and independently verified with `agda-evidence verify`. The attached index was then loaded only through the verified bundle and queried for lexical `Data.Nat` module candidates.

```text
sourceId:      sha256:5a64564ab914a6af0c4b3ec06b78a469fe382f9cfe9d158f220dd2efc2cbb295
resolutionId:  sha256:0b281336d57f6ab47e043ad2393f402273d2f5679e1c59263f860085a911dd49
attestationId: sha256:7f02b1e2f9aa08b5924f890d8ae6c2c2da9c2b4178f964ec7a56c1a2fcf3af6f
indexId:       sha256:c98c01120714f2ae175128185dedcb8ea7d2a5a6fa950c3179fc40a486f12ca6
bundleId:      sha256:0906937844f33e418f7dff96074e3d0a8b58baede79d1943965894915d388760
```

The snapshot contains 1,417 source files. The source-bound index contains 12,990 lexical candidates. A verified query for `--prefix Data.Nat --kind module` returned 42 candidates; the first was `Data.Nat` at `src/Data/Nat.agda:12`, bound to source digest `sha256:d2a41bea1f1368e1cd5d31c9599486f27bc263a65797db0063ae4e0da9838967`.

The checker attestation passed with exit code `0`. The index result does not say that 12,990 entities typecheck independently, are exported, are complete, or are in scope in a consumer module. It records only lexical source-text candidates bound to the verified snapshot. The full-library typecheck remains the separate, explicitly scoped command claim. The workflow’s direct HTTPS Hackage configuration addressed current runner package availability; it does not preserve or authenticate the Cabal dependency closure. The artifact remains available for 30 days under the linked Actions run.
