# Verified-byte declaration reuse

Development research workspaces reuse **pure lexical file fragments**, not complete indexes or freshness verdicts. This applies to project search in the ordinary v1 facade and project/dependency search in the explicit source-aware v2 facade. Catalog evidence remains independently reloaded and verified through its existing path. Public constructor/request/response signatures, scanner policy, index formats and scope/typing claims are unchanged.

## Exact byte binding first

The previous builder hashed a source file, then reopened it for text reading. A change between those opens could associate different scanned text with the approved digest. The builder now retains its first regular-file/hash check, reads source bytes again and validates the digest of **those exact bytes** before decoding or scanning. Both checks execute even on a reuse hit. This intentionally rejects a previously undetected race, rather than claiming equivalence for unsafe interleavings.

Strict UTF-8 decoding and universal-newline handling remain. No Unicode normalization, path case folding, replacement decoding, implicit exports or source rewriting is introduced. For stable inputs, lexical records, physical lines, scanner/source/index identities and query outputs remain exact. Invalid source still fails rather than becoming an empty result.

Before each workspace index build, the helper takes an additional complete fresh root snapshot and compares its source identity with the supplied snapshot. The earlier public builder with a supplied snapshot checked indexed sources but did not independently rehash non-indexed inputs; facade pre/post observations did. The new helper explicitly covers that whole-tree boundary as well. This added work may offset lexical parsing savings, particularly on small filesystems or small projects.

## What may be reused

A workspace owns one private memo of file-level candidate arrays, keyed by:

- the operation-admitted generation;
- exact relative path spelling;
- approved source-byte SHA-256;
- the unchanged lexical scanner format.

Each candidate fragment is immutable internally and returned as newly detached records. Source bytes, whole indexes, query responses, scope information, compiler observations and library attestations are not stored in this memo. The same path and exact bytes can share pure scanning work across project/dependency roots in the same session, but origins and current evidence subjects are constructed afresh. Different paths, bytes, scanner formats or generations cannot share a fragment.

A hit still requires regular-file checks, both source-byte digest checks and strict decoding. Full index normalization, hashing and query validation execute each time. No source/bundle/compiler read is omitted because the memo contains a result. There is no mtime, inode, size or cached-source-identity authority.

The fixed internal budget is at most 4,096 file fragments and 16 MiB of accounted key/immutable payload bytes per workspace. File count bounds per-entry overhead; this is not a process RSS limit. Empty fragments can be cached. Eviction and oversized fragments simply cause ordinary scanning rather than a search failure. Memo capacity is independent of the evidence-history store and not configurable by client request.

## Revision and concurrency rules

The complete search is pinned to the generation captured under the existing operation-admission state lock, before work starts. Both project and dependency builds use that same generation. Every generation advance invalidates the memo: edit/save notifications, observed subject changes, failed freshness observation and conservative source-capture invalidation.

Lexical scanning happens outside the memo lock. Lookup and insertion recheck the supplied generation against its current epoch. An old miss finishing after invalidation cannot populate the new generation. Notifications before search starts or between root builds likewise do not give an already admitted old operation a newer epoch. The existing post-operation observation/publication checks still decide whether the response is current, stale or invalid.

Host responsibilities remain: notify every input edit/save event—including edit-and-revert—save complete buffers, isolate workspace instances by tenant/session and discard superseded UI responses. This is not atomic access to live files. Unobserved transients that disappear between all checks remain outside the contract; verified bytes cannot repair missing host event information.

## Provenance and assurances

Repeated search retains exact candidate fields, sort order, filters, limits, origin, source/index IDs and explicit dependency bundle/resolution/attestation metadata. Every hit still says `scopeStatus: not-established`, `candidateUsability: not-tested`, and `contextualRanking: false`.

Catalog-only and mixed searches still validate every configured selected bundle and identity pin according to the existing catalog contract, including entries not matching the lexical query. A live fragment never authorizes an archived catalog index or candidate. Source copying does not insert an import, and discovery does not prove that a name is usable at a goal. Native type/context/trial observations remain separate evidence.

## Validation and finite measurement

Regression tests compare full uncached/reused indexes and queries across Unicode, Markdown fences, line endings, empty files and module headers. Structural tests require fewer warm scanner calls while retaining whole-root snapshots and exact-byte checks. They exercise same-length edits with restored metadata, non-indexed file changes, hash/read races, stale source IDs, invalid UTF-8, symlinks, detached-result mutation, capacity bounds, generation races and unchanged catalog provenance/failures.

Fresh wheel/source package smoke uses genuine native Agda to list a goal and perform repeated project/dependency discovery. A finite pilot on an externally provisioned standard library is available:

```sh
python -I scripts/discovery-pilot.py \
  --dependency-root /host/provisioned/stdlib \
  --agda-bin /absolute/path/to/agda --expected-version 2.6.4.3 \
  --expect-reuse --output /tmp/new-discovery-run
```

Use an interpreter with the built package installed; `-I` intentionally ignores repository source paths. Compiler/library provisioning occurs separately. The pilot checks the explicit `Function.Base` gate, lists an unfinished client, repeats scoped search, retains complete source envelopes and API exchanges, tests dirty/clean selection invalidation and a same-metadata non-indexed edit, and verifies unchanged original source identities. It retains host-call times and lexical/file-hash call counts. Its native session budget is 20 seconds and gate budget is 180 seconds; neither is a total request SLA.

Compare the same script against the fixed old installed package without `--expect-reuse` and a new installed package with it to inspect structural scan savings and timing differences. Cold versus warm calls include filesystem warming and different scope mixes; they are not by themselves a controlled version speedup. Full-byte checks and extra snapshot work remain real costs. Report actual complete-call measurements before asserting any improvement. This memo does not address the larger editor `Data.Nat.Base` native load timeout, establish production compiler equivalence or enable an agent/deployment.

## Completed native result

The [5 November 2026 result](pilots/discovery-reuse-result-2026-11-05.md) verifies four serialized old/new installed consumers on pinned Agda 2.6.4.3 and stdlib v2.0. Warm dependency scans fell from 1,124 to zero, while retained/added source checks made warm dependency and mixed searches approximately 2.6% and 3.0% slower in two samples per variant. This is a correctness and lexical-work reuse result, not an overall latency improvement or production timeout fix.
