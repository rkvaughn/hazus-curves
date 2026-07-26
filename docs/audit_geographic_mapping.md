# Audit: geographic scoping and curve mapping logic

Date of audit: 2026-07-26. Scope: the web tool's geography-adjacent filters and the
`assignment_rules` mapping layer, checked against the Hazus source data and FEMA
documentation.

Every figure below is reproducible from `dist/*.parquet`; the queries are in the audit
commit message and can be re-run against the published artifacts.

---

## 0. Scope correction: there is no region database

The audit was requested against "region definitions, spatial boundaries, and region
database". **No such component exists in this project**, by design and by an explicit
earlier decision:

- No spatial code of any kind. A search for `shapefile|geojson|geometry|polygon|latitude|
  longitude|census|tract|county|fips|spatial|epsg` across `hazus_curves/`, `scripts/`,
  `site/` and `tests/` returns only chart min/max band variables and the two UI
  disclaimers stating that no state or county key exists.
- The Hazus curve tables contain no state, county, tract, or coordinate field. Curve
  selection by address requires the Hazus state inventory databases, which are
  Windows-only and not publicly extractable.
- An open address-selection model is recorded as separate future work in
  `docs/roadmap.md`.

So there are no region boundaries to validate against FEMA specifications, and no
region→curve mapping to audit. What *does* exist, and what this audit covers, are three
geography-adjacent dimensions: **hurricane geographic applicability case**, **flood
zone**, and **source region/agency**.

Those turned out to contain real defects.

---

## 1. CRITICAL — `geographic_case` is filtered by equality but is set-valued

**Severity: critical. Silently returns wrong results rather than failing.**

Hazus's `CaseID` table describes where each wind building type applies. Its own
`CaseDescription` values are explicit that three of the four cases cover *more than one*
territory:

| Value | FEMA's description | Territories covered |
|---|---|---|
| `ContinentalUS` | "Used in Continental US" | CONUS |
| `Hawaii` | "Used in Hawaii" | Hawaii |
| `ContUS+Hawaii` | "Used in Continental and Hawaii" | CONUS **and** Hawaii |
| `ContUS+Caribbean` | "Used in Continental and Caribbean" | CONUS **and** Caribbean |

The site filters with exact string equality (`site/app.js`, `attrConditions.push({ key:
"geographic_case", value: geoCase })`). Because the cases overlap, equality is the wrong
operator:

| User selects | Curves returned | Curves that actually apply | Silently excluded |
|---|---:|---:|---:|
| Hawaii | 14,400 | 179,820 | **92.0%** |
| ContinentalUS | 43,200 | 255,420 | **83.1%** |

Four building types — `WSF1`, `WSF2`, `MSF1`, `MSF2`, the single-family classes — carry
distinct curves per case, which is exactly where the error bites. The remaining 35 types
are all `ContUS+Hawaii` and disappear entirely from a "Hawaii" selection.

**Why this is worse than a plain filter bug:** when more than one curve matches, the tool
returns an *unweighted mean* with a min/max dispersion band, labelled DERIVED. A user
selecting "Hawaii" therefore receives a confident-looking averaged curve computed over
8% of the applicable population. Nothing on screen indicates the set was truncated.

**Fix:** filter by membership, not equality. The territory decomposition is given by
FEMA's own `CaseDescription` strings and needs no inference:

```
ContinentalUS    -> {CONUS}
Hawaii           -> {Hawaii}
ContUS+Hawaii    -> {CONUS, Hawaii}
ContUS+Caribbean -> {CONUS, Caribbean}
```

The selector should offer territories (CONUS / Hawaii / Caribbean) and match any case
whose territory set contains the selection.

---

## 2. CRITICAL — the flood zone filter excludes every Hazus 4.0 curve

**Severity: critical. Returns zero results for a valid selection.**

`assignment_rules` is built exclusively from the Hazus 6.1 workbook, so every
`curve_id` it references is prefixed `fl-6.1-`. The site applies a flood zone by
INNER JOINing against it. Any Hazus 4.0 curve therefore fails the join:

| Zone | Version | Structure curves returned | Of |
|---|---|---:|---:|
| Riverine | 4.0 | **0** | 597 |
| CoastalA | 4.0 | **0** | 597 |
| CoastalV | 4.0 | **0** | 597 |

Selecting a zone *without* a version is worse than selecting 4.0 explicitly: the tool
appears to search both vintages but silently returns 6.1 only.

---

## 3. HIGH — the zone filter collapses the library to default curves only

**Severity: high. Silent 40x narrowing of the result set.**

`assignment_rules` records Hazus's *default* curve per occupancy/stories/basement
combination. It is not an applicability index. Using it as a zone filter reduces the
searchable library to the defaults:

| Zone | Structure curves returned | Of all versions |
|---|---:|---:|
| Riverine | 36 | 1,489 |
| CoastalA | 38 | 1,489 |
| CoastalV | 38 | 1,489 |

Across all damage types, `assignment_rules` references **101 distinct curve_ids out of
3,046 flood curves — 3.3%**. The other 96.7% become unreachable the moment a user
touches the zone control.

This is a semantic mismatch, not a data error: `docs/schema.md` correctly describes
`assignment_rules` as default selection, but the site consumes it as a zone applicability
filter. One of the two has to change.

---

## 4. MEDIUM — the Hazus 7.0 depth-limited coastal rule is documented but absent

`docs/version_changes.md` states that the Hazus 7.0 coastal assignment change is
"recorded here, not as curve data … it belongs in your metadata as a selection rule".
`hazus_curves/schema.py` repeats this in the `assignment_rules` docstring.

