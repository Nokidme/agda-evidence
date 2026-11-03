# Pinned local discovery catalogs

A local catalog searches an explicit selection of indexed evidence bundles without combining their source trees, resolution contexts, or claims. Use it to explore several pinned libraries or to compare two library revisions while preserving which evidence each candidate came from.

It is a **local reference configuration**, not a portable artifact. It contains bundle paths and expected source/resolution identities. Unlike a closed aggregate, it can contain different sources and non-passing checks. No catalog-wide checker success, dependency graph, compatibility, or Agda scope is implied.

## Create, verify, query

First capture each library with a [source-bound lexical index](declaration-index.md). Then select the indexed evidence directories explicitly:

```sh
agda-evidence catalog create --output /work/research/catalog.json \
  --entry stdlib=/work/evidence/stdlib.evidence \
  --entry my-library=/work/evidence/my-library.evidence

agda-evidence catalog verify /work/research/catalog.json
agda-evidence catalog query /work/research/catalog.json --prefix Data.Nat
agda-evidence catalog query /work/research/catalog.json \
  --exact My.Module.lemma --kind signature --library my-library
```

`create` verifies all selected bundles and indexes before writing a new file. It records the verified source/resolution identities and paths relative to the catalog's directory where possible; across different Windows drives it retains a validated native absolute path. It refuses existing output files, duplicate names, duplicate bundle aliases, or output inside a referenced evidence directory. It does not modify source or evidence, discover installed libraries, fetch dependencies, invoke Agda, or rerun a check.

Both `verify` and `query` validate **every configured entry**. A missing or invalid entry, pin mismatch, or unbound index fails the whole operation, even if a query's filters would have excluded that entry. No partial JSON results are emitted on failure. A valid query with zero hits succeeds.

## Configuration

The complete format is [`local-catalog-v1.schema.json`](../schemas/local-catalog-v1.schema.json):

```json
{
  "format": "agda-evidence/local-catalog-v1",
  "entries": {
    "stdlib": {
      "bundle": "../evidence/stdlib.evidence",
      "expected": {
        "sourceId": "sha256:<64 lowercase hex digits>",
        "resolutionId": "sha256:<64 lowercase hex digits>"
      }
    }
  }
}
```

The digest strings above are placeholders; `catalog create` writes actual values. Entry labels match `[a-z0-9][a-z0-9._-]{0,62}` and are not Agda library names. All displayed fields are required; unknown fields and duplicate JSON keys are errors. Entries cannot be empty.

Paths are local paths: absolute, or relative to the catalog file's directory, never the caller's working directory. Parent segments are allowed because references may intentionally point outside that directory. URLs, URI schemes, and network-style `//` or UNC references are rejected. Rooted drive-letter paths such as `C:/evidence/library` are accepted on Windows, not interpreted as URI schemes or as foreign paths on POSIX. Drive-relative `C:library` and extended/device path forms are not supported. No glob, tilde, or environment-variable expansion is performed. Named bundle roots, manifests, and listed component files must not themselves be symlinks. This does not sandbox local filesystem access or establish a trust boundary against hostile filesystem mutation.

The `0.1.0a1` schema patch widens local-catalog-v1 path syntax for native Windows drives without changing fields, pins or artifact identities. Existing relative/POSIX catalog syntax is unchanged. Newly emitted cross-drive references require the patched reader on Windows and are not portable to POSIX or older readers; keep evidence and catalogs on the same drive and recreate relative references if older-reader interoperability is required. A catalog has always been a machine-local reference configuration rather than a portable archive.

The catalog has no content-derived ID or signature. Inspect its paths and pins before using or sharing it. Moving a catalog without its referenced layout can break it; a catalog does not copy source, evidence, or dependencies.

## Results and provenance

Queries support mutually exclusive `--exact` and `--prefix`, repeatable `--kind`, and repeatable `--library` labels. Filters use the same lexical semantics as single-bundle queries. An unknown library label is an error. Omitting filters returns all candidates from the selected entries.

A query returns `format: "agda-evidence/catalog-query-v1"`, `checkedEntries` (all configured labels, sorted, including zero-hit and filtered-out entries), and `entries`. Each result retains the existing `qualifiedName`, `kind`, `path`, `line`, and `sourceSha256`, plus an `evidence` object:

| Field | Meaning |
| --- | --- |
| `entry` | Caller-selected catalog label. |
| `bundleId` | Exact validated bundle artifact. |
| `sourceId` | Validated source-tree identity. |
| `resolutionId` | Validated partial resolution observation. |
| `attestationId` | Specific recorded check occurrence. |
| `indexId` | Validated lexical source index. |
| `scope`, `command`, `outcome` | The actual recorded check scope, argv, and complete outcome, including errors or timeouts. |

Apart from the label, provenance comes from the same in-memory payloads used in validation, not a later reread or unchecked configuration summary. Results sort by qualified name, kind, entry label, path, and line. Identical names across libraries remain separate records; there is no winning definition or merged namespace.

`verify` returns `format: "agda-evidence/catalog-verification-v1"` and an `entries` array containing the same provenance objects for all entries, even those with no lexical candidates.

Exit codes are `0` for success, `1` for missing/invalid evidence, index or pin failures, and `2` for malformed configuration or CLI arguments. Diagnostics go to stderr.

## Pins are identity agreement, not automatic freshness

A source or resolution mismatch rejects an entry. Pins do not mean that the referenced capture is the latest, that the current source checkout still matches it, or that the libraries are installed or compatible. The tool does not inspect a live project environment or infer whether an import is needed.

A new capture with the same source and resolution may satisfy both pins even if its command, check outcome, or time differs. Results always expose that capture's actual bundle/attestation IDs and outcome; pinning an exact attestation is not part of v1. To change a source/environment pin, review and edit the configuration or create a new catalog explicitly. There is no silent refresh.

A failed, timed-out, or execution-error check remains searchable if its bundle and source index verify. Discovery must not promote such work to successful checking. Missing indexes, legacy opaque references, and legacy/partial identity profiles are not supported in catalogs; existing byte-integrity verification of complete legacy bundles is unchanged.

All [lexical index limitations](declaration-index.md#limits-and-trust-boundary) still apply. Candidates are not necessarily exported, in scope, typechecked individually, or complete. Internal digest consistency is not producer authentication. Search verifies evidence but never executes the command recorded in it.

## Real-library validation

The [2 November 2026 catalog pilot](pilots/local-catalog-result-2026-11-02.md) queried independently verified standard-library and algebra artifacts, preserved their distinct provenance, and rejected both source and resolution pin mismatches even for filtered-out entries.
