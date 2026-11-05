# Alpha distribution and support contract

`0.1.0a2` is the second bounded alpha of `agda-evidence`, not a stable API, public proving service or finished research platform. Package, CLI and distribution metadata derive their version from `agda_evidence.__version__`. Package releases do not rename the existing artifact formats or strengthen their assurance.

The immutable [`v0.1.0a1` release](https://github.com/Nokidme/agda-evidence/releases/tag/v0.1.0a1) and its [historical support guide](https://github.com/Nokidme/agda-evidence/blob/v0.1.0a1/docs/alpha-release.md) remain unchanged. First-alpha claims must not be inferred from this updated second-alpha guide. Exact release commit, CI run IDs, artifact checksums and actual observed compiler results belong in each release's notes.

## What changed since a1

The second alpha adds explicit one-dependency source composition for unfinished clients and the opt-in `SourceResearchWorkspace` API version 2: source-pinned goal listing/context, non-filling expression trials, lexical dependency discovery and complete current/stale/unknown envelope access. Dependency source, compiler/resolution and exact bundle pins are frozen at host admission; requests cannot repin or provision dependencies.

It also reduces duplicate pure validation, fixes the separate file-hash/text-read indexing race, and reuses bounded immutable lexical fragments per workspace/generation. Complete live source/compiler/bundle observations, exact byte checks, aggregate index validation and independent catalog provenance remain. Generation changes invalidate reuse; old work cannot populate a new epoch. [Measured scan reuse](pilots/discovery-reuse-result-2026-11-05.md) eliminated repeated lexical scans but made warm dependency/mixed searches approximately 3% slower in a small sample because of added correctness checks. This release makes no overall search latency improvement or SLA claim.

## Distribution contents

The wheel includes Python modules, license and **13 canonical JSON schemas**. The source archive additionally includes contract/pilot documentation, examples, tests and reusable scripts. Neither includes a compiler, dependency checkout, credentials or prior pilot evidence. No runtime Python dependencies beyond Python 3.11+ are declared. Source builds may download declared build tools; this is not an offline build or dependency-replay guarantee.

Read installed schemas through Python resources rather than assuming a checkout exists:

```python
import json
from importlib.resources import files
schema = json.loads(
    files("agda_evidence.schemas")
    .joinpath("source-observation-v1.schema.json")
    .read_text(encoding="utf-8")
)
```

Export/register the entire schema family together when resolving relative references. Restrict validation to local resources to avoid accidental network retrieval. Structural JSON Schema validation is not equivalent to the built-in semantic identity/cross-binding verifiers. External JSON Schema tooling remains optional.

## Bounded support levels

| Area | Second-alpha scope |
|---|---|
| Python | CI targets 3.11 and 3.12. Metadata permits newer versions but does not establish a wider tested matrix. |
| Distribution installs | Fresh wheel and source installs on Ubuntu 24.04 and Windows, outside the checkout, with installed-module/CLI versions, resources and non-native workflows checked. |
| POSIX native interaction | Separate installed-artifact native CI uses the actual separately installed `agda-bin`; release notes record its version. Source/goal/context/candidate operations are native acceptance checks, not proof completion. |
| Agda 2.6.4.3 | Release gate tests the **same ordinary-CI wheel/source bytes** with separately provisioned exact compiler source `714c7d2c76c5ffda3180e95c28669259f0dc5b5c`, builtin and stdlib v2.0 `Function.Base` profiles. Each consumer must pass all 21 finite conformance cases; this covers ordinary research goal/trial behavior and source-aware sessions, not every adapter/module/version. |
| Source dependency | Exactly one explicit pinned native source tree with declared includes; builtin fixture and stdlib `Function.Base` profiles are finite examples. Existing Agda 2.6.3/stdlib v1.7.3 equality pilot remains a separate observed profile. No transitive solving or implicit library resolution. |
| Agda 2.8.0 | Prior pinned stdlib pilot observed top-level type inference. It did not establish all goal/candidate/client/source operations on 2.8.0. See [that result](pilots/checker-result-2026-11-02.md). |
| Windows/macOS | Windows installation and non-native CLI behavior are checked, **not Windows native interaction**. Native captures are POSIX-only; macOS is not a tested alpha platform. |
| Nix | Manual project pilots capture visible partial Nix resolution and explicit native project gates. Generic interaction/source adapters do not activate Nix dependency environments. |
| Live AgdaLab | Not deployed or established by library release tests. The editor host owns authorization, source materialization/revision notifications, process/filesystem/network isolation, limits and runtime-profile acceptance. Exact source/version conformance does not prove live binary equivalence or resolve the larger `Data.Nat.Base` timeout. |

A green job describes its recorded environment and executed cases, not universal support. Fake protocol fixtures test parsing/errors; they do not replace actual compiler checks. The `py3-none-any` wheel tag is not native platform/compiler compatibility evidence.

## Compatibility and assurance

The original research facade retains API version 1 and its workspace subject meanings. Source-aware requests must explicitly use the separate version 2 facade/schemas; no automatic upgrade occurs. The three added schemas are `source-observation-v1`, `source-research-request-v2` and `source-research-response-v2`; the ten a1 schemas remain byte-for-byte unchanged during stabilization. Native bundle/type/client/goal/candidate/index/aggregate formats and their semantics are not renamed.

Stable-input indexing remains deterministic; racy second reads and stale supplied whole-root snapshots are intentionally rejected more strictly. Lexical names are not checked declaration origins, exports, scope or candidate usability. An API `ok` can contain a native rejection. Positive candidates mean **contextual-elaboration-only**, not residual-obligation freedom or proof completion. Retained evidence is not live freshness or producer authentication. Host history remains bounded, session-local, in-memory and non-durable.

First-alpha-format retained artifacts are verified offline as a release acceptance check. This is representative backward-reader coverage, not all possible historical data or a claim that an a1 reader understands the new source envelope/API.

## Artifact installation and content checks

Use a fresh external distribution directory:

```sh
python -m pip install build twine
python -m build --outdir /tmp/agda-alpha-dist
python -m twine check /tmp/agda-alpha-dist/*.whl /tmp/agda-alpha-dist/*.tar.gz
(cd /tmp/agda-alpha-dist && sha256sum *.whl *.tar.gz > SHA256SUMS)
python scripts/check-release-inputs.py distributions \
  --dist-dir /tmp/agda-alpha-dist --repository-root . --expected-version 0.1.0a2
python scripts/check-distributions.py \
  --dist-dir /tmp/agda-alpha-dist --smoke-script scripts/package-smoke.py
```

Add `--agda-bin /absolute/path/to/agda` to installed smoke checks on a supported POSIX host with an already provisioned compiler. Default packaging fixtures use an explicitly probe-only fake or unavailable compiler and Python check commands; those passes are **not Agda proof checks**.

The installed-artifact runner creates separate wheel/source environments, removes source-path overrides and invokes isolated Python from external consumer directories. It checks import/CLI/distribution versions, schema/reference resources, capture/index/catalog/aggregate behavior and, when enabled, actual goal/context/candidate/source session acceptance. Source-tree editable-install tests alone cannot establish built-package contents.

Release-input checks compare exact metadata/version, no-runtime-dependency declarations, checksum map, safe archive contents and canonical source/module/schema bytes against the selected repository checkout. They read archives without executing or extracting their contents. These checks detect unintended contents or mismatches; they are not security attestations or signatures.

## Exact-artifact release procedure

1. Commit the final candidate version, documentation and acceptance checks. Run the complete ordinary eight-job CI matrix at that exact commit, including the installed native lane. Do not tag an untested candidate.
2. Dispatch `native-conformance.yml` **at the same commit/ref**, supplying `ci_run_id` for that completed successful ordinary CI run. The workflow requires matching repository/head-repository, commit, CI workflow path and push event; missing/wrong/failed runs are rejected before artifact download. It downloads `alpha-distributions-<commit>` rather than rebuilding in release mode.
3. Validate those downloaded wheel/source/checksum bytes against the candidate checkout. Run fresh installed builtin and explicit stdlib-function conformance for both artifacts with exact Agda 2.6.4.3, plus installed repeated-discovery acceptance. Required failures cannot be skipped into a green release gate. Default developer mode still builds locally and runs its serialized old/new diagnostic comparisons.
4. Download the ordinary CI artifacts and release-mode native artifact copies. Recompute checksums and confirm they are **identical**. Independently verify complete retained native records, requests/responses, source/bundle/index pins and expected rejected outcomes offline. Test representative retained a1-format evidence with the candidate installed package.
5. Inspect contents and release notes for actual matrix/version/profile limits. Attach **those tested** wheel/source files and `SHA256SUMS` to GitHub prerelease `v0.1.0a2` at the exact green candidate commit. Never rebuild after testing and describe the new bytes as verified. Preserve the existing a1 tag/assets. This does not publish to PyPI.
6. Download the published assets, compare their hashes/bytes with the tested inputs and record final release validation.

CI artifacts expire after 30 days. GitHub release attachments provide durable distribution downloads subject to repository lifecycle; detailed CI evidence is not automatically a permanent mirrored proof bundle. Checksums detect byte differences against supplied values, not producer authenticity. A release-input JSON report is a diagnostic sidecar, not a new evidence certificate.

## Deliberately deferred

Preserved dependency closure/offline replay, export/declaration identity graphs, residual-obligation-free candidate checking, untrusted execution sandboxing, durable multi-user collaboration/history and autonomous agents remain outside this alpha. No silent proof/source edits, import insertion, package solving or deadline relaxation is added by stabilization. The authorized original AgdaLab task owns live editor integration.

### CI input admission

Release input admission requires **all eight expected jobs** to be completed successfully: both Python source-test lanes, distribution construction, four Linux/Windows installed-package lanes, and the native installed-package lane. A skipped, missing, duplicated, failed or wrong-run job is not sufficient. Artifact admission also requires exactly one nonexpired matching distribution artifact bound to the same run/repository/commit; ambiguous or expired downloads are not substituted from another run.

### Source archive test fixtures

The source archive also includes the explicitly public `.github/workflows/*.yml` fixtures used by its workflow regression tests. It does not include Git history or private account/configuration files. Release content checks compare these workflow bytes with the selected checkout, so shipped tests are not missing their repository-local inputs.
