# Database schema reference

## Design overview

The database has three layers.

**Layer 1 — tidy core: `curves` and `curve_points`.** One row per curve in `curves`; one row per (curve, x-value) in `curve_points`. Every peril's curves land in these same two tables. This is the shape that downstream tools — pandas, R, DuckDB — can query without understanding anything about Hazus.

**Layer 2 — peril-specific dimensions: `curve_attributes`.** Flood curves are keyed by occupancy, flood zone, stories, and basement. Hurricane curves are keyed by wind building type, specific building type, terrain, and a family of building characteristics (roof shape, shutters, roof deck attachment, and so on). Encoding all of those as columns in `curves` would require a different table per peril, and most columns would be null for every row of every other peril. Instead, `curve_attributes` stores them as key/value rows: `(curve_id, key, value)`. Adding earthquake later adds rows, not columns. This is what makes the schema lossless and peril-pluggable.

**Layer 3 — verbatim audit: `provenance`.** Every upstream file is recorded with its URL, SHA-256 hash, byte count, and retrieval timestamp. The record is copied into the database itself so that a detached copy of the database file carries enough information to verify its own provenance.

---

## Unit warning

`x` and `y` in `curve_points` mean different things depending on the peril and damage type. Do not assume units. Always join to `curve_kind` first.

For flood, `x` is depth in feet above (or below, when negative) the first finished floor, and `y` is damage as a percent of replacement value (0–100).

For hurricane, there are nine loss classes with three different unit systems:

| damage_type | y units |
|---|---|
| damage_slight | exceedance probability (0–1) |
| damage_moderate | exceedance probability (0–1) |
| damage_severe | exceedance probability (0–1) |
| damage_total | exceedance probability (0–1) |
| building_loss | loss ratio (0–1) |
| content_loss | loss ratio (0–1) |
| loss_of_use | days |
| debris_brick_wood | lbs per square foot |
| debris_concrete_steel | lbs per square foot |

Averaging y-values across these classes is meaningless. A loss ratio of 0.5 and a debris weight of 0.5 have nothing to do with each other. The `curve_kind` table makes the units explicit; consumers must read it rather than inferring from column names or position.

---

## curve_id format

Flood: `fl-{hazus_version}-{damage_type}-{source_row_id}`

Example: `fl-6.1-structure-129` is the flood structure curve whose native Hazus primary key is 129.

Hurricane: `hu-{hazus_version}-{damage_type}-{wind_building_type_id}-t{terrain_id}`

Example: `hu-6.1-building_loss-81-t3` is the building-loss curve for wind building type 81, terrain 3.

The `source_row_id` component is the verbatim Hazus primary key, preserved exactly as it appears in the source file. This makes it possible to trace any row back to its origin without parsing the curve_id.

---

## Table reference

### curves

One row per damage or vulnerability curve.

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| curve_id | TEXT | NOT NULL | Stable synthetic key; see format above. Primary key. |
| peril | TEXT | NOT NULL | `fl` = flood, `hu` = hurricane wind. |
| hazus_version | TEXT | NOT NULL | Hazus release the content represents (e.g. `4.0`, `6.1`). This is the version of the *content*, not necessarily the tool that published it. |
| damage_type | TEXT | NOT NULL | `structure`, `contents`, `inventory` for flood; one of nine loss class names for hurricane. |
| occupancy | TEXT | nullable | Hazus occupancy class (e.g. `RES1`, `COM1`). Populated for flood; null for hurricane. |
| building_type | TEXT | nullable | Hazus specific building type (e.g. `WSF1`). Populated for hurricane; null for flood. |
| source_agency | TEXT | nullable | Originating agency, verbatim from Hazus (e.g. `USACE - Galveston`). |
| description | TEXT | nullable | Hazus description field, verbatim. |
| defect_flag | TEXT | nullable | Non-null when FEMA has disclosed a defect in this curve. See docs/hurricane_defect.md. A null value means no *known* defect, not that the curve has been independently verified correct. |
| source_file | TEXT | NOT NULL | Filename under `raw/` this row came from. |
| source_table | TEXT | NOT NULL | Sheet or table within that file. |
| source_row_id | TEXT | NOT NULL | Native Hazus primary key, verbatim. |

Indexes: `(peril, occupancy)`, `(source_agency)`.

### curve_points

One row per (curve, x-value). The tidy long-format representation.

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| curve_id | TEXT | NOT NULL | Foreign key to `curves`. |
| x | REAL | NOT NULL | Flood: depth in feet relative to first finished floor (range -4 to +24). Hurricane: 3-second peak gust in mph (range 50–250 in 5 mph steps). Units are documented in `curve_kind`. |
| y | REAL | nullable | Damage or loss value at this x. NULL means the source had no value at this depth or speed — gaps are preserved, never filled or interpolated. See the `curve_kind` table for y units. |

