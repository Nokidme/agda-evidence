# Offline evidence accounting acceptance — 6 November 2026

## Result and scope

The development diagnostic `scripts/evidence-accounting.py` verifies explicit saved observations and reports canonical envelope/section sizes plus a FIFO history simulation. It does not invoke a compiler, inspect live source trees or measure process memory. No runtime module, evidence schema or published `v0.1.0a2` tag was changed.

Two fresh consumers, one installed from the development wheel and one from its source archive, processed the same five retained source-observation records from [the 3 November source research pilot](source-research-result-2026-11-03.md). Their diagnostics were identical, original input bytes remained unchanged, and an independent acceptance runner recomputed input/canonical digests, section sizes, framing and FIFO totals.

**These are existing older-fixture records, not results from the proposed complete-stdlib-2.0 editor sizing experiment.** The original editor experiment stopped at aggregate-resource enforcement preflight without native capture. That workload's memory, CPU, runtime and complete-envelope costs remain unmeasured.

## Recorded subjects and measurements

The retained fixture's dependency snapshot describes 1,050 files / 4,448,963 recorded source bytes; its client describes four files / 866 bytes. Snapshot file-size sums concern recorded source manifests, not current source availability, actual Python allocations or bytes of source text embedded in evidence.

Dependency source subject: `sha256:408cd9cf9dea398dc8595b5f032b0e51c3fb3db53fcc1c2a108701cb584e546c`.

Dependency bundle subject: `sha256:58be3c421c2aa9a5692f775db8c5b6c3607a1bd74ef6e2679d7e2ebb973ae333`.

| Arrival | Retained artifact | Original native status | Canonical envelope bytes |
|---|---|---|---:|
| 0 | `listing.source.json` | `listed` | 345,424 |
| 1 | `context.source.json` | `inspected` | 876,275 |
| 2 | `symmetry.source.json` | `elaborated` | 876,849 |
| 3 | `wrong-type.source.json` | `query-error` | 875,834 |
| 4 | `catalog-not-mounted.source.json` | `query-error` | 875,877 |

Original serialized inputs total **3,850,264 bytes**; canonical complete payloads total **3,850,259 bytes**. Each input has one trailing newline, excluded from the facade's canonical history representation.

The current embedded dependency-evidence section is 157,489 canonical bytes per record. Each selected context/trial record retains a complete outer source listing of 345,424 bytes and a native listing inside the current native observation of 184,273 bytes. The diagnostic reports those independently; other nested sections can overlap them and must not be summed indiscriminately. Top-level member-value sizes plus separately measured framing exactly equal the complete envelope size. Original records and priors were not replaced with summaries or references.

With an explicitly simulated **three-record / 8,388,608-byte** history, the final retained arrivals are **2, 3 and 4**, totaling **2,628,560 canonical payload bytes**. This is a deliberately small hypothetical FIFO budget, not a changed host policy. Valid native failures are not filtered out. Each repeated input would be a new arrival; an individually oversized artifact would be refused without evicting previously retained records.

## Validation

The complete local library regression suite passed **327 tests**, including the new offline cases. No production modules or schemas changed, and the published second-alpha tag remains fixed at its original commit.

Seventeen independent unit tests cover all five observation formats using synthetic but genuinely validator-accepted records. They block subprocess and socket creation while testing the accounting path. Cases include complete embedded evidence/prior validation, same-ID and rehashed semantic tampering, exact Unicode/raw binding, strict JSON, positive scalar limits, bounded reads, output/input alias refusal, original-byte preservation and 120 seeded differential FIFO comparisons.

Fresh development wheel and source installations passed ordinary package smoke checks. Their existing tiny native package fixtures also passed with actual **Agda 2.6.3**, followed by strictly offline accounting of the saved source listing/context/trial. These are separate routine regression checks, not a rerun of the blocked whole-library benchmark or evidence of target 2.6.4.3 runtime equivalence.

The independent review found no material issue within the documented trusted, stable-filesystem and diagnostic-only scope. Future CI should continue testing complete saved inputs and must not equate diagnostic verification with producer authenticity or proof completion.

## Reproduction

Use an installed package and the development script from outside the checkout:

```sh
/path/to/venv/bin/python -I /path/to/scripts/evidence-accounting.py \
  --artifact /path/to/listing.source.json \
  --artifact /path/to/context.source.json \
  --artifact /path/to/symmetry.source.json \
  --artifact /path/to/wrong-type.source.json \
  --artifact /path/to/catalog-not-mounted.source.json \
  --max-records 3 --max-stored-bytes 8388608 \
  --output /path/to/existing-directory/accounting.json
```

The output must not exist. Review [the diagnostic contract](../evidence-accounting.md) for exact input caps, full validators, non-additive section fields, failure handling and filesystem assumptions.

## Next boundary

This tool makes evidence storage costs inspectable without compiler execution. It cannot establish safe whole-process CPU/RAM containment or production capacity. The blocked editor experiment still needs an existing verifiably capped development scope, or separately approved precise temporary resource-scope setup and cleanup. No such infrastructure change, app activation, backend modification or deployment follows from this diagnostic acceptance.
