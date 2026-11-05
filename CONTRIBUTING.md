# Contributing

`agda-evidence` records evidence for a project’s declared check. It must not make a stronger claim than the project’s checker supports.

Before proposing a feature, open an issue describing the project style it supports and the exact artifact or compatibility problem it addresses. Changes to the bundle schema require a versioned proposal with at least one fixture and a migration or compatibility statement.

The reference CLI is deliberately dependency-light. Keep the core portable and use optional adapters rather than hard-coding one build manager, hosted platform, or proof assistant client. Never add behavior that silently chooses a check command, downloads dependencies, runs a shell, or changes a project source tree.

Run the tests with:

```sh
python -m unittest discover -s tests -v
```

Packaging changes must also pass clean wheel and source-archive installs outside the checkout with `scripts/check-distributions.py` and `scripts/package-smoke.py`; see [the alpha release guide](docs/alpha-release.md). Keep schemas canonical under `schemas/`: setuptools maps that directory to the installed `agda_evidence.schemas` resource package, so do not maintain a second copied schema family. The package version constant in `src/agda_evidence/__init__.py` supplies distribution and CLI versions. Native compiler tests and non-native distribution tests make different claims; record the actual compiler/version and preserve that distinction.

Contributions are licensed under the Apache License 2.0.

For a release, also validate the exact CI artifact inputs with `scripts/check-release-inputs.py`. The manual native workflow's `ci_run_id` mode must consume the successful same-commit eight-job CI distributions, not a silently rebuilt replacement. Validate representative retained older-format artifacts with the candidate-installed package offline before claiming backward-reader acceptance. The [release guide](docs/alpha-release.md) distinguishes these checks from runtime evidence certificates, native platform support and editor deployment.