Primary key: `(curve_id, x)`.

Note: the `damage` function in `hazus_curves/reader.py` raises rather than extrapolating outside the published domain, and raises rather than interpolating across a NULL gap. This is intentional: a missing source value is information, not a data entry problem to fix silently.

### curve_attributes

Peril-specific keying dimensions, stored as key/value rows. This table is what makes the schema lossless and peril-pluggable.

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| curve_id | TEXT | NOT NULL | Foreign key to `curves`. |
| key | TEXT | NOT NULL | Attribute name, e.g. `flood_zone`, `basement`, `terrain`, `Roof Shape`, `Shutters`. |
| value | TEXT | nullable | Attribute value as text, verbatim from source. |

Primary key: `(curve_id, key)`. Index: `(key, value)`.

Flood curves carry attributes including `comment` and `hazus_default_flag` from the source CSV.

Hurricane curves carry a richer attribute set sourced from the `huListOfBldgChar` decode table, including building characteristic dimensions such as `Roof Shape`, `Roof Deck Attachment`, `Shutters`, `Roof-Wall Connection`, and others. Nine characteristic codes that appear in the hurricane workbook but have no entry in the workbook's own decode table are stored under the key `characteristic_unmapped_code` as a comma-separated list of verbatim codes. Their meaning is not inferred.

### curve_kind

What `x` and `y` actually mean, per peril and damage type. Consumers should read this table rather than assuming units.

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| peril | TEXT | NOT NULL | Part of primary key. |
| damage_type | TEXT | NOT NULL | Part of primary key. |
| x_name | TEXT | NOT NULL | Logical name of the x axis (e.g. `depth`, `wind_speed`). |
| x_units | TEXT | NOT NULL | Physical units (e.g. `ft_above_first_floor`, `mph_3s_gust`). |
| y_name | TEXT | NOT NULL | Logical name of the y axis (e.g. `damage`, `exceedance_probability`, `loss_of_use`). |
| y_units | TEXT | NOT NULL | Physical units (e.g. `percent`, `probability_0_1`, `days`, `lbs_per_sqft`). |
| interpolation | TEXT | NOT NULL | How to read between published points. All current rows: `piecewise_linear`. |
| notes | TEXT | nullable | Additional clarifications from the Hazus technical manual. |

Primary key: `(peril, damage_type)`.

### assignment_rules

Hazus's own default curve selection logic. One row per (peril, version, damage type, occupancy, flood zone, stories, basement) combination. The curve_id column records which curve Hazus selects by default for that combination.

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| rule_id | TEXT | NOT NULL | Synthetic key of the form `fl-6.1-structure-{SOccupId}-{zone}`. Primary key. |
| peril | TEXT | NOT NULL | `fl` or `hu`. |
| hazus_version | TEXT | NOT NULL | `6.1` for all current rows. |
| damage_type | TEXT | NOT NULL | `structure`, `contents`, or `inventory`. |
| occupancy | TEXT | nullable | Hazus occupancy class. |
| flood_zone | TEXT | nullable | `Riverine`, `CoastalA`, or `CoastalV`. |
| stories | TEXT | nullable | Story count as a text label (e.g. `1 Story`, `2 Story`, `Split Level`). |
| basement | TEXT | nullable | `1` if basement present, empty string if not. |
| curve_id | TEXT | nullable | The curve this combination selects by default. |
| source_file | TEXT | NOT NULL | Source workbook. |
| source_table | TEXT | NOT NULL | Sheet within that workbook. |
| notes | TEXT | nullable | Free text. |

Note: Hazus 7.0 changed the coastal DDF assignment rule (depth-limited at 3 ft and 6 ft) without changing any curve values. That rule change is documented in `docs/version_changes.md`. The rules in this table are from the 6.1 workbook.

### dim_occupancy

Hazus occupancy classes. Values in the source CSV are space-padded; padding is stripped on load.

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| occupancy | TEXT | NOT NULL | Occupancy code (e.g. `RES1`, `COM3`). Primary key. |
| category | TEXT | nullable | Broad category (e.g. `Residential`, `Commercial`). |
| description | TEXT | nullable | Full text description. |

### dim_building_type

Hazus specific building types, used by the hurricane model.

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| building_type | TEXT | NOT NULL | Code (e.g. `WSF1`, `MMUH2`). Primary key. |
| description | TEXT | nullable | Description. |

### provenance

