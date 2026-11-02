# Evidence bundle v1

A bundle is an immutable directory of canonical JSON component files plus `bundle.json`. Each listed component is addressed by the SHA-256 digest of its complete canonical JSON payload. The top-level manifest format is described by [`../schemas/evidence-bundle-v1.schema.json`](../schemas/evidence-bundle-v1.schema.json).

The format deliberately distinguishes a stable comparison value from a time-specific evidence artifact. A reader must not use a whole timestamped component, its component digest, or `bundleId` to decide whether two captures describe the same source tree or visible resolution context.

## Four identities

`sourceId` is the stable identity of the captured regular-file tree. It is also emitted as the compatibility field `sourceDigest`. Its preimage is the canonical object containing the tree algorithm and the sorted records `{path, sha256, size}`. It excludes capture time, checkout directory name, exclusion-policy description, toolchain data, diagnostics, and attestation data.

`resolutionId` is the stable identity of the **recorded visible resolution context**, not a proven dependency closure. Its preimage contains the partial-resolution status, the recorded Agda availability/version/binary digest observation, raw root `.agda-lib` file digests, and visible registry file digests. It excludes capture time, checkout directory name, opaque local-path references, convenience-parsed manifest fields, and human-readable limitations. It does not establish that every dependency was resolved, fetched, or archived.

For a flake-provided toolchain, `probe-nix-resolution` can add a `nix` context to the resolution component. New probe identities bind the Nix version observation, evaluated Nix platform (`builtins.currentSystem`), and SHA-256 digests of `flake.nix` and `flake.lock`. The probe runs inside an already activated `nix develop` environment, unwraps the generated project launcher to the underlying executable when possible, and normalizes checkout-local registry entries. A subsequent capture accepts that verified observation through `--resolution-file`; the caller must run the actual check from the staged copy’s own flake environment. Earlier v1 Nix observations that lack a system observation remain valid under their original identity rule.

`attestationId` identifies a specific, time-bound check occurrence. Its preimage contains source and resolution subjects, the complete diagnostics digest, the exact ordered command, scope, execution settings, outcome, and all check timestamps. Changing the time, result, or retained process output therefore changes it.

`bundleId` is the identity of the complete evidence artifact. It is the digest of the bundle format plus its complete component-digest map. Since each component digest covers its entire timestamp-bearing JSON payload, otherwise equivalent recaptures normally have different `bundleId` values. This is intentional: it protects the full evidence record, rather than serving as a source or environment comparison key.

All identities use lowercase hexadecimal SHA-256 identifiers of the form `sha256:<64 hex characters>` and canonical JSON encoding used by the reference implementation.

## Closed lane aggregates

`agda-evidence/aggregate-v1` is a separate, closed artifact format described by [`../schemas/evidence-aggregate-v1.schema.json`](../schemas/evidence-aggregate-v1.schema.json). It includes complete child bundle directories under fixed `lanes/<safe-name>/` paths and records only independently verified, enhanced child bundles with `passed` / exit-code-0 outcomes for one shared `sourceId`.

Its `aggregateId` is a stable digest of the format, common source identity, and sorted lane records. Each lane binds its included child’s complete `bundleId` plus its source, resolution, and attestation identities. It intentionally excludes aggregate creation time and prose limitations. It has no aggregate-level `resolutionId`: child resolution observations remain distinct and partial.

The aggregate verifier recomputes this identity, verifies every physically included child bundle, binds every lane summary to its child, requires each child to be green, and rejects mixed sources, duplicated child bundle or attestation identities, legacy/partial child profiles, symlinks, and any unexpected files. It does not establish that the selected lanes equal an upstream project’s full CI matrix or that their environments have a common dependency closure. See the [aggregate format guide](aggregate.md) for the command interface and complete limits.

## Components

`resolution.json` contains the visible Agda executable observation, root `.agda-lib` data, available registry metadata, the explicit `resolutionStatus: "partial"`, and `resolutionId`.

`snapshot.json` contains regular project files as path, byte size, and SHA-256 digest. The reference implementation rejects symlinks and excludes Git metadata, common build/cache directories, and `.agdai` files. It is source/configuration evidence, not generated interfaces, and contains `sourceDigest` plus `sourceId`.

`attestation.json` records the explicit command, declared scope, isolated-copy execution mode, outcome, `subjects` linking the source and resolution identities, `diagnosticsDigest`, and `attestationId`. `passed` means only that exact command exited successfully in the recorded staged source copy. It does not prove the meaning of the source, unrecorded targets, or offline replayability.

`diagnostics.json` holds bounded stdout/stderr and normalization metadata. v1 does not claim a complete structured Agda diagnostic parser. Its complete canonical payload is the value named by `attestation.diagnosticsDigest`.

`index-ref.json` is optional. New captures contain a `declaration-index-v1` lexical source index built with the fixed `lexical-discovery-v1` scanner policy. The index binds its `sourceId`, every candidate path, and every candidate source digest to `snapshot.json`; it changes `bundleId` but must not change source, resolution, or attestation identities. Capture re-scans the current source before attaching it, and verification rechecks the manifest bindings and index identity. It does not typecheck, resolve, or prove complete declarations. The precise scanner and query contract is in the [declaration-index guide](declaration-index.md).

Earlier `index-ref.json` components using the same wrapper format and an opaque `content` field remain byte-integrity-compatible, but they are not source-bound declaration indexes and cannot be queried through `agda-evidence index query`.

## Verification and compatibility

A reader must reject a manifest whose format is not `agda-evidence/bundle-v1`. It must verify every listed component digest and recompute `bundleId`. Enhanced bundles must contain `snapshot.json`, `resolution.json`, `attestation.json`, and `diagnostics.json`; the verifier recomputes the three derived identities, checks the attestation’s bindings, and checks that capture/check/bundle timestamps are causally ordered.

A legacy v1 profile with none of `sourceId`, `resolutionId`, `subjects`, `diagnosticsDigest`, or `attestationId` is accepted for byte-integrity verification only. A mixed profile is rejected. A valid digest proves internal consistency, not authorship or trust: signatures and trusted transport are separate future work.

Writers must not overwrite a non-empty output directory. Readers may ignore an unknown optional component only after verifying its listed digest.

## Privacy and preservation

Absolute binary and registry paths are represented with opaque path hashes in the resolution component. The reference implementation does not remove sensitive information from source files, command arguments, environment-dependent tool output, or diagnostics. Review bundle contents before publishing.

A re-fetchable dependency declaration is not an archived dependency closure. Claim offline replay only after the toolchain and authorized dependency closure have been preserved and tested.

## Local discovery catalogs

`agda-evidence/local-catalog-v1` is a separate local configuration, not a new bundle component or closed artifact. Each named entry references an indexed enhanced bundle and pins its expected `sourceId` and `resolutionId`. It has no catalog-wide source, environment, success status, or content-derived identity. Existing bundle and aggregate formats and identity projections are unchanged. Complete legacy v1 bundles still support byte-integrity verification but cannot supply a catalog's enhanced provenance.

Catalog readers verify all references before emitting results and retain the actual recorded command/outcome and independent provenance for each hit. Source/environment pins do not pin a specific attestation or establish freshness against a current checkout. See the [local catalog contract](local-catalog.md) and [schema](../schemas/local-catalog-v1.schema.json). JSON readers reject duplicate keys and non-JSON numeric constants rather than accepting ambiguous payloads.
