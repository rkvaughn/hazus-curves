# hazus-curves — static site

Browse and download Hazus flood and hurricane wind vulnerability curves
without installing Hazus, Python, or any build tool.

The site is plain HTML + CSS + JavaScript. No build step. Works on GitHub
Pages, Netlify, any static host, or `python -m http.server`.

---

## Deploy steps

### 1. Copy the Parquet data files

The query engine (DuckDB-WASM) fetches Parquet files over HTTP range
requests, so the files must be served alongside the page.

```sh
# From the repo root:
mkdir -p site/data
cp dist/*.parquet site/data/
```

Files that will be copied (~total ~250 MB):

| File | Contents |
|---|---|
| `curves.parquet` | Flood curves (metadata) |
| `curve_points.parquet` | Flood curve points (~88k rows) |
| `curve_attributes.parquet` | Flood curve attributes |
| `curves_hu.parquet` | Hurricane curves (metadata, 275k rows) |
| `curve_points_hu.parquet` | Hurricane curve points (~11.3M rows) |
| `curve_attributes_hu.parquet` | Hurricane building-characteristic attributes |
| `curve_kind.parquet` | x/y units per peril+damage_type |
| `assignment_rules.parquet` | Hazus default curve selection rules |
| `dim_occupancy.parquet` | Occupancy class descriptions |
| `dim_building_type.parquet` | Building type descriptions |
| `provenance.parquet` | Source file integrity records |

DuckDB-WASM uses HTTP range requests (Accept-Ranges), so it downloads
only the row groups it needs rather than the entire file. The 11M-row
hurricane file is never fully downloaded by a user who filters to a
small subset.

### 2. Serve the site

#### GitHub Pages

Push `site/` to the branch and directory configured for GitHub Pages.
Ensure the data files are committed (they are binary; add them with
`git lfs` or plain git depending on file size policy).

A minimal `.nojekyll` file is not required (no Jekyll processing needed),
but adding one prevents Jekyll from ignoring files that start with `_`.

```sh
touch site/.nojekyll
```

#### Local preview

```sh
cd site
python -m http.server 8080
# then open http://localhost:8080
```

`file://` URLs will not work because DuckDB-WASM's range requests require
HTTP. Always serve from localhost or a real host.

---

## What the site does

- **Query engine**: DuckDB-WASM loaded from jsDelivr CDN, querying the
  Parquet files over HTTP range requests. No server-side code.
- **Peril selector**: Flood or Hurricane Wind.
- **Flood filters**: occupancy class, damage type, Hazus version, flood
  zone (Riverine / Coastal A / Coastal V), and source agency.
- **Hurricane filters**: building type, damage type, terrain, geographic
  case, and all building-characteristic attributes (Roof Shape, Shutters,
  Roof Deck Attachment, etc.) loaded dynamically from the data.
- **Geography note**: these curves contain no state or county key. The
  "region / flood zone" control filters by Hazus flood-zone type, not a
  geographic location.
- **Chart preview**: line chart with Chart.js.
- **Averaging**: when multiple curves match, the site shows the
  unweighted arithmetic mean at each x value, with a min-max band.
  Averaged results are prominently labelled "DERIVED — not a
  FEMA-published curve".
- **Downloads**: CSV and JSON of exactly what is displayed, including
  provenance columns (`hazus_version`, `source_table`, `source_agency`,
  `defect_flag`). Averaged downloads include the list of constituent
  `curve_id` values.
- **Defect warnings**: any result set containing hurricane curves with
  `defect_flag` non-null shows a prominent warning banner.

---

## Data notes

See `docs/hurricane_defect.md` and `docs/version_changes.md` in the
repo for details on the hurricane multi-family defect and on the
flood-curve version history.

---

## Disclaimer

This project is not affiliated with or endorsed by FEMA. "Hazus" is a
registered trademark of the Federal Emergency Management Agency. Data
are extracted from publicly available Hazus source files and republished
for research purposes.