Integrity record for every upstream file. Copied from `raw/MANIFEST.json` so the database is self-describing once detached from the repository.

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| source_file | TEXT | NOT NULL | Local filename under `raw/`. Primary key. |
| url | TEXT | NOT NULL | URL the file was fetched from. |
| sha256 | TEXT | NOT NULL | SHA-256 hex digest of the file as fetched. |
| bytes | INT | NOT NULL | Byte count. |
| retrieved_at | TEXT | NOT NULL | ISO-8601 timestamp of retrieval. |
| hazus_version | TEXT | NOT NULL | Hazus release the content represents. |
| note | TEXT | nullable | Free text note about the file. |

---

## SQL examples

All examples run against `dist/hazus_curves_full.sqlite` (the build that includes both flood and hurricane). Run with `sqlite3 dist/hazus_curves_full.sqlite`.

### Look up flood curves by occupancy

```sql
SELECT curve_id, peril, hazus_version, damage_type, occupancy, source_agency
FROM curves
WHERE occupancy = 'RES1'
  AND hazus_version = '6.1'
  AND damage_type = 'structure'
LIMIT 5;
```

Output:

```
fl-6.1-structure-105|fl|6.1|structure|RES1|FIA
fl-6.1-structure-106|fl|6.1|structure|RES1|FIA (MOD.)
fl-6.1-structure-107|fl|6.1|structure|RES1|FIA
fl-6.1-structure-108|fl|6.1|structure|RES1|FIA (MOD.)
fl-6.1-structure-109|fl|6.1|structure|RES1|FIA
```

### Get the points for a specific curve

```sql
SELECT x, y
FROM curve_points
WHERE curve_id = 'fl-6.1-structure-129'
ORDER BY x;
```

Output (partial):

```
-4.0|0.0
-3.0|0.0
-2.0|0.0
-1.0|3.0
0.0|13.0
1.0|23.0
2.0|32.0
3.0|40.0
...
24.0|...
```

`y` here is percent of structure replacement value. That is because `curve_kind` for `(fl, structure)` defines `y_units = percent`. Check `curve_kind` before interpreting any y column.

### Use assignment_rules to find the default curve for a building

This finds the Hazus 6.1 default structure curve for a 1-story, no-basement RES1 building in a riverine flood zone:

```sql
SELECT ar.occupancy, ar.flood_zone, ar.stories, ar.basement, ar.damage_type, ar.curve_id
FROM assignment_rules ar
WHERE ar.occupancy    = 'RES1'
  AND ar.flood_zone   = 'Riverine'
  AND ar.stories      = '1 Story'
  AND (ar.basement IS NULL OR ar.basement = '')
  AND ar.damage_type  = 'structure';
```

Output:

```
RES1|Riverine|1 Story||structure|fl-6.1-structure-129
```

### Filter hurricane curves by building characteristic

`curve_attributes` holds decoded building characteristics. This finds building-loss curves for structures with a hip roof, excluding any defect-flagged curves:

```sql
SELECT c.curve_id, c.building_type, ca.value AS roof_shape
FROM curves c
JOIN curve_attributes ca ON c.curve_id = ca.curve_id
WHERE c.peril        = 'hu'
  AND c.damage_type  = 'building_loss'
  AND ca.key         = 'Roof Shape'
  AND ca.value       = 'Hip'
  AND c.defect_flag  IS NULL
LIMIT 5;
```

Output:

```
hu-6.1-building_loss-81-t1|WSF1|Hip
hu-6.1-building_loss-81-t2|WSF1|Hip
hu-6.1-building_loss-81-t3|WSF1|Hip
hu-6.1-building_loss-81-t4|WSF1|Hip
hu-6.1-building_loss-81-t5|WSF1|Hip
```

The `-t1` through `-t5` suffix is the terrain ID. The same wind building type has one curve per terrain.

### Exclude defect-flagged curves

The defect flag text is long. Use `IS NULL` to filter, not a string comparison:

```sql
SELECT curve_id, defect_flag
FROM curves
WHERE peril = 'hu'
  AND defect_flag IS NOT NULL
LIMIT 1;
```

Output (truncated for readability):

```
hu-6.1-damage_slight-345-t1|FEMA Hazus 7.1 release notes (RSA-21186): in Hazus 6.1/7.0
the 2- and 3-story multi-family wind damage functions were inadvertently overwritten with
copies of the 1-story functions. Fixed in Hazus 7.1, which is not publicly extractable.
Use with caution.
```

There are 34,560 curves with a non-null `defect_flag`. To work only with unflagged hurricane curves, add `AND defect_flag IS NULL` to any query. See `docs/hurricane_defect.md` for what the flag means and what it does not mean.
