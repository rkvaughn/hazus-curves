"""Registry of upstream Hazus data sources.

Single source of truth for where every byte in this project comes from. `fetch.py`
downloads from here, `validate_mirror.py` reconciles against here, and the provenance
docs are generated from here.

Nothing in this project may read data that is not declared in this file.
"""

from dataclasses import dataclass, field
from typing import Optional

# fema.gov returns HTTP 403 to every automated fetcher we tried (plain curl, browser
# user-agents, several CORS proxies). The Internet Archive serves the identical PDFs
# with HTTP 200 / application/pdf. The `id_` suffix asks Wayback for the original
# unmodified bytes rather than its rewritten viewer page.
WAYBACK_PREFIX = "https://web.archive.org/web/2025id_/"

FAST_RAW = (
    "https://raw.githubusercontent.com/nhrap-hazus/FAST/main/Lookuptables/"
)

# WARNING: this bucket went dark on 2026-08-12, returning
# 403 AllAccessDisabled for every object and for the bucket listing. That is an
# AWS-level shutdown, not an ACL change. os-climate/physrisk still names this exact
# bucket and path in its published source, so the origin of these files remains
# checkable, but they can no longer be downloaded from here.
#
# We mirror them ourselves (MIRROR_BASE below) precisely because upstream sources
# decay -- FEMA's own fema-ftp-snapshot bucket died the same way before this project
# started. Files fetched from the mirror are verified against the SHA-256 recorded in
# raw/MANIFEST.json, which is committed, so a mirrored copy is provably the same bytes
# that were originally retrieved from upstream.
OSC_RAW = (
    "https://os-climate-physical-risk.s3.amazonaws.com/vulnerability/"
)

# Our own re-hosted copies, attached to the v0.1.0 GitHub release.
MIRROR_BASE = (
    "https://github.com/rkvaughn/hazus-curves/releases/download/v0.1.0/"
)


@dataclass(frozen=True)
class Source:
    """One upstream file.

    Attributes:
        name: Local filename under ``raw/``.
        url: Where to fetch it.
        hazus_version: Which Hazus release the *content* represents. This is not
            always the version of the tool that published it.
        peril: ``fl``, ``hu``, ``all`` (shared dimensions), or ``doc``.
        kind: ``data`` or ``doc``.
        expected_bytes: Byte size observed when this entry was written. ``None``
            where upstream is not byte-stable (Wayback re-captures). A mismatch is
            reported, never silently accepted.
        expected_rows: Row count including header, for CSVs verified during planning.
        note: Why this file matters / what to watch out for.
    """

    name: str
    url: str
    hazus_version: str
    peril: str
    kind: str = "data"
    expected_bytes: Optional[int] = None
    expected_rows: Optional[int] = None
    note: str = ""


