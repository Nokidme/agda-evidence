# agda-stdlib pilot

This pilot validates that `agda-evidence` can snapshot and attest the existing full-library typecheck of the Agda standard library without inventing a new project gate.

## Target

The initial target is the `master` commit `565739a4d82b8bb47d2f15cb99178db15ca60e9b`, observed on 30 October 2026. The commit is deliberately pinned: `master`, a standard-library release tag, and the library descriptor’s `standard-library-3.0` name are different reproducibility targets.

The project’s current Ubuntu CI selects Agda `tags/v2.8.0`, runs `GenerateEverything` with deprecated modules included, and then typechecks `EverythingSafe.agda` under `--safe` plus `Everything.agda` with the same compiler/include settings. The initial `agda-evidence` workflow transcribes that sequence rather than substituting the contributor documentation check or a guessed `agda --build-library` command.

```sh
cabal run GenerateEverything -- --include-deprecated
agda -Werror +RTS -M5G -H3.5G -A128M -RTS -i. -isrc -idoc \
  -WnoUserWarning --safe EverythingSafe.agda
agda -Werror +RTS -M5G -H3.5G -A128M -RTS -i. -isrc -idoc \
  -WnoUserWarning Everything.agda
```

`Everything*.agda`, `*.agdai`, and Cabal outputs are generated artifacts. The bundle snapshots the source before the command runs and executes the gate in an isolated copy, so the generated aggregate modules and interfaces do not become part of the source identity.

## How to run it

The repository provides a manual-only GitHub Actions workflow, **agda-stdlib pilot**. Its default input is the commit above. The workflow installs the same broad GHC/Cabal/Agda setup used by the upstream CI, configures Cabal’s package route to direct HTTPS Hackage when current runner mirror selection is unavailable, builds a lexical declaration index outside the checkout, binds it to the captured snapshot, captures the composite gate as an evidence bundle, uploads the bundle even when the gate is red, and fails the run unless the attestation outcome is `passed`. This availability workaround does not turn the Cabal dependency set into an archived or trusted closure.

The composite `sh -eu -c` command is intentional in v0.1. The reference CLI attests one explicit process invocation; `-e` ensures that a failure in the generator or either Agda typecheck makes that recorded composite gate fail. A later structured multi-step execution format can retain individual step records without weakening this v0.1 claim.

The workflow also records a separate native-Agda type observation for `_+_` in `src/Data/Nat/Base.agda`, with `--include src --safe`. It pins live source/resolution against the just-captured enhanced bundle, loads another isolated source copy with library files and cached interfaces disabled, requires the displayed type `ℕ → ℕ → ℕ`, and verifies the observation offline. The observation is uploaded as a separate artifact rather than inserted into the project-check bundle or lexical index. This does not change the composite upstream gate or establish canonical declaration origin or scope in another module.

## Acceptance criteria

A successful run must have all of the following:

- an attestation outcome of `passed` for the recorded composite command;
- a `sourceId` matching the source tree at the selected standard-library commit under the documented snapshot policy;
- a `resolutionId` that records the Agda 2.8.0 binary observation and visible partial resolution data;
- successful local verification of the uploaded bundle before upload.
- a source-bound index query returning at least one lexical `Data.Nat` module candidate from the verified bundle.
- a separately verified, source/resolution-pinned checker observation returning `ℕ → ℕ → ℕ` for the explicit addition expression.

A failed run is still useful pilot evidence. Its bundle records the same source/resolution observations, full bounded process output, and a red outcome. It must not be described as a successful typecheck.

The current `resolutionId` remains partial. The pilot does not claim an archived dependency closure, offline replay, or that `--safe` covers every module: the gate separately checks an aggregate safe set and the complete aggregate set according to upstream’s own generator. The attached index is lexical discovery metadata, not a claim that its candidates are typechecked, exported, or a complete symbol catalog.

## Initial result

The first pinned run passed on 30 October 2026. Its independently verified identifiers and the scope of its claim are recorded in [the initial result](agda-stdlib-result-2026-10-30.md).

## Source-index result

The follow-up pinned run attached and independently verified a source-bound lexical declaration index while preserving the same upstream typecheck gate. Its index identifier, query result, and boundaries are recorded in [the source-index result](agda-stdlib-index-result-2026-10-30.md).

## Checker result

The 2 November 2026 follow-up preserved that gate and separately recorded Agda 2.8.0's displayed addition type. Both downloaded artifacts and their basis identities were independently verified. See the [checker result](checker-result-2026-11-02.md) for exact identifiers, transcript counts, and reproduction commands.

## Sources

- [agda-stdlib Ubuntu CI](https://github.com/agda/agda-stdlib/blob/master/.github/workflows/ci-ubuntu.yml)
- [agda-stdlib generator](https://github.com/agda/agda-stdlib/blob/master/GenerateEverything.hs)
- [agda-stdlib manifest](https://github.com/agda/agda-stdlib/blob/master/standard-library.agda-lib)
- [agda-stdlib contributor guide](https://github.com/agda/agda-stdlib/blob/master/HACKING.md)
- [Agda library management](https://agda.readthedocs.io/en/latest/tools/package-system.html)
