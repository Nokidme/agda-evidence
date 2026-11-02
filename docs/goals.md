# Read-only goals and local proof context

`goals list` records unfinished interaction points from a source-copy load. `goals inspect` queries the displayed goal type and local context for **one explicitly selected point**, using a previously verified listing. Neither command fills a hole, refines a term, searches for a proof, edits the original source, or marks an unfinished proof complete.

This native POSIX adapter shares the checker's prompt-aware session, absolute staged include anchors, source snapshot policy, compiler digest checks, and runtime/output bounds. It is a separate format and load policy; existing completed-module inference still rejects unfinished loads.

## List first, then select

The committed example has a plain `?`, an explicit `{! !}` hole with a Unicode local name, and a dependent equality goal:

```sh
agda-evidence goals list \
  --project-root examples/goal-query --file Main.agda --safe \
  --output /tmp/goals.list.json

agda-evidence goals inspect \
  --project-root examples/goal-query --listing /tmp/goals.list.json \
  --goal-id 1 --output /tmp/goal-context.json

agda-evidence goals verify /tmp/goal-context.json
```

Select an actual `id` from the listing's `result.goals`; do not assume IDs are dense or persistent. On tested Agda 2.6.3 the example's Unicode hole has ID 1 and displayed type `Nat`, with local context entry `λ₁ : Nat`. Other executables or source changes may yield different IDs. An accepted listing with an empty goal array is legitimate and does not imply project-wide proof coverage.

The list command accepts `--include DIR`, `--safe`, `--agda-bin`, and the usual time/output limits. Inspect inherits the file, include order, safe flag, rewrite mode, and load policy from the saved listing. It does not accept replacements for those policies. Both commands must use the same recorded native executable request and resolution; if listing used `/usr/bin/agda`, supply the same `--agda-bin /usr/bin/agda` for inspection rather than switching to the default request `agda`.

Before starting interaction, inspection compares the complete current source snapshot and fresh partial native resolution against the listing. Stale source—including an unrelated file change—or a different compiler/registry observation fails without a new artifact or load/query. After fresh loading, the selected ID and its full interval list must match the listing before the query is sent. A mismatch saves `selection-error` with the current inventory, rather than guessing another ID. Native metadata probes may run to compute the resolution pin.

Each output must be a new JSON file outside the project. Existing files and symlinks are not overwritten. Single-valued selectors reject repetition. Default bounds are a 60-second total interaction session and 4 MiB combined stdout/stderr; version/configuration probes and source copying happen before the session budget. A selected query uses only:

```text
IOTCM "<staged file>" None Direct (Cmd_goal_type_context Simplified <ID> noRange "")
```

No expression is passed and no source replacement action is applied. The complete exchange must reach the next non-newline `JSON> ` prompt before its semantic result is accepted. [1] [2]

## Unfinished-load acceptance

The versioned policy is `unfinished-no-diagnostics-v1`. A completed native load must return exactly one unambiguous `AllGoalsWarnings` summary and one matching `InteractionPoints` array. Visible typed goals and invisible metas are allowed. `Status.checked: false` is retained and is expected for ordinary unfinished modules; it is not upgraded to true. [1] [2]

Fatal `DisplayInfo/Error` always blocks listing/inspection. Nonempty summary `warnings` or `errors` produce **`load-blocked`**, not a fatal-load verdict. The latter array contains Agda's nonfatal-error warning category, and can legitimately include unsolved constraints even when holes are available. This first policy deliberately declines such modules rather than forgiving messages by substring. It also declines unsupported or inconsistent visible goal shapes. [3] [4]

Inspection requires one matching ordinary `OfType` visible interaction goal and the combined `GoalSpecific` / `GoalType` response with the selected ID. A false checked status does not block it, but any query Error, missing/mismatched type/context response, unexpected editing action, or incomplete exchange prevents `inspected` success.

Invisible metas are retained as raw diagnostic/display objects. They can use named metas rather than interaction IDs, and some `JustSort` entries have no `type`. They are not converted into selectable IDs, defaulted to goal zero, or passed to a hole-level query. [3] [4]

## Returned context and source association

An inspected result contains the selected ID, its recorded interval array, a displayed type, structured `entries`, and the `boundary` and `outputForms` string arrays. Each context entry retains `originalName`, `reifiedName`, displayed `binding`, and boolean `inScope`; false is legitimate data. The serializer does not provide full binding modalities or let-bound values. This is local goal context, not a library-wide symbol table. [5] [6]

Visible listing types are displayed under Agda's `AsIs` enumeration, whereas selected goal/context displays use `Simplified`. They need not be textually equal. `outputForms` contains displayed constraints concerning the selected goal, not a structured solver state; `boundary` contains displayed cubical boundaries, not source positions. Empty arrays are valid and do not prove that all constraints or global declarations are absent. [3] [4] [5] [6]

