# Native conformance result — 4 November 2026

The finite conformance tooling in [commit f54f280](https://github.com/Nokidme/agda-evidence/commit/f54f280e39c4cec7d7a34ceb4f1a850c9915bcc5) passed [pinned Agda 2.6.4.3 workflow 41792691712](https://github.com/Nokidme/agda-evidence/actions/runs/41792691712). Both builtin-only and stdlib `Function.Base` profiles passed in separately installed wheel and source-archive consumers. Each of the four consumers executed **all 21 mandatory cases**, exported **15 complete native/source artifacts**, and retained **57 v1/v2 request/response exchanges**. None of those required conformance cases was skipped.

This closes a specific development compiler/profile coverage gap. It does not deploy AgdaLab, prove equivalence with its actual backend binary, establish production isolation or resolve the larger editor `Data.Nat.Base` timeout. The current package remains unreleased `0.1.0a2.dev0`; the existing `v0.1.0a1` release is unchanged.

## Exact native environment

The workflow built Agda release source commit `714c7d2c76c5ffda3180e95c28669259f0dc5b5c` and required exact stdout `Agda version 2.6.4.3`. It used GHC 9.4.8, cabal-install 3.10.3.0, Happy constrained below 2 and `-O1`. The recorded compiler binary digest in all four profiles was:

```text
sha256:a55596aaf28bf4baeb1134fcd1cda9345ad13efc91846e96a196269ae23e99d5
```

The stdlib profile used separately provisioned v2.0 source commit `2b8fff10f4033b91a6df4007e4a65cb10047c89c`. Its dependency snapshot ID was:

```text
sha256:a56306c900676de019ce49fdbbfb37551ed05ef7fdaf241cc7a485b2b2b956f4
```

The narrow recorded gate checked `src/Function/Base.agda` with explicit source includes, `--safe --no-libraries --ignore-interfaces`; this was **not** a whole-stdlib gate. The client used builtin `Nat` and explicitly imported `Function.Base.id`; `id n` was tried at a real unfinished `Nat` goal. All generated client fixtures used only the `--safe` pragma, without inferred library warning settings or automatic suppression. This is a newly observed pairing, not a retrospective change to the older 2.6.3/stdlib v1.7.3 equality profile or released alpha's support contract.

The builtin profile instead used an independent tiny safe `Mini.identity` dependency and the same finite behavioral checks. Compiler/library build downloads occurred during provisioning; the conformance runtime fetched nothing. Fresh consumer interpreters ran in isolated `-I` mode outside the checkout. Wheel installation used no index/runtime dependencies; source installation could fetch declared build tools. No preserved build dependency closure or offline compiler reconstruction is claimed.

## What passed

Ordinary `ResearchWorkspace` v1 and source-aware v2 goal listings and selected type/context queries passed using the actual scalar interaction IDs. Context retained the local `n : Nat` binding. Unicode/multiple-hole fixtures returned two goals; a completed fixture returned a valid empty listing.

The explicit `identity n` or stdlib `id n` candidate elaborated with `contextual-elaboration-only` assurance and unchanged restored goal postflight. A wrong-type `Nat`, missing name, absent dependency import and independent catalog expression remained genuine native `query-error` records. No expression was inserted into a hole.

An unreachable-clause fixture produced actual warning diagnostics and `load-blocked`; a fatal type mismatch produced an actual `Error` response and `load-error`. Those records were exported before assertions and could not be selected for context queries. Prompt completion or API `ok` was never substituted for successful native checking.

Project, dependency, catalog and combined lexical searches retained distinct source/check provenance. Scope stayed `not-established`, candidate usability `not-tested`, contextual ranking false. Catalog-only filters did not leak dependency declarations; supplying catalog filters to dependency-only requests was deliberately rejected as an invalid request. That negative wire request is intentionally not schema-valid and its rejection was checked, rather than treated as an accepted malformed request.

Dirty/clean notifications invalidated old selections even when source bytes matched again. An unrelated private dependency edit gave known changed subjects, false frozen-pin admission and `dependency-changed` under a refreshed revision; earlier exact evidence remained stale. Moving required bundle evidence made null-revision history unknown and revision-bound reads fail `freshness-unavailable`. A separately constructed current session refused old opaque records/selections. Each profile retained 15 current, two stale and one unknown successful artifact reads.

The runner's 21-case scope does not duplicate every integrity regression. In particular, same-source/resolution bundle recapture refusal remains covered by the earlier dedicated [source research pilot](source-research-result-2026-11-03.md) and unit tests, not newly exercised by this conformance lane. Full original-source snapshot IDs remained unchanged, and original roots received no generated `.agdai` interfaces.

## Measured latency, not an SLA

The stdlib `Function.Base` wheel consumer observed total host-call times of **4.988 seconds** for listing, **5.759 seconds** for context inspection and **5.811 seconds** for the accepted candidate. The source-archive consumer observed **4.978**, **5.685** and **5.855 seconds**, respectively. Initial source-aware constructor admission was about **0.84–0.85 seconds**. The corresponding builtin-profile calls were about **1.98–2.00 seconds**.

Each stdlib record's existing inner execution timestamps yielded a **one-second recorded span** for those three native operations. These timestamps include inner preparation and cleanup and have second precision; they are not compiler CPU or separately timed load/check phases. Some short builtin operations yielded zero-second inner spans despite positive monotonic total time. The report sidecar keeps that precision limit visible instead of manufacturing finer native timings.

The native session budget stayed **20 seconds**. Total host calls include additional source/environment stabilization, copying, hashing, semantic verification and publication; the session budget is not an end-to-end deadline. The measurements are single-run observations on this built compiler and Ubuntu runner, not percentiles, throughput guarantees, cold-machine benchmarks or production latency claims. No interface cache, deadline increase, native policy relaxation or performance optimization was introduced.

The original editor task had reported its larger `Data.Nat.Base` fixture exceeding the 20-second limit. This finite lane did not rerun that fixture or establish a fix. The measured gap between full calls and coarse inner spans points to additional host work, but it does not isolate a single bottleneck or justify skipping freshness checks.

## Independent verification and ordinary CI

The workflow artifact was downloaded and independently verified locally, rather than trusting its green status alone. All four reports required the exact compiler/version, the complete mandatory-case set, matching complete artifact IDs and unchanged frozen source/resolution/bundle/composition subjects. All retained native/source artifacts passed existing semantic verification plus their schema checks. Exact prior leaf listings matched independently exported records. Recorded execution spans matched the underlying timestamps, while monotonic measurements remained producer diagnostics, not authenticated performance evidence.

Every accepted v1/v2 exchange passed its unchanged wire schema, with deliberate invalid-request negatives checked for rejection. Historical downloads matched the exported complete artifacts. Native warning/fatal/failed trial outcomes remained unchanged. During verification, both subprocess launch entry points were blocked, and a local schema registry rejected unregistered retrieval instead of fetching resources. This establishes internal evidence consistency, not producer authentication or live freshness. The downloaded wheel/source checksums matched the workflow's retained `SHA256SUMS`.

All **198 local tests passed**. Ordinary [CI 41792689598](https://github.com/Nokidme/agda-evidence/actions/runs/41792689598) passed all eight jobs, including Linux/Windows fresh package installs and native Agda 2.6.3 installed-package smoke. Its compiler-free Python 3.11 and 3.12 source jobs discovered 198 tests with 17 native-dependent skips; those skips are distinct from the mandatory no-skip 2.6.4.3 conformance workflow. All 13 canonical schema resources remained unchanged and installed. Windows installation is not a native Windows Agda support claim.

The increment changed tooling, tests and documentation only. Production Python modules, wire/evidence schemas, previous source fixtures and the existing stdlib 2.8 checker workflow were not modified.

## Reproduce and next work

While CI artifacts are retained:

```sh
gh run download 41792691712 --repo Nokidme/agda-evidence \
  --name native-conformance-2.6.4.3-f54f280e39c4cec7d7a34ceb4f1a850c9915bcc5 \
  --dir /tmp/agda-conformance-run
```

The download contains `conformance-dist` with the exact tested wheel/source archive and checksums, plus `native-conformance-consumers` with `consumers.json`, four `summary.json`/`exchanges.json` pairs, native/source exports and bundles. Existing CLI `goals verify`, `goals verify-check`, `source verify` and `verify` commands check their respective artifact types offline. Diagnostic summary success alone is not an evidence verifier. Artifact retention is 30 days, not a permanent archive.

The [conformance guide](../native-conformance.md) provides fresh consumer commands and exact bootstrap constraints. To use the checks on AgdaLab's actual runtime, its authorized editor/backend task must supply that binary and isolated source profile, run the same required cases and assess execution isolation separately. A matching version string alone is insufficient.

The next useful performance step is narrowly measuring and optimizing the repeated host observation/discovery work while preserving full-byte source/compiler/bundle checks, root containment and notified-generation invalidation. Merely adding interface reuse or increasing the native deadline would evade the current integrity and latency questions. Production enabling or publishing remains outside this library increment.
