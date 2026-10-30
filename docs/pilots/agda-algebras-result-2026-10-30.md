# agda-algebras pilot result — 30 October 2026

The initial Nix-aware real-project pilot completed successfully in [GitHub Actions run 41092347421](https://github.com/Nokidme/agda-evidence/actions/runs/41092347421). It pinned `ualib/agda-algebras` to commit `c7617677f0e4233939660aa42e7fafb2f68e95e0`.

The workflow first observed the flake-provided Agda environment, then removed the generated project-local `.agda` registry before snapshotting source. The final evidence bundle was downloaded and independently verified with `agda-evidence verify`. Its recorded command ran the upstream Type-check library lane in the staged project copy:

```sh
nix flake check --no-write-lock-file
nix develop --no-write-lock-file --command make check
```

The composite command exited with status `passed` and exit code `0`.

```text
sourceId:      sha256:9404a28d1c7c5a70f9d055936d850daef6c7e33f13e2eb0f3792ed1eec185dca
resolutionId:  sha256:2c1fccb01e3f9111b28fe9cb84290985511ff31c585a26239357965473ec702c
attestationId: sha256:7ad9374712f2f714a4b25aabe8de78636a9a5ec73ea8c9ce6dff072d3de84622
bundleId:      sha256:70eb5ab32cd35dcf8e0cffa37a371fe9910c204d49255bb2f5ee43ff89649464
```

The source snapshot contains 515 regular files. The resolution observation records Nix `2.35.4`, Agda `2.9.0`, and these flake-input file identities:

```text
flake.nix:  sha256:5f2fc2b511671a2a333c192084abeeb7e5e8f194c699736e8693e7a987ec0773
flake.lock: sha256:08ecce250133613308fa7cd3eec58e8614627a978cce9537a67d4df5a49b5431
```

This result attests only the recorded Type-check library lane. It does not claim the separate `All checks` aggregate (link, barrel, span-class, docstring, landing-stat, or offline/site lanes), a preserved Nix store closure, offline replayability, signatures, or the informal mathematical meaning of the code. The uploaded bundle is retained as a GitHub Actions artifact for 30 days under the linked run.
