# Closed aggregate v1

A closed aggregate is a portable envelope for several independently verified, successful evidence bundles that all describe the **same captured file tree**. It supports a narrow and useful statement:

> Every included lane recorded a successful explicit command for one `sourceId`.

It does not infer that the included lanes are an upstream project’s full CI matrix. A producer must choose meaningful lane names and only create an aggregate after it has obtained the child bundles.

## Create an aggregate

```sh
agda-evidence aggregate create \
  --output /tmp/project.aggregate \
  --lane typecheck=/tmp/project-typecheck.evidence \
  --lane docs=/tmp/project-docs.evidence

agda-evidence aggregate verify /tmp/project.aggregate
```

Each `--lane` has a safe lowercase name and an existing child bundle directory. The writer verifies every input before writing anything. It then copies only `bundle.json` and each component named by that child manifest into the fixed child location.

```text
project.aggregate/
├── aggregate.json
└── lanes/
    ├── docs/
    │   ├── bundle.json
    │   ├── snapshot.json
    │   ├── resolution.json
    │   ├── attestation.json
    │   └── diagnostics.json
    └── typecheck/
        └── ...
```

There are no URL, sibling-path, GitHub Actions-artifact, or content-address-only references in v1. A reader can verify every required child bundle from this one directory.

## Manifest and identity

`aggregate.json` follows [`../schemas/evidence-aggregate-v1.schema.json`](../schemas/evidence-aggregate-v1.schema.json). Its `lanes` object maps each lane name to the included child bundle’s `bundleId`, `sourceId`, `resolutionId`, `attestationId`, and compact green outcome.

`aggregateId` is the SHA-256 identity of the aggregate format, common source identity, and sorted lane records. It intentionally excludes `createdAt`, the schema path, and explanatory limitations. Recreating an aggregate from the same named child bundles therefore has the same `aggregateId`; replacing any child bundle, changing a lane name, or changing its attestation produces a different value.

## Validation rules

A valid aggregate requires every included child to be a complete enhanced v1 bundle that verifies independently. Each child must have outcome `passed` and exit code `0`, and every child must have the top-level aggregate’s `sourceId`.

The verifier rejects duplicated child bundle or attestation identities, legacy or partial-identity bundles, failed/timed-out child results, altered lane summaries, unsafe lane names, symlinks, missing child files, and unexpected root, lane, or component files. It does **not** require child `resolutionId` values to match. Lanes may legitimately run in different toolchain environments; each remains a separate partial resolution observation.

## Limits

An aggregate does not prove that its lanes cover a project’s authoritative CI configuration. It does not merge or solve their dependency environments, preserve dependency closures, guarantee offline replay, establish a shared Git commit, or supply signatures, authorship, or trust. Each claim remains bounded by the exact command and scope in its included child attestation.
