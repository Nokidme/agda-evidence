# One-library client observation result — 2 November 2026

The client adapter was implemented in [e9d8309](https://github.com/Nokidme/agda-evidence/commit/e9d83099f62bab42f49b03e4463e3a044441c11d). The native integration workflow passed in [run 41519868952](https://github.com/Nokidme/agda-evidence/actions/runs/41519868952) at [74ebe70](https://github.com/Nokidme/agda-evidence/commit/74ebe70d58e6aaf174b36ceab5c307ac716061f5), using Ubuntu 24.04's installed Agda 2.6.3. Compiler version and binary digest were captured; distro packages are not an archived dependency closure.

The uploaded library evidence and all five client envelopes were downloaded into the development environment. Each envelope passed local semantic verification and its JSON Schema. The complete embedded library manifest and component payloads in **every** envelope exactly matched the independently verified uploaded library bundle. The original checkout check passed, and the pilot's client/library snapshot checks found no source changes or generated interfaces in either original source tree.

## Real client behavior

All cases select the same recorded lexical `Example.identity` signature at `src/Example.agda`, line 6. The supplied expression and client file differ explicitly:

- `Main.agda`, `Example.identity`: `inferred`, displayed type `Nat → Nat`; the existing client imports `Example`.
- `Main.agda`, `importedIdentity`: `inferred`, displayed type `Nat → Nat`; the existing client contains a caller-authored renaming.
- `NoImport.agda`, `Example.identity`: `query-error`, null type; making source available does not add an import.
- `Main.agda`, `Example.secret`: `query-error`, null type; the library's private name is not silently treated as public.
- `Homonym.agda`, `identity`: `inferred`, displayed type `Nat → Nat`; this client defines a local homonym and does not import `Example`.

The homonym is an intentional counterexample to claiming that successful inference establishes selected-candidate identity. Every summary reports `selectionRelation: lexical-context-only`. These results are behavior of explicit expressions in existing client modules, not a declaration-origin or export graph. The private query still selects the identity candidate as contextual evidence; the tool never substitutes the selection's qualified name for the supplied expression.

## Exact observation identifiers

```text
imported:  sha256:c350b5e73a597636147d84adcb320428c26f1468e11833cf0f9fc94ac3ccc926
alias:     sha256:b2f9cb7ca14b4cf1d755ce2ac1d12bb706345e3e489745c6c436c7363294d78e
no-import: sha256:0dd965b24af85d61fd69bdbc90e47f004619037f72402b08b06ae37c9c26c928
private:   sha256:366a7f077a9b192cb6549bc145a5b9a34db41d7ec287b6dadb419351bd978b85
homonym:   sha256:140a72347a2856b929b2e4594deb52ef6eeb9d7a00169e797198101cdcd89abe
```

Shared source and library subjects:

```text
clientSourceId:        sha256:093ceaae200813db2f15cd62cd2228b387d057b624adb208c8689b16f3c784d0
librarySourceId:       sha256:c198216e64dba957b0d731a56e19b13e843d9ff341e385281be3d96425726720
workspaceSourceId:     sha256:1cf75a0393fdcdbb964ee7f547b4cd0be95a3fc4fb646aea4e9720d705427b3b
libraryResolutionId:   sha256:d62e7ce7e239150e5f2d5d7f084fc40004a99396c5552f0369cd02c209cdd002
workspaceResolutionId: sha256:5d96ead6f9d4e407766c18d2c1c42f6e0e9e594444378d6668255c2774df7f3e
libraryBundleId:       sha256:8f3cf3362ed8c633cad0f10e78553ab95523418d444e39d285150e75148f6f68
libraryCheckId:        sha256:73cca89e8987ce3786b72287e285e944e2b62978de8175eda29b3bace40caaab
compilerBinaryDigest:  sha256:852806142a15951f667df303c73cfce5f4123218ce6e1f1b29acaddc242af00d
selectedSourceFile:    sha256:937cfa9301ea1f2789ea9cde9e0817dca25826f9c4eca3dfd111f08866fd343e
```

The workspace is exactly the prefixed client/library file union. Its source identity is not either individual project's identity. The different native resolution IDs are expected: the original library root has `example.agda-lib`, while the composed workspace root has no root-level library descriptor. Explicit anchored include argv, not implicit registry activation, controls source availability.

## Reproduce retained-record verification

Use a new download directory and an installed `agda-evidence`:

```sh
mkdir downloaded-client-pilot
gh run download 41519868952 --repo Nokidme/agda-evidence \
  --name native-client-pilot-74ebe70d58e6aaf174b36ceab5c307ac716061f5 \
  --dir downloaded-client-pilot

agda-evidence verify downloaded-client-pilot/library.evidence
for label in imported alias no-import private homonym; do
  agda-evidence client verify "downloaded-client-pilot/$label.client.json"
done
```

The verification commands do not execute Agda or access live client/library source. A valid failure envelope also returns verification exit zero; inspect its nested `result.status` to distinguish query success. GitHub artifact download requires access/network and artifacts are retained for 30 days from the run. This reproduces retained-record verification, not offline source/toolchain replay.

To run the fixture again rather than just verify its records:

```sh
python scripts/client-pilot.py --agda-bin /usr/bin/agda \
  --output /tmp/new-native-client-pilot
```

## Tests, compatibility, and repairs

All 83 local tests passed, including real Agda imports, aliases, public reexports, missing imports, private-name rejection and local homonyms. Deterministic fixtures cover full candidate tuples, duplicate names, legacy/opaque/missing/Nix evidence, source and native-resolution mismatches, compiler changes before interaction, full source-prefix binding, tampering after rehash, offline verification without processes, output/root protections, repeated selectors, observed original-source additions/removals during copying, and staged mutations. The [implementation CI](https://github.com/Nokidme/agda-evidence/actions/runs/41519594132) and [workflow-repair CI](https://github.com/Nokidme/agda-evidence/actions/runs/41519869422) passed on Python 3.11 and 3.12. Real-Agda unit tests skip when Agda is absent; the manual native pilot supplements those runs.

Real sibling-source imports exposed Agda's interpretation of relative `-i` options from the loaded file directory. New writer invocations therefore use absolute staged include roots and normalize saved argv to `$PROJECT_ROOT` anchors. Old relative-argv type-observation-v1 records remain verifiable under their original semantics. The previously downloaded Agda 2.8 standard-library observation `a9b4b6f78030529fddf9f80ef584ec7b74d6090b17e0aae710dec8575469687b` was successfully reverified after the change. New client envelopes require anchored argv and do not reinterpret old records.

The first remote run, [41519654198](https://github.com/Nokidme/agda-evidence/actions/runs/41519654198), passed every client capture/verification case but failed its strict untracked-file checkout check. A disposable clean-clone reproduction showed that wheel installation creates `build/lib/agda_evidence/*` packaging files, with no tracked source change. The workflow switched to an editable development install and added checkout-status diagnostics; strict tracked/untracked checks remained intact. The successful retry above used identical fixtures and inference policies.

## Scope stop

One explicitly supplied library and one existing client context are supported. The full library snapshot and native-resolution subjects must match their evidence; no Nix environment or dependencies are fetched. Prior failed library checks remain failed contextual evidence. No imports, proofs or expressions are edited. Complete embedded evidence makes the record portable, but source snapshots are still manifests rather than archives, and hashes do not authenticate a producer or rule out consistently fabricated transcripts. See the [client contract](../client.md) for exact limits and failure behavior.
