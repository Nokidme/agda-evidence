# Native research API workflow — 2 November 2026

The library-side workflow passed on real **Agda 2.6.3** in [GitHub Actions run 41529089328](https://github.com/Nokidme/agda-evidence/actions/runs/41529089328), at implementation commit `910744aad45ffd1a28581264f37cf79d741f108f`. The original source checkout remained unchanged. The downloaded artifact was independently verified locally, including all 17 API request/response pairs, both goal records, all three candidate records, their exact embedded leaf listing, and the example-library evidence bundle. All API and native artifact schema checks passed.

This validates the optional Python host API, **not an integration or deployment of the live AgdaLab editor**. The native fixture is self-contained plus Agda builtins; a configured discovery catalog does not become a dependency environment for native queries. No claim is made here about the live app's compiler/runtime, authentication or persistence.

## Observed workflow

The host binds one materialized workspace and a `main` document ID. The API lists three unfinished goals, inspects the selected dependent-equality context, returns bounded project lexical results, and finds a source-pinned catalog declaration `Example.identity`. Search results remain `scopeStatus: not-established` and `candidateUsability: not-tested`; truncation is explicit, and catalog provenance retains its own actual check outcome.

The explicit expression `refl` at the equality goal produces `elaborated` with `contextual-elaboration-only` assurance. The wrong-type expression `n` produces a retained native `query-error` even though the API operation response itself is `ok`. `Example.identity n` at the Nat goal also produces `query-error`: catalog discovery did not silently mount/import the example library.

A trusted dirty-buffer notification blocks another trial as `stale`. After a newer source revision is materialized, the old listing is rejected as stale. The earlier successful trial remains retrievable byte-for-byte as historical evidence with `freshness: stale`, never promoted as an active result. Only the disposable external workspace is modified for that case; the committed examples remain untouched.

## Exact recorded subjects and observations

```text
sourceId
sha256:8d6243e60517ca8a08a9edcb6888d41269def7d369d174f3ef1e21727a01d076

partial native resolutionId
sha256:5d96ead6f9d4e407766c18d2c1c42f6e0e9e594444378d6668255c2774df7f3e

leaf listing observationId
sha256:e0f2ba7e9ad6e5c9024b399976ed139be7b7caf0c409bea4e87c42a4a646cebd

selected context observationId
sha256:ea7c17522307b306ceaf4ae6a5e3999bec8ebe9c10b7589c7e71160085510027

elaborated trial observationId
sha256:5589edc97efffff85b2869364e09d7e4d740244c65450804a8018eacbdb133e4

wrong-type trial observationId
sha256:6b6dc653c9c7b0ecaa2734b5ab9ebfd09f1ccdb7732221e8b8d12b8ec439ee15

unmounted-catalog-expression observationId
sha256:1eb605184496ab727ea1c0fa64d12325d572b58fa79a20077dedb6d8ab5d3e97

example-library bundleId
sha256:b9dac083647bb6b43c798386efcd678cb7263612942ce7955a9474c8c0f810bc

Agda binarySha256
sha256:852806142a15951f667df303c73cfce5f4123218ce6e1f1b29acaddc242af00d
```

Instance-local opaque record IDs and revision tokens are deliberately not durable evidence subjects. Native observation IDs include time-specific transcript/capture information; another valid run need not reproduce these complete observation IDs.

## Regression coverage and follow-up

The implementation baseline passed all 132 local tests and its normal GitHub CI. Fourteen focused integration tests exercise real fake-wire capture/validators and optional real Agda, including path/config injection rejection, session-only selectable records, immutable bounded FIFO history, source/compiler/registry changes, errors after concurrent edits, dirty/edit-and-revert notifications, nonblocking concurrency, duplicate provenance and no implicit library usability.

A focused review identified a minor envelope-precondition mismatch: non-null revisions on status/history reads were accepted without comparison. The follow-up enforces supplied read revisions, keeps null-revision historical access intentional, and adds a regression for both read operations and unavailable live inputs. All **15 focused tests** passed after that correction. The native workflow above used null revisions for status/history, so this correction does not alter the behavior recorded here. No underlying goal, candidate, catalog or bundle format was changed.

## Reproduce and inspect

```sh
python scripts/research-pilot.py --agda-bin /usr/bin/agda \
  --output /tmp/native-research-pilot
agda-evidence goals verify /tmp/native-research-pilot/listing.json
agda-evidence goals verify /tmp/native-research-pilot/context.json
agda-evidence goals verify-check /tmp/native-research-pilot/elaborated.candidate.json
agda-evidence goals verify-check /tmp/native-research-pilot/rejected.candidate.json
agda-evidence goals verify-check /tmp/native-research-pilot/unmounted.candidate.json
agda-evidence verify /tmp/native-research-pilot/library.evidence
```

Choose a fresh external output directory. The workflow log `exchanges.json` is not a new proof certificate. The archived `workspace/` intentionally contains the newer editor revision from the invalidation test; use the original committed example at the recorded implementation commit for the historical listing's source bytes, not that modified workspace as a purported replay of old evidence. Offline verification establishes retained artifact consistency, not a new native check, producer authenticity, source archival guarantee or proof completion.
