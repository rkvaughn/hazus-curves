# Hazus flood damage function changes: 4.0 → 6.1 → 7.x

Two things are documented here. The 4.0 → 6.1 comparison is **measured** from
the data in this repository. The 6.1 → 7.x rows are **quoted** from FEMA
release notes and technical manuals, because the 7.x curve tables are not
publicly extractable.

## Measured: Hazus 4.0 → 6.1

Sources: FEMA's FAST repository CSVs (direct dumps of the Hazus 4.0 SQL
tables) versus `HazusFloodDamageFunctions_Hazus61.xlsx`.

| Damage type | 4.0 curves | 6.1 curves | Added | Removed | Values changed |
|---|---:|---:|---:|---:|---:|
| structure | 597 | 892 | 295 | 0 | 0 |
| contents | 507 | 818 | 311 | 0 | 0 |
| inventory | 116 | 116 | 0 | 0 | 0 |

**Hazus 6.1 was purely additive for flood.** 606 curves were added,
none were removed, and **0 existing curves had any value
changed**. Every curve that existed in Hazus 4.0 survives into 6.1 bit for bit.

This matters because it means results computed against the 4.0 library remain
reproducible under 6.1 — the expansion widened coverage without revising
existing curves.

### A note on FEMA's own count

The Hazus 6.1 release notes state that *"Almost 300 new structure and 400 new
content damage functions were added."* The structure figure matches this
extract closely (295 added). The content figure does not: this extract contains **311** new content functions, not ~400.
We report what the data contains. The discrepancy may mean the release note
counts something this extract does not include; it is not resolved here.

## Corroboration of the third-party mirror

The 6.1 workbook carries a sheet named `flBldgStrucDmgFn (2)` holding the
pre-6.1 structure library. Comparing it against FEMA's own FAST 4.0 CSV:

> **597 curves, identical in every one of the 29 depth values.**

The 6.1 workbook is mirrored by a third party (os-climate), and how they
obtained it is not documented upstream. This exact agreement with a
FEMA-published source is independent evidence that the mirror reproduces
Hazus data faithfully rather than approximating it.

## Documented: Hazus 6.1 → 7.x

Quoted from FEMA release notes and technical manuals (retrieved via the
Internet Archive; `fema.gov` blocks automated fetchers).

| Version | Date | Flood damage functions |
|---|---|---|
| 6.1 | Nov 2023 | Library expanded. New source families: Colorado State University, FEMA Risk MAP, USACE NACCS, USACE Sacramento. |
| 7.0 | Nov 2024 | **No curve data change.** Technical Manual §5.4.1.2 (Damage Function Library) is word-for-word identical to 6.1. What changed is the *selection rule*: coastal DDF assignment became depth-limited — Coastal V at ≥6 ft, Coastal A between 3 and 6 ft, riverine below 3 ft. |
| 7.1 | Sep 2025 | No flood change. |
| 7.2 | ~Jun 2026 | Unknown — the 7.2 release notes ship inside a CAPTCHA-gated download and were not retrieved. |

**Practical consequence:** the flood curve *values* published here are current
as of Hazus 7.1. What is version-dependent is which curve a given building
selects, and that is recorded in `assignment_rules`, not in the curve data.

Reproduce with `python scripts/diff_versions.py`.
