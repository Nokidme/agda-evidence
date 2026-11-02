# Read-only goal/context result — 2 November 2026

Read-only unfinished-goal observation support shipped in [85aa0ef](https://github.com/Nokidme/agda-evidence/commit/85aa0ef98009fd73da138908333fcfd280d5b591). The [native pilot run 41523267002](https://github.com/Nokidme/agda-evidence/actions/runs/41523267002) passed on Ubuntu 24.04 using installed Agda 2.6.3, including its strict unchanged-checkout check. The [implementation CI](https://github.com/Nokidme/agda-evidence/actions/runs/41523234863) passed on Python 3.11 and 3.12.

The uploaded unfinished listing, three selected inspections, and completed-module empty listing were downloaded and independently verified in the development environment. All five passed semantic verification and their JSON Schema. Each inspection's complete embedded leaf listing exactly matched the uploaded listing. The recorded source identity matched a fresh snapshot of the committed example. Native runtime validation here is for Agda 2.6.3; the combined command and serializers were also checked against upstream v2.8.0 source, not a new v2.8.0 runtime run.

## Actual unfinished proof context

The [example Main.agda](../../examples/goal-query/Main.agda) contains three ordinary typed interaction points, selected from its saved listing rather than assumed universal IDs:

- Goal 0: displayed type `Nat`, local entry `n : Nat`.
- Goal 1: displayed type `Nat`, local Unicode entry `λ₁ : Nat`.
- Goal 2: displayed dependent type `n ≡ n`, local entry `n : Nat`.

The listing's last native load status was **`checked: false`** and remains false in each retained listing. Inspection succeeded without pretending these unfilled obligations were checked proofs. Each selected context retained its original/reified names, string binding, boolean `inScope`, and empty `boundary`/`outputForms` arrays. Empty arrays are observations from these examples, not a proof that arbitrary constraints are absent.

`Complete.agda` produced an accepted empty interaction-point listing. No hole was filled, source action applied, or proof-search command sent. All five saved observations verified locally without rerunning Agda. Original regular source and original-tree interface checks passed in the pilot.

## Exact retained identities

```text
unfinished listing: sha256:03cda95e2048c0ba7168a9449a6228919dc9d9ccc9d45e0f19fa64c47898d73b
selected goal 0:    sha256:64bd8f6b52a96ae718c6fbbbe199755e96925ea11269ada04be31253fc2e57f4
selected goal 1:    sha256:d5c4236483b7d3d7b86a7f4a6389bc2e932fa221128ef3f035014f0f0dd71474
selected goal 2:    sha256:9563ccbb74fd5ddb79cc1a6b9761325f73b8c2e100074ab7436d2105dff50439
empty listing:      sha256:516e08780156d28593651f67cb844b9f1725b3c4bb4db2265ea8c45fa66341c5
sourceId:           sha256:8d6243e60517ca8a08a9edcb6888d41269def7d369d174f3ef1e21727a01d076
resolutionId:       sha256:5d96ead6f9d4e407766c18d2c1c42f6e0e9e594444378d6668255c2774df7f3e
compiler binary:    sha256:852806142a15951f667df303c73cfce5f4123218ce6e1f1b29acaddc242af00d
```

These are whole-observation/time-specific IDs and source/native-environment subjects, not persistent hole identities. Agda interaction IDs belong to their load context. The complete listing is embedded in each inspection, and fresh source/resolution pins plus a reloaded ID/range check precede the selected query.

## Reproduce record verification

From a new download directory and an installed current `agda-evidence`:

```sh
mkdir downloaded-goals-pilot
gh run download 41523267002 --repo Nokidme/agda-evidence \
  --name native-goals-pilot-85aa0ef98009fd73da138908333fcfd280d5b591 \
  --dir downloaded-goals-pilot

for file in listing.json goal-0.json goal-1.json goal-2.json empty.json; do
  agda-evidence goals verify "downloaded-goals-pilot/$file"
done
```

The download requires GitHub access/network, and the artifact retention is 30 days from the workflow. Subsequent record verification runs no Agda and reads no live source checkout. To run the source fixture again instead of just verifying retained records:

```sh
python scripts/goals-pilot.py --agda-bin /usr/bin/agda \
  --output /tmp/new-native-goals-pilot
```

For manual selection, use `goals list`, choose an actual ID, then `goals inspect --listing ... --goal-id ...`; see the [goal guide](../goals.md). Inspection inherits the file, includes, safe policy and rewrite/load policy, rather than allowing silent replacements.

## Regression coverage and corrected defect

All **100 local unittest methods** passed. Sixteen focused methods cover real-pipe fake-compiler contracts plus optional real Agda integration. Real coverage includes multiple plain/explicit holes, Unicode/dependent context, zero goals, fatal missing-name errors, benign warning refusals, termination errors and unsolved constraints. Deterministic fixtures cover invisible named metas including a `JustSort` without a `type` field, non-dense IDs, false checked state, strict inventories/ranges, distinct AsIs versus Simplified type text, structured out-of-scope local entries, boundary/constraint display arrays, query Error despite OS exit zero, fragmented prompts, EOF, timeout, combined output limits, exact source/native-resolution pins, stale selections, staged/original mutations, offline verification, corruption after rehash, nested-history rejection, CLI guards and exit codes.

Tests exposed a JSON scalar-type validation defect: Python structural equality equates `False` with `0`. A result-only Boolean goal ID or numeric `inScope` could therefore compare equal to correctly typed retained data after rehashing. The goal verifier now compares canonical JSON results, preserving JSON Boolean/integer distinctions; both mutations are permanent rejection regressions. The completed-module checker's clean-load policy and earlier artifact formats were not weakened or migrated.

Ordinary CI skips optional installed-real-Agda tests when no executable is present. The manual native workflow supplements those tests and archives the five real records. Distro installation records the observed compiler but does not archive or lock the complete apt dependency set.

## Scope stop

This release provides read-only goal/context evidence for one native project. It does not check a proposed proof term, fill holes, run auto/refine/case splitting, activate Nix, mount selected library evidence, or certify a completed theorem. It deliberately blocks nonempty warning/nonfatal-error summaries under `unfinished-no-diagnostics-v1`; a blocked unfinished load is not mislabeled as a native fatal error.

Native load can create interface caches outside regular-source identity policy; isolated copies are not hostile-compiler security sandboxes. Snapshots remain file manifests rather than source archives, and hashes prove internal consistency rather than producer authenticity. Retained verification is not offline source/toolchain replay. See the [goal contract](../goals.md) for exact policies and limits.
