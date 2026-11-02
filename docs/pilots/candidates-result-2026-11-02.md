# Non-filling candidate trial result — 2 November 2026

Candidate trials shipped in [b1b6f90](https://github.com/Nokidme/agda-evidence/commit/b1b6f9047f9cfc8cace4e4f04ea8e2dc3ea52c4c). The [native pilot run 41525995772](https://github.com/Nokidme/agda-evidence/actions/runs/41525995772) passed on Ubuntu 24.04 with observed Agda 2.6.3 and an unchanged original source checkout. [Implementation CI](https://github.com/Nokidme/agda-evidence/actions/runs/41525960037) passed on Python 3.11 and 3.12. Runtime results below are from Agda 2.6.3; v2.8.0 command/serializer/local-state semantics were also researched from pinned upstream source, not a new v2.8.0 runtime run.

The listing and all seven trial records were downloaded and independently checked against their semantic verifiers and JSON Schemas. Every trial embedded the exact uploaded accepted leaf listing, matched its source/native-resolution subjects, and retained the unfinished load's `checked: false`. The source identity matched a fresh snapshot of the committed example. For every positive trial, the entire postflight `AllGoalsWarnings` summary exactly equaled the fresh load summary, retaining all three source goals.

## Actual trials

The example is [Main.agda](../../examples/goal-query/Main.agda); IDs below are observations for this source/compiler load, not permanent identifiers.

- `n` at goal 0 (`Nat`, local `n : Nat`): **elaborated**, displayed term `n`.
- `λ₁` at goal 1 (`Nat`, Unicode local `λ₁ : Nat`): **elaborated**, displayed term `λ₁`.
- `refl` at goal 2 (`n ≡ n`): **elaborated**, displayed term `refl`.
- `λ x → x` at goal 0: **query-error**, native expected-type mismatch retained.
- `notInScope` at goal 0: **query-error**, native absent-name diagnostic retained.
- `_` at goal 0: **query-error**, native internal Error retained. This compiler cannot render that speculative temporary meta after state restoration; the record is not relabeled as a meaningful type mismatch or as proof that checking prohibits holes.
- `let x = _ in refl` at goal 2: **elaborated**, displayed term `refl`. This intentionally demonstrates why elaboration and empty restored diagnostics do not establish candidate-local obligation freedom.

All records say `assurance: contextual-elaboration-only`. No candidate was inserted and no selected source goal was filled. The dedicated command checks the expression against the contextual expected type, but restores its temporary checker state before producing the goal display. Postflight therefore observes restored source goals, not discarded candidate-local constraints, metas or warnings. Even a positive trial is not an insertion/termination result or a completed-proof certificate. See the [candidate contract](../candidates.md) and its pinned protocol sources.

## Retained evidence identities

```text
listing:         sha256:340e74ad3e5171fc4291b8055ae5008dce30bde3bc6266314a78c9c6b7db260d
nat-local:       sha256:0aa45c78fcb079dcacaa6d8472afaa9c15646701c5fe9bfd424c8d89bf608514
unicode-local:   sha256:1e00025a4f9ef075a89c963bd8e157d039beb064e64de6ed143ff5b7d98bb237
reflexivity:     sha256:ee2598f854ea5bcad3583b099f70f008daccdd6c7f48d4f1bf4fdff7ca7ba8f1
wrong-type:      sha256:5b6da89bfc68f76129c19f378419a0b0e9b31b110b2dcef90ec8e428daf7c9b2
out-of-scope:    sha256:ac69dbabbaa65cd1ebfc36284b202134a79369dcff96f03b32698c8bf6e72d7a
bare-underscore: sha256:18eeced1896b30e175d67d10ead3e769290d94ff777e14fcb73be597f7b43073
unused-meta:     sha256:f69ed5c40537bee82c7c0d8752f9c10762dbdc84b6e126d2dd7f0d8920f3c801
sourceId:        sha256:8d6243e60517ca8a08a9edcb6888d41269def7d369d174f3ef1e21727a01d076
resolutionId:    sha256:5d96ead6f9d4e407766c18d2c1c42f6e0e9e594444378d6668255c2774df7f3e
compiler binary: sha256:852806142a15951f667df303c73cfce5f4123218ce6e1f1b29acaddc242af00d
```

Source and resolution IDs match the earlier native goal pilot's subjects. Whole observation IDs are time-specific and change on recapture.

## Download and verify without rerunning Agda

From an installed current `agda-evidence`, create a new download directory:

```sh
mkdir downloaded-candidates-pilot
gh run download 41525995772 --repo Nokidme/agda-evidence \
  --name native-candidates-pilot-b1b6f9047f9cfc8cace4e4f04ea8e2dc3ea52c4c \
  --dir downloaded-candidates-pilot

agda-evidence goals verify downloaded-candidates-pilot/listing.json
for record in downloaded-candidates-pilot/*.candidate.json; do
  agda-evidence goals verify-check "$record"
done
```

GitHub access/network is needed for the download, and the workflow artifact retention is 30 days. After download, verification itself runs no compiler and reads no live source tree. Verification success also applies to internally valid failed trials: inspect `result.status` rather than interpreting a successful verification exit as expression success. The summary file is a convenience report, not independently authoritative evidence.

To repeat the fixture against a new native session instead of verifying the retained records:

```sh
python scripts/candidates-pilot.py --agda-bin /usr/bin/agda \
  --output /tmp/new-native-candidates-pilot
```

The bare-underscore case records either elaboration or query Error on other supported native versions; the observed 2.6.3 run here returned Error. Its presence never upgrades the assurance claim.

## Tests and compatibility

All **117 local unittest methods** passed, including optional installed-real-Agda tests. Sixteen focused candidate methods use independent real-pipe fake-compiler fixtures and real native trials. They cover exact Unicode/control-character wire encoding, the 65,536-byte UTF-8 input cap, structured elaboration/context responses, rich and numeric IDs, source/registry/compiler pins, source-copy mutation guards, exact restored-summary comparison with JSON Boolean/integer distinctions, query and postflight Errors, unsupported editing/search responses, timeouts/EOF/output limits, rehashed corruption, invalid recursive/inspected prior history, offline verification and CLI exit/output guards.

Focused tests found that a negative runtime selector was classified as an evidence failure (exit 1) instead of invalid configuration (exit 2). It already launched no interaction and wrote no output. Runtime selector validation now uses the correct configuration error; offline malformed evidence still returns a validation failure. Earlier goal and type formats are unchanged. The previously downloaded Unicode goal record from run 41523267002 still verifies under its original complete ID after the shared source-copy capture refactor.

Ordinary Python CI does not install Agda and skips optional native tests when absent; the separate manual native pilot supplies these real recorded results. The observed compiler binary is hashed, but the apt dependency closure and source contents are not archived. Hash consistency does not authenticate a producer or resist consistently fabricated transcripts. Isolated project copies do not sandbox a hostile compiler or reflection side effects. This milestone is finite, non-filling research assistance, not proof search, insertion, dependency replay or proof certification.