# --------------------------------------------------------------------------------
# Hazus 4.0 flood -- published by FEMA itself in the FAST repo as direct dumps of the
# Hazus SQL Server tables. Lookuptables/README.txt states verbatim: "DDFs and other
# tables were obtained from Hazus 4.0 SQL database. We verified that no additions,
# changes, or deletions to the DDFs occurred in Hazus 3.1, 3.2, and 4.0."
#
# expected_rows below were counted directly from the live files and include the header.
# --------------------------------------------------------------------------------
FAST_SOURCES = [
    Source(
        "flBldgStructDmgFn.csv", FAST_RAW + "flBldgStructDmgFn.csv",
        "4.0", "fl", expected_rows=598,
        note="Building structure depth-damage functions. Wide: m4..m1, p0..p24.",
    ),
    Source(
        "flBldgContDmgFn.csv", FAST_RAW + "flBldgContDmgFn.csv",
        "4.0", "fl", expected_rows=508,
        note="Building contents depth-damage functions.",
    ),
    Source(
        "flBldgInvDmgFn.csv", FAST_RAW + "flBldgInvDmgFn.csv",
        "4.0", "fl", expected_rows=117,
        note="Business inventory depth-damage functions.",
    ),
    Source(
        "Building_DDF_Riverine_LUT_Hazus4p0.csv",
        FAST_RAW + "Building_DDF_Riverine_LUT_Hazus4p0.csv",
        "4.0", "fl", expected_rows=197,
        note="Default structure DDF assignment, riverine.",
    ),
    Source(
        "Building_DDF_CoastalA_LUT_Hazus4p0.csv",
        FAST_RAW + "Building_DDF_CoastalA_LUT_Hazus4p0.csv",
        "4.0", "fl", note="Default structure DDF assignment, Coastal A.",
    ),
    Source(
        "Building_DDF_CoastalV_LUT_Hazus4p0.csv",
        FAST_RAW + "Building_DDF_CoastalV_LUT_Hazus4p0.csv",
        "4.0", "fl", note="Default structure DDF assignment, Coastal V.",
    ),
    Source(
        "Content_DDF_Riverine_LUT_Hazus4p0.csv",
        FAST_RAW + "Content_DDF_Riverine_LUT_Hazus4p0.csv",
        "4.0", "fl", note="Default contents DDF assignment, riverine.",
    ),
    Source(
        "Content_DDF_CoastalA_LUT_Hazus4p0.csv",
        FAST_RAW + "Content_DDF_CoastalA_LUT_Hazus4p0.csv",
        "4.0", "fl", note="Default contents DDF assignment, Coastal A.",
    ),
    Source(
        "Content_DDF_CoastalV_LUT_Hazus4p0.csv",
        FAST_RAW + "Content_DDF_CoastalV_LUT_Hazus4p0.csv",
        "4.0", "fl", note="Default contents DDF assignment, Coastal V.",
    ),
    Source(
        "Inventory_DDF_LUT_Hazus4p0.csv",
        FAST_RAW + "Inventory_DDF_LUT_Hazus4p0.csv",
        "4.0", "fl", note="Default inventory DDF assignment.",
    ),
    Source(
        "OccupancyTypes.csv", FAST_RAW + "OccupancyTypes.csv",
        "4.0", "all",
        note="Occupancy class dimension. Values are space-padded; strip on load.",
    ),
    Source(
        "FAST_Lookuptables_README.txt", FAST_RAW + "README.txt",
        "4.0", "doc", kind="doc",
        note="States the DDFs came from the Hazus 4.0 SQL database unchanged since 3.1.",
    ),
]

# --------------------------------------------------------------------------------
# Hazus 6.1 -- via the public anonymous-read S3 bucket used by os-climate/physrisk
# (Apache-2.0, actively maintained). These are Excel extracts of the Hazus SQL tables;
# the sheet names are authentic Hazus table names. How OS-Climate obtained them is not
# documented upstream -- see docs/provenance.md. The 4.0-vs-6.1 diff provides partial
# corroboration.
# --------------------------------------------------------------------------------
OSC_SOURCES = [
    Source(
        "HazusFloodDamageFunctions_Hazus61.xlsx",
        OSC_RAW + "HazusFloodDamageFunctions_Hazus61.xlsx",
        "6.1", "fl", expected_bytes=403_618,
        note="Sheets: flBldgStrucDmgFn (2), flBldgStrucDmgFn, flBldgContDmgFunc, "
             "flBldgInvDmgFn, SOoccupId_Occ_Xref, flBldgStructDmgFinal, "
             "flBldgContDmgFinal, flBldgInvDmgFinal, OccupancyTypes.",
    ),
    Source(
        "HazusWindDamFunctions_Hazus61.xlsx",
        OSC_RAW + "HazusWindDamFunctions_Hazus61.xlsx",
        "6.1", "hu", expected_bytes=102_182_624,
        note="Sheets: huListOfWindBldgTypes, huDamLossFunDescription, huDamLossFun. "
             "FEMA's 7.1 release notes disclose that in 6.1/7.0 the WMUH2/WMUH3/"
             "MMUH2/MMUH3 curves were overwritten with 1-story copies -- these are "
             "flagged, not withheld. See docs/provenance.md.",
    ),
    Source(
        "flUtilFltyDmgFn.csv", OSC_RAW + "flUtilFltyDmgFn.csv",
        "6.1", "fl", expected_bytes=7_480,
        note="Utility facility damage functions.",
    ),
]

# --------------------------------------------------------------------------------
# FEMA documentation, fetched through the Wayback bypass. Not parsed for curve values
# in v1 -- retained so provenance claims in docs/ are checkable against primary text,
# and as the acquisition path for the v2 earthquake/tsunami work.
# --------------------------------------------------------------------------------
_FEMA = "https://www.fema.gov/sites/default/files/documents/"

