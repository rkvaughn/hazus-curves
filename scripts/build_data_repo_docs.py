#!/usr/bin/env python3
"""Generate the documentation shipped with the hazus-curves-data repository.

The data repository is consumed on its own -- by the web tool, and by anyone who wants
the Parquet without the Python package -- so it needs to explain itself without
referring back to code the reader does not have.

Everything here is derived from the schema definition and from the Parquet files
themselves: row counts, column types, null counts, distinct counts and sample values are
measured at build time, so the documentation cannot drift from the data it describes.

    python scripts/build_data_repo_docs.py --out ../hazus-curves-data
"""

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"
sys.path.insert(0, str(REPO))

from hazus_curves.schema import TABLES  # noqa: E402

MAIN_REPO = "https://github.com/rkvaughn/hazus-curves"
BROWSER = "https://rkvaughn.github.io/hazus-curves/"
DATA_BASE = "https://rkvaughn.github.io/hazus-curves-data/"

# Files that are hurricane-only slices of a combined table. They exist because the build
# produces them and the browser reads them; they duplicate rows already present in the
# combined file.
DERIVED_SLICES = {
    "curves_hu": "curves",
    "curve_points_hu": "curve_points",
    "curve_attributes_hu": "curve_attributes",
}


def profile(con, path: Path):
    """Measure a Parquet file: rows, and per-column type/nulls/distinct/sample."""
    src = f"read_parquet('{path}')"
    rows = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    cols = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
    out = []
    for name, dtype, *_ in cols:
        nulls, distinct = con.execute(
            f'SELECT count(*) FILTER (WHERE "{name}" IS NULL), '
            f'count(DISTINCT "{name}") FROM {src}'
        ).fetchone()
        sample = con.execute(
            f'SELECT DISTINCT "{name}" FROM {src} WHERE "{name}" IS NOT NULL LIMIT 3'
        ).fetchall()
        out.append({
            "name": name, "type": dtype, "nulls": nulls, "distinct": distinct,
            "sample": [str(s[0]) for s in sample],
        })
    return rows, out


def md_cell(value) -> str:
    """Escape a value for a markdown table cell.

    Several schema docstrings enumerate options as "Riverine | CoastalA | CoastalV",
    and an unescaped pipe silently splits the row into extra columns.
    """
    return str(value).replace("|", "\\|").replace("\n", " ")


def md_table(header, rows):
    aligns = "|" + "|".join("---" for _ in header) + "|"
    lines = ["| " + " | ".join(md_cell(h) for h in header) + " |", aligns]
    for r in rows:
        lines.append("| " + " | ".join(md_cell(c) for c in r) + " |")
    return "\n".join(lines)


