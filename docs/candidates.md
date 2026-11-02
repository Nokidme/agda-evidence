# Non-filling candidate expression trials

`goals check` tries one explicit expression against one selected goal's contextual expected type, in a fresh source-copy session. It uses Agda's dedicated checking command, not inference or displayed-type string comparison. It does not insert the expression, fill a hole, run proof search, or rewrite original source.

The positive status is **`elaborated`**, with `assurance: contextual-elaboration-only`. It means Agda returned an elaborated expression while checking against the selected contextual goal type, followed by an unchanged restored goal summary. It does **not** mean the candidate has no unresolved metavariables/constraints, is warning-free, would pass all checks after insertion, or completes a proof. Agda restores speculative checking state before producing the goal display; later diagnostic queries cannot recover discarded candidate-local obligations. [1] [2]

## Use an accepted goal listing

Start from the unchanged committed unfinished example:

```sh
agda-evidence goals list \
  --project-root examples/goal-query --file Main.agda --safe \
  --output /tmp/candidate-goals.json

agda-evidence goals check \
  --project-root examples/goal-query --listing /tmp/candidate-goals.json \
  --goal-id 0 --expression 'n' --output /tmp/candidate-n.json

agda-evidence goals verify-check /tmp/candidate-n.json
```

Use the actual selected ID returned by the listing, rather than assuming stable numbering. On tested Agda 2.6.3, goal 0 expects `Nat` with local `n : Nat`; `n` elaborates. Goal 1 has local `λ₁ : Nat`, and goal 2 expects `n ≡ n`, where `refl` elaborates. Trying `λ x → x` at the Nat goal or an absent name yields a saved `query-error`, not a fabricated fit.

The trial inherits the listing's source file, source identity, include order, safe flag, native resolution identity, rewrite mode, and unfinished-load policy. It accepts no replacements for file/include/safe. Use the same native executable request as the listing; if that used `/usr/bin/agda`, pass the same `--agda-bin /usr/bin/agda`. A fresh snapshot/native-resolution comparison precedes interaction. Reloaded selected ID/range must match before any candidate query. Stale source, changed compiler/registry, missing selection, or invalid prior evidence is rejected rather than silently loading another context.

One exact nonblank expression is required, capped at **65,536 UTF-8 bytes**. It is not trimmed, qualified, substituted from a library candidate, or rewritten. Haskell wire quoting escapes paths and expressions, including quotes, backslashes and controls, and rejects unpaired Unicode surrogates. This prevents adding a separate protocol command through the expression string; it is not an Agda parser, macro filter, or security sandbox.

Each trial gets a new disposable session. Defaults remain 60 seconds for the whole interaction and 4 MiB combined stdout/stderr, including postflight. Metadata probes and copying happen before that budget. Outputs must be new JSON files outside the project; existing files and symlinks are not overwritten. Repeated single-valued selectors are rejected.

## Exact query and restored-goal postflight

A successful native trial has four prompt-bounded phases: startup, load, check, and postflight. The two query requests are:

```text
IOTCM "<staged file>" None Direct (Cmd_goal_type_context_check Simplified <ID> noRange "<expression>")
IOTCM "<staged file>" None Direct (Cmd_metas AsIs)
```

The first command genuinely invokes expected-type checking for the selected interaction point; the similarly named infer command does not. Success requires one matching `GoalSpecific` / `GoalType` response with `rewrite: Simplified` and `typeAux: {kind: GoalAndElaboration, term: ...}`. `term` is pretty-printed elaborated text, not a serialized kernel proof. The saved selected result also retains the contextual type, structured local entries, and displayed boundary/constraint arrays. [1] [2] [3] [4]

The postflight must return exactly one well-shaped `AllGoalsWarnings` summary with no reported warnings/errors. Its **entire canonical JSON summary must equal the fresh load summary**, including visible goals, invisible metas and their display data. Thus the original selected source goal remains present; no unfilled source goal is quietly removed. Extra, missing, duplicate, changed or diagnostically blocked postflight evidence prevents a positive result. This exact comparison is deliberately conservative and may refuse a harmless reordered display.

Postflight observes the **restored source session**, not discarded candidate state. The `boundary` and `outputForms` in the check response also refer to the restored selected goal, not an exhaustive list of candidate residuals. Nonempty baseline invisible metas or displayed boundaries are preserved; they are not reported as solved or treated as proof of candidate validity. This policy makes no residual-freedom assertion. If a future workflow needs candidate-local zero-obligation assurance or insertion-related checks, it needs a different, explicitly labeled operation; repeating a restored-state query cannot establish it. [1] [2]

The prior unfinished-load policy remains unchanged: visible/invisible goals and `checked: false` are allowed, while reported load warnings/nonfatal errors cause `load-blocked`. Fatal Error and unexpected give/case-split/solve/search actions block progress. Query Error stops the trial before postflight. No `Cmd_give`, refine, auto, case-split, compile, or source-action application occurs.

## Why elaboration is not a proof certificate

