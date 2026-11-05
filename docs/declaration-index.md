# Source-bound declaration discovery

`agda-evidence index` builds a deterministic **lexical candidate index** for a project’s snapshot-visible Agda source. It is the discovery layer for questions such as “which captured library source contains a likely module or declaration name?”

It is not an Agda parser, scope resolver, export graph, dependency solver, interface reader, or typechecker. A result means only that the scanner recognized a documented source-text pattern at a recorded path and physical line.

## Build and attach

Build the index outside the project root so it cannot become a source input itself:

```sh
agda-evidence index build \
  --project-root ./library \
  --output /tmp/library.index.json

agda-evidence capture \
  --project-root ./library \
  --output /tmp/library.evidence \
  --index-reference /tmp/library.index.json \
  --scope "the project’s designated check" \
  -- make check
```

A capture re-scans the current project before it runs the command. It rejects the input if its `sourceId`, file digest bindings, lexical records, scanner policy, or deterministic `indexId` do not match the snapshot. Attaching an index adds `index-ref.json` and changes only `bundleId`; it does not change `sourceId`, `resolutionId`, or `attestationId`.

## Query an evidence bundle

```sh
agda-evidence index query /tmp/library.evidence --prefix Data.Nat
agda-evidence index query /tmp/library.evidence --exact Data.Nat.zero --kind signature
```

The query first verifies the full evidence bundle, then validates the source-bound index against `snapshot.json`. Results are deterministic JSON records containing `qualifiedName`, lexical `kind`, `path`, physical `line`, and `sourceSha256`.

## Scanner policy v1

The scanner reads regular snapshot-visible `.agda` files and only `agda` or `agda2` fenced blocks in `.lagda.md` files. It examines non-indented source lines and recognizes these candidate patterns:

- `module <name> ... where` → `module`
- `data <name> ...` → `data`
- `record <name> ...` → `record`
- `postulate <name> : ...` → `postulate`
- `primitive <name> : ...` → `primitive`
- `<name> : ...` → `signature`

The most recently recognized module header in a file prefixes subsequent candidate names. This is lexical context, not a claim that nested modules, syntax extensions, qualification, visibility, or imports were interpreted correctly. Operators, complex patterns, declarations inside indented blocks, Bird-style literate source, and untagged Markdown code are deliberately omitted in v1 rather than guessed.

The exact object format is specified by [`../schemas/declaration-index-v1.schema.json`](../schemas/declaration-index-v1.schema.json). Every record binds to the snapshot’s source digest for its path, and every index binds to the snapshot’s `sourceId`.

## Limits and trust boundary

Bundle verification can prove that a source-bound index is internally consistent with the snapshot file manifest. It cannot re-run lexical scanning because evidence bundles contain file digests, not source bytes. A capture validates the supplied index against the live snapshot before it is attached; later trust in who created the bundle still requires trusted transport or signatures, which v1 does not provide.

No query result establishes that a declaration typechecks, is exported, is in scope for another module, is unique, or exhausts a library. The explicit check recorded by the containing evidence bundle remains the only checker-backed claim, and it has exactly the scope stated by that bundle’s attestation.

## Development workspace reuse

Research sessions may [reuse bounded lexical file fragments](discovery-reuse.md), but only after verifying the bytes being scanned/reused. Complete root observations, source/index identity validation, query checks and independent catalog provenance remain. Generation changes invalidate reuse; this is not a freshness, scope or compiler-interface cache. The builder also closes the prior separate hash/text-read race by checking the exact second-read bytes before scanning.
