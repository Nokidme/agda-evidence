# Offline evidence accounting

`scripts/evidence-accounting.py` measures explicit, already-existing JSON observations. It calls the installed package's existing offline validators and reports serialized byte sizes plus a hypothetical bounded FIFO history. It does not capture new evidence, traverse source trees, invoke Agda or another subprocess, use a network or LLM, or change production code or public schemas.

The report label is **`evidence-accounting-diagnostic-v1`**. This is a diagnostic format, not a public evidence schema or certificate. A structurally valid retained artifact is not necessarily a successful native observation: load errors, query errors, transport failures, and other valid error outcomes remain reportable. Validation does not establish proof completion, native compiler conformance, workload performance, process memory, freshness of a live checkout, or authenticity of the recorded producer. All measurements concern the supplied records, not a representative workload. No native experiment or benchmark is performed.

See [the independently checked retained-artifact acceptance](pilots/evidence-accounting-result-2026-11-06.md) for matching fresh wheel/source diagnostics and explicit measurement limits.

## Invocation

Use a Python interpreter in which `agda-evidence` is already installed. The script is deliberately usable from an external working directory in isolated mode; it does not inject the repository into `sys.path` or fall back to a source checkout.

```sh
cd /tmp
/path/to/installed-environment/bin/python -I \
  /path/to/agda-evidence/scripts/evidence-accounting.py \
  --artifact /path/to/saved-listing.json \
  --artifact /path/to/saved-candidate.json \
  --output /path/to/existing-report-directory/accounting.json
```

Repeat `--artifact` to specify arrival order, including repeated occurrences of the same file. `--output` is required and must not exist. Put reports outside the repository when evaluating fixtures or saved observations. This standalone script is not a new package console entry point.

| Option | Default | Constraint |
| --- | ---: | --- |
| `--artifact` | Required | One to 64 explicit files, in order |
| `--output` | Required | New path; existing non-symlink directory parents |
| `--max-records` | 24 | Positive scalar integer |
| `--max-stored-bytes` | 8,388,608 | Positive scalar integer; canonical payload budget |
| `--max-input-bytes` | 16,777,216 | Positive scalar integer, at most 67,108,864 |

The total original input budget is always 67,108,864 bytes, including repeated arrivals. Each input is one UTF-8 JSON object; the default individual limit is 16 MiB and can be raised only within the fixed 64 MiB total ceiling. There is no stdin, directory discovery, source-root option, or implicit artifact search. Nested JSON containers are limited to 128 levels, counting the root container as level one. Both a lexical nesting scan before JSON parsing and a parsed-value walk enforce that bound. Duplicate keys anywhere, `NaN`, infinities (including overflowed floating-point JSON numbers), unsupported scalar objects, non-string dictionary keys, and Unicode strings that cannot be encoded as UTF-8 are rejected. Ordinary JSON integers, finite floats, booleans, strings, lists, dictionaries, and null retain their distinct serialized types; values are not coerced.

Exit status **0** means the complete diagnostic was written. Status **1** means invalid, unsupported, or unprocessable retained evidence/JSON. Status **2** means invalid configuration, missing installed package, or filesystem failure, including an input byte-limit breach. Errors go to stderr; no report is published on validation failure. A native error recorded in otherwise valid evidence does not cause status 1. The report's history can also reject an oversized arrival without invalidating its artifact accounting.

## Exported functions

The hyphenated standalone file can be imported with `importlib.util.spec_from_file_location` and `module_from_spec`; normal installed-package imports remain in force. The exported functions are:

```python
account_artifact(value, *, input_bytes: bytes) -> dict
simulate_history(sizes: list[int], *, max_records: int = 24,
                 max_stored_bytes: int = 8_388_608) -> dict
main(argv=None) -> int
```

