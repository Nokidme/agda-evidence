# Isolated checker-backed type observations

`checker infer` runs native Agda in a temporary copy of the snapshot-visible source, loads one explicit module, and asks for the displayed type of one explicit expression in that module's top-level inside scope. It does not insert a hole, apply a proof step, edit the original source, or attach a type to every lexical discovery candidate.

The first adapter supports POSIX native Agda with explicit project-relative include roots and compiler-provided builtin modules. It disables library files with `--no-libraries` and ignores pre-existing interfaces with `--ignore-interfaces`. It does not resolve external dependencies, activate a Nix shell, unwrap project launchers, or silently import a catalog's libraries. Projects needing external libraries must provide authorized source under the project root or wait for an explicit toolchain adapter.

## Infer and save

The repository includes a small safe example:

```sh
agda-evidence checker infer \
  --project-root examples/type-query \
  --file Main.agda --expression identity --safe \
  --output /tmp/identity.type.json

agda-evidence checker infer \
  --project-root examples/type-query \
  --file Main.agda --expression '_⊕_' --safe \
  --output /tmp/addition.type.json

agda-evidence checker verify /tmp/identity.type.json
```

The first expression displays `Nat → Nat`; the second displays `Nat → Nat → Nat` on locally tested Agda 2.6.3. Pretty-printing may differ across versions. `--agda-bin` selects one executable, not a shell command. `--include src` adds a project-relative include directory; repeat it if needed. The project root is always included. Absolute includes, parent segments, symlinks in captured source, and files absent from the snapshot are rejected.

`--safe` is explicit and optional; it is recorded in the compiler argv. A clean load without `--safe` can still involve postulates or source options that weaken proof claims. Neither mode proves informal mathematical intent or independently checks every declaration returned by lexical discovery.

The output must be a new JSON file outside the source project and outside any referenced basis bundle. The CLI checks this before launching Agda. Defaults are a 60-second total interaction timeout and a 4 MiB combined stdout/stderr byte limit. Metadata/version probing occurs before that session and uses the existing small-command timeouts. The process group is terminated on completion or failure so native launchers do not leave descendants running.

## Optionally pin an earlier evidence bundle

```sh
agda-evidence checker infer \
  --project-root /work/library --file src/My/Module.agda \
  --include src --expression lemma \
  --bundle /work/library.evidence \
  --output /tmp/lemma.type.json
```

The optional basis must be an internally verified enhanced evidence bundle. Before starting interaction, the adapter compares its source and partial resolution identities against the current source snapshot and native Agda observation. Any mismatch rejects the operation without writing an observation or issuing load/inference requests. Metadata probes still run to compute the current resolution identity.

The basis reference binds the exact earlier `bundleId` and matching source/resolution IDs; it does not reuse that bundle's success status or claim its command covered this expression. The new observation records its own query policy, responses, timestamps, and whole `observationId`. The earlier bundle and its lexical index are not modified.

The partial `resolutionId` includes visible registry metadata even though this adapter's `--no-libraries` command does not use library registries. Matching it is a conservative comparison precondition, not proof of equal dependency closure. Query argv and include roots are recorded separately. Nix-aware resolution observations are not interchangeable with native host observations.

## Clean-load policy and failure records

The adapter consumes bare newline-delimited JSON responses plus the flushed `JSON> ` prompt, which has no newline. It waits through trailing responses to the next prompt before issuing another request. Paths and expressions use Haskell string escaping, not JSON `\u` escapes. Unicode names and operators are preserved.

The explicit requests are:

```text
IOTCM "<staged-file>" NonInteractive Direct (Cmd_load "<staged-file>" [])
IOTCM "<staged-file>" None Direct (Cmd_infer_toplevel Simplified "<expression>")
```

Inference is issued only after a completed load with an empty `InteractionPoints` list, empty visible/invisible goals and warning/error arrays in `AllGoalsWarnings`, and the final checked status true. This is deliberately stricter than Agda's ability to query unfinished work. `InteractionPoints` alone does not certify a clean load. A semantic `Error`, incomplete load, malformed protocol, unexpected EOF, timeout, or output-limit failure is never converted into a type because the OS process happened to exit zero.

`result.status` is `inferred`, `load-error`, `load-incomplete`, `query-error`, `timed-out`, `output-limit`, `protocol-error`, or `execution-error`. Only `inferred` carries a non-null displayed `type`. Failure observations preserve complete parsed responses from completed or partial phases, bounded stderr, and transport diagnostics; output-limit or mid-record failures do not retain a complete transcript. Non-JSON diagnostic excerpts are bounded. Unsupported response shapes fail conservatively rather than being guessed.

