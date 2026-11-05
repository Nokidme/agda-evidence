# Verified-byte declaration reuse — 5 November 2026

## Completed increment

Implementation [`5618d029ac16086829b9fc1fe1abef607024374e`](https://github.com/Nokidme/agda-evidence/commit/5618d029ac16086829b9fc1fe1abef607024374e) closes the separate source-hash/text-read race and adds bounded host-session lexical fragment reuse, keyed by operation-admitted generation, exact path, approved source digest and lexical scanner format. Every generation advance clears reuse; old work cannot repopulate a new epoch. The [contract](../discovery-reuse.md) describes retained checks and the intentional stricter rejection of stale whole-tree inputs and byte-read races.

The exact [native workflow 42093259680](https://github.com/Nokidme/agda-evidence/actions/runs/42093259680) passed. Ordinary eight-job [CI 42093257957](https://github.com/Nokidme/agda-evidence/actions/runs/42093257957) also passed, including 268 tests on each Python 3.11/3.12 unit lane, Linux/Windows installed wheel/source smoke and a separate genuine native installed-artifact lane. The local full suite passed 268 tests. The 46 added discovery tests comprise 42 memo/workspace cases and four finite tool constraints. An independent read-only implementation review found no introduced actionable correctness issue.

This remains unreleased `0.1.0a2.dev0` development. The `v0.1.0a1` release/tag, existing schemas/scanner policy, native interface/timeout policies, compiler support claims and live AgdaLab deployment were not changed. No source imports are inserted, dependencies fetched at runtime or proof goals filled.

## Exact native subjects

The workflow provisions these inputs separately from runtime library execution:

| Input | Pin |
|---|---|
| Agda | 2.6.4.3; upstream commit `714c7d2c76c5ffda3180e95c28669259f0dc5b5c` |
| Standard library | v2.0; commit `2b8fff10f4033b91a6df4007e4a65cb10047c89c` |
| Old installed wheel source | `d1f56692d4ecc48adaff26c63a7fe26b662f470e` |
| New wheel/source archive source | `5618d029ac16086829b9fc1fe1abef607024374e` |
| Serialized discovery run order | `1-before`, `1-after`, `2-after`, `2-before` |

The dependency check is the explicit safe, no-library, ignore-interface `src/Function/Base.agda` check, **not all-standard-library validation**. Goal listing uses a separately constructed safe unfinished client that explicitly imports `Function.Base.id`. Native session budget is 20 seconds, dependency gate budget 180 seconds; neither is a complete-request SLA. Both installed variants use the same final finite runner, native executable, dependency tree and query sequence. No timing threshold is required to pass.

Stable subjects were equal across all four consumers:

```text
compiler binary:       sha256:a55596aaf28bf4baeb1134fcd1cda9345ad13efc91846e96a196269ae23e99d5
dependency source:     sha256:a56306c900676de019ce49fdbbfb37551ed05ef7fdaf241cc7a485b2b2b956f4
dependency resolution: sha256:e28c9665c48918f8b734319bc4b1d998f3137743e4b8650a9d2fbd7a613e033e
dependency index:      sha256:d7052458b0363bf02d071c910181c68481b7c5832faccfd2c9081126a5449b7c
client source:         sha256:cb80f333aa7be264c64f2cb5895b3b9b423c5fcfa32decbd81a5945d5a3d63f3
client resolution:     sha256:e5b5c2b6dc9cbaae27f7f1c3134a40aa3f28c679071148060378cfaa8921b5ee
composition:           sha256:5dfb8cde201113f5f17727977f7927cf6780a6e01a5fc13daaf4fd1322e19a67
```

Time-specific bundle/attestation/listing identities intentionally differ between independently captured consumers. Each exported envelope was bound to its own exact bundle and session listing, not substituted based only on equal stable source IDs. For example, `1-after` dependency bundle is `sha256:4ea2a863139666d72e0e8e34764376bee0c9864c4f4618ac35d0e99d396abcb4`; its initial listing is `sha256:4d3b35626df3335cacea090c7e85c6b6bc17f418371b362af57627547f92a5d7` and relisted envelope `sha256:b969c40202e4e1041a485cd7e21c84106cab9b8a7132715237e0539242141de0`.

Downloaded CI distributions matched their retained SHA-256 sums:

```text
fa62ba0c4c388a5f9a20ad5c99bba91f41cb659bd844f76c81e3265724ffa7b0  agda_evidence-0.1.0a2.dev0-py3-none-any.whl
2e34cd8313c6f61a480608a151d907a5748017fe24c8312a3e4ff9bf255da57b  agda_evidence-0.1.0a2.dev0.tar.gz
```

These are development artifact checksums for this exact run, not a new public release or producer signature.

## Structural reuse and retained byte work

Each discovery consumer passed 17 API exchanges, eight accepted queries, two stale-search refusals and two complete exported native source listings. Four consumers therefore retain 68 exchanges, 32 accepted queries, eight stale refusals and eight listings. Offline verification reconstructed each entire query result from the live project index, captured dependency index and independently verified catalog—not merely checking a success flag or scanner count.

The exact lexical results, physical paths/lines, filters, truncation, query context and origin-specific source/index/bundle/resolution/attestation provenance matched across repeated calls within a consumer. Every candidate retains `scopeStatus: not-established`, `candidateUsability: not-tested`, and `contextualRanking: false`.

| Work on an accepted search | Before | After |
|---|---:|---:|
| Initial dependency lexical scans | 1,124 | 1,124 |
| Warm dependency lexical scans | 1,124 | 0 |
| Warm project lexical scans | 1 | 0 |
| Mixed search after both roots are warmed | 1,125 | 0 |
| Dependency-search `sha256_file` calls | 6,216 | 7,484 |
| Project-search `sha256_file` calls | 5,093 | 5,095 |
| Mixed-search `sha256_file` calls | 6,217 | 7,487 |

Hash counts include full live source snapshots and existing compiler/registry/bundle observation work. The new helper adds a complete fresh root guard. The exact second-read source digest uses a byte digest helper and is **additional** work, not part of the `sha256_file` counter. This counter is not a total count of all hashes or disk reads.

Dirty-then-clean notifications invalidate the original selection even without changed bytes. Relisting establishes a new generation: its first dependency query again performs 1,124 scans; the second performs zero. A same-length edit to non-indexed client notes with restored mtime is refused as stale, with unchanged complete historical envelope retrieval. Inputs are restored only for fixture cleanup; the old generation is not reactivated. Original project and dependency source identities remain unchanged at pilot completion.

## Timing result: not an end-to-end latency win

For a like-for-like warm query sequence, use the second dependency/project/all search in each run before notification. Each row has two samples per variant, from the serialized AB/BA sequence:

| Search | Before samples (s) | After samples (s) | Before median | After median | Change |
|---|---|---|---:|---:|---:|
| Dependency | 3.404604, 3.445970 | 3.517972, 3.510282 | 3.425287 s | 3.514127 s | 2.59% slower |
| Project | 2.945539, 2.960476 | 2.932824, 2.914391 | 2.953008 s | 2.923607 s | 1.00% faster |
| Mixed | 3.824422, 3.902755 | 3.992237, 3.963463 | 3.863589 s | 3.977850 s | 2.96% slower |

These are host monotonic complete-search intervals, including retained live observations, full guards, index/query normalization, catalog verification and response publication. They are not lexical-scanner CPU times or total native compiler load measurements. The sample is small, repeated queries share filesystem/OS warming, and there are no confidence bounds. Instrumentation is identical across variants, but the new variant deliberately does more correctness checking. Bundle captures differ in timestamps and IDs despite equal stable subjects.

**Conclusion:** lexical rescanning disappeared as intended, but extra source checking outweighed that saving for dependency and mixed searches in this workload. Do not market the change as a search latency improvement. It is a correctness repair and bounded reuse mechanism whose end-to-end effect depends on workload. The larger editor `Data.Nat.Base` native timeout is neither exercised nor fixed. Future optimization should profile the remaining validation/observation costs and preserve their independence rather than caching freshness.

A local native baseline using Agda 2.6.3 and compatible stdlib v1.7.3 likewise passed old/new offline checks: warm dependency scans went from 990 to zero; source hash-call counts rose from 5,210 to 6,260. It did not establish a clear total latency gain. The initial local pilot stopped after a successful dependency gate because its catalog call used the wrong argument order; only the pilot invocation was corrected to the existing output-first catalog API, then old/new runs passed. No adapter policy was loosened.

## Independent verification and compatibility

Downloaded artifacts were verified with subprocess execution blocked and schema retrieval restricted to an offline local registry. Checks included:

- Complete source-envelope validation, exact dependency bundle/component equality, source/native/composition pins, clean-listing outcomes and retained session-budget/argv fields.
- Every API request/response against unchanged source-research-v2 schemas; deterministic full query reconstruction using the ordinary index validator/query path and independently loaded catalog.
- All origin-specific evidence, repeated equality, cold/warm scanner counts, retained file hash counts, notified generation invalidation and restored-metadata edit refusal.
- CI wheel/source checksums and four installed conformance consumers: builtin and explicit stdlib-function profiles for both wheel and source archive, each passing all 21 mandatory cases, 15 saved native records and 57 exchanges. That is 60 independently checked goal/candidate/source artifacts and 228 exchanges. Correct, rejected, absent-import, warning/fatal-load and current/stale/unknown-history cases retain their distinct outcomes and exact priors.

Regression tests additionally cover the hash-then-read mutation race; complete supplied-snapshot notes changes; malformed IDs/sources; Unicode/literate/newline equivalence; immutable memo results; count/key/payload eviction and oversized/empty fragments; notifications before search starts, during scanning and between root builds; all generation-invalidation paths; independent workspace ownership; and filtered-out catalog corruption after warm live discovery. Stable-input index/query bytes and old public signatures remain unchanged. Newly detected racy/stale cases are intentionally more strictly rejected.

Verification establishes retained data consistency and declared-command results. It is not producer authentication, dependency closure, atomic filesystem access, module export/scope resolution, candidate usability, proof completion or a production support guarantee.

## Reproduce

Use separately provisioned immutable Agda 2.6.4.3 and stdlib v2.0 inputs. Build/install the source commit into fresh environments outside the repository; do not inject `src` into import paths:

```sh
/host/current-venv/bin/python -I scripts/discovery-pilot.py \
  --dependency-root /host/stdlib-v2.0 \
  --agda-bin /host/agda-2.6.4.3 --expected-version 2.6.4.3 \
  --expect-reuse --output /tmp/new-discovery-run
```

Run the same script with the old installed wheel and omit `--expect-reuse` for its expected uncached behavior. The maintained manual [`native-conformance.yml`](../../.github/workflows/native-conformance.yml) performs separately pinned provisioning, fresh wheel/source conformance, serialized old/new discovery runs, retained checksums and original-checkout cleanliness checks. [`scripts/discovery-pilot.py`](../../scripts/discovery-pilot.py) is finite and does not provision dependencies. Reports, exact exported envelopes and exchanges are uploaded together with the installed development distributions. Artifact retention is 30 days; this checked-in result preserves pins and measurements but is not a permanent source-bundle mirror.