Agda's native intervals contain positive, one-based `pos`, `line`, and `col` endpoints. Positions advance by characters, not UTF-8 bytes; ends are exclusive. Intervals contain no native filename in the verified serializers. File association comes from the explicitly loaded main file and retained request, not an invented `range.file` field. The verifier checks interval shape/order and a coarse file-size upper bound; a source manifest alone is not enough to reconstruct exact line/character boundaries offline. [5] [6]

## Saved format and verification

`agda-evidence/goal-observation-v1` is separate from type, client, bundle, index, and catalog records. Its [schema](../schemas/goal-observation-v1.schema.json) uses adjacent schema references, so keep the schema files together. The envelope includes its source snapshot, partial native resolution, explicit operation/policy, anchored argv, timestamps, bounded phased responses, transport diagnostics, and a response-derived result.

An inspection embeds the full accepted **leaf listing**, so selection can be verified without a dangling local path. Recursive inspection histories are rejected. Its `observationId` hashes the entire canonical envelope except its own ID field, including the embedded listing. It is time-specific, not a persistent goal identity.

`goals verify` recomputes source/resolution/whole-artifact identities, file and policy bindings, prior-listing selection and capture order, fresh ID/range agreement, exact read-only requests, phase order, anchored argv, and result agreement with retained responses. It runs no Agda, reads no live project tree, and applies no source actions. Internally valid failed/blocked records also verify successfully; check `result.status` to distinguish success.

Success statuses are `listed` and `inspected`. Other saved outcomes are `load-error`, `load-blocked`, `selection-error`, `query-error`, `protocol-error`, `execution-error`, `timed-out`, and `output-limit`. Selected type/context is null unless inspection succeeded. Parsed load inventories can remain available in a failed later query; diagnostics and partial phases remain recorded without promoting them to a successful inspection.

List/inspect exit zero only for their successful statuses. A saved failure or evidence/pin failure returns one; invalid configuration returns two. Preflight/staged-source failures write no record. Offline verification returns zero for any internally valid record, including a failure. Records can contain source-derived names and compiler messages; inspect them before sharing.

## Scope limits

An inspected goal is still an unfilled proof obligation. `--safe` records the requested compiler setting but does not complete the proof or certify informal mathematical intent. This adapter does not weaken clean-only inference or enable proof actions. It handles one existing native project, not Nix activation or implicit dependencies; client/library composition for unfinished goals is a separate future adapter.

The original source is not used as the writable working copy, and staged regular inputs are hashed before/after queries. Loading can write interface caches for clean dependencies or compiler-provided primitives even with `--ignore-interfaces`. Copy isolation is not a hostile-compiler security sandbox or a promise of no host filesystem/network effects. [1] [2]

Snapshots are file manifests, not source archives. Hashes establish internal consistency, not producer authenticity or protection against a consistently fabricated transcript. These records support inspection/research provenance, not offline source/toolchain replay or a proof certificate.

The [2 November 2026 native pilot result](pilots/goals-result-2026-11-02.md) records the successful remote run, five independently verified record identifiers, exact source/compiler subjects, and artifact download/verification commands. Run `python scripts/goals-pilot.py --agda-bin /usr/bin/agda --output /tmp/native-goals-pilot` from a checkout to repeat its fixture with a new output directory.

## References

[1]: https://raw.githubusercontent.com/agda/agda/v2.6.3/src/full/Agda/Interaction/InteractionTop.hs "Agda v2.6.3 combined goal command, load continuation and checked status"
[2]: https://raw.githubusercontent.com/agda/agda/v2.8.0/src/full/Agda/Interaction/InteractionTop.hs "Agda v2.8.0 combined goal command, load continuation and checked status"
[3]: https://raw.githubusercontent.com/agda/agda/v2.6.3/src/full/Agda/Interaction/BasicOps.hs "Agda v2.6.3 goal enumeration, context and diagnostic filtering"
[4]: https://raw.githubusercontent.com/agda/agda/v2.8.0/src/full/Agda/Interaction/BasicOps.hs "Agda v2.8.0 goal enumeration, context and diagnostic filtering"
[5]: https://raw.githubusercontent.com/agda/agda/v2.6.3/src/full/Agda/Interaction/JSONTop.hs "Agda v2.6.3 goal, context, interval and constraint display serializers"
[6]: https://raw.githubusercontent.com/agda/agda/v2.8.0/src/full/Agda/Interaction/JSONTop.hs "Agda v2.8.0 goal, context, interval and constraint display serializers"
