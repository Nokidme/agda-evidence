# Explicit source-aware research sessions

`SourceResearchWorkspace` connects the [one-dependency source adapter](sources.md) to an editor-hosted research session: goal listing, context inspection, lexical discovery, explicit non-filling trials and exact evidence retrieval. It is an opt-in **API version 2** facade, not a replacement for `ResearchWorkspace` version 1, a public server or a live AgdaLab deployment. Existing native artifact formats and released `v0.1.0a1` assets remain unchanged; this is development on `main`.

The host configures exactly one native source dependency, with complete verified evidence, declared includes and the compiler which produced that evidence. Clients never choose paths, dependency bundles, compiler settings, flags, output files or observation dictionaries. Dependency resolution, downloads, Nix activation, imports, hole filling, agents and billing are not provided by this API.

## Bind and use the explicit profile

```python
from pathlib import Path
from agda_evidence.source_research import SourceResearchWorkspace

host = SourceResearchWorkspace(
    Path('/host/authorized/client'), {'main': 'Main.agda'},
    dependency_root=Path('/host/provisioned/stdlib-1.7.3'),
    dependency_bundle=Path('/host/evidence/stdlib.evidence'),
    dependency_includes=['src'],
    agda_binary='/usr/bin/agda', includes=['.'], safe=True,
    # catalog=Path('/host/config/discovery.catalog.json'),
    max_stored_bytes=67_108_864,
)

state = host.handle({
    'apiVersion': 2, 'requestId': 'ui-1', 'op': 'workspace.status',
    'revision': None, 'args': {},
})
revision = state['currentRevision']
listing = host.handle({
    'apiVersion': 2, 'requestId': 'ui-2', 'op': 'goals.list',
    'revision': revision, 'args': {'documentId': 'main'},
})
```

Constructor validation establishes a live baseline and **freezes the dependency's source ID, complete native resolution ID and exact bundle ID**. It must initially match the configured native source tree and compiler; a mismatch is an error at the trusted host boundary. A failed recorded dependency attestation is retained unchanged rather than promoted by later client work. A source dependency does not require a lexical index merely to be available for native queries.

Give each authorized workspace/session a separate instance. Record IDs are opaque handles, not authorization tokens; every transport call and evidence download still requires the application's own authorization. Configure roots and document bindings once; reconfiguration requires an explicitly authorized new instance/session.

## Versioned request and response subjects

Requests contain exactly `apiVersion: 2`, `requestId`, `op`, `revision` and `args`; a missing/v1/Boolean version is rejected. The [request schema](../schemas/source-research-request-v2.schema.json) is separate from the existing v1 schema. Responses retain the same top-level correlation, revision, status, record, result and error fields, but always use `apiVersion: 2` and the [source response schema](../schemas/source-research-response-v2.schema.json).

Current observed `workspace` contains exactly:

```text
clientSourceId, clientResolutionId,
dependencySourceId, dependencyResolutionId,
dependencyBundleId, compositionId
```

All are digests. These are **current observations**, not substituted frozen pins or temporary workspace subjects. The original v1 `workspace.sourceId` meaning has not changed. The composed workspace source/native resolution remains in the full source envelope, where exact prefix-union and native binding verification apply.

`compositionId` hashes the canonical object `{'format': 'agda-evidence/source-research-composition-v2', 'composition': composition}`, with composition containing the fixed source policy, canonical client includes, explicitly declared dependency includes and Boolean `safe`. Absolute paths, temporary directory names, timestamps and opaque session revisions are not part of this digest. The client source digest separately binds any source `OPTIONS` pragmas; warning settings are not silently inferred from library manifests.

Status returns document IDs, limits, dirty state, compiler availability, catalog configuration, includes/safe policy, explicit composition, immutable `dependencyPins`, and current `dependencyMatchesPin`. A diagnostic status response may be `ok` while that Boolean is false: **API success is not pin admission, native acceptance or proof success**.

## Goals, trials and complete records

The six operation names remain `workspace.status`, `goals.list`, `goals.inspect`, `library.search`, `candidate.check` and `record.get`. Research operations require a current opaque revision. Only an accepted leaf source listing from the same instance is selectable; goal IDs are nonnegative scalar integers, not guessed fallbacks. The host fixes the original file/include/safe profile and the selected record's complete client/dependency/composition subjects.

Native operation results expose `sourceObservationId`, the unchanged inner `observationId`, document ID and native `outcome`. A valid rejected native trial can be API `ok` with `outcome.status: query-error`. A successful candidate remains `elaborated` with **contextual-elaboration-only** assurance, not proof completion or freedom from residual obligations. Source holes remain untouched.

The session stores the **complete validated `source-observation-v1` envelope**, including dependency evidence and exact prior source/native listings, as canonical immutable bytes. `record.get` returns a detached decoded copy, the record's revision/kind/document and `freshness: current|stale|unknown`, plus whether current dependency subjects still match the frozen pins. Record handles and content-derived observation IDs are not interchangeable. Unknown, evicted and cross-session handles all return `record-unavailable` before filesystem probes.