def build_readme(con, stats):
    total_curves = stats["curves"]["rows"]
    total_points = stats["curve_points"]["rows"]
    perils = con.execute(
        f"SELECT peril, hazus_version, count(*) FROM read_parquet('{DIST}/curves.parquet') "
        f"GROUP BY 1,2 ORDER BY 1,2").fetchall()

    peril_rows = [
        ("flood" if p == "fl" else "hurricane wind", v, f"{n:,}") for p, v, n in perils]

    file_rows = []
    for name in sorted(stats):
        s = stats[name]
        note = ""
        if name in DERIVED_SLICES:
            note = f"hurricane-only slice of `{DERIVED_SLICES[name]}`"
        file_rows.append((f"`{name}.parquet`", f"{s['rows']:,}",
                          f"{s['bytes'] / 1e6:.1f} MB", note))

    return f"""# hazus-curves-data

Prebuilt data tables for **[hazus-curves]({MAIN_REPO})** — an open database of FEMA Hazus
damage and vulnerability curves.

This repository holds the data. It is designed to be usable on its own: the schema is
documented in [SCHEMA.md](SCHEMA.md), worked queries are in [EXAMPLES.md](EXAMPLES.md),
and where the numbers come from is in [PROVENANCE.md](PROVENANCE.md).

> Not affiliated with or endorsed by FEMA. "Hazus" is a trademark of the Federal
> Emergency Management Agency. See [Licence and reuse](#licence-and-reuse).

**Browse without downloading:** {BROWSER}

---

## What is in here

{md_table(["Peril", "Hazus version", "Curves"], peril_rows)}

**{total_curves:,} curves, {total_points:,} data points** in total.

Flood curves are depth-damage functions: depth in feet relative to the first finished
floor (−4 to +24 ft, 29 points per curve), damage as a percentage of replacement value,
split into structure, contents and business inventory.

Hurricane curves run over 3-second peak gust wind speed (50–250 mph in 5 mph steps), for
6,116 wind building types × 5 terrain roughnesses × 9 loss classes.

## ⚠️ Read this before using the hurricane data

**The nine hurricane loss classes do not share units.** Four are damage-state exceedance
probabilities, two are loss ratios, one is measured in **days**, and two are in
**lbs/sq ft**. Averaging or plotting them together produces a meaningless number.

Join the `curve_kind` table to get the units for any curve rather than assuming them.
[SCHEMA.md](SCHEMA.md#units) explains this in full.

## Files

{md_table(["File", "Rows", "Size", "Note"], file_rows)}

The three `_hu` files are hurricane-only slices of the combined tables, kept because the
web browser reads them directly. If you are working with this data yourself, prefer the
combined tables (`curves`, `curve_points`, `curve_attributes`) and filter on
`peril = 'hu'` — they contain the same rows plus flood.

## Quickstart

These files are Parquet, readable by most data tools without a download step.

```sql
-- DuckDB, straight over HTTP
INSTALL httpfs; LOAD httpfs;
SELECT c.curve_id, c.occupancy, p.x AS depth_ft, p.y AS pct_damage
FROM   read_parquet('{DATA_BASE}curves.parquet') c
JOIN   read_parquet('{DATA_BASE}curve_points.parquet') p USING (curve_id)
WHERE  c.occupancy = 'RES1' AND c.damage_type = 'structure'
  AND  c.hazus_version = '6.1'
ORDER  BY c.curve_id, p.x;
```

```python
import pandas as pd
curves = pd.read_parquet("{DATA_BASE}curves.parquet")
points = pd.read_parquet("{DATA_BASE}curve_points.parquet")
```

Prefer a local database, or another SQL engine? The companion Python package builds
SQLite, DuckDB, PostgreSQL or Snowflake from these same files in one command:

```bash
pip install "git+{MAIN_REPO}@v0.1.0"
hazus-curves install --perils fl,hu
```

More worked examples, including the hurricane joins, are in [EXAMPLES.md](EXAMPLES.md).

## Data quality flags you should not ignore

Two columns on `curves` carry warnings that travel with the data rather than living in a
footnote:

- **`defect_flag`** — non-null when FEMA has publicly disclosed a defect affecting this
  curve. Null means *no known defect*, not *verified correct*.
- **`defect_verified`** — our own measurement, kept separate from FEMA's disclosure.
  `identical_to_1_story` means the curve was measured to be a byte-for-byte duplicate of
  its 1-story counterpart.

{con.execute(f"SELECT count(*) FROM read_parquet('{DIST}/curves.parquet') WHERE defect_flag IS NOT NULL").fetchone()[0]:,} curves carry a defect flag and
{con.execute(f"SELECT count(*) FROM read_parquet('{DIST}/curves.parquet') WHERE defect_verified = 'identical_to_1_story'").fetchone()[0]:,} are confirmed duplicates. They are published rather than
withheld: a flagged curve is more useful than a missing one, and the corrected data is
not publicly extractable. See [PROVENANCE.md](PROVENANCE.md#known-defects).

## How this data was made

No damage value in these files was computed, interpolated, smoothed, clamped or inferred.
The pipeline renames columns and reshapes wide source tables into long ones; the numbers
pass through untouched, and a missing source value is preserved as `NULL` rather than
estimated.

Every row carries `source_file`, `source_table` and `source_row_id` identifying the
originating cell, and every input file is pinned by SHA-256. See
[PROVENANCE.md](PROVENANCE.md).

A 23-page report verifying this data against FEMA's own published manuals — with source
pages reproduced as screenshots — is in the main repository at
[`docs/Hazus_Data_Verification_Report.docx`]({MAIN_REPO}/blob/main/docs/Hazus_Data_Verification_Report.docx).

## Regenerating

Nothing here is authored by hand. To rebuild from FEMA sources:

```bash
git clone {MAIN_REPO}.git
cd hazus-curves
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/build_all.py --perils fl,hu
cp dist/*.parquet /path/to/hazus-curves-data/
.venv/bin/python scripts/build_data_repo_docs.py --out /path/to/hazus-curves-data
```

## Licence and reuse

The curves are, to the best of our understanding, works of the United States Government
and therefore not subject to domestic copyright under 17 U.S.C. § 105. We assert no
additional copyright over them and place no restrictions on their reuse.

Please cite FEMA and the originating agencies, and state which Hazus version you used.
The open questions on this — and there are some — are set out in full in
[LICENSE-DATA.md]({MAIN_REPO}/blob/main/LICENSE-DATA.md).

**Do not use these curves for life-safety decisions without independent verification
against the current official Hazus release.**
"""


