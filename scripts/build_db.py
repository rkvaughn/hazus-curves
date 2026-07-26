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

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hazus_curves.schema import TABLES, TYPE_MAP, ddl

REPO = Path(__file__).resolve().parent.parent
RAW, DATA, DIST, SQL = REPO / "raw", REPO / "data", REPO / "dist", REPO / "sql"

WORKBOOK_61 = "HazusFloodDamageFunctions_Hazus61.xlsx"

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


def build_assignment_rules() -> pd.DataFrame:
    """Hazus's own default curve selection, from the 6.1 workbook.

    SOoccupId_Occ_Xref gives occupancy x stories x basement; the *Final tables give the
    curve each combination selects and which flood zones it applies to.
    """
    xl = pd.ExcelFile(RAW / WORKBOOK_61)
    xref = xl.parse("SOoccupId_Occ_Xref")
    out = []
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
                fn = str(int(fn))
                out.append({
                    "rule_id": f"fl-6.1-{damage_type}-{r['SOccupId']}-{zone}",
                    "peril": "fl",
                    "hazus_version": "6.1",
                    "damage_type": damage_type,
                    "occupancy": str(r.get("Occupancy") or "").strip() or None,
                    "flood_zone": zone,
                    "stories": str(r.get("NumStories") or "").strip() or None,
                    "basement": str(r.get("Basement") or "").strip() or None,
                    "curve_id": f"fl-6.1-{damage_type}-{fn}",
                    "source_file": WORKBOOK_61,
                    "source_table": sheet,
                    "notes": None,
                })
    return pd.DataFrame(out).drop_duplicates("rule_id")


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

    tables = {
        "curves": pd.concat(curves, ignore_index=True),
        "curve_points": pd.concat(points, ignore_index=True),
        "curve_attributes": pd.concat(attrs, ignore_index=True),
        "curve_kind": pd.DataFrame(CURVE_KIND, columns=[
            "peril", "damage_type", "x_name", "x_units", "y_name", "y_units",
            "interpolation", "notes"]),
        "assignment_rules": build_assignment_rules(),
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
