# Pinned source dependencies for unfinished clients

The additive `source` adapter lists and inspects unfinished client goals, then tries explicit expressions, with **one caller-selected native source dependency** available through declared include roots. It is the next development increment after `v0.1.0a1`, not part of that released wheel. It does not fetch sources, solve transitive dependencies, activate a Nix shell, infer includes from `.agda-lib`, add imports, or fill holes.

Unlike `client infer`, this workflow does not require selecting an indexed declaration or a clean completed client. A dependency supplies source availability, not a claim that an expression resolves to a particular lexical hit. Its bundle may omit a declaration index. A prior failed dependency check is preserved as failed; successful client research never upgrades the dependency's recorded outcome.

## Explicit preparation

Select and provision the compiler/source checkout yourself. The pilot uses Agda **2.6.3** and stdlib **v1.7.3**, immutable source commit `0817da6877aa045932221134913d8511caa78d97`; that release's [installation guide](https://github.com/agda/agda-stdlib/blob/0817da6877aa045932221134913d8511caa78d97/notes/installation-guide.md) declares compatibility with 2.6.3 or 2.6.4. Stdlib v2.0's guide instead declares 2.6.4/2.6.4.1; it was not substituted for this profile. This does not establish the actual AgdaLab backend profile.

Capture an explicit narrow safe dependency-module check with the compiler executable that subsequent work will use:

```sh
agda-evidence capture --project-root /work/stdlib-1.7.3 \
  --output /work/stdlib.evidence --agda-bin /usr/bin/agda \
  --scope 'safe equality Core module check; not the whole stdlib gate' \
  -- /usr/bin/agda --no-libraries --ignore-interfaces --safe \
     -i src src/Relation/Binary/PropositionalEquality/Core.agda
```

The bundle captures the complete regular-file source snapshot while the command checks only its specified module and imports. Neither snapshot completeness nor command success is a full-library/dependency-closure guarantee. All visible resolution subjects, including registry metadata and requested compiler path, must still agree when the source adapter performs preflight, even though implicit library files are disabled for native interaction.

## List, inspect and try

The committed `examples/source-query/Main.agda` already imports standard-library equality and proposes a reversal goal. The adapter does not write that import. With fresh external outputs:

```sh
agda-evidence source list \
  --project-root examples/source-query --file Main.agda \
  --dependency-root /work/stdlib-1.7.3 --dependency-bundle /work/stdlib.evidence \
  --dependency-include src --agda-bin /usr/bin/agda --safe \
  --output /work/source-goals.json

agda-evidence source inspect \
  --project-root examples/source-query --listing /work/source-goals.json --goal-id 0 \
  --dependency-root /work/stdlib-1.7.3 --dependency-bundle /work/stdlib.evidence \
  --dependency-include src --agda-bin /usr/bin/agda \
  --output /work/source-context.json

agda-evidence source check \
  --project-root examples/source-query --listing /work/source-goals.json --goal-id 0 \
  --expression 'sym p' \
  --dependency-root /work/stdlib-1.7.3 --dependency-bundle /work/stdlib.evidence \
  --dependency-include src --agda-bin /usr/bin/agda \
  --output /work/source-sym.json

agda-evidence source verify /work/source-sym.json
```

Use the actual scalar ID returned by the listing rather than assuming `0`. Additional client-relative include roots are explicit `--include` values on `list`; the fixed policy includes the client root. At least one dependency-relative `--dependency-include` is required. Inspection/trials inherit the listing's original client file, include order and safe policy; dependency include arguments must agree with it. Native commands use anchored workspace include paths with `--no-libraries --ignore-interfaces`.

Stdlib v1.7.3 explicitly declares `--warning=noUnsupportedIndexedMatch` in its library manifest. Because this profile does not activate that manifest, the supported fixture declares the same specific compatibility setting in its own `OPTIONS` pragma, alongside `--safe`. This suppresses that indexed-match/Cubical-compatibility warning, not all warnings or proof checking. The separate `Warnings.agda` fixture omits the setting and must remain `load-blocked`; the adapter's conservative no-diagnostics acceptance policy is unchanged. The captured source digest binds the explicit pragma. No Cubical execution compatibility is claimed.

The initial profile intentionally has no reusable local manifest or additional editor API. Local paths and compiler selection are explicit trusted-host/CLI configuration; they are not embedded as live references in an observation. The ordinary `ResearchWorkspace` still has its existing self-contained native profile. No live application deployment is changed here.

## Exact source composition and freshness

Client and dependency roots must be separate and non-overlapping. Include directories must exist and stay inside their own source roots. Outputs must be new, outside both source trees and the dependency bundle. Capture verifies dependency evidence once and retains the same payloads. A fresh full dependency snapshot and full native resolution must match that evidence, with no Nix observation. The original client's resolution is independently captured, and its root manifest records must match its own snapshot.

The staged workspace has exactly `client/<captured file>` and `library/<captured file>` plus empty explicitly included directories. Its file/digest/size manifest is the exact sorted prefix union. All compiler projections must agree across recorded dependency evidence, fresh dependency/client preflight and native workspace observation. The workspace's resolution ID need not equal the dependency's: each is checked against its own manifest context.

Before launching native interaction, the adapter verifies source/composition/compiler/resolution preconditions. It checks original sources and observed resolution again after the operation, including failed trials. A detected edit or environment change rejects the envelope rather than publishing it as current. This is not an atomic filesystem lock and cannot detect every edit-and-revert race; editor hosts must still track dirty buffers, generation/revisions and superseded requests.

Selections require an accepted **leaf source listing**, not a context/trial history or an ordinary single-project listing. The entire earlier native listing is embedded unchanged inside the current native record and compared to the source envelope's prior listing. Client source/resolution, dependency bundle/source/resolution and composition policy must all agree. A same-source replacement bundle still changes the exact dependency provenance and rejects a stale selection. The native reload separately verifies scalar goal ID/range before issuing selected queries.

## Portable records, not replay archives

The new `agda-evidence/source-observation-v1` envelope retains the client snapshot and native resolution, complete dependency bundle/payloads, fresh dependency resolution, explicit composition, unchanged native goal/candidate observation and nullable complete prior source listing. `sourceObservationId` hashes the entire canonical envelope except that ID field. Inner goal/candidate IDs retain their original format and semantics.

Offline verification checks the complete envelope, embedded evidence, source unions, includes, root manifests, compiler agreement, capture/execution order and all native response-derived result invariants. It needs no current checkout, catalog lookup or subprocess. Structural schema validation is not a replacement for semantic verification. Source snapshots are manifests, not archives; neither the dependency source nor toolchain can be replayed offline just from this record. Internally consistent hashes cannot authenticate the producer.

A valid saved failed query verifies successfully. `list`/`inspect`/`check` exit `0` means the corresponding native status is `listed`, `inspected` or `elaborated`; native failures/pin failures use exit `1`, bad configuration uses `2`. No envelope is written for preflight failure. Saved transport/load/query failures retain the original native diagnostics. Candidate assurance remains **contextual-elaboration-only**, not proof completion or residual-obligation freedom. Original source holes are left untouched.

## Reproducible pilot

`scripts/sources-pilot.py` takes an already-provisioned dependency checkout and native compiler; it downloads nothing. It records a narrow equality-module gate, a real imported goal/context, successful `sym p`, rejected `refl`, an absent-import trial, an unsuppressed warning-blocked load, and stale dependency-source rejection. The manual source pilot workflow provisions the immutable stdlib commit separately before running that script. A local source-only dependency profile is not a general installed-library compatibility claim or a secure sandbox for hostile compiler/reflection effects.
