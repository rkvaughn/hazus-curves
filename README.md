# hazus-curves

An open, tidy database of **FEMA Hazus damage and vulnerability curves** — flood and
hurricane wind — that installs into a local SQL environment in one command.

Hazus is the most widely used natural-hazard loss model in US practice, but its damage
functions live inside a Windows-only ArcGIS Pro application backed by SQL Server. Getting
at them normally means a ~50 GB install and a licensed ArcGIS Pro seat, or copying tables
out of PDFs by hand.

This project extracts them, reshapes them into tidy long format, documents where every
number came from, and packages the result so a researcher can start querying in under a
minute.

**→ [Browse the curves in your browser](https://rkvaughn.github.io/hazus-curves/)** — no
install, no account. Filter, chart and download curves as CSV or JSON.

> Not affiliated with or endorsed by FEMA. "Hazus" is a trademark of the Federal
> Emergency Management Agency. See [LICENSE-DATA.md](https://github.com/rkvaughn/hazus-curves/blob/main/LICENSE-DATA.md).

---

## Quickstart

> **Not on PyPI yet.** `pip install hazus-curves` does **not** work today — the first
> release has not been published. Install from GitHub instead; everything below behaves
> identically either way.

```bash
pip install "git+https://github.com/rkvaughn/hazus-curves@v0.1.0"   # until PyPI is live
hazus-curves install                 # flood curves -> ~/.hazus_curves/ (7 MB)
hazus-curves query "SELECT curve_id, occupancy, source_agency FROM curves LIMIT 5"
```

Once published this becomes:

```bash
pip install hazus-curves
```

```python
from hazus_curves import connect, get_curve, damage

con = connect()
damage(con, "fl-6.1-structure-129", 3.5)     # % structure damage at 3.5 ft depth
curve = get_curve(con, "fl-6.1-structure-129")
curve["kind"]["y_units"]                      # 'percent' - never assume units
```

Other engines, from the same artifacts:

```bash
hazus-curves install --perils fl,hu --target duckdb:///hazus.duckdb
hazus-curves install --perils fl    --target postgresql://user@localhost/hazus
```

DDL for SQLite, DuckDB, PostgreSQL and Snowflake is generated from a single schema
definition ([`hazus_curves/schema.py`](https://github.com/rkvaughn/hazus-curves/blob/main/hazus_curves/schema.py)) into [`sql/`](https://github.com/rkvaughn/hazus-curves/tree/main/sql/), so
the engines cannot drift apart.

## What's in it

| Peril | Hazus version | Curves | Points |
|---|---|---:|---:|
| Flood | 4.0 | 1,220 | 35,380 |
| Flood | 6.1 | 1,826 | 52,954 |
| Hurricane wind | 6.1 | 275,220 | 11,284,020 |
| **Total** | | **278,266** | **11,372,354** |

Flood curves are depth-damage functions: depth in feet relative to the first finished
floor (−4 to +24 ft, 29 points), damage as percent of replacement value, split into
structure, contents and business inventory, keyed by occupancy class and flood zone.

Hurricane curves run over 3-second peak gust wind speed (50–250 mph in 5 mph steps), for
6,116 wind building types × 5 terrain roughnesses × 9 loss classes. The nine loss classes
include four damage-state exceedance probabilities, building and content loss ratios,
**loss of use in days**, and two debris measures in lbs/sq ft.

**Those nine classes do not share units.** Join the `curve_kind` table rather than
assuming — see [docs/schema.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/schema.md).

## The rule this project is built on

**No fabricated values.** The pipeline renames columns and reshapes wide tables into long
ones. It never computes, interpolates, smooths, clamps, or infers a damage value. Gaps
stay gaps — a missing source value becomes `NULL`, never an estimate. Every row carries
`source_file`, `source_table` and `source_row_id` back to the originating cell, every
source file is pinned by SHA-256, and the round-trip is enforced by tests.

That rule is why several things below are reported as problems rather than quietly fixed.

## Findings

Three things came out of building this that are not documented elsewhere.

### Hazus 6.1 was purely additive for flood curves

FEMA's release notes say the flood library was expanded but not whether existing curves
were revised. Measured directly:

| Damage type | 4.0 | 6.1 | Added | Removed | **Values changed** |
|---|---:|---:|---:|---:|---:|
| structure | 597 | 892 | 295 | 0 | **0** |
| contents | 507 | 818 | 311 | 0 | **0** |
| inventory | 116 | 116 | 0 | 0 | **0** |

Every curve that existed in Hazus 4.0 survives into 6.1 bit for bit, so results computed
against the older library remain reproducible. → [docs/version_changes.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/version_changes.md)

### A FEMA-disclosed hurricane defect, independently confirmed

FEMA's Hazus 7.1 release notes disclose that in 6.1 and 7.0 the 2- and 3-story
multi-family wind curves had been overwritten with copies of the 1-story curves. We tested
that claim against the data instead of taking it on faith, comparing every 2-/3-story
curve with the 1-story curve having identical characteristics, terrain and loss class:

> **15,200 of 34,560** multi-story multi-family curves are byte-identical to their
> 1-story counterpart.

The defect is real and measurable. Affected curves ship with a `defect_flag` **column in
the data**, not a footnote, plus a `defect_verified` column recording our own measurement
separately from FEMA's disclosure. We flag rather than withhold — a flagged curve is more
useful than a missing one, and Hazus 7.1+ (which has the fix) is not publicly
extractable. → [docs/hurricane_defect.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/hurricane_defect.md)

### The third-party source checks out against FEMA's own data

The Hazus 6.1 workbooks reached us via a public bucket belonging to
[os-climate/physrisk](https://github.com/os-climate/physrisk), not directly from FEMA,
and how they obtained them is undocumented. That is a real provenance gap — so we tested
it rather than assert it.

- **Flood:** the 6.1 workbook embeds the pre-6.1 structure library; against FEMA's own
  published Hazus 4.0 CSVs, all 597 curves across all 29 depth values are **identical,
  zero discrepancies**.
- **Hurricane:** matches the FEMA Technical Manual on four independent counts — 62 wind
  building characteristics, 39 specific building types, "over 275,000 damage functions"
  (275,220), and it **reproduces a specific defect FEMA disclosed in its 7.1 release
  notes** (15,200 confirmed duplicate curves). A re-derived dataset would not carry that.

> ⚠️ **That bucket went dark on 2026-08-12** (`403 AllAccessDisabled`, whole bucket, no
> Internet Archive capture). The originals can no longer be downloaded by anyone, so
> re-downloading and byte-comparing is no longer possible. We re-host our SHA-256-verified
> copies on the [v0.1.0 release](https://github.com/rkvaughn/hazus-curves/releases/tag/v0.1.0);
> `fetch.py` falls back to them and rejects any file whose hash does not match the
> committed manifest.

→ [docs/provenance.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/provenance.md)

Also worth knowing before you use the data: some upstream probabilities exceed 1.0, and
nine building-characteristic codes are missing from Hazus's own decode table. Both are
preserved as-is and documented in [docs/data_quality.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/data_quality.md).

## Verification

Everything here is checkable against FEMA's own documents, and
**[the verification report](https://github.com/rkvaughn/hazus-curves/blob/main/docs/Hazus_Data_Verification_Report.docx)**
(Word, 23 pages) does exactly that: nine quantities FEMA states in four published
documents, each tested against this dataset, with the source page reproduced as a
screenshot alongside its URL and page number. Eight match; one is a partial match and is
reported as a discrepancy rather than presented as agreement.

All eleven FEMA manuals and release notes it cites are committed under
[`raw/`](https://github.com/rkvaughn/hazus-curves/tree/main/raw/), so the evidence base
travels with the repository. Regenerate the report with:

```bash
.venv/bin/python scripts/build_verification_evidence.py   # locate, render, measure
node scripts/build_verification_docx.js                   # build the document
```

## Building from source

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/build_all.py --perils fl,hu   # fetch + build everything
.venv/bin/python -m pytest                             # 114 tests
```

The repository carries the FEMA source documents (~101 MB), so a full clone is
correspondingly large. If you only want the code:

```bash
git clone --depth 1 --single-branch https://github.com/rkvaughn/hazus-curves.git
```

The Parquet tables behind the web tool live in a separate repository,
[hazus-curves-data](https://github.com/rkvaughn/hazus-curves-data), so they are not
pulled by a clone or by `pip install`.

`build_all.py` runs the whole pipeline; each stage is also runnable on its own
(`fetch.py`, `build_flood.py`, `build_hurricane.py`, `verify_hurricane_defect.py`,
`extract_building_types.py`, `diff_versions.py`, `build_db.py`).

`fetch.py` is idempotent: re-running verifies checksums rather than re-downloading.

## Documentation

| | |
|---|---|
| [docs/schema.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/schema.md) | Table reference, units, worked SQL |
| [docs/provenance.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/provenance.md) | Where every number comes from |
| [docs/version_changes.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/version_changes.md) | Hazus 4.0 → 6.1 → 7.x |
| [docs/hurricane_defect.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/hurricane_defect.md) | The defect and its verification |
| [docs/data_quality.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/data_quality.md) | Known upstream quirks |
| [docs/audit_geographic_mapping.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/audit_geographic_mapping.md) | Audit of geographic scoping and curve mapping |
| [docs/prior_art.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/prior_art.md) | Honest comparison with existing work |
| [docs/roadmap.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/roadmap.md) | Earthquake, tsunami, weighting, address model |

## Scope and limits

- **Vintage is Hazus 6.1**, the newest publicly extractable release. Flood curve values
  are unchanged through Hazus 7.1, so flood is effectively current; hurricane is not, and
  carries the defect above. Hazus 7.2's release notes ship inside a CAPTCHA-gated
  download, so what changed there is unknown.
- **No earthquake or tsunami yet.** Their parameters are in technical-manual PDFs. See
  the roadmap.
- **No geography.** The Hazus curve tables contain no state or county key, so this
  database cannot map an address to a curve. What it does carry is flood zone and source
  region (USACE district, FIA, FEMA PFRA). An open address-selection model is on the
  roadmap as a separate project.
- **The flood curves substantially overlap existing prior art.** The value added here is
  the schema, the version diff and the packaging — not that the data was unavailable.
  Hurricane wind in open tidy form does appear to be new. See
  [docs/prior_art.md](https://github.com/rkvaughn/hazus-curves/blob/main/docs/prior_art.md).

## Licence

Code: MIT ([LICENSE](https://github.com/rkvaughn/hazus-curves/blob/main/LICENSE)). Data: believed to be a US Government work under
17 U.S.C. § 105, with the uncertainties stated plainly in
[LICENSE-DATA.md](https://github.com/rkvaughn/hazus-curves/blob/main/LICENSE-DATA.md).

Please cite FEMA and the originating agencies — see [CITATION.cff](https://github.com/rkvaughn/hazus-curves/blob/main/CITATION.cff).