def build_schema(con, stats):
    parts = [
        "# Schema reference",
        "",
        "Generated from the schema definition and measured against the Parquet files, so "
        "it cannot drift from the data.",
        "",
        "## Design in one minute",
        "",
        "Three layers:",
        "",
        "1. **`curves`** — one row per curve, carrying identity and provenance.",
        "2. **`curve_points`** — the curve itself, in long format: one row per "
        "`(curve_id, x)`. No measurements are encoded in column names.",
        "3. **`curve_attributes`** — a key/value table holding the dimensions that "
        "differ by peril (terrain, shutters, roof deck attachment, flood zone, …).",
        "",
        "The third layer is what lets one schema hold perils that are keyed completely "
        "differently. Flood curves are keyed by occupancy, zone, stories and basement; "
        "hurricane curves by building type, terrain and around a dozen construction "
        "characteristics. Rather than widening `curves` with columns that are null for "
        "most rows, peril-specific keys live as rows in `curve_attributes`. Adding "
        "earthquake later adds rows, not columns.",
        "",
        "## Units",
        "",
        "**`x` and `y` mean different things depending on the curve.** Join `curve_kind` "
        "on `(peril, damage_type)` rather than assuming.",
        "",
    ]

    kinds = con.execute(
        f"SELECT peril, damage_type, x_name, x_units, y_name, y_units "
        f"FROM read_parquet('{DIST}/curve_kind.parquet') ORDER BY peril, damage_type"
    ).fetchall()
    parts.append(md_table(
        ["peril", "damage_type", "x", "x units", "y", "y units"],
        [(p, d, xn, f"`{xu}`", yn, f"`{yu}`") for p, d, xn, xu, yn, yu in kinds]))
    parts += [
        "",
        "Note in particular that hurricane `loss_of_use` is measured in **days** and the "
        "two debris classes in **lbs/sq ft**. They are not ratios and must not be mixed "
        "with the loss curves.",
        "",
        "## curve_id format",
        "",
        "```",
        "flood:      fl-<hazus_version>-<damage_type>-<source_row_id>",
        "            e.g. fl-6.1-structure-129",
        "hurricane:  hu-<hazus_version>-<damage_type>-<wbID>-t<terrain_id>",
        "            e.g. hu-6.1-damage_severe-1-t1",
        "```",
        "",
        "The trailing identifier is the native Hazus primary key, preserved verbatim so "
        "any curve can be traced back to its source row.",
        "",
        "## Tables",
        "",
    ]

    for t in TABLES:
        if t.name not in stats:
            continue
        s = stats[t.name]
        parts += [f"### `{t.name}`", "", t.doc, "",
                  f"**{s['rows']:,} rows** · primary key "
                  f"`({', '.join(t.pk)})`", ""]
        rows = []
        docs = {c.name: c.doc for c in t.columns}
        for c in s["cols"]:
            filled = ("no nulls" if c["nulls"] == 0
                      else f"{c['nulls']:,} null ({100 * c['nulls'] / max(s['rows'], 1):.0f}%)")
            sample = ", ".join(f"`{v[:38]}`" for v in c["sample"][:2]) or "—"
            rows.append((f"`{c['name']}`", c["type"], f"{c['distinct']:,}", filled,
                         sample, docs.get(c["name"], "").replace("\n", " ")))
        parts.append(md_table(
            ["column", "type", "distinct", "nulls", "example values", "meaning"], rows))
        parts.append("")

    parts += [
        "## A note on the `_hu` files",
        "",
        "`curves_hu.parquet`, `curve_points_hu.parquet` and `curve_attributes_hu.parquet` "
        "are hurricane-only slices of the corresponding combined tables. They exist "
        "because the web browser queries them directly, and they duplicate rows already "
        "present in the combined files.",
        "",
        "For your own work prefer the combined tables and filter `peril = 'hu'`.",
        "",
    ]
    return "\n".join(parts)


