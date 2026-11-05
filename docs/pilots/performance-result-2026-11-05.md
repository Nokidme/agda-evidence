# Check-preserving performance result — 5 November 2026

[Implementation 712daba](https://github.com/Nokidme/agda-evidence/commit/712dabae905dd588cd791622805d618280268bc5) reduces validation overhead without caching live freshness or weakening native evidence. The [pinned Agda 2.6.4.3 workflow 42058984399](https://github.com/Nokidme/agda-evidence/actions/runs/42058984399) passed current wheel/source conformance plus a serialized, alternating-order comparison against the fixed pre-optimization commit `c1f3a58b772619be561e58b6ea2d7d509e5db4ec`.

The matched `Function.Base` comparison observed approximately **6–8% lower median total host-call time** for goal listing, context inspection and accepted candidate elaboration. This is a bounded development improvement, not a production SLA, statistical significance result or a resolution of the larger editor `Data.Nat.Base` timeout. No app deployment, alpha release replacement, evidence schema, native deadline or interface policy was changed.

## Exact workload and installed consumers

Both old and new wheels used the same finite runner, separately installed with no runtime dependencies/index into fresh virtual environments outside the checkout, and executed with isolated `python -I`. Both are development version `0.1.0a2.dev0`; their different actual wheel bytes were identified by SHA-256:

```text
before: 28469d37724a637e871af9bcc030ecd5663c7570695cc6f92586f572ee6c1f72
after:  a69fd19aa68d233c8c1b4e707a5a1ff9e558c19096f0fd0b35b3cf6cf72ddd9c
```

The workflow separately built exact Agda release source `714c7d2c76c5ffda3180e95c28669259f0dc5b5c` with GHC 9.4.8, cabal-install 3.10.3.0, Happy below 2 and `-O1`. Native version output was exactly `Agda version 2.6.4.3`. All compared artifacts recorded compiler digest:

```text
sha256:a55596aaf28bf4baeb1134fcd1cda9345ad13efc91846e96a196269ae23e99d5
```

The real stdlib profile used v2.0 source commit `2b8fff10f4033b91a6df4007e4a65cb10047c89c`, dependency snapshot `sha256:a56306c900676de019ce49fdbbfb37551ed05ef7fdaf241cc7a485b2b2b956f4`, and the narrow safe `Function.Base` gate. The unfinished client explicitly imported `id` and tried `id n` at a builtin Nat goal. No implicit imports, warning suppression, interface reuse or dependency closure was added.

Two repetitions ran in order **before, after, after, before**, serialized on the same GitHub runner after initial conformance/provisioning. Each comparison run passed **all 21 mandatory cases**, exported **15 complete native/source artifacts** and retained **57 v1/v2 exchanges**. Client source, client/dependency native resolution, dependency source and composition subjects matched across all four runs. Bundle and observation IDs can differ legitimately because each run captures new time-specific evidence; those exact IDs and priors were verified individually, not falsely equated.

## Matched unprofiled timings

These are monotonic total host-operation times from the matched comparison, not the cProfile-instrumented run or a comparison to yesterday's runner.

| Source v2 operation | Before samples (seconds) | After samples (seconds) | Before median | After median | Observed reduction |
|---|---|---|---:|---:|---:|
| Goal listing | 3.690, 3.743 | 3.543, 3.444 | 3.717 s | 3.494 s | 6.00% |
| Context inspection | 4.154, 4.180 | 3.856, 3.791 | 4.167 s | 3.823 s | 8.25% |
| Accepted candidate trial | 4.232, 4.207 | 3.947, 3.872 | 4.219 s | 3.909 s | 7.35% |

Raw full-precision samples are retained in `comparison.json` and in the original per-run timing sidecars; rounded numbers above do not supply the calculation inputs. For these three groups, each run contributes one call. Other grouped operations can contribute multiple calls; their raw samples remain inspectable rather than being represented as independent benchmark repetitions.

The native session budget stayed **20 seconds** in every old/new artifact. Inner execution spans were predominantly one second, with some zero-second context spans under the existing coarse timestamps. They include preparation/cleanup and are neither compiler CPU nor load-only timings. Total host calls additionally include source/environment observation, hashing, semantic validation, copying and publication. No end-to-end timeout or SLA is inferred from the session budget.

Two alternating-order samples per version cannot establish significance, percentiles or general throughput. Filesystem/OS warming, scheduling noise and fixture size still matter. The earlier 4 November run had different runner conditions and is **not** the baseline for the reduction above. Local 2.6.3 comparisons also passed but ran concurrently with profiling/regression jobs; their timings are not the primary performance evidence. Nothing here remeasures or fixes AgdaLab's larger `Data.Nat.Base` failure, or proves equivalence with its deployed compiler binary.

## The optimization and retained checks

The SHA-256 identifier validator replaced a Python character generator with an exact compiled `fullmatch` for `sha256:` followed by 64 lowercase ASCII hexadecimal characters. It still checks every value and rejects uppercase, Unicode lookalikes, wrong lengths, suffixes and trailing newlines. Differential tests against the prior implementation cover 2,500 deterministic cases plus explicit malformed values, preserving prefix/type error categories and original returned strings. No digest calculation was removed and no accepted plain JSON identifier language was broadened.

The private source evidence loader now calls the generic verified disk loader once and immediately applies the same stricter source profile to the **exact parsed objects already verified**. It avoids only an immediate second execution of the generic verifier over those unchanged objects. Enhanced identities/subjects, diagnostics digest, canonical/safe snapshot records, timestamps, available partial native compiler, resolution identity and root-manifest binding remain required.

Untrusted embedded evidence still receives complete shape/component/name checks and full generic verification. Prior listings, final capture envelopes, stored records and offline validation retain that full path. Objects returned by a prior load confer no authority on a later disk read or mutated dictionary. No trust boolean, mtime/size cache, object-identity cache or cached dependency admission was introduced.

The before/after finite profile independently confirmed the intended structural change:

| Function | Before calls | After calls | Interpretation |
|---|---:|---:|---|
| Generic bundle verifier | 395 | 253 | Immediate duplicate executions removed |
| JSON reader | 794 | 794 | Same reads retained |
| Full snapshot builder | 449 | 449 | Same complete source observations retained |
| Native resolution builder | 391 | 391 | Same native/compiler observations retained |
| Source research observer | 66 | 66 | Same observer invocations retained |

Those counts come from the same finite Agda 2.6.3/stdlib v1.7.3 profiling workload, not from the 2.6.4.3 comparison. cProfile overhead particularly amplifies generator-heavy work; instrumented cumulative times overlap and are not the measured user-visible reductions. A standalone valid-identifier hot-loop diagnostic also ran faster, but it is not a native/facade speedup claim.

Each source-facade observation still independently rereads and verifies the bundle twice, snapshots both live trees twice, and performs four root-specific native observations. Full compiler-byte hashing, version/app-directory probes, registry/root manifests, source-copy containment, staged union, pre/post native guards, dirty/edit-revert generation invalidation and serialized freshness publication remain. Independent review found no actionable runtime issue in the bounded patch.

## Integrity, native outcomes and independent verification

All **222 local tests passed**. New regressions include one generic verifier per disk read, same-object handoff, independent repeated reads, changes after component parsing, same-length corruption with restored inode/size/mtime, rehashed valid bundle replacement between passes and requests, detached embedded mutation, stricter source-only policy rejection, failed explicit attestations remaining admissible, and unchanged four native observations per source observer. Existing source/compiler/publication race tests remained green.

The pinned workflow's current **four installed consumers**—wheel/source archive crossed with builtin/stdlib profiles—also each passed 21 mandatory cases, exported 15 full artifacts and retained 57 exchanges. Missing names/imports and wrong types remained native `query-error`; unreachable clauses remained diagnostic-bearing `load-blocked`; fatal type mismatch remained `load-error`. Accepted elaboration retained `contextual-elaboration-only` and unchanged postflight. No source hole was filled. Dirty-generation and changed dependency refusals, stale records, unknown missing-bundle history, revision-bound read errors and cross-session rejection all remained.

Downloaded current conformance and all four comparison runs were independently checked locally with subprocess launch blocked and a local schema registry that rejected unregistered retrieval. Existing semantic verifiers plus schemas validated full artifacts, source/compiler/bundle/composition bindings, exact embedded prior leaf listings and preserved native outcomes. Accepted wire exchanges passed unchanged schemas; deliberate invalid-request negative requests were checked for rejection. Historical artifacts matched their complete exports. Recorded inner spans matched timestamps; raw host-call samples and diagnostic median/reduction calculations were recomputed. Current distribution checksums matched retained `SHA256SUMS`.

Ordinary [eight-job CI 42058981225](https://github.com/Nokidme/agda-evidence/actions/runs/42058981225) passed, including Linux/Windows wheel/source installs and genuine native Agda 2.6.3 package smoke. Its compiler-free source jobs discovered 222 tests and legitimately skipped native-dependent fixtures; the exact 2.6.4.3 mandatory conformance/comparison runs did not skip their cases. All 13 canonical schema resources remained unchanged and installed. Windows package installation does not claim native Windows adapter support.

## Reproduction and next step

```sh
gh run download 42058984399 --repo Nokidme/agda-evidence \
  --name native-conformance-2.6.4.3-712dabae905dd588cd791622805d618280268bc5 \
  --dir /tmp/agda-performance-run
```

The download retains current `conformance-dist` with checksums, `native-conformance-consumers`, `performance-before-dist` and `native-performance-comparison`. The last directory includes old/new installation logs, `runs.json`, `comparison.json`, and full per-run conformance reports/exports. The [performance guide](../performance.md) documents finite profiling and fresh comparison commands. Workflow artifacts have 30-day retention, not permanent archiving.

All reports are unsigned producer data. Offline consistency checks do not establish producer authenticity, permanent freshness, live-runtime isolation or performance guarantees. Compiler/library build provisioning is separate and does not preserve every transitive build dependency.

The next useful step is to investigate **verified project-aware declaration discovery** and reduce redundant source-index computation while retaining exact byte checks, source/scanner identities, generation invalidation and catalog provenance. Persistent live freshness caches or shared compiler observations remain inappropriate without a separately justified contract. Multi-dependency support, agents, alpha release promotion and production editor enabling remain separate milestones.
