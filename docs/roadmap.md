# Roadmap

Future work items, each with motivation, concrete approach, and known blockers.

---

## 1. Earthquake and tsunami perils

**Motivation.** Hazus covers earthquake and tsunami as first-class perils with tabulated fragility and vulnerability functions comparable to what is published here for flood and hurricane. Omitting them means the schema's cross-peril claim applies to only two perils.

**Approach.** Curve parameters live in FEMA Technical Manual PDFs. `fema.gov` returns HTTP 403 to automated fetchers, but prefixing any `fema.gov` PDF URL with `https://web.archive.org/web/2025id_/` returns HTTP 200 with the original unmodified bytes — this has been verified working for the manuals already in `raw/`. Acquisition is therefore scriptable using the same Wayback bypass pattern in `hazus_curves/sources.py`.

Target files:

- Earthquake TM 6.1: `fema_hazus-earthquake-model-technical-manual-6-1.pdf`. Fragility medians and lognormal betas are reported around Chapter 5; the exact table numbers have not been verified against the PDF. These are the parameters this project would need to build fragility curves.
- Tsunami TM 6.1: `Hazus_6.1_Tsunami_Model_Technical_Manual.pdf`.
- Inventory TM 7.0: `fema_rsl_hazus-7-invtm_06272025_1.pdf`. Contains building classification and inventory data shared across perils.

**Blockers.** The highest-risk step is PDF table extraction, not acquisition. Extracting numeric tables from PDFs programmatically is fragile; some tables are images; column alignment can break; footnotes can be captured as data. Under this project's no-fabricated-values rule, every extracted number must be traceable to a specific table cell in the source document. Model transcription — asking a language model to read a table — is not acceptable, because there is no way to verify completeness or detect transcription errors. The required approach is programmatic extraction (pdfplumber, camelot, or equivalent) with explicit verification against a known reference value for each table. This is feasible but expensive to get right.

---

## 2. Building-stock and building-code weighting module

**Motivation.** Any summary statistic computed by averaging curves across occupancy classes or building types is currently unweighted. An unweighted average implicitly treats a warehouse and a one-story wood-frame house as equally common, which is not realistic. A weighting module would let averages represent a real building population rather than a uniform prior.

**Approach.** Weights would be keyed by building-code era and building-stock distribution. Hazus's own mapping schemes are the natural source — they encode how the model translates census data into model inputs — but they live in Windows-only state databases (`.mdb` files accessed through ArcGIS Pro). The USACE National Structure Inventory (NSI, https://www.hec.usace.army.mil/nsi/) is the most accessible open substitute: it provides address-level building records with attributes including occupancy class, year built, and square footage for structures across the contiguous US.

The weighting module would be a separate, optional component. It would not modify any curve value; it would produce exposure weights that consumers could apply when aggregating.

**Blockers.** The NSI is a large dataset and its building-type classifications do not map one-to-one to Hazus occupancy codes. A mapping between NSI attributes and Hazus occupancy classes would need to be developed and documented. Decisions involved in that mapping are not straightforward.

---

## 3. Demand surge and remaining downtime functions

**Motivation.** Flood and hurricane events cause post-event cost escalation (demand surge) and business-interruption losses beyond the building repair period. These are relevant to full economic impact estimates.

**Current state.** Downtime is partially done. The hurricane model's `loss_of_use` damage type, measured in days, is published in v1. The `curve_kind` table documents its units (`days`) and explicitly notes it should not be mixed with loss-ratio curves.

**Remaining work.** Flood restoration-time and business-interruption functions are not yet included. Demand surge (post-event cost escalation factors applied to repair costs) is not included. Whether Hazus exposes tabulated demand surge factors at all has not been established — research is needed before any extraction work begins. No values are to be introduced until their source is identified and the extraction approach is designed.

---

## 4. Open-source address selection model

**Motivation.** Knowing which Hazus curve applies to a given building requires knowing the building's occupancy class, flood zone, number of stories, basement presence, and building characteristics. FEMA's answer to this is the Hazus state inventory databases, which are Windows-only and not public. There is no open tool that maps a street address to the correct Hazus curve.

**Approach.** Such a tool would combine three open data sources: the USACE NSI for building-level attributes, FEMA flood zone layers for flood zone assignment, and inference from building attributes for characteristics that are not directly available (e.g., roof shape from building age and construction type). It would use this project's database as the curve library it selects from.

This is genuinely a separate project — the scope, data engineering, and validation are distinct enough that it should have its own repository. This project supplies the curve library it would select from.

**Blockers.** Building-attribute inference is the main risk. Attributes like roof shape, presence of shutters, or roof deck attachment quality are not available in the NSI. Inference approaches involve assumptions that are hard to validate without ground-truth data. Any inference model would need explicit documentation of its assumptions and a way for users to override inferred values.

---

## 5. Track Hazus 7.2

**Motivation.** Hazus 7.2 was released approximately June 2026 (based on the inventory technical manual date in `hazus_curves/sources.py`). Its release notes may document curve changes, new perils, or corrections.

**Blocker.** The Hazus 7.2 release notes ship inside a CAPTCHA-gated download. What changed in 7.2 is currently unknown and cannot be determined through automated retrieval. Manual inspection would require downloading the Hazus 7.2 installer, which in turn requires a Windows machine with ArcGIS Pro. Until the release notes are accessible, no 7.2 content can be added.
