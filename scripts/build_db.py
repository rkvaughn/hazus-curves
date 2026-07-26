#!/usr/bin/env python3
"""Assemble the published database: SQLite, Parquet, and per-engine DDL.

Reads the tidy CSV/Parquet produced by build_flood.py and build_hurricane.py, adds the
metadata tables (curve_kind, assignment_rules, provenance), and emits:

    dist/hazus_curves.sqlite      flood by default; --perils fl,hu to include wind
    dist/*.parquet                one file per table
    sql/<engine>.sql              CREATE TABLE DDL for sqlite/duckdb/postgresql/snowflake
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import openpyxl
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hazus_curves.schema import TABLES, TYPE_MAP, ddl

REPO = Path(__file__).resolve().parent.parent
RAW, DATA, DIST, SQL = REPO / "raw", REPO / "data", REPO / "dist", REPO / "sql"

WORKBOOK_61 = "HazusFloodDamageFunctions_Hazus61.xlsx"
WORKBOOK_HU = "HazusWindDamFunctions_Hazus61.xlsx"

# What x and y mean, per peril and damage type. Sourced from the Hazus technical
# manuals and the workbook's own huDamLossFunDescription sheet. Consumers should read
# this table rather than assuming units -- the nine hurricane loss classes do NOT
# share units, so averaging across them is meaningless.
CURVE_KIND = [
    ("fl", "structure", "depth", "ft_above_first_floor", "damage", "percent",
     "piecewise_linear",
     "Depth is relative to the first finished floor, not ground level. Negative "
     "depths represent basement flooding."),
    ("fl", "contents", "depth", "ft_above_first_floor", "damage", "percent",
     "piecewise_linear", "Percent of contents replacement value."),
    ("fl", "inventory", "depth", "ft_above_first_floor", "damage", "percent",
     "piecewise_linear", "Business inventory. Percent of inventory value."),
    ("hu", "damage_slight", "wind_speed", "mph_3s_gust", "exceedance_probability",
     "probability_0_1", "piecewise_linear",
     "Probability of reaching or exceeding Slight damage."),
    ("hu", "damage_moderate", "wind_speed", "mph_3s_gust", "exceedance_probability",
     "probability_0_1", "piecewise_linear", ""),
    ("hu", "damage_severe", "wind_speed", "mph_3s_gust", "exceedance_probability",
     "probability_0_1", "piecewise_linear", ""),
    ("hu", "damage_total", "wind_speed", "mph_3s_gust", "exceedance_probability",
     "probability_0_1", "piecewise_linear", ""),
    ("hu", "building_loss", "wind_speed", "mph_3s_gust", "loss", "loss_ratio_0_1",
     "piecewise_linear", "Loss as a fraction of building replacement value."),
    ("hu", "content_loss", "wind_speed", "mph_3s_gust", "loss", "loss_ratio_0_1",
     "piecewise_linear", ""),
    ("hu", "loss_of_use", "wind_speed", "mph_3s_gust", "loss_of_use", "days",
     "piecewise_linear", "Downtime in days. NOT a ratio -- do not mix with loss curves."),
    ("hu", "debris_brick_wood", "wind_speed", "mph_3s_gust", "debris", "lbs_per_sqft",
     "piecewise_linear", ""),
    ("hu", "debris_concrete_steel", "wind_speed", "mph_3s_gust", "debris",
     "lbs_per_sqft", "piecewise_linear", ""),
]


# Hazus 7.0 Release Notes section 2.2, "Depth-Limited Coastal Zone Assignment",
# verbatim: "Hazus automatically assigns Coastal V Zone DDFs when water depths are 6
# feet or greater, and Coastal A Zone DDFs for water depths between 3 and 6 feet. When
# water depths are 3 feet or less, the software will assign A Zone DDFs, also referred
# to as the Riverine DDFs in Hazus." This supersedes the flat default-by-zone assignment
# recorded in the rules below, which is what Hazus 6.1 and earlier used.
COASTAL_DEPTH_RULE_7_0 = (
    "Superseded in Hazus 7.0 by the depth-limited coastal rule: Coastal V DDFs at "
    "depths >= 6 ft, Coastal A DDFs between 3 and 6 ft, Riverine (A-Zone) DDFs below "
    "3 ft. Source: Hazus 7.0 Release Notes 2.2. The rule below is the Hazus 6.1 and "
    "earlier behaviour."
)

# 4.0 assignment lookups published by FEMA in the FAST repository. Each row maps an
# occupancy/stories/basement combination to a DDF_ID and carries per-zone applicability
# flags. These were fetched and checksummed from the start but never parsed, which is
# why no Hazus 4.0 curve was reachable through the zone filter.
LUT_4_0 = [
    ("structure", "Building_DDF_Riverine_LUT_Hazus4p0.csv", "Riverine"),
    ("structure", "Building_DDF_CoastalA_LUT_Hazus4p0.csv", "CoastalA"),
    ("structure", "Building_DDF_CoastalV_LUT_Hazus4p0.csv", "CoastalV"),
    ("contents",  "Content_DDF_Riverine_LUT_Hazus4p0.csv",  "Riverine"),
    ("contents",  "Content_DDF_CoastalA_LUT_Hazus4p0.csv",  "CoastalA"),
    ("contents",  "Content_DDF_CoastalV_LUT_Hazus4p0.csv",  "CoastalV"),
    ("inventory", "Inventory_DDF_LUT_Hazus4p0.csv",         "Riverine"),
]

ZONE_FLAGS = (("Riverine", "HazardRiverine"), ("CoastalA", "HazardCA"),
              ("CoastalV", "HazardCV"))


def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None


def build_assignment_rules() -> pd.DataFrame:
    """Hazus's own default curve selection, for BOTH published vintages.

    6.1 comes from the workbook's *Final tables joined to SOoccupId_Occ_Xref.
    4.0 comes from FEMA's published DDF lookup tables in the FAST repository.

    Covering 4.0 matters: the website filters flood zone by joining this table, so while
    it held 6.1 rows only, selecting any zone silently returned zero Hazus 4.0 curves.
    """
    out = []

    xl = pd.ExcelFile(RAW / WORKBOOK_61)
    xref = xl.parse("SOoccupId_Occ_Xref")
    for damage_type, sheet, idcol in [
        ("structure", "flBldgStructDmgFinal", "BldgDmgFnId"),
        ("contents",  "flBldgContDmgFinal",   "ContDmgFnId"),
        ("inventory", "flBldgInvDmgFinal",    "InvDmgFnId"),
    ]:
        df = xl.parse(sheet).merge(xref, on="SOccupId", how="left")
        for _, r in df.iterrows():
            for zone, col in (("Riverine", "HazardR"), ("CoastalA", "HazardCA"),
                              ("CoastalV", "HazardCV")):
                if not r.get(col):
                    continue
                fn = r[idcol]
                if pd.isna(fn):
                    continue
                out.append({
                    "rule_id": f"fl-6.1-{damage_type}-{r['SOccupId']}-{zone}",
                    "peril": "fl",
                    "hazus_version": "6.1",
                    "damage_type": damage_type,
                    "occupancy": _clean(r.get("Occupancy")),
                    "flood_zone": zone,
                    "stories": _clean(r.get("NumStories")),
                    "basement": _clean(r.get("Basement")),
                    "curve_id": f"fl-6.1-{damage_type}-{int(fn)}",
                    "source_file": WORKBOOK_61,
                    "source_table": sheet,
                    "notes": (COASTAL_DEPTH_RULE_7_0
                              if zone in ("CoastalA", "CoastalV") else None),
                })

    for damage_type, filename, zone in LUT_4_0:
        path = RAW / filename
        if not path.exists():
            print(f"  warning: {filename} missing; Hazus 4.0 {damage_type}/{zone} "
                  f"assignment rules will be absent")
            continue
        df = pd.read_csv(path)
        for i, r in df.iterrows():
            fn = r.get("DDF_ID")
            if pd.isna(fn):
                continue
            occ = _clean(r.get("Occupancy"))
            stories = _clean(r.get("Stories"))
            basement = _clean(r.get("Basement"))
            out.append({
                "rule_id": f"fl-4.0-{damage_type}-{zone}-{i}",
                "peril": "fl",
                "hazus_version": "4.0",
                "damage_type": damage_type,
                "occupancy": occ,
                "flood_zone": zone,
                "stories": stories,
                "basement": basement,
                "curve_id": f"fl-4.0-{damage_type}-{int(fn)}",
                "source_file": filename,
                "source_table": filename.rsplit(".", 1)[0],
                "notes": (COASTAL_DEPTH_RULE_7_0
                          if zone in ("CoastalA", "CoastalV") else None),
            })

    return pd.DataFrame(out).drop_duplicates("rule_id")


def build_zone_applicability(curves: pd.DataFrame) -> pd.DataFrame:
    """Which flood zones Hazus flags each curve as applicable to.

    Distinct from assignment_rules: a rule says "this combination selects that curve by
    default in this zone", whereas this says "Hazus marks this curve usable in this
    zone". A single curve is often flagged for more than one zone.

    Hazus only publishes zone flags for the curves it assigns; the rest of the library
    is alternates a user picks by hand, and no published table gives them a zone. So
    absence here means "Hazus states no zone", not "not applicable" -- callers must not
    read a missing row as an exclusion.
    """
    rows = []

    for damage_type, filename, _default_zone in LUT_4_0:
        path = RAW / filename
        if not path.exists():
            continue
        df = pd.read_csv(path)
        for _, r in df.iterrows():
            fn = r.get("DDF_ID")
            if pd.isna(fn):
                continue
            for zone, col in ZONE_FLAGS:
                if col in df.columns and r.get(col) == 1:
                    rows.append({
                        "curve_id": f"fl-4.0-{damage_type}-{int(fn)}",
                        "flood_zone": zone,
                        "source_file": filename,
                        "source_table": filename.rsplit(".", 1)[0],
                    })

    xl = pd.ExcelFile(RAW / WORKBOOK_61)
    for damage_type, sheet, idcol in [
        ("structure", "flBldgStructDmgFinal", "BldgDmgFnId"),
        ("contents",  "flBldgContDmgFinal",   "ContDmgFnId"),
        ("inventory", "flBldgInvDmgFinal",    "InvDmgFnId"),
    ]:
        df = xl.parse(sheet)
        for _, r in df.iterrows():
            fn = r.get(idcol)
            if pd.isna(fn):
                continue
            for zone, col in (("Riverine", "HazardR"), ("CoastalA", "HazardCA"),
                              ("CoastalV", "HazardCV")):
                if r.get(col):
                    rows.append({
                        "curve_id": f"fl-6.1-{damage_type}-{int(fn)}",
                        "flood_zone": zone,
                        "source_file": WORKBOOK_61,
                        "source_table": sheet,
                    })

    out = pd.DataFrame(rows).drop_duplicates(["curve_id", "flood_zone"])
    known = set(curves["curve_id"])
    dangling = sorted(set(out["curve_id"]) - known)
    if dangling:
        raise ValueError(
            f"zone applicability references {len(dangling)} curve_id(s) that do not "
            f"exist, e.g. {dangling[:5]}"
        )
    return out


def build_geographic_cases() -> pd.DataFrame:
    """Decompose Hazus geographic applicability cases into territories.

    Hazus's CaseID table is set-valued: 'ContUS+Hawaii' means "Used in Continental and
    Hawaii". Filtering by case equality therefore excludes most curves that actually
    apply in a territory -- selecting Hawaii returned 14,400 of 179,820 applicable
    curves before this table existed.

    The decomposition is read from Hazus's own CaseDescription strings, not inferred.
    """
    wb = openpyxl.load_workbook(RAW / WORKBOOK_HU, read_only=True)
    ws = wb["CaseID"]
    it = ws.iter_rows(values_only=True)
    header = [str(h).strip() for h in next(it)]
    rows = []
    for raw in it:
        rec = dict(zip(header, raw))
        name = _clean(rec.get("CaseName"))
        desc = _clean(rec.get("CaseDescription")) or ""
        if not name:
            continue
        low = desc.lower()
        territories = []
        if "continental" in low:
            territories.append("CONUS")
        if "hawaii" in low:
            territories.append("Hawaii")
        if "caribbean" in low:
            territories.append("Caribbean")
        if not territories:
            raise ValueError(
                f"CaseDescription {desc!r} for case {name!r} names no recognised "
                f"territory; refusing to guess its coverage"
            )
        for t in territories:
            rows.append({"case_name": name, "territory": t,
                         "case_description": desc})
    wb.close()
    return pd.DataFrame(rows)


def provenance_table() -> pd.DataFrame:
    manifest = json.loads((RAW / "MANIFEST.json").read_text())
    return pd.DataFrame([
        {"source_file": name, "url": m["url"], "sha256": m["sha256"],
         "bytes": m["bytes"], "retrieved_at": m["retrieved_at"],
         "hazus_version": m["hazus_version"], "note": m.get("note")}
        for name, m in sorted(manifest.items())
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--perils", default="fl",
                    help="comma-separated: fl,hu (hurricane adds ~11M rows)")
    args = ap.parse_args()
    perils = {p.strip() for p in args.perils.split(",") if p.strip()}

    DIST.mkdir(parents=True, exist_ok=True)
    SQL.mkdir(parents=True, exist_ok=True)

    for engine in TYPE_MAP:
        (SQL / f"{engine}.sql").write_text(
            f"-- Generated by scripts/build_db.py from hazus_curves/schema.py.\n"
            f"-- Target: {engine}. Do not edit by hand.\n\n" + ddl(engine)
        )
    print(f"  DDL for {len(TYPE_MAP)} engines -> sql/")

    # Read metadata as text. Left to infer, pandas turns hazus_version "4.0"/"6.1"
    # into floats, which then collide with the hurricane parquet's string column and
    # silently mislabel versions.
    curves = [pd.read_csv(DATA / "curves_fl.csv", dtype=str)]
    points = [pd.read_csv(DATA / "curve_points_fl.csv",
                          dtype={"curve_id": str, "x": float, "y": float})]
    attrs = [pd.read_csv(DATA / "curve_attributes_fl.csv", dtype=str)]

    if "hu" in perils:
        curves.append(pd.read_parquet(DIST / "curves_hu.parquet"))
        attrs.append(pd.read_parquet(DIST / "curve_attributes_hu.parquet"))
        points.append(pd.read_parquet(DIST / "curve_points_hu.parquet"))

    all_curves = pd.concat(curves, ignore_index=True)
    tables = {
        "curves": all_curves,
        "curve_points": pd.concat(points, ignore_index=True),
        "curve_attributes": pd.concat(attrs, ignore_index=True),
        "curve_kind": pd.DataFrame(CURVE_KIND, columns=[
            "peril", "damage_type", "x_name", "x_units", "y_name", "y_units",
            "interpolation", "notes"]),
        "assignment_rules": build_assignment_rules(),
        "curve_zone_applicability": build_zone_applicability(all_curves),
        "dim_geographic_case": build_geographic_cases(),
        "dim_occupancy": pd.read_csv(DATA / "dim_occupancy.csv"),
        "dim_building_type": (pd.read_csv(DATA / "dim_building_type.csv")
                              if (DATA / "dim_building_type.csv").exists()
                              else pd.DataFrame(columns=["building_type",
                                                         "description"])),
        "provenance": provenance_table(),
    }

    # Keep only curve_kind rows for perils actually present, so the metadata does not
    # promise data the database does not contain.
    tables["curve_kind"] = tables["curve_kind"][
        tables["curve_kind"].peril.isin(perils)]
    if "hu" not in perils:
        tables["dim_building_type"] = tables["dim_building_type"].iloc[0:0]

    # The flood-only build is the lightweight default users get from `install`.
    # The full build carries hurricane too and is a separate, much larger artifact.
    name = "hazus_curves.sqlite" if perils == {"fl"} else "hazus_curves_full.sqlite"
    db = DIST / name
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.executescript(ddl("sqlite"))
    for t in TABLES:
        df = tables[t.name]
        cols = [c.name for c in t.columns]
        for c in cols:
            if c not in df.columns:
                df[c] = None
        # Sort the big per-curve tables so Parquet row groups hold disjoint curve_id
        # ranges. Without this every row group spans the whole key range, no row group
        # can be pruned, and the website has to fetch the entire file over HTTP range
        # requests to answer a query for a handful of curves.
        if t.name in ("curve_points", "curve_attributes"):
            sort_cols = ["curve_id"] + (["x"] if "x" in df.columns else [])
            df = df.sort_values(sort_cols, kind="stable")
        df[cols].to_sql(t.name, con, if_exists="append", index=False)
        df[cols].to_parquet(DIST / f"{t.name}.parquet", index=False,
                            compression="zstd")
        print(f"  {t.name:<20} {len(df):>10,} rows")
    con.commit()
    con.close()

    size_mb = db.stat().st_size / 1e6
    print(f"\n  {db.relative_to(REPO)}  {size_mb:,.1f} MB  (perils: {','.join(sorted(perils))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