def build_examples():
    return f"""# Worked examples

All queries run directly against the hosted Parquet — no download required. Substitute a
local path if you have cloned this repository.

```sql
INSTALL httpfs; LOAD httpfs;
SET VARIABLE base = '{DATA_BASE}';
```

For brevity the examples below write the URL out in full.

## Flood

### A single depth-damage curve

```sql
SELECT p.x AS depth_ft, p.y AS pct_damage
FROM   read_parquet('{DATA_BASE}curve_points.parquet') p
WHERE  p.curve_id = 'fl-6.1-structure-129'
ORDER  BY p.x;
```

### Every structure curve for single-family homes

```sql
SELECT c.curve_id, c.source_agency, c.description
FROM   read_parquet('{DATA_BASE}curves.parquet') c
WHERE  c.peril = 'fl' AND c.occupancy = 'RES1'
  AND  c.damage_type = 'structure' AND c.hazus_version = '6.1';
```

### Which curve does Hazus pick by default?

`assignment_rules` records Hazus's own default selection per building combination.

```sql
SELECT occupancy, stories, basement, flood_zone, curve_id
FROM   read_parquet('{DATA_BASE}assignment_rules.parquet')
WHERE  occupancy = 'RES1' AND damage_type = 'structure'
ORDER  BY flood_zone, stories;
```

### Curves valid in a given flood zone

`curve_zone_applicability` records which zones Hazus flags a curve as usable in. Note it
covers only the curves Hazus assigns — absence means *Hazus states no zone*, not *not
applicable*.

```sql
SELECT c.curve_id, c.occupancy, c.description
FROM   read_parquet('{DATA_BASE}curves.parquet') c
JOIN   read_parquet('{DATA_BASE}curve_zone_applicability.parquet') z
       USING (curve_id)
WHERE  z.flood_zone = 'CoastalV' AND c.damage_type = 'structure';
```

## Hurricane

### A fragility curve for one building type

```sql
SELECT p.x AS wind_mph, p.y AS prob_exceeding_severe
FROM   read_parquet('{DATA_BASE}curves.parquet') c
JOIN   read_parquet('{DATA_BASE}curve_points.parquet') p USING (curve_id)
WHERE  c.peril = 'hu' AND c.building_type = 'WSF1'
  AND  c.damage_type = 'damage_severe'
  AND  c.curve_id LIKE '%-t1'          -- terrain 1 = Open
LIMIT  41;
```

### Filter by construction characteristics

Characteristics live in `curve_attributes` as key/value rows.

```sql
SELECT DISTINCT c.curve_id, c.building_type
FROM   read_parquet('{DATA_BASE}curves.parquet') c
WHERE  c.peril = 'hu' AND c.damage_type = 'damage_total'
  AND  EXISTS (SELECT 1 FROM read_parquet('{DATA_BASE}curve_attributes.parquet') a
               WHERE a.curve_id = c.curve_id
                 AND a.key = 'Shutters' AND a.value = 'Yes')
  AND  EXISTS (SELECT 1 FROM read_parquet('{DATA_BASE}curve_attributes.parquet') a
               WHERE a.curve_id = c.curve_id
                 AND a.key = 'Roof Shape' AND a.value = 'Hip');
```

### Curves applicable in a territory

Hazus geographic cases are **set-valued** — `ContUS+Hawaii` applies in both CONUS and
Hawaii. Matching the raw case with `=` silently drops most applicable curves, so join
`dim_geographic_case` and match on territory instead.

```sql
SELECT count(DISTINCT c.curve_id)
FROM   read_parquet('{DATA_BASE}curves.parquet') c
JOIN   read_parquet('{DATA_BASE}curve_attributes.parquet') a
       ON a.curve_id = c.curve_id AND a.key = 'geographic_case'
JOIN   read_parquet('{DATA_BASE}dim_geographic_case.parquet') g
       ON g.case_name = a.value
WHERE  c.peril = 'hu' AND g.territory = 'Hawaii';
```

### Exclude curves with a known FEMA defect

```sql
SELECT c.curve_id, c.building_type, c.defect_verified
FROM   read_parquet('{DATA_BASE}curves.parquet') c
WHERE  c.peril = 'hu' AND c.defect_flag IS NULL;      -- no disclosed defect
```

## Always check units

```sql
SELECT k.peril, k.damage_type, k.x_units, k.y_units, k.notes
FROM   read_parquet('{DATA_BASE}curve_kind.parquet') k;
```

## Evaluating a curve between published points

Hazus curves are piecewise linear between published points. The companion Python package
implements this, and refuses to extrapolate beyond a curve's published domain:

```python
from hazus_curves import connect, damage
con = connect()
damage(con, "fl-6.1-structure-129", 3.5)   # % structure damage at 3.5 ft
```

Rolling your own: interpolate linearly between the two bracketing `x` values, and do not
read past the first or last point — a curve that stops at 24 ft says nothing about 30 ft.

## Python

```python
import duckdb
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
df = con.execute(\"\"\"
    SELECT c.occupancy, p.x AS depth_ft, p.y AS pct_damage
    FROM read_parquet('{DATA_BASE}curves.parquet') c
    JOIN read_parquet('{DATA_BASE}curve_points.parquet') p USING (curve_id)
    WHERE c.curve_id = 'fl-6.1-structure-129'
    ORDER BY p.x
\"\"\").df()
```

## R

```r
library(arrow)
curves <- read_parquet("{DATA_BASE}curves.parquet")
points <- read_parquet("{DATA_BASE}curve_points.parquet")
merge(curves[curves$curve_id == "fl-6.1-structure-129", ], points)
```
"""


