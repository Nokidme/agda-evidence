# Native compiler conformance and timing

`scripts/native-conformance.py` runs a finite set of real native operations against an explicitly selected compiler, with mandatory cases rather than green skipped coverage. It tests the existing ordinary research facade and opt-in source research API; it does not change their wire formats, evidence semantics or acceptance policies. It is a development diagnostic, not a compiler installer, agent, benchmark service or AgdaLab deployment.

The original AgdaLab task reported a development checkpoint with a passing stdlib `Function.Base` workflow and a `Data.Nat.Base` fixture exceeding its 20-second native research budget. Its backend reported Agda 2.6.4.3. That establishes a useful version target for library checks, not an equivalence between a newly built compiler and the actual live backend. Production research execution remains an application isolation/deployment decision, not something this runner enables.

## Explicit profiles and required checks

The `builtin` profile creates a small safe source dependency using Agda builtin Nat, a separate client and an independent catalog library. It needs no external stdlib checkout. The `stdlib-function` profile requires an already provisioned source directory and narrowly checks `Function.Base`; it is not an upstream whole-library gate. Both use source copies and explicit includes; neither inserts imports, guesses qualifiers, reads a package-manager profile, downloads dependencies or repairs warning flags. The old 2.6.3/stdlib v1.7.3 equality fixture remains unchanged.

Each required case must actually execute and pass. Missing or mismatched compilers, failed loads, unexpected native outcomes and unexecuted required cases fail the run. The retained report includes failed/not-run cases and any evidence captured before failure. An API `ok` rejected trial is a successful *conformance case* only if it preserves the expected native failure; it is not a successful proof attempt.

The finite suite has 21 required cases covering scalar goal selections, structured local context, Unicode/multiple goals, empty listings, explicit contextual elaboration, wrong-type and missing-name failures, missing imports, actual warning-blocked and fatal loads, lexical scopes/provenance, catalog discovery without mounting, complete offline artifact verification, dirty-generation invalidation, dependency pin changes, unknown missing-bundle history and cross-session handles under an explicitly constructed new session. Same-subject bundle recapture refusal remains covered by the separate [source research pilot](pilots/source-research-result-2026-11-03.md), not duplicated in this finite runner. Original sources and holes remain unchanged. Positive candidates retain **contextual-elaboration-only** assurance; speculative residual freedom or completion is not established.

Blocked listings retain native diagnostics and cannot become selectable merely because their transport reached a prompt. Native warning acceptance is not relaxed to fit another compiler. Unsupported options/import behavior remain recorded failures; the runner does not retry with different flags, higher limits or interface caches.

## Run against a separately provisioned compiler

```sh
python scripts/native-conformance.py \
  --agda-bin /absolute/path/to/agda --expected-version 2.6.4.3 \
  --profile builtin --timeout-seconds 20 \
  --output /tmp/agda-native-builtin-conformance

python scripts/native-conformance.py \
  --agda-bin /absolute/path/to/agda --expected-version 2.6.4.3 \
  --profile stdlib-function --dependency-root /host/provisioned/stdlib-2.0 \
  --timeout-seconds 20 --output /tmp/agda-native-function-conformance
```

Use a fresh output directory outside the checkout and dependency tree. The runner uses an explicit empty registry and records the actual compiler version and binary subject in its native evidence. `--expected-version` must match exactly; having a similar major/minor version is insufficient. A diagnostic report and exact artifact exports are retained under the output directory. There is no persistent worker or scheduled background monitor.

## Test the installed artifacts, not source imports

```sh
python -m build --outdir /tmp/agda-native-dist
python scripts/check-native-conformance.py \
  --dist-dir /tmp/agda-native-dist --runner scripts/native-conformance.py \
  --agda-bin /absolute/path/to/agda --expected-version 2.6.4.3 \
  --dependency-root /host/provisioned/stdlib-2.0 --timeout-seconds 20 \
  --output /tmp/agda-native-consumers
```

The wrapper creates separate wheel and source-archive virtual environments and consumer working directories outside the repository. It strips source-path overrides and invokes Python in isolated `-I` mode. Both artifacts run the builtin profile; supplying a stdlib root adds the separate `stdlib-function` profile to both. Logs and reports survive disposal of the consumer environments. Any failed consumer produces a nonzero final result, rather than a passing summary based only on the successful profile.

