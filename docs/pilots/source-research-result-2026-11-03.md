# Source-aware research API result — 3 November 2026

`SourceResearchWorkspace` API version 2 was implemented in [commit 0f2efca](https://github.com/Nokidme/agda-evidence/commit/0f2efcabc61415e56a80dd3c77386d67c4c0f717). The [remote native stdlib session pilot 41713148821](https://github.com/Nokidme/agda-evidence/actions/runs/41713148821) and all eight jobs of [implementation CI 41713145094](https://github.com/Nokidme/agda-evidence/actions/runs/41713145094) passed. This is unreleased `0.1.0a2.dev0` development, not a second published alpha, running service or editor deployment. The published `v0.1.0a1` tag/assets and ordinary `ResearchWorkspace` version 1 remain unchanged.

## Native source profile

The pilot ran on Ubuntu 24.04 with recorded **Agda 2.6.3** and separately provisioned stdlib **v1.7.3** commit `0817da6877aa045932221134913d8511caa78d97`. The original supplied checkout and committed examples stayed unchanged. All changes for freshness probes were made to disposable external copies.

The source snapshot included 1,050 regular dependency files. Its explicit gate was the safe `Relation.Binary.PropositionalEquality.Core` module check with `--no-libraries --ignore-interfaces -i src`; it was not a whole-stdlib gate. Supported clients retained the previously documented explicit `--warning=noUnsupportedIndexedMatch` source pragma alongside `--safe`, matching that release's declared manifest compatibility setting without activating library files or weakening the adapter's conservative load policy. See the [source pilot result](sources-result-2026-11-03.md) for that warning boundary and source/compiler compatibility evidence.

The goal was `n ≡ m` under `m n : ℕ` and `p : m ≡ n`. The native listing supplied scalar ID `0` and its source range; selected requests used the actual listing, not a fallback ID. The source policy was `one-dependency-source-copy-v1` with client includes `["."]`, dependency includes `["src"]`, and `safe: true` for the API composition identity.

## Verified session workflow

The archived log contains **30 API version 2 request/response exchanges** and five independently exported complete `source-observation-v1` envelopes:

| Record | Native outcome | Meaning |
| --- | --- | --- |
| `listing.source.json` | `listed` | One real unfinished goal under the bound stdlib source profile. |
| `context.source.json` | `inspected` | Structured local type/context, with the exact prior source/native listing retained. |
| `symmetry.source.json` | `elaborated` | Explicit `sym p`, contextual elaboration only, with unchanged restored goal postflight. |
| `wrong-type.source.json` | `query-error` | `refl` did not establish equality of arbitrary `m` and `n`. |
| `catalog-not-mounted.source.json` | `query-error` | Discovering `Example.identity` did not mount/import that independent catalog library. |

Failed native trials remained valid API `ok` responses with failed native outcomes, not green proof results. The positive trial retained `contextual-elaboration-only` assurance and `postflightUnchanged: true`; no source hole was filled.

Project lexical discovery returned explicit project evidence. Dependency discovery found `Relation.Binary.PropositionalEquality.Core.sym` with `origin: dependency`, source/index and the actual bound check's bundle/resolution/attestation/command/scope/outcome provenance. Its scope remained `not-established`, usability `not-tested`, and contextual ranking false. An independent catalog found `Example.identity`, but the corresponding native expression still failed. Search provenance was not silently interpreted as selected-declaration identity or importability.

## Frozen admission and history

The constructor established a baseline and froze dependency source/resolution/bundle pins. Dirty then clean edit notifications invalidated the generation even without a final source-byte change; old selections were stale and history was not reactivated.

Adding an unrelated file to the private dependency copy produced known changed subjects and `dependencyMatchesPin: false`. A fresh revision did not bypass admission: new research returned `error / dependency-changed`. The exact earlier positive artifact remained retrievable as **stale** history. An explicitly outdated non-null read revision returned stale rather than ignoring its precondition.

Temporarily moving required bundle evidence out of its configured location made complete freshness unobservable. A null-revision history read returned the same full artifact as **unknown**, with null current workspace and null pin-match state. A revision-bound read instead failed `freshness-unavailable`; it did not satisfy the precondition from cached pins.

A separately recaptured bundle preserved source and native resolution but changed exact `bundleId`. The existing instance refused it and did not auto-update its frozen pins. An explicitly constructed new host instance admitted the separately captured evidence, while rejecting the old opaque record handle as `record-unavailable`. Exported full artifacts retain their original offline evidence semantics; a new session does not inherit old handles.

The independent log check found five current, two stale and one unknown successful record reads. The remaining exchanges include diagnostic status, selection/search/trial requests, refused research, strict reads and explicit rebinding/cross-session checks. These counts describe this finite fixture, not a production service guarantee.

## Exact verified subjects and envelopes

```text
clientSourceId:       sha256:ba89ab617e120653dff71c0f2f8f424e81d32a0a1c1128737b6c7879fc6eef6f
clientResolutionId:   sha256:35ef6face5421d69fe20ce114f546a43e44a9250bf530792be266eada270afa0
dependencySourceId:   sha256:408cd9cf9dea398dc8595b5f032b0e51c3fb3db53fcc1c2a108701cb584e546c
dependencyResolution: sha256:976e7334a7a9485bcbcfea106eacb463b6160e28be1ef80cee5edb785aa46841
dependencyBundleId:   sha256:58be3c421c2aa9a5692f775db8c5b6c3607a1bd74ef6e2679d7e2ebb973ae333
compositionId:        sha256:5dfb8cde201113f5f17727977f7927cf6780a6e01a5fc13daaf4fd1322e19a67
compilerBinary:       sha256:852806142a15951f667df303c73cfce5f4123218ce6e1f1b29acaddc242af00d

listing envelope:     sha256:c8e59273b872cc45e0298717556f4c00b133933ac1426fc01eedf7d3be266a23
context envelope:     sha256:3033b8f73a61f909fe763837bad05641f295fd091466dfa893bac7111e07dc30
symmetry envelope:    sha256:6b5fece530cb37f27a1afba0439f104810966de77b9b5715be359dd8b6f7ab6e
wrong-type envelope:  sha256:a6b41381939789c497d8de78b81ecd852e0ce91d02f662425b46b6910cfe51e0
unmounted envelope:   sha256:e147da7cdde455df54279b247c38245e8d51517ad121659d16a33a90d5b08575
```

The original client and dependency subjects are not substituted for the temporary composed workspace subjects. Native goal/candidate IDs and formats are unchanged inside each source envelope. Wire status, session generations and opaque handles are not additional evidence certificates.

## Independent verification and distribution checks

The remote artifact was downloaded and checked outside the producing workflow. Every v2 request/response passed its separate schema. All five source envelopes and every artifact returned through successful history reads passed semantic verification plus schema validation; each selected envelope's prior source listing and native listing matched the exported leaf exactly in canonical JSON. Source subjects matched the unchanged fixture and independently retained stdlib checkout. Dependency hit provenance matched the complete embedded attestation. The retained original, recaptured and catalog bundles verified independently.

Subprocess `run` and `Popen` were blocked during those offline checks. A local `referencing.Registry` held all schemas; unregistered retrieval raised rather than fetching a remote resource. These checks establish retained record consistency, not authentication of the producer, a live freshness recheck, or an offline rerun of Agda.

All **182 local tests passed**. The compiler-free Python 3.11 and 3.12 CI source jobs discovered 182 tests with 16 native-fixture-dependent skips. Separate artifact jobs tested fresh wheel/source installs on Linux/Windows for both Python versions. The Ubuntu native installed-artifact lane actually exercised source CLI and source-aware API listing/trial/retrieval/frozen-pin/stale-history behavior under Agda 2.6.3 for both artifacts. All **13 installed schema resources** were present. Native construction/capture remains POSIX-only; Windows package installation is not native Windows Agda support.

Independent tests also cover pre-capture expected-subject races, concurrent coherent status publication, nonblocking busy responses, source failures and store failures followed by freshness checks, immutable detached records, count/byte eviction budgets, unknown/cross-session lookups before probes and preserved v1 behavior.

## Reproduce and next boundary

While the workflow artifact is retained:

```sh
gh run download 41713148821 --repo Nokidme/agda-evidence \
  --name native-source-research-pilot-0f2efcabc61415e56a80dd3c77386d67c4c0f717 \
  --dir /tmp/source-research-pilot

for record in /tmp/source-research-pilot/*.source.json; do
  agda-evidence source verify "$record"
done
agda-evidence verify /tmp/source-research-pilot/dependency.evidence
agda-evidence verify /tmp/source-research-pilot/replacement.evidence
```

Downloading needs GitHub/network access; semantic verification does not launch Agda. CI artifact retention is 30 days, not permanent preservation. To run again, provision a compatible native compiler and exact dependency checkout separately, then run `scripts/source-research-pilot.py` with a fresh external output directory or dispatch its maintained manual workflow. The [source-aware API guide](../source-research-api.md) describes binding and wire behavior.

Full source/environment stabilization intentionally repeats snapshots and native metadata probes. Its native timeout does not bound overall copying, discovery, history serialization or transport latency. The host still owns global request budgets, staging/edit notifications, authenticated persistence, worker/process/filesystem/network isolation and any performance optimization. Hash observation is not atomic and cannot detect all unnotified edit-and-revert races.

Before editor adoption, validate the profile against AgdaLab's actual toolchain and connect its authorized host to explicit v2 routing, materialized revisions, dependency notifications and current/pin-admission/native-outcome/history display. No AgdaLab application code or deployment was changed by this result.
