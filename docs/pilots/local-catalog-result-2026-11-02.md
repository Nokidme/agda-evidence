# Local multi-library catalog result — 2 November 2026

The pinned local discovery catalog was validated against two independently checked real-library artifacts. The implementation is in [commit 079f4ad](https://github.com/Nokidme/agda-evidence/commit/079f4ad5a5afa15de9745544d5c18b2325e719cb).

The indexed algebra follow-up passed in [GitHub Actions run 41491274456](https://github.com/Nokidme/agda-evidence/actions/runs/41491274456). It retained `ualib/agda-algebras` commit `c7617677f0e4233939660aa42e7fafb2f68e95e0`, the Nix resolution handoff, and the exact native gate:

```sh
nix flake check --no-write-lock-file
nix develop --no-write-lock-file --command make check
```

The workflow attached a source-bound lexical index, verified the resulting evidence, and exercised local catalog creation, pin verification, and module discovery. Its artifact was then downloaded and verified independently in the development environment. The follow-up source identity matches the [initial algebra pilot](agda-algebras-result-2026-10-30.md); resolution, attestation, and whole-bundle identities remain separate observations.

The second catalog entry used the already checked standard-library artifact from [run 41125759317](https://github.com/Nokidme/agda-evidence/actions/runs/41125759317), pinned to `agda/agda-stdlib` commit `565739a4d82b8bb47d2f15cb99178db15ca60e9b`. Both complete bundles were reverified by catalog queries.

## Discovery results

| Catalog label | Lexical candidate records | Module-kind candidate records | Recorded native gate |
| --- | ---: | ---: | --- |
| `stdlib` | 12,990 | 2,096 | Upstream generate/safe/full aggregate typecheck: passed, exit 0. |
| `algebras` | 1,732 | 740 | Native Nix Type-check library lane: passed, exit 0. |

These are lexical scanner records, not counts of unique exported modules or independently checked declarations. All existing scanner omissions and possible lexical false positives remain applicable.

A query for `--prefix Data.Nat --kind module` returned the same 42 standard-library candidates, with that entry's exact bundle, source, resolution, attestation, and index identifiers. A catalog-wide module query returned candidates from both entries while retaining separate provenance; it did not merge namespaces or choose a preferred library.

The local validation separately replaced the algebra entry's expected `sourceId` and `resolutionId` with mismatching digests. Both queries were rejected with the entry name, field, expected ID, and actual ID, even when `--library stdlib` excluded algebra from the result selection. No partial candidates were returned. This tests identity agreement, not freshness against a live source checkout.

## Exact evidence identities

### agda-algebras

```text
sourceId:      sha256:9404a28d1c7c5a70f9d055936d850daef6c7e33f13e2eb0f3792ed1eec185dca
resolutionId:  sha256:3fba429486ee15e0766402542409dd61a61978bbf87f0f08b6f0705d3f6ee591
attestationId: sha256:e745a28fda8a25e60bfbace34bd39435d82dd4018b62d43e95ec1699146b2286
indexId:       sha256:9cae222cd162f2f3daf3a72100b7975bac8ff125ca18fce9d1515bd1ce679133
bundleId:      sha256:e8c0946e45433b2e6a03926584e3de5d8a4e920fb715db46ea552b344333a60f
```

### agda-stdlib

```text
sourceId:      sha256:5a64564ab914a6af0c4b3ec06b78a469fe382f9cfe9d158f220dd2efc2cbb295
resolutionId:  sha256:0b281336d57f6ab47e043ad2393f402273d2f5679e1c59263f860085a911dd49
attestationId: sha256:7f02b1e2f9aa08b5924f890d8ae6c2c2da9c2b4178f964ec7a56c1a2fcf3af6f
indexId:       sha256:c98c01120714f2ae175128185dedcb8ea7d2a5a6fa950c3179fc40a486f12ca6
bundleId:      sha256:0906937844f33e418f7dff96074e3d0a8b58baede79d1943965894915d388760
```

## Reproduce discovery while artifacts are retained

From an installed or editable checkout of `agda-evidence`:

```sh
mkdir -p evidence/algebras evidence/stdlib

gh run download 41491274456 --repo Nokidme/agda-evidence \
  --name agda-algebras-evidence-c7617677f0e4233939660aa42e7fafb2f68e95e0 \
  --dir evidence/algebras

gh run download 41125759317 --repo Nokidme/agda-evidence \
  --name agda-stdlib-evidence-565739a4d82b8bb47d2f15cb99178db15ca60e9b \
  --dir evidence/stdlib

agda-evidence catalog create --output research.catalog.json \
  --entry algebras=evidence/algebras --entry stdlib=evidence/stdlib
agda-evidence catalog verify research.catalog.json
agda-evidence catalog query research.catalog.json --prefix Data.Nat --kind module
```

Use fresh output directories and a new catalog filename. Download requires ordinary GitHub access and network availability; catalog verification and search themselves are local, read-only operations that do not invoke Agda or rerun the original checks. This reproduces discovery over retained evidence, not source/toolchain replay. The workflows retain their artifacts for 30 days from their respective run dates.

## Test and trust boundary

The implementation passed 47 local tests, including colliding names across sources, malformed/ambiguous configuration, both pin mismatches, no-partial-output failures, legacy compatibility, symlink rejection, same-pins recapture with changed outcome, and failed/timed-out/execution-error disclosure. Independent review found a static symlink-parent plus `..` path-normalization bug in catalog creation; the fix and regression were included before publication. Ordinary [Python 3.11/3.12 CI](https://github.com/Nokidme/agda-evidence/actions/runs/41491258874) also passed.

The catalog is not a shared Agda environment. In particular, the standard-library and algebra pilots use different toolchain/library contexts; selecting both bundles does not establish dependency compatibility, installed availability, importability, or scope. No catalog-wide success badge, authenticated producer claim, complete dependency closure, preserved source archive, or offline replay guarantee follows. The [local catalog contract](../local-catalog.md) defines the exact boundary.