## Dependency changes and history

Observation is distinct from admission:

| Current situation | API behavior |
| --- | --- |
| Dependency source/resolution changes or a valid replacement bundle is observed | Current subjects and revision change; status reports `dependencyMatchesPin: false`. |
| Research requested under a refreshed revision but frozen pins do not match | `error` / `dependency-changed`; refreshing status does **not** repin the dependency. |
| Existing record read with null revision and observable changed inputs | Complete historical evidence remains available with `freshness: stale`. |
| Required source/bundle inputs are missing, corrupt or unobservable | Complete current workspace becomes unknown; null-revision history may return `freshness: unknown`. Status/revision-bound reads fail `freshness-unavailable`. |
| A read supplies an outdated non-null revision | `stale` / `workspace-changed`, not an unconditionally accepted historical read. |
| Client buffers or notified dependency inputs change and revert | Generation changes; old selections/history stay stale even when final source bytes match again. |

A separately recaptured bundle with the same source and resolution still changes exact dependency provenance and is refused by an existing frozen instance. After explicit source/environment validation and recapture as needed, the host may authorize a new instance with new pins. The new instance cannot read the old session's opaque record handles; existing downloadable complete artifacts retain their original evidence meaning.

Call `notify_buffers(dirty=True/False)` for **every client or dependency input edit/save event**, including edit-and-revert. Do not mark clean until the complete authorized revision is materialized. These are trusted host notifications, not payload arguments, and they do not change frozen dependency pins. The host must also discard superseded UI replies and serialize staging; final hashes do not detect all unnotified edit-and-revert races.

## Publication and concurrency

One research action runs per instance. Other research requests receive `workspace-busy` rather than entering an unbounded queue. Status/history and notifications remain available during native interaction. Current input observation and subject synchronization are serialized through their publication step so concurrent reads cannot overwrite newer subjects with out-of-order observations; no state lock is held throughout native work.

Before interaction, source capture receives private expected client/dependency source/resolution/bundle preconditions from the requested revision. It retains its exact source-copy/compiler/workspace guards. After successful **and failed** work, including discovery or storage failures, the facade re-observes full source/environment/bundle subjects and generation. Changed inputs take precedence over native success; an already retained valid envelope is history, not an active result. A source evidence failure with an ambiguous restored-input race conservatively invalidates the generation rather than reactivating old selections or manufacturing a partial envelope.

Error messages are bounded and generic rather than exposing host paths or stack traces. Native artifact diagnostics remain exact normalized evidence and should be reviewed before sharing. Overall copying, metadata, catalog, transport and snapshot size budgets remain host responsibilities; the native timeout does not bound every host operation. This interface is not a security sandbox for untrusted Agda or reflection effects.

## Lexical discovery remains separate

Version 2 adds `scope: dependency`, alongside `project`, `catalog` and `all`. Its `all` explicitly means project + the single bound dependency + configured catalog. Dependency lexical scanning is allowed only while frozen pins match, uses the actual pinned source snapshot, and returns `origin: dependency` with index/source and recorded dependency-check provenance. No declaration index is fabricated as typechecked metadata.

Catalog entries are independent discovery evidence and are never mounted just because a result appears. Catalog library filters apply to catalog results only; they are rejected for project/dependency-only searches. Duplicate names/provenance are retained, result counts/limits are explicit, and `contextualRanking: false`, `scopeStatus: not-established`, `candidateUsability: not-tested` remain visible. Finding `Example.identity` in a catalog does not authorize its import or prove a selected expression resolves to that candidate.

## Budgets, artifacts and integration

The default FIFO store is 64 records and **67,108,864 bytes**, accommodating complete source-envelope histories more readily than the ordinary v1 default. It is bounded, in-memory, session-local and non-durable. A single oversize envelope returns `store-capacity`; eviction removes oldest records. The host still owns authenticated durable storage/export, cancellation, process/filesystem/network isolation and global limits. There is no automatic upload, persistence or public endpoint.

The finite `scripts/source-research-pilot.py` takes an already provisioned stdlib source checkout and compiler; it downloads nothing. It exercises source listing → context → project/dependency/catalog search → explicit accepted/rejected trials → exact artifact access → dirty invalidation → dependency change/stale history → missing evidence/unknown history → same-subject bundle recapture refusal → explicit new binding and cross-session rejection. Only disposable external copies are edited, and original examples/supplied dependencies remain unchanged. Its manual workflow provisions the immutable stdlib checkout separately.

To use this in AgdaLab, the authorized original editor task must opt into the source-aware host binding, route v2 envelopes explicitly, notify client/dependency revisions and display current observations, frozen-pin admission, native outcomes and historical evidence separately. The ordinary v1 profile must remain available where appropriate. No application code or deployment is changed by this library increment.