`account_artifact` requires the parsed artifact and its original serialized bytes. It strictly parses `input_bytes` for a byte-to-value binding check and compares the two objects using the installed canonical JSON helper, not Python equality. Whitespace, key order, and equivalent Unicode escape spellings may differ; integer/float/boolean substitutions do not compare equal. The existing validator receives **the supplied `value` object itself**, and all canonical envelope and section measurements use that same object. The separately parsed comparison object is not substituted for it. The CLI reads each file once, then performs this in-memory binding check; there is no verification-versus-measurement filesystem reread. Neither input object is mutated. Invalid evidence raises `AccountingError`; missing package or invalid limits raise `ConfigurationError`. These are `ValueError` subclasses.

Supported dispatch is exactly:

| Artifact format | Existing validator |
| --- | --- |
| `agda-evidence/type-observation-v1` | `checker.validate_observation` |
| `agda-evidence/goal-observation-v1` | `goals.validate_goal_observation` |
| `agda-evidence/candidate-observation-v1` | `candidates.validate_candidate_observation` |
| `agda-evidence/client-observation-v1` | `client.validate_client_observation` |
| `agda-evidence/source-observation-v1` | `sources.validate_source_observation` |

The client and source validators validate their complete embedded dependency evidence and inner observations; source validation also validates and cross-binds the complete embedded prior source listing and native listing. Goal and candidate validation checks their embedded native priors. This is not an outer-ID-only check. For native type observations, the diagnostic additionally compares the retained result with `checker.response_result` canonically to prevent Python boolean/integer equality from hiding a result scalar mismatch.

The pure API imposes the fixed 64 MiB serialized ceiling and depth bound. CLI-specific individual, total, and arrival-count limits are applied by `main`; callers of the functions must enforce their own multi-artifact resource budget. `simulate_history` uses only sizes and does not import the installed package, validate artifacts, or mutate its size list.

## Report fields and byte meanings

The top-level report contains `format`, `scope`, `records`, `history`, `totalInputBytes`, `limits`, and `sectionAccounting`. There are no generated timestamps or supplied filesystem names. Each record includes a zero-based `inputIndex`; `account_artifact` itself returns the record without that arrival index.

| Record field | Meaning |
| --- | --- |
| `artifactFormat`, `artifactId` | Original artifact format and observation/envelope identity |
| `validation` | `valid-retained-evidence`, not proof or native success |
| `nativeStatus`, `nativeResult`, `nativeTransportStatus` | Unchanged inner native outcome, complete result, and transport status; envelopes use their inner observation |
| `inputBytes`, `inputSha256` | Count and `sha256:` digest of the exact original bytes, including whitespace, Unicode escapes, and trailing newline |
| `canonicalPayloadBytes`, `canonicalPayloadSha256` | Count and digest of the canonical complete artifact payload, without a trailing newline |
| `sectionValueBytes` | Every top-level member key mapped to its separately serialized canonical **value** size |
| `topLevelFramingBytes` | Canonical envelope bytes minus the sum of top-level value sizes: braces, serialized keys, colons, and commas |
| `clientSnapshotBytes`, `dependencyEvidenceBytes`, `innerObservationBytes` | Canonical sizes of those complete nested values where present |
| `embeddedSourceListingBytes` | Complete outer prior source envelope, or zero if absent/null |
| `embeddedNativeListingBytes` | Complete prior native observation inside the current native observation, or zero if absent/null |
| `snapshotFileCounts`, `sourceContentBytes` | Per-role file count and sum of **recorded** snapshot file sizes |

Canonical serialization is exactly `core.canonical_json_bytes`: sorted keys, compact separators, `ensure_ascii=False`, and UTF-8 encoding. It is the same byte representation stored by the research facades' history policy. Original-file formatting is not a history payload cost. The diagnostic output itself ends with a newline, but neither envelope payload counts nor section counts include an added newline. SHA-256 here identifies byte strings; it is not a signature or producer-authentication mechanism.

`sectionValueBytes` is a disjoint map of top-level member **values**. Its sum is not the envelope total until `topLevelFramingBytes` is added. In this map a JSON null value costs four bytes, and every member is included. The separately named nested section fields use **zero** for null/absent optional sections and are deliberately non-additive: an inner observation includes its native listing; a dependency evidence section is contained in the dependency/library top-level value; an outer source prior includes its own inner observation and evidence. Those nested section numbers must not be summed as an envelope total. Exact repeated embedded evidence is counted each time it appears; there is no compression or structural deduplication assumption.

