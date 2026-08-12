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

### ⚠️ This bucket is no longer reachable

**As of 2026-08-12 the bucket returns `403 AllAccessDisabled` for every object and for
the bucket listing.** That is an AWS-level shutdown of the whole bucket, not a
permissions change by the owner. There is no Internet Archive capture of the objects.

Consequences, stated plainly:

- The Hazus 6.1 flood and hurricane workbooks **can no longer be downloaded from their
  original location by anyone**, including us.
- We hold copies whose SHA-256 matches what was recorded at retrieval time
  (2026-07-26), and we now re-host them as assets on the
  [v0.1.0 release](https://github.com/rkvaughn/hazus-curves/releases/tag/v0.1.0).
  `scripts/fetch.py` falls back to that mirror automatically and **refuses any mirrored
  file whose hash does not match `raw/MANIFEST.json`**, which is committed to this
  repository.
- Nobody can now independently re-download the originals and compare bytes with us. That
  verification path is closed, and no amount of care on our part reopens it.

### What can still be verified independently

**1. The origin claim is checkable in public source code.** os-climate/physrisk
(Apache-2.0, actively maintained) names this exact bucket and path in
`src/physrisk/vulnerability_models/configuration/hazus_config_builders.py`:

```python
s3 = s3fs.S3FileSystem(anon=True)
s3.download(str(PurePosixPath("os-climate-physical-risk") / "vulnerability" / filename), ...)
```

and reads the sheets `huListOfWindBldgTypes`, `huDamLossFunDescription` and
`huDamLossFun` from `HazusWindDamFunctions_Hazus61.xlsx`. OS-Climate is a real
organisation (96 public repositories, os-climate.org). This establishes where the files
came from; it does not establish how OS-Climate obtained them, which remains
undocumented upstream.

**2. The flood workbook agrees exactly with a FEMA publication.** The 6.1 workbook
carries a sheet `flBldgStrucDmgFn (2)` holding the pre-6.1 structure library. Compared
against FEMA's own FAST 4.0 CSVs — still live on GitHub:

> **597 curves, 17,313 values, zero discrepancies.**

Reproduce with `python scripts/diff_versions.py`.

**3. The hurricane workbook agrees with the FEMA Technical Manual on four independent
counts.** This matters because check 2 says nothing about the wind data. Each of these
is verifiable against a PDF you can download yourself:

| Check | FEMA Technical Manual 7.0 | This workbook |
|---|---|---|
| Wind building characteristics | *"there are 62 individual WBCs"* | **62** distinct codes |
| Specific building types | 39, named in Table C-1 | **39**, all names match |
| Damage function count | *"over 275,000 damage functions"* | **275,220** = 6,116 × 5 × 9 |
| Multi-family defect (7.1 notes) | 2-/3-story overwritten with 1-story | **15,200** confirmed duplicates |

The last is the strongest of the four. FEMA's Hazus 7.1 release notes disclose a
specific, non-obvious defect in the 6.1 wind data; that defect is present in this
workbook and reproducible at row level. A re-derived or synthetic dataset would not
carry it.

Note that check 1 also explains the nine "missing" characteristic codes recorded in
`data_quality.md`: 53 documented + 9 undocumented = the 62 the manual states.

### What remains unverified

- How OS-Climate obtained the workbooks from Hazus. Not documented anywhere we could
  find.
- Whether the hurricane workbook is byte-faithful to the Hazus 6.1 SQL Server tables. The
  four checks above are strong structural evidence, not proof of every cell.
- Why the bucket was disabled. We have no information, and it would be irresponsible to
  speculate about whether it relates to the contents.

If byte-level fidelity to an official source matters for your use, the only authoritative
route is a licensed Hazus install on Windows with ArcGIS Pro. This project exists because
that route is closed to most researchers, not because it is equivalent.

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

### Building characteristic labels in the web tool

Most Hazus building characteristic values are already plain English ("Wood Truss",
"Toe-nail", "Low"/"Medium"/"High") and are shown verbatim. A few are engineering
shorthand, and the web tool shows a readable label for those:

| Hazus value | Shown as | Source |
|---|---|---|
| `6d @ 6"/12"` | Six-penny nails — 6" edge / 12" field spacing | HU TM 7.0 p. 553 |
| `8d @ 6"/12"` | Eight-penny nails — 6" edge / 12" field spacing | same notation |
| `6d/8d Mix @ 6"/6"` | Mixed six/eight-penny nails — 6" edge / 6" field spacing | same notation |
| `8D @ 6"/6"` | Eight-penny nails — 6" edge / 6" field spacing | HU TM 7.0 p. 553 |
| `OWSJ` | Open-web steel joist (OWSJ) | HU TM 7.0 acronym list |
| `SFBC 1994` | South Florida Building Code 1994 (SFBC) | HU TM 7.0 |
| `Res./Comm.` | Residential / commercial | — |

The nailing notation is spelled out by FEMA directly: *"six penny roof panel nailing at
6-inch spacing on the edges and 12-inch spacing in the field ('6d @ 6"/12" roof deck
attachment')"*. Two of the four values are quoted from that sentence and its companion
for `8d @ 6"/6"`; the other two apply the same stated `<size> @ <edge>/<field>` grammar.

These labels are display-only. The underlying value is never rewritten — the query still
filters on the exact stored string, and each option carries a tooltip showing it. Note
that Hazus is internally inconsistent about case here (`8D @ 6"/6"` in `bcName` versus
`8d` in `bcDescription`), so the lookup key must match the data byte for byte.

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
