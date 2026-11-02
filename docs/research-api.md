# Host-owned research workflow API

`ResearchWorkspace` connects goal selection, context inspection, explicit lexical discovery, non-filling expression trials and exact evidence display behind one JSON-ready Python API. It is a library-side integration point, **not a running AgdaLab feature or a replacement editor**. The actual AgdaLab application repository/attached website was unavailable in this session; its routes, authentication, editor buffers and UI have not been changed.

The facade adds no dependency, HTTP server, shell tool, model provider, billing, automatic imports, proof insertion or new evidence certificate. Existing goal/candidate artifacts and catalog provenance keep their original identities and claims. The real host application decides its worker/transport and authorizes every request.

## Bind a host-authorized workspace

```python
from pathlib import Path
from agda_evidence.research import ResearchWorkspace

workspace = ResearchWorkspace(
    Path("/host/materialized/authorized-project"),
    {"main": "Main.agda"},
    agda_binary="/usr/bin/agda",
    includes=(".",), safe=True,
    # catalog=Path("/host/config/research.catalog.json"),
)

state = workspace.handle({
    "requestId": "ui-1", "op": "workspace.status",
    "revision": None, "args": {},
})
revision = state["currentRevision"]
listed = workspace.handle({
    "requestId": "ui-2", "op": "goals.list", "revision": revision,
    "args": {"documentId": "main"},
})
```

The host alone configures project root, document-ID-to-relative-file mapping, compiler request, includes, safe setting, optional local catalog and resource/store budgets. Client payloads cannot choose host paths, commands, compiler flags, new library references, output filenames or uploaded observation dictionaries. Rename/reconfiguration requires a newly bound facade, rather than changing an old ID's meaning in place.

Create a separate authorized instance per workspace/session. Opaque record IDs do not replace authorization. The real app must authorize every operation and evidence download; never pool an instance across unrelated users or expose its dispatcher as an unauthenticated service.

## One request and response envelope

Requests contain exactly `requestId`, `op`, `revision` and `args`. Each response has `apiVersion: 1`, those request identifiers, `currentRevision`, current observed `workspace` subjects, `status`, nullable `recordId`, `result`, and nullable `error: {code, message}`. The [request schema](../schemas/research-request-v1.schema.json) and [response schema](../schemas/research-response-v1.schema.json) describe the envelopes. Runtime checks additionally enforce host document membership, valid Unicode, UTF-8 byte limits and current revision/evidence bindings.

Top-level status is `ok`, `error` or `stale`. **API `ok` is not Agda acceptance or proof success.** A valid failed trial is `ok` at this transport-independent layer with `result.outcome.status: query-error`. The UI must present the native outcome, not a green badge based on API status or successful offline verification.

`currentRevision` is an opaque per-instance generation token, not a source hash, kernel certificate or durable project version. `workspace.sourceId` and `workspace.resolutionId` remain the existing source and partial-native-resolution subjects. Request IDs are correlation labels, not deduplication/idempotency keys; replaying a candidate request starts another trial.

## Supported operations

`workspace.status` takes empty args and may use null revision. It refreshes source/native-resolution observations and returns host-exposed document IDs, dirty-buffer state, compiler availability, whether a catalog is configured, includes/safe policy and limits. It does not return absolute host root, compiler or catalog filenames.

`goals.list` takes `documentId` and the current revision. It records an isolated native listing and returns an opaque `recordId` plus `result.observationId`, document ID and native `outcome`. Only a record with native `listed` status is selectable. The opaque ID is not interchangeable with the content-derived observation ID.

`goals.inspect` takes `listingId` and nonnegative scalar `goalId`. The listing must be an accepted leaf created in this instance, current under its original revision/subjects. The response retains displayed type, structured bindings, boundaries and goal-related display constraints through the unchanged goal-observation format.

`library.search` takes `listingId`, `goalId`, exactly one nonempty `exact`/`prefix` string, and optional `scope`, `limit`, `kinds` and `libraries`. Scope is `project`, `catalog` or default `all`; limit is 1–100, default 30. Project search builds a current source-bound lexical index. Catalog search re-verifies every configured catalog entry before returning any hit, even entries excluded by filters. No catalog is mounted into Agda. Unknown/mismatched catalog evidence fails the whole search rather than silently returning only project hits.

Search results retain duplicate names and independent provenance, add `origin`, `scopeStatus: not-established` and `candidateUsability: not-tested`, and report total/truncation and checked catalog entries. The selected goal is explicit context, but `contextualRanking: false`: this first integration does not rank by goal type, establish importability or declaration origin, or claim a lexical head is a checked declaration. Project hits have index/source evidence, not a fabricated project-check attestation. Catalog hits retain the actual attested command/outcome, which may itself be failed research evidence.

`candidate.check` takes `listingId`, `goalId` and an explicit nonblank `expression`, capped at 65,536 UTF-8 bytes. The host fixes runtime limits and inherits the listing's source/compiler/file/include/safe policy. Search results never automatically become expressions or imports. A positive native result is `elaborated` with `contextual-elaboration-only` assurance; it is not candidate-local obligation freedom, insertion acceptance or proof completion. All trials leave source unfilled.

