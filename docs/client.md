# One-library client expression observations

`client infer` asks native Agda for an explicit expression's displayed type in an **existing client module**, with one selected library's recorded source available through explicit include roots. It snapshots and copies both projects, verifies the library's source and native resolution pins, and reuses the isolated checker adapter. It never adds an import, inserts a hole, rewrites an expression, or modifies either working tree.

The selected lexical candidate remains contextual evidence. Successful inference does **not** establish that the expression resolved to that candidate, that an import was used, or that a library exports a canonical declaration. A local homonym can succeed even when the selected library is not imported. CLI summaries therefore label `selectionRelation` as `lexical-context-only`.

## Example: select, import, and infer

The repository includes separate `examples/client-query/library` and `examples/client-query/client` roots. The library declares `Example.identity` in `src/Example.agda`; the client's `Main.agda` already contains `import Example` and a caller-authored alias. First create indexed evidence for the library's explicit safe check:

```sh
agda-evidence index build --project-root examples/client-query/library \
  --output /tmp/example.index.json
agda-evidence capture --project-root examples/client-query/library \
  --output /tmp/example.evidence --index-reference /tmp/example.index.json \
  --scope 'safe example library typecheck' \
  -- agda --no-libraries --ignore-interfaces --safe -i src src/Example.agda
agda-evidence index query /tmp/example.evidence \
  --exact Example.identity --kind signature
```

Use the complete `(path, line, qualifiedName, kind)` tuple returned by that query or a catalog hit. In this committed fixture the signature is at line 6:

```sh
agda-evidence client infer \
  --project-root examples/client-query/client --file Main.agda \
  --expression Example.identity \
  --library-bundle /tmp/example.evidence \
  --library-root examples/client-query/library --library-include src \
  --candidate-path src/Example.agda --candidate-line 6 \
  --candidate-qualified-name Example.identity --candidate-kind signature \
  --safe --output /tmp/imported.client.json

agda-evidence client verify /tmp/imported.client.json
```

With locally tested Agda 2.6.3, the displayed type is `Nat → Nat`. Use fresh outputs and select the actual returned tuple if the example source changes. The candidate's `sourceSha256` is copied from the verified index, not accepted from the caller. Candidates with the same qualified name remain distinguishable by path, line and kind. The tool makes no expression-text substitution or qualification guess.

`--include DIR` adds a client-relative include root; the client root is always included. At least one `--library-include DIR` is mandatory; library roots are never inferred from `.agda-lib`. `.` is an explicit valid library include. Include order is preserved with stable deduplication. Single-valued selectors reject repetition rather than silently taking the last value.

## Source and environment preflight

Client and library roots must be separate, non-overlapping directories. The new output must be outside both roots and the selected bundle, and cannot overwrite a file or symlink. Paths follow the existing snapshot policy and captured symlinks are rejected. Only one direct library bundle/source pair is supported; catalogs remain selection tools, not automatic mount specifications.

The selected bundle must have enhanced source/resolution/attestation identities and a source-bound lexical index. Its recorded resolution must be native, not Nix-aware. The library checkout's entire snapshot—not just the selected file or include subtree—must match the recorded `sourceId`. A fresh native resolution must match the complete recorded `resolutionId`, including the requested compiler, observed binary digest and visible registry metadata. Matching compiler version text alone is insufficient. A different recorded executable request can intentionally fail the pin even when its bytes match.

An earlier failed library command is allowed as context and remains explicitly failed in the embedded evidence. It is not upgraded to a passed project check when the client expression succeeds. A Nix observation, missing/opaque index, wrong tuple, stale source, or native-resolution mismatch fails preflight without issuing load/inference commands or writing a client observation. Native metadata probes may be required to compute the current resolution pin.

The temporary workspace contains only `client/<captured path>` and `library/<captured path>`, plus explicit empty include directories. Its source identity is the exact prefixed union, not either original project's identity. The checker independently observes the composed workspace's native resolution and confirms its compiler projection against the library preflight before interaction. Workspace and library `resolutionId` values may legitimately differ, because their root manifests and normalized registry observations differ.

