# agda-evidence

`agda-evidence` creates a portable evidence bundle for an **explicit** Agda project check. A bundle captures the exact project source tree, visible Agda/library configuration, the command that ran, bounded process output, and content-addressed component digests.

It is intentionally small and local. It does not choose a build command, fetch or solve dependencies, replace Agda’s package system, provide an interactive proving server, or claim that a passed check proves informal mathematical intent.

## Status

This is a pre-alpha reference implementation of the v1 bundle contract. The core has no runtime dependencies beyond Python 3.11+.

A passed bundle means only that the **recorded explicit command** exited successfully in an isolated copy of the recorded project source. It does not claim a full dependency closure, offline replayability, all-project coverage, or structured Agda diagnostics.

## Install

For development:

```sh
python -m pip install -e .
```

Or run directly from a checkout:

```sh
PYTHONPATH=src python -m agda_evidence --help
```

## Capture a project check

Pass the intended project command after `--`. The command is executed without a shell in a temporary copy of the project, so generated files do not modify the working tree.

```sh
agda-evidence capture \
  --project-root /path/to/project \
  --output /tmp/project.evidence \
  --scope "whole-library check" \
  -- make check
```

The output directory must be new or empty and must be outside the project root. If the project needs a particular Agda executable, record it explicitly:

```sh
agda-evidence capture \
  --project-root /path/to/project \
  --output /tmp/project.evidence \
  --agda-bin /path/to/agda \
  -- agda Everything.agda
```

The reference CLI records that Agda was unavailable when it cannot run the configured binary. It can still capture an explicit command that does not require the binary, which is useful for testing the bundle contract but does not create a meaningful Agda attestation.

## Verify a bundle

```sh
agda-evidence verify /tmp/project.evidence
```

Verification recomputes every component digest and the bundle identifier. It does not rerun the check. A future replay command will be a separate feature because it must state which environment and dependency guarantees it makes.

## Bundle contents

| File | Meaning |
| --- | --- |
| `bundle.json` | Version, bundle identifier, and component-digest map. |
| `snapshot.json` | Content-addressed regular source/configuration files. |
| `resolution.json` | Visible Agda executable, project `.agda-lib` data, and available registry metadata. |
| `attestation.json` | Explicit command, declared scope, isolated-copy mode, and outcome. |
| `diagnostics.json` | Bounded process stdout/stderr; v0.1 does not claim a structured Agda parser. |
| `index-ref.json` | Optional reference to externally produced declaration-index metadata. |

Read the [v1 schema notes](docs/schema.md) before publishing a bundle. Bundle contents can include source, command arguments, and tool output; inspect them before sharing.

## Development

```sh
python -m unittest discover -s tests -v
```

The first validation target is a common contract across `agda-stdlib`, `agda-algebras`, and the Cardano formal ledger. The core will use adapters only where project-specific conventions cannot fit the generic contract.

## License

Apache-2.0. See [LICENSE](LICENSE).