def build_provenance(con):
    prov = con.execute(
        f"SELECT source_file, hazus_version, bytes, sha256 "
        f"FROM read_parquet('{DIST}/provenance.parquet') ORDER BY source_file"
    ).fetchall()
    rows = [(f"`{f}`", v, f"{b:,}", f"`{h[:16]}…`") for f, v, b, h in prov]

    return f"""# Provenance

Where every number in these files comes from. The full account, including the parts that
could not be verified, is in the main repository at
[docs/provenance.md]({MAIN_REPO}/blob/main/docs/provenance.md).

## Sources

Hazus is a Windows-only ArcGIS Pro application backed by SQL Server. There is no official
standalone download of its damage function tables and no API. These files were assembled
from two public sources that had already escaped that enclosure:

- **Hazus 4.0 flood** — FEMA's own Flood Assessment Structure Tool repository
  (`github.com/nhrap-hazus/FAST`), which publishes direct CSV dumps of the Hazus SQL
  tables.
- **Hazus 6.1 flood and hurricane** — Excel extracts from a public bucket operated by the
  OS-Climate physrisk project, which names that exact bucket and file in its published
  source code.

**That bucket was disabled on 12 August 2026** and now returns HTTP 403 for every object.
The original files can no longer be downloaded or byte-compared by anyone. SHA-256
verified copies are re-hosted by the main repository.

## Integrity record

Every input file, with the hash recorded when it was retrieved:

{md_table(["source file", "Hazus version", "bytes", "sha256"], rows)}

The same record ships inside the data as `provenance.parquet`, so a detached copy of
these files remains self-describing.

## What the pipeline does and does not do

It renames columns and reshapes wide source tables into long format. It performs **no
arithmetic on damage values** — nothing is computed, interpolated, smoothed, clamped or
inferred, and a missing source value is preserved as `NULL` rather than estimated.

Every row in `curves` carries `source_file`, `source_table` and `source_row_id`
identifying the exact originating cell.

## Verification against FEMA documents

Nine quantities FEMA states in its published manuals were tested against this data. Eight
match; one is a partial match reported as an unresolved discrepancy. The full report,
with FEMA source pages reproduced as screenshots alongside URLs and page numbers, is at
[docs/Hazus_Data_Verification_Report.docx]({MAIN_REPO}/blob/main/docs/Hazus_Data_Verification_Report.docx).

Highlights:

- FEMA states 62 wind building characteristics; the data contains exactly 62.
- FEMA states 39 specific building types; all 39 names match Table C-1 verbatim.
- FEMA states "over 275,000" hurricane damage functions; the data contains 275,220.
- FEMA disclosed a specific defect in the Hazus 6.1 wind data in its 7.1 release notes;
  **that defect is present and reproducible here at row level.** A fabricated or
  re-derived dataset would not carry another organisation's bug.

Independently, the flood curves agree with a separate FEMA publication across 17,313
individual values with zero discrepancies.

## Known defects

FEMA's Hazus 7.1 release notes disclose that in Hazus 6.1 and 7.0 the 2- and 3-story
multi-family wind damage functions were inadvertently overwritten with copies of the
1-story functions. Comparing every affected curve against its 1-story counterpart with
identical characteristics, terrain and loss class confirms it.

Affected curves are flagged in the data (`defect_flag`, `defect_verified`) rather than
removed. The corrected functions exist only in Hazus 7.1+, which is not publicly
extractable.

Other upstream quirks preserved as-is — including probabilities marginally exceeding 1.0
and nine building characteristic codes missing from Hazus's own decode table — are
documented at [docs/data_quality.md]({MAIN_REPO}/blob/main/docs/data_quality.md).

## Vintage

Flood curve values are current: FEMA's documentation shows the flood library unchanged
from Hazus 6.1 through 7.1. Hurricane data is Hazus 6.1 and carries the defect above.
Hazus 7.2's release notes ship inside a CAPTCHA-gated download, so what changed there is
unknown.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="path to the hazus-curves-data checkout")
    args = ap.parse_args()
    out = Path(args.out).expanduser().resolve()
    if not out.is_dir():
        print(f"not a directory: {out}", file=sys.stderr)
        return 1

    import duckdb
    con = duckdb.connect()

    stats = {}
    for path in sorted(DIST.glob("*.parquet")):
        name = path.stem
        rows, cols = profile(con, path)
        stats[name] = {"rows": rows, "cols": cols, "bytes": os.path.getsize(path)}

    files = {
        "README.md": build_readme(con, stats),
        "SCHEMA.md": build_schema(con, stats),
        "EXAMPLES.md": build_examples(),
        "PROVENANCE.md": build_provenance(con),
    }
    for name, text in files.items():
        (out / name).write_text(text)
        print(f"  wrote {name:<16} {len(text):>7,} chars")
    con.close()
    print(f"\n  documentation written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