It is not recorded anywhere. The `notes` column is **NULL for all 1,338 rows**, and no
row in `assignment_rules`, `curve_kind` or `curves` mentions the rule. Searching the
published data for "depth-limited", "depth limited" or "6 feet" returns zero rows in
every table.

The rule itself (FEMA Hazus 7.0 Release Notes §2.2, verbatim): Coastal V at depths ≥6 ft,
Coastal A between 3 and 6 ft, riverine/A-Zone below 3 ft.

The documentation currently promises something the database does not deliver.

---

## 5. MEDIUM — FEMA's own 4.0 assignment tables are fetched but never parsed

`scripts/fetch.py` downloads, checksums and records six FEMA-published assignment lookup
tables that nothing then reads:

`Building_DDF_{Riverine,CoastalA,CoastalV}_LUT_Hazus4p0.csv`,
`Content_DDF_{Riverine,CoastalA,CoastalV}_LUT_Hazus4p0.csv`, `Inventory_DDF_LUT_Hazus4p0.csv`

They contain precisely what findings 2 and 3 need — `Occupancy`, `Stories`, `Basement`,
`DDF_ID`, and per-zone applicability flags `HazardRiverine` / `HazardCA` / `HazardCV`:

| File | Rows | Distinct DDF_ID | Riverine | CoastalA | CoastalV |
|---|---:|---:|---:|---:|---:|
| Building_DDF_Riverine_LUT | 196 | 36 | 196 | 190 | 184 |
| Building_DDF_CoastalA_LUT | 64 | 16 | 58 | 64 | 58 |
| Building_DDF_CoastalV_LUT | 64 | 16 | 52 | 58 | 64 |

Note the flags are genuinely multi-zone: a curve listed in the riverine table is often
also flagged applicable to Coastal A and V. That is the applicability index finding 3
needs, and it is already sitting in `raw/` under checksum.

---

## 6. PASS — referential integrity and non-geographic dimensions

Checks that came back clean:

- **No dangling references.** Every `curve_id` in `assignment_rules` resolves to a real
  row in `curves` (0 dangling of 1,338).
- **Uniform zone coverage.** Each of the three flood zones has identical rule counts per
  damage type (196 structure / 196 contents / 54 inventory), so no zone is
  under-represented relative to the others.
- **Terrain** is a clean 5-value exclusive enumeration (Open, Light Suburban, Suburban,
  Light Trees, Trees) with surface roughness values from `huTerrain`. Equality filtering
  is correct here.
- **`geographic_case` dropdown populates** with all four values.
- **Source agency / region** values pass through verbatim from Hazus and are used only as
  provenance labels, not as a spatial selector.

---

## Summary

| # | Finding | Severity | Fails how |
|---|---|---|---|
| 1 | `geographic_case` equality filter on set-valued attribute | Critical | Silently wrong |
| 2 | Zone filter excludes all Hazus 4.0 curves | Critical | Silently empty |
| 3 | Zone filter collapses library to 3.3% defaults | High | Silently narrow |
| 4 | Hazus 7.0 coastal rule documented but absent | Medium | Docs overstate data |
| 5 | FEMA 4.0 assignment LUTs fetched but unused | Medium | Missing capability |
| 6 | Referential integrity, terrain, coverage | Pass | — |

Findings 1–3 share a failure mode worth stating plainly: none of them throws an error.
Each returns a plausible curve computed over the wrong population, and finding 1 wraps it
in a dispersion band that makes the truncated result look well-characterised.

---

## Remediation (completed)

All five findings are fixed. Regression coverage is in
`tests/test_geographic_mapping.py` (15 tests), which pins absolute counts rather than
"returns something", because every one of these bugs returned something.

**1. Territory membership replaces case equality.** New `dim_geographic_case` table
decomposes each Hazus case into the territories it covers, read from Hazus's own
`CaseDescription` strings. The selector now offers CONUS / Hawaii / Caribbean and matches
any case containing that territory.

| Territory | Before (equality) | After (membership) | Recovered |
|---|---:|---:|---:|
| Hawaii | 1,600 | 19,980 | +18,380 |
| CONUS | 4,800 | 28,380 | +23,580 |
| Caribbean | n/a | 5,200 | — |

*(`damage_severe` curves; verified identical in SQL and in the browser.)*

**2. Hazus 4.0 assignment rules now exist.** The six FEMA-published 4.0 lookup tables are
parsed. `assignment_rules` grew from 1,338 rows (6.1 only) to 2,040 covering both
vintages. Zone + version 4.0 returns 36 curves for Riverine and 38 for Coastal V, where
it previously returned zero.

**3. Zone filtering moved to a real applicability index.** New
`curve_zone_applicability` table records which zones Hazus flags a curve as usable in,
built from the multi-zone flags in both the 4.0 LUTs and the 6.1 `*Final` tables. The
site filters on this instead of on default assignments.

An important limit, now stated in the UI rather than hidden: **Hazus publishes zone flags
only for the curves it assigns.** The rest of the library is alternates a Hazus user
selects manually, with no zone recorded in any published table. A complete applicability
index is therefore not derivable from the available data. Selecting a zone still narrows
the library — it just does so explicitly, and leaving the control on *All* searches all
3,046 flood curves.

**4. The Hazus 7.0 coastal rule is in the data.** 1,148 Coastal A and Coastal V rules
carry a `notes` value quoting the depth-limited rule (V ≥ 6 ft, A 3–6 ft, riverine
< 3 ft) and citing Hazus 7.0 Release Notes §2.2. Riverine rules are deliberately left
unannotated, since the change does not apply to them, and a test asserts that.

**5. The unused FEMA LUTs are now the source for findings 2 and 3.**
