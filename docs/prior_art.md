# Prior art and related work

This document surveys existing open-source tools that work with Hazus damage functions or comparable vulnerability models. The goal is an honest comparison, not a sales pitch.

---

## FEMA nhrap-hazus: FAST and hazpy

Organization: https://github.com/nhrap-hazus

FAST (Flood Assessment Structure Tool) and hazpy are FEMA's own open-source tools for working with Hazus output. Both are licensed GPL-3.0.

FAST is directly relevant here. It publishes the Hazus 4.0 flood depth-damage function tables as CSV files in its `Lookuptables/` directory:

- https://github.com/nhrap-hazus/FAST/tree/main/Lookuptables

The `Lookuptables/README.txt` states verbatim that the DDFs were obtained from the Hazus 4.0 SQL database and were verified unchanged across Hazus 3.1, 3.2, and 4.0. These CSVs are the authoritative source for the 4.0 flood vintage in this project. The last commit to the FAST repo is dated 2022-03-30; the project appears unmaintained.

FAST's README also references a FEMA S3 snapshot bucket (`fema-ftp-snapshot`) as a secondary source. That bucket no longer exists; attempts to access it return HTTP 404 or equivalent errors.

The R `hazus` package (https://CRAN.R-project.org/package=hazus) provided flood depth-damage functions for R users. It was archived on CRAN on 2022-06-15 and covers flood only.

---

## Deltares HydroMT-FIAT

https://github.com/Deltares/hydromt_fiat

License: GPL-3.0

HydroMT-FIAT is an open-source tool built on the HydroMT framework for building FIAT (Flood Impact Assessment Tool) models. It bundles preprocessed Hazus flood depth-damage functions for use within the FIAT ecosystem. The damage functions are part of the tool's asset data rather than a standalone distributable.

HydroMT-FIAT is actively maintained (as of mid-2025). Its intended use case is building complete impact assessment models; it is not designed as a curve library that other tools import.

---

## os-climate/physrisk

https://github.com/os-climate/physrisk

License: Apache-2.0

physrisk implements Hazus wind vulnerability functions among its physical climate risk models and is actively maintained. It is also the source of the public anonymous-access S3 bucket that this project's Hazus 6.1 workbooks come from:

- `https://os-climate-physical-risk.s3.amazonaws.com/vulnerability/HazusWindDamFunctions_Hazus61.xlsx`
- `https://os-climate-physical-risk.s3.amazonaws.com/vulnerability/HazusFloodDamageFunctions_Hazus61.xlsx`

How OS-Climate obtained the workbooks is not documented upstream. This project verified the 6.1 workbook's flood content against the FEMA-published FAST 4.0 CSVs as a corroboration step; see `docs/version_changes.md`. physrisk should be credited clearly as an upstream dependency: without its public S3 bucket, the 6.1 data would not be accessible without a Windows/ArcGIS Pro installation.

---

## USACE go-consequences and the National Structure Inventory

https://github.com/USACE/go-consequences

go-consequences is a USACE open-source consequence modeling tool. It uses USACE depth-damage functions, not Hazus functions. The National Structure Inventory (NSI, https://www.hec.usace.army.mil/nsi/) provides building stock data that USACE tools consume. These are related but distinct: USACE curves and Hazus curves are not the same library.

---

## OpenQuake / GEM

https://github.com/gem/oq-engine

License: AGPL-3.0

OpenQuake is GEM's open-source seismic hazard and risk engine. It handles earthquake fragility and vulnerability functions. It does not cover flood or hurricane wind. Mentioned here because it is the most prominent open comparable for seismic perils, which this project does not yet cover.

---

## What is genuinely new here

Stated plainly, without overclaiming:

**The flood curves substantially duplicate prior art.** The 4.0 vintage comes directly from FAST (FEMA published them). The 6.1 vintage comes from the physrisk S3 bucket. Anyone who has used FAST or physrisk has worked with this data. The value this project adds for flood is the schema, the 4.0-vs-6.1 version diff (which is measured from the data rather than taken from release notes), and the packaging into a queryable, engine-independent format.

**The hurricane wind curves in open tidy tabular form are not available elsewhere.** The Hazus 6.1 hurricane workbook is accessible through the physrisk S3 bucket, but it has not previously been published in a tidy, queryable, peril-normalized form. This project produces 275,220 curves and 11,284,020 points covering nine loss classes across five terrain categories. physrisk uses these functions internally but does not publish them as a standalone distributable.

**The cross-peril schema is novel.** Storing flood and hurricane curves in the same three-table structure, with peril-specific dimensions in a key/value attribute table, is not done by any of the tools above. The consequence is that adding a new peril later requires no schema changes.

**The 4.0-vs-6.1 version diff is original work.** The comparison is computed from the data in this project; it has not been published elsewhere. The finding that the 6.1 expansion was purely additive for flood — zero existing curves modified — is not documented in the FEMA release notes in this form.

**The empirical defect verification is original.** FEMA disclosed the multi-family hurricane curve defect in the Hazus 7.1 release notes (RSA-21186), but disclosed it as a description, not as a measured count. This project verified the claim against the data directly, finding that 15,200 of 34,560 affected curves are byte-identical to their 1-story counterparts. See `docs/hurricane_defect.md`.

**One-command multi-engine local install.** The combination of SQLite, DuckDB, PostgreSQL, and Snowflake DDL, plus Parquet files, is not offered by any existing tool.