`record.get` takes `recordId` and may use null revision. It returns the complete exact artifact, kind, document ID, recorded revision and `freshness: current|stale|unknown`. A stale artifact remains useful historical evidence, never an active result. Unknown freshness is used when live inputs cannot be observed; historical evidence is still retrievable. This operation does not activate an old listing or authorize another trial.

## Example selected-goal workflow

Use an actual ID from `listed["result"]["outcome"]["goals"]`:

```python
listing_id = listed["recordId"]
goal_id = listed["result"]["outcome"]["goals"][0]["id"]

search = workspace.handle({
    "requestId": "ui-3", "op": "library.search", "revision": revision,
    "args": {"listingId": listing_id, "goalId": goal_id,
             "prefix": "Main", "scope": "project", "limit": 20},
})
trial = workspace.handle({
    "requestId": "ui-4", "op": "candidate.check", "revision": revision,
    "args": {"listingId": listing_id, "goalId": goal_id, "expression": "n"},
})
record = workspace.handle({
    "requestId": "ui-5", "op": "record.get", "revision": None,
    "args": {"recordId": trial["recordId"]},
})
```

Check API status before using results and check the native outcome before showing success. `n` is relevant only in the committed example's particular Nat goal; do not derive an expression from a lexical name or assume it works at another selected goal.

## Editor changes, unsaved buffers and late results

The facade reads a materialized regular-file tree, not browser editor memory. The host must represent the exact requested editor revision on disk before checking. It must notify **every** edit/save event, including edit-and-revert or same-content changes:

```python
workspace.notify_buffers(dirty=True)   # immediately on an editor edit
# Host saves/stages the complete requested revision under the authorized root.
workspace.notify_buffers(dirty=False)  # only after materialization is complete
```

These methods are trusted host notifications, not dispatcher commands. Every notification advances the generation; dirty workspaces reject research actions as stale. Obtain the new status/revision, relist goals and reselect rather than silently reusing old interaction IDs. A client cannot supply `dirty: false` to bypass this step.

Before research work, current source and native-resolution subjects must match the request revision and stored listing. After **successful and failed** work, the facade re-observes live subjects, including compiler/registry changes, and compares the generation under its publication lock. A concurrent input change takes precedence over native success or error: the response is `stale` and any retained artifact is historical. If freshness cannot be established, no result is published active.

The UI must also discard responses whose revision or request ID is superseded in its view. This is necessary for events after publication and responses from unrelated async requests. Hash observations are not atomic filesystem snapshots; unnotified edit-and-revert races cannot be detected from final bytes alone. The host must serialize staging and send the edit notifications. The unchanged core source-copy captures check staged inputs; this facade additionally rechecks live inputs after the operation.

## Scheduling, storage and errors

One research operation may run per instance; concurrent research requests get `workspace-busy` rather than an unbounded queue. Status and historical reads remain available, and trusted edit notifications are not blocked by the long operation. The host owns cancellation, overall request deadlines, snapshot/catalog size budgets and process isolation. The default 60-second/4 MiB limits apply to the native interaction, not all copying, metadata probes, catalog verification or host transport time.

Artifacts are defensive canonical-JSON copies in an instance-local FIFO store, default 64 records and 33,554,432 bytes. Oldest records are evicted to maintain either budget. A single oversize artifact returns `store-capacity` and is not retained. There is no silent disk persistence, durable store, cross-instance lookup or automatic upload; history disappears on instance restart. Unknown, evicted and cross-session IDs all return `record-unavailable`. Callers receive decoded copies, not mutable references to internal evidence. The host can persist authorized downloaded artifacts outside the source tree using its existing storage/authentication system; this facade is not a persistence guarantee.

Errors use codes including `invalid-request`, `record-unavailable`, `catalog-invalid`, `catalog-unavailable`, `evidence-invalid`, `freshness-unavailable`, `workspace-busy`, `store-capacity`, `workspace-unavailable` and `internal-error`. Stale outcomes use `workspace-changed` or `listing-stale`. Unexpected/configuration errors return bounded generic messages rather than stack traces or host paths; native artifact diagnostics remain exact normalized evidence and should be reviewed before sharing.

This interface does not make an untrusted Agda project safe to run. A public service must supply process/filesystem/network isolation and resource controls, including reflection side effects, and must scope every storage/read operation to the authorized workspace. Source snapshots remain manifests, native resolution remains partial, and observation hashes establish internal consistency rather than producer authenticity or offline toolchain replay.

## Native integration pilot and actual app hookup

```sh
python scripts/research-pilot.py --agda-bin /usr/bin/agda \
  --output /tmp/native-research-pilot
```

The finite fixture connects the API end to end: listing → context → bounded project search → verified catalog hit → explicit elaboration and rejection trials → exact record retrieval → dirty/revision invalidation → historical evidence. It also proves that a catalog hit is not automatically imported: `Example.identity n` still fails in the example goal module. Only a disposable external workspace is edited in the invalidation case; original examples remain unchanged. API exchanges are a workflow log, not a new proof certificate; the included native records remain independently verifiable.

To complete the live AgdaLab feature, attach its existing repository/site, map authorized project/document IDs and materialized revisions to this facade, wire edit/save notifications, and add a research panel using the existing editor's UI conventions. Display current goal/context, lexical results/provenance, explicit trial input, native outcomes and current/stale evidence separately. No live editor integration is claimed until that application code and runtime have actually been changed and validated.
