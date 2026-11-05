# Check-preserving performance work

This development increment optimizes two pure validation paths, not the native compiler or live input-observation contract. It adds finite profiling and installed-wheel comparison tools. It does not change a wire/evidence format, source-composition policy, accepted native diagnostics, native timeout, interface behavior, public API or published alpha release.

## What changes, and what does not

`_digest_identifier` still checks every supplied identifier for the exact `sha256:` prefix followed by 64 lowercase ASCII hex characters. A compiled regular expression with `fullmatch` replaces its Python character generator. Uppercase, Unicode lookalikes, wrong lengths, suffixes, control characters and trailing newlines remain rejected; error categories and returned strings are unchanged. Differential tests compare against the prior validator, including 2,500 deterministic mutations. There is no identifier cache or bypass of validation.

Previously the source consumer immediately called a full generic verifier twice on the exact same parsed manifest/components: once in `load_verified_bundle`, then again in the source-specific evidence validator. The new private `_load_source_evidence` consumes the exact verified objects and applies the existing stricter source-profile requirements once, without repeating the generic verifier. Those additional requirements remain: enhanced identifiers/subjects, diagnostic identity, canonical/safe source records and timestamp, available partial non-Nix native compiler, resolution identity and root-manifest/snapshot binding.

The untrusted embedded-evidence validator remains a **full** verifier. Offline loading, final envelopes, prior listings and store validation still use it. A verified in-memory result is not persistent authority for later filesystem reads or mutated dictionaries. No trust boolean, object-identity cache, mtime/size cache or dependency repinning is introduced.

Each source-facade observation still makes two independent complete capture passes. Both reread required source/bundle bytes and observe client/dependency native contexts separately. Compiler SHA-256 reads, version/app-directory probes, root-specific manifest/registry observation, containment checks, staged-source checks, before/after native guards, notified-generation invalidation and serialized publication remain. Changes between passes or requests still invalidate current evidence; missing required evidence still yields unknown history rather than a guess from cached subjects.

## Why these paths

A finite profile of the unchanged source facade on native Agda 2.6.3 with a real pinned stdlib v1.7.3 `Function.Base` profile passed all 21 conformance cases. It identified millions of digest-identifier checks and immediate duplicate generic evidence validation as avoidable Python work. Full-byte snapshot and compiler observation remain substantial, necessary work.

`cProfile` instruments Python calls and strongly amplifies generator-heavy paths. Its cumulative spans overlap and include caller work; they cannot be added to obtain a total or equated with native CPU. A reduction in instrumented time or a hot-loop microbenchmark is not a user-visible speedup. Use the separate unprofiled installed-wheel comparison for that narrower observation.

## Finite profiler

```sh
python scripts/profile-native-conformance.py \
  --runner scripts/native-conformance.py --agda-bin /absolute/path/to/agda \
  --expected-version 2.6.4.3 --profile stdlib-function \
  --dependency-root /host/provisioned/stdlib-2.0 --timeout-seconds 20 \
  --output /tmp/agda-profile-new-run
```

The profiler runs the existing finite conformance suite, retaining its complete native artifacts plus `conformance.pstats` and `profile.json`. It does not install/fetch a compiler or library and does not skip verification to obtain a profile. Use a new external output directory. To profile an actual installed consumer, invoke this script with that consumer's isolated `python -I`; no repository source-path injection is performed by the script.

Profile timing is explicitly marked instrumented. The existing conformance sidecars separately label monotonic host-call time and coarse recorded inner execution spans; the [conformance guide](native-conformance.md) explains why neither is compiler CPU or an end-to-end timeout.

## Matched installed-wheel comparison

```sh
python scripts/compare-native-conformance.py \
  --before-wheel /tmp/before/agda_evidence-0.1.0a2.dev0-py3-none-any.whl \
  --after-wheel /tmp/after/agda_evidence-0.1.0a2.dev0-py3-none-any.whl \
  --runner scripts/native-conformance.py --agda-bin /absolute/path/to/agda \
  --expected-version 2.6.4.3 --profile stdlib-function \
  --dependency-root /host/provisioned/stdlib-2.0 --repetitions 2 \
  --output /tmp/agda-compare-new-run
```

The old and new wheels may share the development version string, so the summary records each actual wheel digest. Installations use separate fresh virtual environments, no runtime dependencies/index and isolated `-I` interpreters outside the repository. The same finite runner, compiler and dependency profile are applied to both wheels. Two repetitions run **before/after, then after/before**, retaining all logs, native artifacts, raw host-call samples and median diagnostic summaries. The repetition count is bounded to 1–3, not an unattended benchmark service. Every run retains the same 20-second native budget and must pass conformance; no speed threshold is used to excuse correctness failure.

OS/filesystem warming and scheduling effects remain. Two alternating-order repetitions are not statistical significance, percentiles, production throughput, a cold-machine benchmark or an SLA. Grouped host-call medians may contain multiple calls with the same case/operation label; the source listing/context/accepted-trial groups each contain one measured call per run. Raw samples are retained to make that distinction inspectable. Negative/unknown/stale cases retain their actual native and API outcomes.

The manual exact Agda 2.6.4.3 workflow also builds the fixed pre-optimization commit `c1f3a58b772619be561e58b6ea2d7d509e5db4ec` in an external archive checkout and runs the comparison, in addition to current fresh wheel/source conformance. It separately provisions exact compiler and stdlib source commits. Exact pins do not preserve all build dependencies or establish equivalence to AgdaLab's deployed binary. The profiler and comparison do not authorize or change production execution.

## Verification discipline

Structural regression tests spy on verified reads and generic verification calls, and cover immediate captured-object handoff, detached embedded mutation, source-profile violations, changes between capture passes, valid bundle replacement and same-length tampering with restored mtimes. Existing source/compiler/publication race and offline tamper suites remain required. A faster path is acceptable only if those boundaries and all native conformance cases continue to pass.

Report actual installed-artifact results and precise source/compiler subjects before asserting observed improvement. Retained diagnostic timings are unsigned producer data, not new evidence certificates. Existing artifact validators establish internal bindings and outcome semantics, not producer authenticity, permanent freshness or performance guarantees.

## Verified result

The [5 November 2026 result](pilots/performance-result-2026-11-05.md) records the exact old/new wheels and pinned compiler/source subjects, serialized alternating-order raw samples, unchanged read/probe counts and independent offline checks. It observed modest lower median host-call times while preserving all mandatory conformance cases; it does not claim production equivalence, statistical significance or a fix for the larger editor timeout.
