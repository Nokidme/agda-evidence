# Contributing

`agda-evidence` records evidence for a project’s declared check. It must not make a stronger claim than the project’s checker supports.

Before proposing a feature, open an issue describing the project style it supports and the exact artifact or compatibility problem it addresses. Changes to the bundle schema require a versioned proposal with at least one fixture and a migration or compatibility statement.

The reference CLI is deliberately dependency-light. Keep the core portable and use optional adapters rather than hard-coding one build manager, hosted platform, or proof assistant client. Never add behavior that silently chooses a check command, downloads dependencies, runs a shell, or changes a project source tree.

Run the tests with:

```sh
python -m unittest discover -s tests -v
```

Contributions are licensed under the Apache License 2.0.