Before interaction, the adapter also resnapshots both original roots and rejects observed regular-file additions, removals or changes during composition. The inner checker independently verifies the composed source pin and its own staged copy. These checks are not an atomic lock on live files; later host edits are not silently incorporated into the already captured workspace.

New checker invocations anchor include paths to the **absolute temporary workspace**. This matters because Agda can interpret relative `-i` options from the loaded module's directory. The saved argv uses `$PROJECT_ROOT/client`, `$PROJECT_ROOT/library/src`, and equivalent normalized anchors; the include policy remains a list of relative directories. Existing relative-argv type observations are still verifiable under their original recorded rules, but new client envelopes require anchored argv.

## Saved envelope and offline checks

The separate format is `agda-evidence/client-observation-v1`; see its [schema](../schemas/client-observation-v1.schema.json). Keep adjacent schemas together when resolving its relative JSON Schema references. The envelope contains a full client snapshot, the selected library's complete verified bundle manifest and component payloads, a fresh native library resolution, one exact lexical selection, explicit composition include lists, and a complete existing type-observation-v1 record. It contains no live source path or dangling catalog reference.

`clientObservationId` hashes the entire canonical envelope except its own ID field. The embedded bundle retains its command, scope, outcome, diagnostics and index identities. The nested type observation retains its own query, bounded responses, result and timestamps. Neither the earlier library bundle nor its index is edited, and the nested observation's single-project `basis` is null rather than incorrectly naming the library as the whole workspace.

`client verify` checks the envelope hash, complete embedded bundle/component identities, candidate membership, root-manifest bindings, source-prefix union, client-file digest, exact include mapping, anchored argv, compiler agreement, capture/execution ordering, and all nested checker invariants. It runs no Agda, reads no current source checkout, fetches no dependency, and performs no catalog lookup. Verification returning zero means internal consistency, including for a saved failure record—not expression success.

Infer exit `0` means an `inferred` nested result. Exit `1` means a saved non-inferred result or evidence/pin failure; exit `2` means invalid configuration. Preflight/staging failures write no envelope. Protocol-stage failures retain the nested load/query/timeout/output-limit diagnostics and are saved without turning them into a type. Defaults remain a 60-second total interaction budget and 4 MiB combined output limit; metadata probes and source copying precede the interaction budget.

## Native integration pilot

The manual `native client pilot` workflow runs `scripts/client-pilot.py` against the committed fixture on Ubuntu 24.04 with distro-provided native Agda. The installed compiler's version and binary digest are recorded; the apt dependency set is not an archived toolchain closure. Run it locally with:

```sh
python scripts/client-pilot.py --agda-bin /usr/bin/agda \
  --output /tmp/native-client-pilot
```

The script creates indexed library evidence and independently saves/verifies five cases: explicit import, caller-authored alias, missing import, private-name query, and local homonym. Imported/aliased/homonym expressions infer; missing-import and private-name queries fail. Crucially, the homonym's success does not become a selected-library resolution claim. Outputs remain separate envelopes rather than a green aggregate of successful and failed queries.

The [2 November 2026 native-client result](pilots/client-result-2026-11-02.md) records the completed remote run, all five independently verified envelope identifiers, source/compiler subjects, and artifact verification commands.

## Non-claims and next boundaries

This is evidence of one expression's behavior in one clean client load with explicit source availability. It is not a full scope resolver, declaration-origin graph, proof search agent, exporter analysis, dependency solver, Nix adapter, or multi-library workspace manager. Imported library options, postulates when `--safe` is absent, module parameters and displayed metavariables retain the ordinary checker caveats.

Embedded source snapshots are manifests, not source archives. Embedded evidence makes the **record** portable, not source/toolchain replay offline. Hashes prove internal consistency, not producer authenticity; consistently forged transcripts remain possible without trusted capture/transport or signatures. Temporary copies isolate original source edits, not all compiler/reflection filesystem or network effects. See the [checker contract](checker.md) for protocol, load acceptance and transport limits.
