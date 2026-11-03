# Pinned stdlib source workflow result — 3 November 2026

The one-dependency source adapter was implemented in [commit 060997c](https://github.com/Nokidme/agda-evidence/commit/060997c64ae5ac0cd5333e45368a8c9ca5dd904a) as unreleased `0.1.0a2.dev0` development. The published `v0.1.0a1` tag and assets remain unchanged. This result establishes actual unfinished-client goal work with one explicit stdlib source tree, not a dependency closure or live AgdaLab editor integration.

The remote [native source pilot run 41707939568](https://github.com/Nokidme/agda-evidence/actions/runs/41707939568) completed successfully on Ubuntu 24.04 with recorded native **Agda 2.6.3**. The workflow separately provisioned stdlib **v1.7.3**, fixed commit `0817da6877aa045932221134913d8511caa78d97`. Its [installation guide](https://github.com/agda/agda-stdlib/blob/0817da6877aa045932221134913d8511caa78d97/notes/installation-guide.md) declares 2.6.3/2.6.4 compatibility. Stdlib v2.0 instead declares 2.6.4/2.6.4.1 and was not used as an assumed compatible replacement.

## Explicit native gate and source profile

The dependency bundle captured all **1,050 snapshot-visible regular files** from the pinned source checkout. Its recorded gate was:

```text
/usr/bin/agda --no-libraries --ignore-interfaces --safe -i src
  src/Relation/Binary/PropositionalEquality/Core.agda
```

It passed with exit code zero, with the recorded scope “Explicit safe equality Core module check; not a whole-library gate.” Capturing the whole source snapshot does not turn this module check into a complete stdlib gate. Dependency evidence did not require a lexical declaration index.

The client fixture already imported `Data.Nat.Base` and `Relation.Binary.PropositionalEquality.Core`; the latter supplied `_≡_`, `sym` and `refl`. The goal was `reverseEquality : (m n : ℕ) → m ≡ n → n ≡ m`, with a hole under `m`, `n` and `p`. Workspace includes were exactly `[".", "client", "library/src"]`, anchored to the staged workspace. Implicit library files remained disabled, and no import/source edits were made.

The first local unsuppressed load was correctly `load-blocked` by stdlib indexed-match/Cubical-compatibility warnings. The pinned stdlib's own manifest declares `--warning=noUnsupportedIndexedMatch`; the supported client fixtures therefore declare that exact specific setting in their source `OPTIONS` pragma alongside `--safe`. The adapter neither infers manifest flags nor suppresses all warnings. A separate `Warnings.agda` fixture without that setting remains blocked. Source digests retain the explicit pragma, and no Cubical transport-computation compatibility is claimed.

## Native observations

Seven complete envelopes were retained and verified:

- `listing.source.json`: `listed`, one goal with scalar ID `0`, displayed type `n ≡ m`, and the original source range.
- `context.source.json`: `inspected`, retaining structured local bindings and the exact accepted prior source/native listing.
- `symmetry.source.json`: `elaborated` for explicit `sym p`, with `contextual-elaboration-only` assurance and `postflightUnchanged: true`.
- `wrong-type.source.json`: `query-error` for `refl`; arbitrary `m` and `n` are not definitionally equal.
- `no-proof-import-listing.source.json`: `listed` for a client which imports equality but not `sym`.
- `no-proof-import.source.json`: `query-error` for `sym p`; making sources available did not insert an import or place the missing name in scope.
- `unsuppressed-warnings.source.json`: `load-blocked`; only startup/load were recorded, with no selected query issued.

A separate ordinary goal record without the dependency mount was `load-error`. Adding an unrelated regular file to a **private dependency copy** invalidated its full source pin and rejected the saved selection. The workflow checked original client and dependency source identities remained unchanged; the private stale copy was removed. Temporary source copying is not a sandbox for every compiler/reflection side effect, nor an atomic guard against edit-and-revert races.

## Exact verified identities

```text
clientSourceId:      sha256:ba89ab617e120653dff71c0f2f8f424e81d32a0a1c1128737b6c7879fc6eef6f
dependencySourceId:  sha256:408cd9cf9dea398dc8595b5f032b0e51c3fb3db53fcc1c2a108701cb584e546c
dependencyBundleId:  sha256:8780840fa316a292d794860dfa2c38168271e05110ae45826d3d5a27e0c75a45
workspaceSourceId:   sha256:984178ebe70ad7f36cee9615dae1fb089a14fdf0f59aeace0726191df010b367
compilerBinary:      sha256:852806142a15951f667df303c73cfce5f4123218ce6e1f1b29acaddc242af00d

listing:             sha256:52a5f38c87088e19b5c587196a494a75c0e1ae769bcfa9efef1ad5bd2dc96496
context:             sha256:cdac15849211938487a351607df8163eaa3e1b4a461c55620754c220f575cf7f
symmetry:            sha256:bc0a5f25c12af4833c5e478c90c756c279a79473e962fe83b7a2e748b7846d8a
wrong-type:          sha256:81caadbcef10bb626dee0a978c7cddb2a43b8aee82bb99b5d42748997107e3d2
no-import listing:   sha256:df8fc599d0c5d9d60594e9ee8928d875cf976fcfdbabab07cd5aceaabf91b32b
no-import trial:     sha256:eeafe836ffaa3f64ed3e5fe26f940199e7ad0bf5f3aa808538b60a8b038bab7c
unsuppressed load:   sha256:5c4b985b5c905e95a800bf33024722756c32699770b2b8f00f5eb65800348039
```

These are time-specific complete source-envelope IDs, not replacements for the native observation IDs or the dependency source subject. Each record retains its own full native resolution and query diagnostics. The source and workspace manifests matched the original checked-in fixture and independently retained stdlib checkout.

## Independent verification and CI

The uploaded artifact was downloaded into the development environment. All seven source envelopes passed semantic offline verification and Draft 2020-12 schema validation with an explicit local `referencing.Registry`; unregistered retrieval raised an error rather than fetching a remote schema. Subprocess `run` and `Popen` were blocked during verification. The verifier also checked exact canonical equality between each selected envelope's prior source listing and its unchanged nested native listing, dependency bundle integrity, fixture/dependency source subjects, explicit assurance and unmounted failure. This verifies retained record consistency, not producer authentication or a rerun of the compiler.

All **158 local regression tests passed**, including the real native tests. The [development CI run 41707885618](https://github.com/Nokidme/agda-evidence/actions/runs/41707885618) passed eight jobs. Its compiler-free Python 3.11/3.12 source jobs discovered 158 tests and skipped 12 native tests. Separate installed-artifact jobs tested wheel and source-archive installs on Linux/Windows with both Python versions. The Ubuntu native artifact lane actually exercised the installed source CLI with a tiny unindexed pinned dependency under Agda 2.6.3 for both artifacts, alongside ordinary goal tests. All **11 schema resources** and their relative references were present. Windows artifact installation does not establish native source capture support there; capture remains POSIX-only.

## Reproduce

To verify retained artifacts while they are available:

```sh
gh run download 41707939568 --repo Nokidme/agda-evidence \
  --name native-source-pilot-060997c64ae5ac0cd5333e45368a8c9ca5dd904a \
  --dir /tmp/source-pilot-download

agda-evidence verify /tmp/source-pilot-download/dependency.evidence
agda-evidence goals verify /tmp/source-pilot-download/unmounted.goal.json
for record in /tmp/source-pilot-download/*.source.json; do
  agda-evidence source verify "$record"
done
```

Downloads require network/GitHub access; verification commands do not rerun Agda. CI retains these artifacts for 30 days, so this is not a permanent replay archive. To execute the workflow again, provision the exact source checkout and compatible native compiler yourself and run `scripts/sources-pilot.py` with a fresh external output directory, or dispatch the maintained manual source pilot. The [source contract](../sources.md) describes its explicit configuration and boundaries.

Existing goal/candidate/type/client-v1 formats remain unchanged. The ordinary `ResearchWorkspace` has not silently gained dependency mounts. The next integration step is a separately explicit, source-aware host facade which extends freshness to dependency subjects; multi-dependency solving, source archives, offline replay and obligation-free proof completion remain outside this result.