DOC_SOURCES = [
    Source("fema_Hazus-6.1-Release-Notes.pdf",
           WAYBACK_PREFIX + _FEMA + "fema_Hazus-6.1-Release-Notes.pdf",
           "6.1", "doc", kind="doc",
           note="Documents the ~300 structure / ~400 content DDF expansion in 6.1."),
    Source("fema_hazus_7_release_notes.pdf",
           WAYBACK_PREFIX + _FEMA + "fema_hazus_7_release_notes.pdf",
           "7.0", "doc", kind="doc",
           note="Depth-limited coastal DDF assignment rule; hurricane defects disclosed."),
    Source("fema_hazus-7-1-release-notes.pdf",
           WAYBACK_PREFIX + _FEMA + "fema_hazus-7-1-release-notes.pdf",
           "7.1", "doc", kind="doc",
           note="RSA-21186: the huDamLossFun multi-family wind curve correction."),
    Source("fema_rsl_hazus-7-fltm_06272025_0.pdf",
           WAYBACK_PREFIX + _FEMA + "fema_rsl_hazus-7-fltm_06272025_0.pdf",
           "7.0", "doc", kind="doc", note="Flood Model Technical Manual 7.0."),
    Source("fema_rsl_hazus-7-hutm_06272025_0.pdf",
           WAYBACK_PREFIX + _FEMA + "fema_rsl_hazus-7-hutm_06272025_0.pdf",
           "7.0", "doc", kind="doc", note="Hurricane Model Technical Manual 7.0."),
    Source("fema_rsl_hazus-7-invtm_06272025_1.pdf",
           WAYBACK_PREFIX + _FEMA + "fema_rsl_hazus-7-invtm_06272025_1.pdf",
           "7.0", "doc", kind="doc",
           note="Inventory Technical Manual 7.0 - occupancy and building type code lists."),
    Source("fema_hazus-flood-model-technical-manual-6-1.pdf",
           WAYBACK_PREFIX + _FEMA + "fema_hazus-flood-model-technical-manual-6-1.pdf",
           "6.1", "doc", kind="doc",
           note="Flood Model Technical Manual 6.1 - matches the flood curve vintage."),
    Source("Hazus_6.1_Hurricane_Model_Technical_Manual.pdf",
           WAYBACK_PREFIX + _FEMA + "Hazus_6.1_Hurricane_Model_Technical_Manual.pdf",
           "6.1", "doc", kind="doc",
           note="Hurricane Model Technical Manual 6.1 - matches the wind curve vintage."),
    Source("fema_hazus-inventory-technical-manual-6.1.pdf",
           WAYBACK_PREFIX + _FEMA + "fema_hazus-inventory-technical-manual-6.1.pdf",
           "6.1", "doc", kind="doc", note="Inventory Technical Manual 6.1."),
    # Earthquake and tsunami are not extracted in v1, but the manuals are retained so
    # the acquisition path is proven and the v2 work has its sources pinned.
    Source("fema_hazus-earthquake-model-technical-manual-6-1.pdf",
           WAYBACK_PREFIX + _FEMA + "fema_hazus-earthquake-model-technical-manual-6-1.pdf",
           "6.1", "doc", kind="doc",
           note="Earthquake Model Technical Manual 6.1 - fragility parameters, for v2."),
    Source("Hazus_6.1_Tsunami_Model_Technical_Manual.pdf",
           WAYBACK_PREFIX + _FEMA + "Hazus_6.1_Tsunami_Model_Technical_Manual.pdf",
           "6.1", "doc", kind="doc",
           note="Tsunami Model Technical Manual 6.1 - for v2."),
]

ALL_SOURCES = FAST_SOURCES + OSC_SOURCES + DOC_SOURCES
DATA_SOURCES = [s for s in ALL_SOURCES if s.kind == "data"]


def by_name(name: str) -> Source:
    for s in ALL_SOURCES:
        if s.name == name:
            return s
    raise KeyError(f"no such source: {name!r}")


def for_perils(perils) -> list:
    """Sources needed for the given perils, plus shared dimension tables."""
    wanted = set(perils) | {"all"}
    return [s for s in DATA_SOURCES if s.peril in wanted]
