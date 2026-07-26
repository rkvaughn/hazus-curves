# Provenance

Where every number in this repository comes from, and how far it can be traced.

The machine-readable version of this is `raw/MANIFEST.json` (SHA-256, byte size, URL and
retrieval time for every source file) and the `provenance` table inside the database.
Every row in `curves` carries `source_file`, `source_table`, and `source_row_id`, so any
published value can be traced back to the exact source cell.

## The acquisition problem

Hazus is a Windows-only ArcGIS Pro application backed by SQL Server, requiring roughly
50 GB of disk and a licensed ArcGIS Pro install. Its damage functions live in the
application's database. There is no official standalone download of the curve tables,
and no API.

This project therefore assembles the curves from two public sources that had already
escaped that enclosure.

## Source 1 — Hazus 4.0 flood, published by FEMA

`https://github.com/nhrap-hazus/FAST/tree/main/Lookuptables`

FEMA's Flood Assessment Structure Tool repository contains direct CSV dumps of the Hazus
SQL tables — the filenames *are* the Hazus table names (`flBldgStructDmgFn`,
`flBldgContDmgFn`, `flBldgInvDmgFn`). `Lookuptables/README.txt` states:

> DDFs and other tables were obtained from Hazus 4.0 SQL database. We verified that no
> additions, changes, or deletions to the DDFs occurred in Hazus 3.1, 3.2, and 4.0.

This is the strongest provenance in the project: FEMA published it itself. The repository
is GPL-3.0 (covering the code; it says nothing about the data) and was last updated
2022-03-30.

Note that the same README points at a FEMA S3 snapshot bucket, `fema-ftp-snapshot`. That
bucket **no longer exists** — we checked. It is a useful reminder that the sources this
project depends on decay, which is why we mirror them.

## Source 2 — Hazus 6.1 flood and hurricane, third-party mirror

`https://os-climate-physical-risk.s3.amazonaws.com/vulnerability/`

A public, anonymously readable S3 bucket belonging to
[os-climate/physrisk](https://github.com/os-climate/physrisk), an actively maintained
Apache-2.0 project that implements Hazus wind vulnerability. It holds:

| File | Size | Content |
|---|---:|---|
| `HazusFloodDamageFunctions_Hazus61.xlsx` | 403,618 B | Hazus 6.1 flood tables |
| `HazusWindDamFunctions_Hazus61.xlsx` | 102,182,624 B | Hazus 6.1 hurricane tables |
| `flUtilFltyDmgFn.csv` | 7,480 B | Utility facility damage functions |

The worksheets inside are named for authentic Hazus database tables — `huDamLossFun`,
`huListOfWindBldgTypes`, `huDamLossFunDescription`, `flBldgStrucDmgFn` — and their row
counts match FEMA's published descriptions of the model (6,116 wind building types,
39 specific building types, "over 275,000 damage functions").

### The honest caveat

**How os-climate obtained these Excel extracts is not documented upstream.** They are not
a FEMA publication. We are relying on a third party's copy.

### Why we publish them anyway

Because we were able to check it. The 6.1 flood workbook contains a sheet named
`flBldgStrucDmgFn (2)` holding the pre-6.1 structure library. We compared all 597 of its
curves, across all 29 depth values, against FEMA's own FAST 4.0 CSV:

> **Every value is identical. 597 curves, 17,313 values, zero discrepancies.**

That is independent evidence that this mirror reproduces Hazus data faithfully rather
than approximating or re-deriving it. It does not prove the hurricane workbook is equally
faithful — nothing available to us can prove that — but it materially raises confidence,
and it is a real check rather than an appeal to plausibility.

Reproduce it with `python scripts/diff_versions.py`.

## Source 3 — FEMA documentation

FEMA release notes and technical manuals, used to document version history and to supply
the hurricane building type names.

### Building type names

The wind workbook identifies building types by bare code (`WSF1`, `MMUH3`) and contains
no natural-language names for them — every sheet was checked. The names come from
**Table C-1, "List of SBT Abbreviations", Appendix C of the Hazus Hurricane Model
Technical Manual 7.0**, parsed programmatically by
`scripts/extract_building_types.py`. All 39 codes present in the data have a description
from that table.

They are parsed rather than transcribed, and a test re-parses the manual and requires the
published strings to match it exactly. Names like "Single Family Homes, 1 Story - Wood"
are easy to write plausibly from general knowledge and impossible to audit afterwards, so
the pipeline refuses to write a description it cannot cite: if a code has no entry in the
manual, the field stays empty and the site falls back to showing the bare code.

One wrinkle worth recording: Table C-2 immediately follows and reuses the same
`NN_SBT` row labels for per-region statistics, so a naive parse picks up rows like
`01_WSF1 01-Roof Shape Hip 13 26.9 34 ...`. The extractor stops at the first row whose
description carries a WBC number prefix, and a test asserts no such row reached the
published data.

`fema.gov` returns **HTTP 403 to every automated fetcher** we tried. The Internet Archive
serves the identical PDFs: prefix any fema.gov PDF URL with
`https://web.archive.org/web/2025id_/` and it returns HTTP 200 `application/pdf`. This is
how `scripts/fetch.py --docs` retrieves them, and it is the route by which the
earthquake and tsunami manuals become tractable for a future version.

## Known problems carried through from upstream

We republish these rather than fix them, because fixing them would mean inventing values.

1. **A FEMA-disclosed hurricane defect.** In Hazus 6.1 and 7.0, the 2- and 3-story
   multi-family wind curves were overwritten with copies of the 1-story curves. We
   independently confirmed this — 15,200 of 34,560 affected curves are byte-identical to
   their 1-story counterpart — and flagged them in the data. See
   `docs/hurricane_defect.md`.
2. **Out-of-range values in the wind workbook.** Some probabilities reach 1.001 and some
   loss ratios 1.000052. See `docs/data_quality.md`.
3. **An incomplete decode table.** Nine building characteristic codes used in
   `huListOfWindBldgTypes` have no entry in the workbook's own `huListOfBldgChar`
   dictionary. See `docs/data_quality.md`.

## What this project does not do

It does not compute, interpolate, adjust, smooth, or infer any damage value. The pipeline
renames columns and reshapes wide tables into long ones. Numbers pass through untouched,
and gaps stay gaps — a missing source value becomes `NULL`, never a filled-in estimate.
