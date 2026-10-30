# Evidence bundle v1

A bundle is an immutable directory of canonical JSON component files plus `bundle.json`. Each listed component is addressed by the SHA-256 digest of its canonical JSON representation. `bundleId` is the SHA-256 digest of the bundle format and its component-digest map. The top-level schema is [`../schemas/evidence-bundle-v1.schema.json`](../schemas/evidence-bundle-v1.schema.json).

## Required components

`resolution.json` captures the visible Agda executable, root `.agda-lib` files, and available registry metadata. Its status is intentionally `partial`: v1 does not resolve, fetch, or prove a complete dependency closure.

`snapshot.json` captures regular project files as path, byte size, and SHA-256 digest. The reference implementation rejects symlinks and excludes Git metadata, common build/cache directories, and `.agdai` files. It therefore captures source/configuration evidence, not generated interfaces.

`attestation.json` records the explicit command supplied by the caller, the declared scope, an isolated-copy execution mode, and outcome. `passed` means only that exact command exited successfully in the recorded staged source copy. It is not a claim about unrecorded targets, source meaning, or offline replayability.

`diagnostics.json` contains bounded stdout/stderr and status metadata. v1 does not claim fully structured Agda diagnostics; parser adapters can add a later, separately versioned component.

`index-ref.json` is optional. It binds externally produced declaration-index metadata to the bundle without making index extraction part of the core CLI.

## Compatibility rules

A v1 reader must reject a manifest whose `format` is not `agda-evidence/bundle-v1`, must recompute every listed component digest, and must recompute `bundleId`. Readers may ignore an unknown optional component only after verifying its digest. Writers must not overwrite a non-empty output directory.

Timestamps are evidence metadata and can differ between otherwise equivalent captures. Compare `snapshot.json` and `resolution.json` when deciding whether two captures describe the same source and visible environment.

## Privacy and preservation

The reference implementation replaces absolute host paths in recorded resolution data with opaque path hashes. It does not remove sensitive information from project source, command arguments, or process output. Do not publish a bundle until its source, configuration, check command, and output have been reviewed.

A re-fetchable dependency declaration is not an archived dependency closure. Claim offline replay only after the toolchain and authorized dependency closure have been preserved and tested.
