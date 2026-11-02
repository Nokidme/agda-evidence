# Checker-backed type observation result — 2 November 2026

The native checker adapter was validated against installed Agda 2.6.3 in local tests and pinned Agda 2.8.0 in the standard-library pilot. The implementation was published in [commit 834c07f](https://github.com/Nokidme/agda-evidence/commit/834c07f5574070fb9bea07b85a9a85244601a878).

The real-library follow-up passed in [GitHub Actions run 41511731206](https://github.com/Nokidme/agda-evidence/actions/runs/41511731206), retaining standard-library commit `565739a4d82b8bb47d2f15cb99178db15ca60e9b` and compiler tag `v2.8.0`. It preserved the existing upstream generate/safe/full-library check sequence and recorded a separate type observation only afterward.

Both uploaded artifacts were downloaded into the development environment. `agda-evidence verify` passed for the evidence bundle; `agda-evidence checker verify` passed for the type observation. The observation also validated against its Draft 2020-12 schema. A local comparison confirmed that all three basis fields exactly identify the downloaded bundle and its source/resolution subjects.

## Observed expression type

The separate query loaded `src/Data/Nat/Base.agda` in another isolated source copy with project-relative include roots `.` and `src`. Its argv included `--interaction-json --no-libraries --ignore-interfaces --safe`. It explicitly asked `Cmd_infer_toplevel Simplified` for `_+_`.

Agda returned:

```text
ℕ → ℕ → ℕ
```

The result status is `inferred`; transport status is `completed`. The saved load phase contains 185 parsed responses, followed by two inference responses. Startup, load, and inference all reached the expected non-newline command prompt. The interaction retained 614,948 stdout bytes and empty stderr, under its 4 MiB limit. Recorded execution timestamps are `2026-11-02T20:08:28Z` through `2026-11-02T20:08:31Z`.

This is Agda's displayed type for that expression in that loaded module's top-level inside scope. It is not a canonical declaration-origin record, a scope check in a different client module, or a stronger proof-validity claim about every lexical candidate.

## Exact identities

```text
observationId: sha256:a9b4b6f78030529fddf9f80ef584ec7b74d6090b17e0aae710dec8575469687b
sourceId:      sha256:5a64564ab914a6af0c4b3ec06b78a469fe382f9cfe9d158f220dd2efc2cbb295
resolutionId:  sha256:0b281336d57f6ab47e043ad2393f402273d2f5679e1c59263f860085a911dd49
basisBundleId: sha256:0c50e8e90a406ec17a9b359000767ec73f39f35c3bd9489d552d12a2f3eafea4
basisCheckId:  sha256:2f5299ae944202b6b74a13ef522117973399b3ea32523e0d47e2e1ffc9214ca2
queriedFile:   sha256:2015a58f93be9820ad005027baa31467601ebc7018f86f17e5edd41dbd3ce6c2
```

The source snapshot contains 1,417 regular files. Its source and partial resolution IDs match the earlier indexed standard-library capture, while the bundle and project-check attestation remain new time-specific artifacts. The basis's recorded native gate is `passed` with exit code `0`; that outcome is independent of the new observation's response-derived result.

## Reproduce retained-artifact verification

With `agda-evidence` installed, use fresh directories:

```sh
mkdir -p downloaded/stdlib downloaded/type

gh run download 41511731206 --repo Nokidme/agda-evidence \
  --name agda-stdlib-evidence-565739a4d82b8bb47d2f15cb99178db15ca60e9b \
  --dir downloaded/stdlib

gh run download 41511731206 --repo Nokidme/agda-evidence \
  --name agda-stdlib-type-observation-565739a4d82b8bb47d2f15cb99178db15ca60e9b \
  --dir downloaded/type

agda-evidence verify downloaded/stdlib
agda-evidence checker verify downloaded/type/stdlib-addition.type.json
```

Downloading requires GitHub access and network availability. The two verification commands are local and do not rerun Agda. The workflows retain these artifacts for 30 days from the run date. This reproduces verification over retained records, not offline source or toolchain replay. To rerun the native source check and query, dispatch the maintained standard-library pilot with the same source pin.

## Regression and scope boundary

All 64 local tests passed. Real Agda tests cover builtin identity, a Unicode operator, explicit subdirectory imports, a fatal load error, unsolved goals, and an absent-name query. Deterministic native-pipe fixtures additionally cover fragmented prompts/JSON, Haskell escaping, warning/incomplete-load gating, semantic errors despite a zero process exit, malformed output and EOF, bounded stdout/stderr, source/resolution pin mismatches before interaction, saved-record tampering, output-path protections, and a stalled stdin writer that still obeys the total session timeout. Ordinary [Python 3.11/3.12 CI](https://github.com/Nokidme/agda-evidence/actions/runs/41511716102) passed; real-Agda unit tests skip on runners without Agda and are supplemented by the manual pinned pilot.

The adapter never inserts a hole or executes a proof step. It disables implicit library configuration and does not adapt Nix project launchers or external dependency environments. Original source files are not used as the writable working copy. Temporary source-copy isolation is not a security sandbox for a hostile compiler or all host side effects.

The observation remains separate from bundle/index/catalog formats. Internal consistency checks cannot authenticate the producer or prove that a fabricated, consistently rehashed transcript came from Agda. Source archives, signatures, declaration graphs, client-module importability, and fully preserved dependency closures remain outside this result. The [checker contract](../checker.md) specifies exact behavior and failure statuses.
