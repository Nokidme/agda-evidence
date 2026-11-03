# Alpha distribution and support contract

`0.1.0a1` is the first bounded alpha of `agda-evidence`, not a stable API or a finished theorem-proving platform. Package, CLI and distribution metadata derive their version from `agda_evidence.__version__`. Artifact format version names remain unchanged: advancing the package version does not rename a v1 evidence format or strengthen its assurance.

## Distribution contents

The wheel includes the Python modules, license and all ten versioned JSON schemas. The source archive additionally includes contract/pilot documentation, example sources, tests and reusable pilot scripts. No compiler, libraries, source checkouts, credentials or prior pilot artifacts are bundled. There are no declared runtime Python dependencies beyond Python 3.11 or later. Building from source requires the declared build tools; source-install CI may download those tools. This is not an offline build or replay guarantee.

Read installed schemas through Python's resource API rather than assuming a Git checkout exists:

```python
import json
from importlib.resources import files

schema = json.loads(
    files("agda_evidence.schemas")
    .joinpath("evidence-bundle-v1.schema.json")
    .read_text(encoding="utf-8")
)
```

Several schemas use relative references to other schemas. Export the entire schema family together if a validator needs disk paths, and register local resources with that validator instead of allowing accidental network retrieval. The schemas describe structure; built-in offline verifiers additionally enforce the documented semantic identities and cross-bindings. Schema validation alone is not equivalent to evidence verification. An external JSON Schema library remains optional, not a new runtime dependency.

## Support levels

| Area | Bounded alpha claim |
| --- | --- |
| Python | CI targets 3.11 and 3.12. Metadata permits newer versions, but that is not a claim of a tested matrix beyond these versions. |
| Distribution installs | CI installs the wheel and source archive into separate fresh environments on Ubuntu 24.04 and Windows, and runs the installed-package smoke script outside the checkout. |
| Native interaction | Capture through the JSON interaction adapters is POSIX-only. The alpha's installed-artifact native smoke lane uses Ubuntu 24.04 and the separately installed `agda-bin`; its log records the actual version. Existing real native fixtures/pilots observed Agda 2.6.3. |
| Agda 2.8.0 | A pinned stdlib pilot validated top-level type inference, with exact saved compiler/source subjects. This does **not** establish every goal/candidate/client operation on 2.8.0. See [that result](pilots/checker-result-2026-11-02.md). |
| Agda 2.6.4.3 / live AgdaLab | Not established by this alpha's package tests. The actual editor integration must verify its own runtime and dependency profile. |
| Windows/macOS | Windows package installation and the dependency-light non-native CLI smoke are CI targets, not support for native Agda sessions. macOS is not a tested alpha platform. |
| Nix | Existing manual project pilots capture a visible, partial Nix resolution observation and explicit native project gates; the generic native interaction adapters do not activate Nix dependency environments. |
| Import/dependency support | The native profile uses explicit project-relative source includes and Agda builtins. The direct client adapter supports one pinned source-library pair. Catalog discovery does not mount/import libraries or establish complete dependency compatibility. |

A successful CI job is evidence for its recorded environment and operations, not an assertion that every machine/version combination works. Deterministic wire fixtures remain useful parser/error tests but do not replace native compiler checks.

## Artifact installation checks

```sh
python -m pip install build twine
python -m build --outdir /tmp/agda-alpha-dist
python -m twine check /tmp/agda-alpha-dist/*.whl /tmp/agda-alpha-dist/*.tar.gz
python scripts/check-distributions.py \
  --dist-dir /tmp/agda-alpha-dist \
  --smoke-script scripts/package-smoke.py
```

Use a fresh distribution directory. On a supported POSIX host with Agda already installed, add `--agda-bin /absolute/path/to/agda` to include native checks. The default smoke tests packaging and non-native command behavior using a probe-only fake compiler on POSIX (or an explicitly unavailable compiler on Windows) plus Python commands; neither fixture is a real Agda compiler, and a passed packaging capture must not be described as an Agda proof check.

The runner installs each artifact without runtime dependencies, removes source-path environment overrides, and invokes Python in isolated mode from a fresh external consumer directory. It checks distribution/module/CLI versions, schema resources and their local references, public adapter imports, explicit command captures, index/catalog queries, aggregates and verification. The optional native lane separately checks actual goal/context/candidate behavior and unchanged source. Ordinary source-tree tests complement these checks; they cannot prove that built artifacts include required files.

## Release procedure

1. Run source regression tests and the artifact checks. Check the full CI matrix at the exact intended release commit, including installed-artifact native results; never rely solely on a source-tree editable install.
2. Inspect the distribution contents and metadata. Confirm no private files or unintended runtime dependencies, and retain local-reference schema relationships.
3. Download the **tested** CI wheel/source archive and `SHA256SUMS`, verify those checksums locally, and attach those exact files to a GitHub prerelease tagged `v0.1.0a1` at that same commit. Do not rebuild silently after testing and label the rebuild as the verified artifact.
4. Record which tests, platforms and actual native compiler version passed in the release notes. A GitHub alpha release is not publication to PyPI; do not imply PyPI availability unless independently confirmed.

CI artifacts expire after 30 days. Attaching the checked distribution files to a GitHub release is the intended durable download path, subject to repository lifecycle. The checksum file detects accidental byte changes against its supplied values; it is not a signature or proof of producer authenticity.

## Deliberately deferred

Dependency closure preservation and offline replay, export/declaration identity graphs, residual-obligation-free candidate checking, untrusted process sandboxing, durable multi-user collaboration/history, and autonomous agents are outside this alpha. No silent proof edits, import insertion or library solving is added during stabilization. The independent AgdaLab task owns actual editor/runtime integration; feedback may justify a focused follow-up library change without expanding this release's claims.
