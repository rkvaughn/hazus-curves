# Status of the data in this repository

The **code** in this repository is MIT licensed (see `LICENSE`).

This file is about the **curve data**, which is a different question, and one worth
being precise about.

## Summary

The damage and vulnerability curves published here are, to the best of our
understanding, works of the United States Government and therefore not subject to
domestic copyright under [17 U.S.C. § 105](https://www.law.cornell.edu/uscode/text/17/105).
We assert no additional copyright or licence over them and place no restrictions on
their reuse.

We ask — but cannot require — that you cite FEMA and the originating agencies, and
state which Hazus version you used. See `CITATION.cff`.

## Why we believe this

- Hazus is developed and distributed by FEMA, a US federal agency.
- The flood curves carry a `source_agency` field naming their originators. Every value
  present is a federal body: US Army Corps of Engineers districts (New Orleans,
  Galveston, Wilmington, Chicago, St. Paul, IWR, American River), the Federal Insurance
  Administration, FEMA's Benefit-Cost Analysis programme, FEMA's Probabilistic Flood
  Risk Assessment studies, and Colorado State University work performed for FEMA.
- FEMA itself published the Hazus 4.0 flood damage function tables as CSV in a public
  GitHub repository ([nhrap-hazus/FAST](https://github.com/nhrap-hazus/FAST)), which is
  where part of this dataset comes from.
- We found no End User Licence Agreement, terms-of-use page, or other FEMA statement
  restricting redistribution of the curve data.

## What we could not confirm — stated plainly

We are not lawyers and this is not legal advice. The following remain genuinely
unresolved, and we would rather say so than imply a certainty we do not have:

1. **FEMA has never issued an explicit public-domain dedication for Hazus data.** Our
   position is an inference from § 105 and from FEMA's own publishing behaviour, not a
   quotation of FEMA policy.
2. **Older Hazus technical manuals have been reported to carry a copyright notice.** We
   were not able to verify this directly — `fema.gov` returns HTTP 403 to automated
   requests — so we neither confirm nor dismiss it.
3. **Hazus was substantially developed under contract**, including by the National
   Institute of Building Sciences. Works prepared by government *contractors* are not
   automatically within § 105. Whether any contractor retains rights in the underlying
   methodology is not something we could establish.
4. The Hazus 6.1 Excel extracts reach us through a third-party mirror rather than
   directly from FEMA. See `docs/provenance.md`.

If you are making a commercial or high-stakes use of this data, do your own diligence
and consider contacting FEMA directly at `FEMA-Hazus-Support@fema.dhs.gov`.

## Trademark and affiliation

**"Hazus" is a trademark of the Federal Emergency Management Agency.**

This project is **not affiliated with, endorsed by, or sponsored by FEMA**, the US Army
Corps of Engineers, or any other government agency. It is an independent repackaging of
publicly available data. The name is used descriptively, to identify the source of the
data, and for no other purpose.

## No warranty

The data is provided as-is. It is republished mechanically from upstream sources and
carries whatever errors those sources contain — including at least one defect FEMA has
publicly disclosed and which we have independently confirmed and flagged in the data
(see `docs/hurricane_defect.md`), and out-of-range values present in the upstream
workbook (see `docs/data_quality.md`).

Do not use these curves for life-safety decisions without independent verification
against the current official Hazus release.