A query-level inferred type is display text, not a canonical closed type representation. It may contain implicit arguments, metavariables, or module parameters. A clean module load does not make every possible query expression a completed proof.

CLI exit codes are `0` for inferred success, `1` for a saved non-inferred observation or evidence/pin failure, and `2` for invalid arguments/configuration. Inference failures that reach the protocol stage write an observation and emit its result JSON. Preflight/pin failures write no artifact. Offline verification returns `0` for any internally valid observation, including a valid failure record; it is not a query-success test.

## Observation v1 and local verification

The separate format is `agda-evidence/type-observation-v1`. Its [JSON schema](../schemas/type-observation-v1.schema.json) describes the envelope. The file contains the source snapshot, visible native resolution, optional basis reference, queried file digest and expression, explicit include/safe policy, normalized argv, timestamps, three phased request/response records, transport status/diagnostics, and response-derived result.

`observationId` is the lowercase SHA-256 identifier of the complete canonical JSON payload except the `observationId` field itself. It is time-specific, not a source-comparison identity. Temporary project paths are replaced with `$PROJECT_ROOT`; the executable in argv is `$AGDA`, bound to the resolution's requested executable and observed binary digest. External paths and sensitive source-derived messages can remain in responses; inspect observations before sharing.

`checker verify` checks the observation identity, source/resolution projections, query file digest, normalized argv and IOTCM requests, phase ordering, timestamp order, optional basis subjects, and agreement of `result` with retained responses. It never runs Agda, accesses current project source, resolves dependencies, or reruns the earlier check. Verification of a referenced basis's actual bundle at read time requires separately supplying and verifying that bundle; the saved observation only preserves its recorded identity bindings.

Hashes establish internal consistency, not producer authentication. A forged but consistently rehashed protocol record is not prevented by v1; trusted capture and transport or future signatures remain necessary. Captured source is a file manifest, not a source archive. No offline source/toolchain replay is promised.

## What scope is established

Successful inference establishes only that the recorded Agda returned the displayed type for that expression in the loaded module's inside scope under those options. Inside-scope lookup is not a public-export graph; imported aliases, module parameters, and names omitted by the lexical scanner may affect a query. It does not establish a candidate's canonical declaration origin, exports, uniqueness, or importability in a different client module.

Choose the expression explicitly for the loaded module. A lexical candidate such as `Main.identity` is not automatically a valid self-qualified expression there; `identity` is the working query in the included example. On locally tested Agda 2.6.3, the example's `Main.identity` and private `localIdentity` queries return scope errors. The adapter preserves those results rather than stripping qualification or inventing visibility rules.

The adapter therefore does not reinterpret Agda's textual `WhyInScope` explanations as an authoritative declaration graph. It also does not merge type observations into catalog query hits. Structured declaration provenance and a client-module scope adapter are separate future capabilities.

Loading may generate normal interface/cache files inside the temporary copy and compiler-managed builtin locations. The original source tree is not used as the working copy, and captured staged regular source inputs are checked for unexpected changes. This is source-copy isolation, not a security sandbox for a hostile compiler, reflection code, source options, or all host filesystem/network effects.

## Real-library validation

The [2 November 2026 checker pilot](pilots/checker-result-2026-11-02.md) preserved the standard library's native gate and separately recorded Agda 2.8.0's `ℕ → ℕ → ℕ` result for `_+_`. The downloaded observation was verified locally and its source/resolution/bundle basis matched the independently verified project artifact.

## Protocol references

The constructor and response shapes were source-checked against Agda v2.6.4.3 and v2.8.0; local end-to-end tests use installed Agda 2.6.3. These references are not a blanket compatibility guarantee:

- [Agda v2.8.0 IOTCM constructors and string reader](https://github.com/agda/agda/blob/v2.8.0/src/full/Agda/Interaction/Base.hs).
- [Agda v2.8.0 JSON prompt and response encoding](https://github.com/agda/agda/blob/v2.8.0/src/full/Agda/Interaction/JSONTop.hs).
- [Agda v2.8.0 REPL framing and UTF-8 setup](https://github.com/agda/agda/blob/v2.8.0/src/full/Agda/Interaction/AgdaTop.hs).
- [Agda v2.8.0 load, inference, error, and completion behavior](https://github.com/agda/agda/blob/v2.8.0/src/full/Agda/Interaction/InteractionTop.hs).
- [Agda v2.8.0 top-level inside-scope setup](https://github.com/agda/agda/blob/v2.8.0/src/full/Agda/Interaction/BasicOps.hs).