Ordinary elaboration can create implicit metas, postpone constraints, process holes, and run macros/unquote. Speculative stored warnings can be discarded with the local state. Empty restored diagnostics therefore do not establish candidate completeness or warning freedom. Plain input filtering for `_` or `?` would not solve implicit obligations and is not presented as an Agda parser. [1] [2] [5] [6]

The native pilot intentionally includes `let x = _ in refl` against the equality goal. On tested Agda 2.6.3 it returns displayed term `refl`, even though the original expression contains an unused unresolved inference request. This remains `elaborated`, never “all candidate obligations discharged.” Conversely, a bare `_` in that compiler can fail while rendering its temporary meta after restoration; the resulting native internal Error is retained as `query-error`. It is not reclassified as a mathematically meaningful type mismatch or evidence that holes were prohibited.

Contextual checking also differs from inserting a term into a surrounding definition and rerunning termination/coverage checks. A check result must not be advertised as predicting every insertion-related check. Safe mode records the requested compiler option; it neither fills the source goal nor closes this protocol observability gap. [1] [2]

## Saved records and verification

The separate format is `agda-evidence/candidate-observation-v1`; its [schema](../schemas/candidate-observation-v1.schema.json) references adjacent goal/type schemas. The full accepted leaf listing is embedded. The current snapshot, partial native resolution, explicit expression/policies, anchored argv, timestamps, phased responses, transport diagnostics and derived result are retained. `observationId` hashes the entire canonical envelope except its own ID. No previous listing or source/index/catalog record is changed.

`goals verify-check` checks complete identities, source/native-environment/listing bindings, inherited policy, selected ID/range, exact check/metas requests and phase ordering, structured elaboration fields, strict JSON scalar types, postflight equality and result agreement. It runs no Agda, reads no live project checkout and loads no external catalog. The earlier `goals verify` remains for goal-observation-v1 and does not reinterpret a candidate trial as a pure goal inspection.

List/inspect and old completed-module inference behavior are unchanged. Candidate trial statuses are `elaborated`, `load-error`, `load-blocked`, `selection-error`, `query-error`, `postflight-error`, `postflight-blocked`, `postflight-changed`, `protocol-error`, `execution-error`, `timed-out`, and `output-limit`. The promoted selected elaboration is null unless the whole trial succeeds; raw partial/error responses stay available in the transcript. `postflightUnchanged` is true for accepted unchanged postflight, false for a valid changed summary, and otherwise null.

`goals check` returns zero for `elaborated`, one for saved trial/evidence failures, and two for invalid configuration. Preflight/staged-input failures write no record. `goals verify-check` returns zero for any internally consistent saved trial, including a failure: inspect its result rather than interpreting verification success as expression success.

## Native pilot and limits

Run the finite committed fixture against a native compiler:

```sh
python scripts/candidates-pilot.py --agda-bin /usr/bin/agda \
  --output /tmp/native-candidates-pilot
```

It records a listing and seven independent trials: Nat local, Unicode local, dependent reflexivity, wrong type, absent name, bare underscore, and an unused-meta expression that demonstrates the assurance limit. The manual native workflow checks original source cleanliness and retains these separate records, rather than aggregating failures into a green proof claim. The observed distro compiler is recorded; the apt package closure is not archived.

This is one explicit candidate at one existing native-project goal, not a search engine, batch agent, implicit dependency solver, Nix adapter, or automatic proof editor. Source snapshots are manifests rather than source archives. Hashes establish internal consistency, not producer authenticity or resistance to consistently fabricated transcripts. Loading can write dependency/primitive caches outside regular-source identity policy, and reflection can have external effects. Isolated source copies are not an operating-system sandbox or offline source/toolchain replay.

## References

[1]: https://raw.githubusercontent.com/agda/agda/v2.6.3/src/full/Agda/Interaction/InteractionTop.hs "Agda v2.6.3 check dispatch, local-state checking, and post-restoration goal display"
[2]: https://raw.githubusercontent.com/agda/agda/v2.8.0/src/full/Agda/Interaction/InteractionTop.hs "Agda v2.8.0 check dispatch and reification inside restored speculative state"
[3]: https://raw.githubusercontent.com/agda/agda/v2.6.3/src/full/Agda/Interaction/JSONTop.hs "Agda v2.6.3 GoalAndElaboration and structured context JSON"
[4]: https://raw.githubusercontent.com/agda/agda/v2.8.0/src/full/Agda/Interaction/JSONTop.hs "Agda v2.8.0 GoalAndElaboration and structured context JSON"
[5]: https://raw.githubusercontent.com/agda/agda/v2.6.3/src/full/Agda/TypeChecking/Rules/Term.hs "Agda v2.6.3 ordinary checking, metas and postponed obligations"
[6]: https://raw.githubusercontent.com/agda/agda/v2.8.0/src/full/Agda/TypeChecking/Rules/Term.hs "Agda v2.8.0 ordinary checking, metas and postponed obligations"