Snapshot roles are `workspace` for the current native observation, `client` for an envelope's current client snapshot, and `dependency` for its embedded dependency/library snapshot. A leaf type, goal, or candidate observation reports only `workspace`. Counts concern these current role snapshots, not every repeated snapshot inside priors. `sourceContentBytes` sums the manifest's recorded `size` fields; it does not measure source files on disk, claim their current presence, or imply source content is embedded in those manifests. The report adds no input path names, but copied `nativeResult` content can contain names or paths already present in the supplied evidence; review it before sharing.

## Exact FIFO simulation

`simulate_history` accepts positive scalar integer payload sizes; booleans, floats, zero and negative sizes are rejected. `max_records` and `max_stored_bytes` are strictly positive scalar integers. An empty arrival list is allowed and produces an empty store; canonical observation payloads themselves are nonempty.

Each list position is a unique arrival event, even if two artifacts, IDs, byte digests, or sizes are equal. For each arrival:

1. If its payload exceeds `max_stored_bytes`, reject it **without eviction** and leave the current store unchanged.
2. Otherwise, evict oldest retained arrivals while the record count is already at its limit or admitting the new payload would exceed the byte limit.
3. Append the accepted arrival and add its complete canonical payload size.

Equality with the byte limit is admissible. There is no success-status filtering: valid native error artifacts are accounted and offered to the simulator just like other valid artifacts. They can be rejected or evicted only by the same capacity policy. Count and byte budgets account for payload bytes only, not Python objects, metadata, dictionary overhead, allocator effects, or RSS.

The returned dictionary contains `maxRecords`, `maxStoredBytes`, `events`, final `retainedInputIndexes`, and final `storedBytes`. Each event contains exactly `inputIndex`, `payloadBytes`, `accepted`, `evictedInputIndexes`, `retainedInputIndexes`, and `storedBytes`. Event retained indexes and stored bytes describe the state **after** that arrival. Evicted indexes are older arrival indexes, in eviction order. Rejected arrivals have an empty eviction list. The CLI reports all artifact records, including those rejected by the hypothetical store.

For example, `[4, 5, 11, 6]` with two records and ten bytes admits indexes 0 and 1, rejects index 2 without removing either, then evicts 0 and 1 to admit index 3. Its final store is `[3]` using six bytes. Retained record counts, identities, and used bytes need not increase monotonically as arrivals occur. A larger budget is not presented as a monotonic retention or performance theorem.

## Filesystem boundary

Preflight checks configuration, the output path, and explicit input file types **before parsing or validation**. Inputs must be regular non-symlink files. Existing symlink parents are rejected for inputs and output, including ancestor directories, and lexical `..` path traversal is unsupported. Output parents must already exist and appear writable; the script does not create directories. Existing output files, directories, symlinks, and hard links are all refused. Identical input/output paths are explicitly rejected; exclusive creation also prevents an existing hard-link alias from being overwritten. Hard-linked regular inputs and repeated input paths are not deduplicated.

Input opens use `O_NOFOLLOW` and `O_NONBLOCK` where available, check the opened descriptor with `fstat`, inspect its size, and read at most the effective per-file/remaining-total limit plus one byte. An unexpectedly growing file is rejected when that bounded read exceeds the limit. No input is modified. The output is opened only after all evidence and the complete in-memory report are ready, using exclusive creation and no-follow where supported. Newly created report permissions are 0600 subject to platform semantics. Write failures trigger best-effort cleanup of only the inode created by this invocation.

These checks assume a **trusted, stable local filesystem**. They are non-atomic across input captures and path preflight/output creation; they are not a directory-descriptor sandbox, an atomic batch snapshot, crash-safe publication, or protection against a concurrent hostile ancestor-directory replacement. No-follow flags are platform-dependent, writability checks do not guarantee free space, and cleanup cannot be guaranteed after process termination or filesystem failure. A report may be briefly visible while it is written. Use an unchanged local directory with no concurrent writers; do not use adversarial shared paths. No partial report is intentionally emitted on failure, and validation failures never create an output.