Wheel installation uses no index/runtime dependencies. Source installation may fetch declared build tools. Compiler/library provisioning and those build downloads are not native-runtime resolution, offline replay or a preserved dependency closure. No compiler, library checkout or previously generated interfaces are shipped with the Python package.

## What the timing means

The conformance sidecar records monotonic elapsed time around host constructor admission, individual `handle` calls and export/offline checks. These are observed **total host-operation times** on that run, including source/environment re-observation, metadata hashing, copying, validation and serialization as applicable. A lookup/status/history read may still be expensive because it observes current inputs; a session handle does not make a cached artifact currently fresh by itself.

For native records, the sidecar separately derives the **recorded inner execution span** from the existing `execution.startedAt` and `finishedAt` values. Those timestamps include inner preparation and cleanup, not just the Agda process or compiler CPU. Existing captures use second-resolution timestamps, so a short operation can report a zero-second inner span even when positive monotonic host time was measured; this does not mean no native work occurred. Untimed transcript phases cannot be turned into individual load/check timings. Timing fields belong to a diagnostic sidecar, not silently added fields in hashed artifacts or wire responses.

The configured 20-second native timeout starts at native session construction; it does **not** cover all facade work, source copying, metadata capture, lexical discovery, verification, output transfer or UI delay. It is not an end-to-end request deadline or SLA. Larger total calls do not prove that the session timeout failed; likewise a small fixture fitting this budget does not prove that `Data.Nat.Base` or other research libraries fit it. No performance optimization, deadline increase or interface cache is introduced by this increment.

Use measured spans to choose the next optimization only after preserving source/compiler/bundle and generation guards. They are single-run observations, not percentiles, throughput claims or equivalence with production infrastructure. Source sizes, build flags, consumer kind and actual compiler subjects matter when comparing runs.

## Exact 2.6.4.3 target and bootstrap limits

The maintained manual workflow independently checks out Agda release source commit `714c7d2c76c5ffda3180e95c28669259f0dc5b5c`, verifies exact version output, and provisions stdlib v2.0 commit `2b8fff10f4033b91a6df4007e4a65cb10047c89c`. It then builds the Python distributions and runs their actual installed consumers. The stdlib guide names Agda 2.6.4/2.6.4.1, so 2.6.4.3 compatibility was tested rather than assumed.[1] The [4 November 2026 verified result](pilots/native-conformance-result-2026-11-04.md) records passing builtin and `Function.Base` profiles in both installed consumers, exact compiler subjects and measured timing limits. This is observed conformance for those operations/profiles, not every stdlib module or the live backend binary.

The compiler's source lists GHC 9.4.8 among tested versions and bounds its custom Setup Cabal library below 3.11.[2] The workflow uses GHC 9.4.8 and cabal-install 3.10.3.0; an upstream report describes a Cabal 3.12 installation regression for this Agda release.[3] It constrains Happy below 2 and builds with `-O1`, without claiming the resulting executable or timings match the deployed backend build. Exact source pins do not fix all transitive Hackage dependencies. The direct HTTPS Hackage route disables secure-index mode to avoid obsolete mirror availability problems; it is not a trust-preserved build closure.

Reports and complete native artifacts are always uploaded when available. Workflow setup failure is not a protocol conformance failure, and a required run that does not reach its cases is not a pass. CI artifact retention is 30 days. The report is unsigned producer data, not a new evidence certificate; existing semantic verifiers establish each retained artifact's internal bindings and outcomes, not producer authenticity or live freshness.

## References

[1]: https://raw.githubusercontent.com/agda/agda-stdlib/2b8fff10f4033b91a6df4007e4a65cb10047c89c/doc/installation-guide.md "Pinned stdlib v2.0 installation guide"
[2]: https://raw.githubusercontent.com/agda/agda/714c7d2c76c5ffda3180e95c28669259f0dc5b5c/Agda.cabal "Pinned Agda 2.6.4.3 source build metadata"
[3]: https://github.com/agda/agda/issues/7401 "Agda Cabal 3.12 installation regression report"
