#!/usr/bin/env python3
"""Build tidy flood curve tables from the Hazus 4.0 and 6.1 sources.

Two vintages are published side by side:

  4.0  from FEMA's own FAST repo CSVs, which are direct dumps of the Hazus 4.0 SQL
       tables. Authoritative because FEMA published them.
  6.1  from HazusFloodDamageFunctions_Hazus61.xlsx (os-climate mirror).

The 6.1 workbook also carries a sheet named ``flBldgStrucDmgFn (2)``. That sheet is not
a duplicate to be dropped: it is the pre-6.1 structure library, and its 597 rows are
value-identical to the FEMA-published FAST 4.0 CSV. We therefore do not emit it as
curves (it would duplicate the 4.0 vintage); we use it as an independent corroboration
that the third-party mirror faithfully reproduces FEMA data. See tests/ and
docs/provenance.md.

Nothing here computes, interpolates, or adjusts a damage value. Columns are renamed and
rows are reshaped; the numbers pass through untouched.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "raw"
DATA = REPO / "data"

WORKBOOK_61 = "HazusFloodDamageFunctions_Hazus61.xlsx"

# Depth columns are the only measurement columns; everything else is metadata.
# Two naming conventions exist for the identical -4..+24 ft grid.
#   FAST 4.0 CSV : m4 m3 m2 m1 p0 p1 ... p24
#   6.1 workbook : ft04m ft03m ft02m ft01m ft00 ft01 ... ft24
# Note ft01m (-1 ft) and ft01 (+1 ft) differ only by the trailing 'm'.
DEPTHS = list(range(-4, 25))


def depth_of(col: str):
    """Return the depth in feet a column encodes, or None if it is not a depth column."""
    c = col.strip()
    if c.startswith("ft"):
        body = c[2:]
        if body.endswith("m"):
            body, sign = body[:-1], -1
        else:
            sign = 1
        return sign * int(body) if body.isdigit() else None
    if len(c) >= 2 and c[0] in "mp" and c[1:].isdigit():
        return (-1 if c[0] == "m" else 1) * int(c[1:])
    return None


# Every source column must be accounted for. Anything not mapped, not stored as an
# attribute, and not listed here fails the losslessness test in tests/.
IGNORED_COLUMNS = {
    # (source_table, column): reason
}

# Non-depth columns and where each one goes.
COLUMN_ROLES = {
    "BldgDmgFnID": "source_row_id",
    "ContDmgFnId": "source_row_id",
    "InvDmgFnId": "source_row_id",
    "Occupancy": "occupancy",
    "Source": "source_agency",
    "Description": "description",
    "Comment": "attr:comment",
    "Default": "attr:hazus_default_flag",
}

DATASETS = [
    # (damage_type, 4.0 csv filename, 6.1 sheet name, id column)
    ("structure", "flBldgStructDmgFn.csv", "flBldgStrucDmgFn", "BldgDmgFnID"),
    ("contents",  "flBldgContDmgFn.csv",   "flBldgContDmgFunc", "ContDmgFnId"),
    ("inventory", "flBldgInvDmgFn.csv",    "flBldgInvDmgFn",    "InvDmgFnId"),
]


def clean(value):
    """Strip Hazus's fixed-width padding. Does not alter numeric values."""
    if isinstance(value, str):
        value = value.strip()
        return value if value and value != "NULL" else None
    if pd.isna(value):
        return None
    return value


def melt_table(df: pd.DataFrame, *, damage_type: str, version: str,
               source_file: str, source_table: str):
    """Reshape one wide damage-function table into tidy curves/points/attributes."""
    depth_cols = {c: depth_of(c) for c in df.columns if depth_of(c) is not None}
    meta_cols = [c for c in df.columns if c not in depth_cols]

    unknown = [c for c in meta_cols if c not in COLUMN_ROLES
               and (source_table, c) not in IGNORED_COLUMNS]
    if unknown:
        raise ValueError(
            f"{source_table}: unmapped columns {unknown}. Add them to COLUMN_ROLES or "
            f"IGNORED_COLUMNS with a reason -- silently dropping source data is not "
            f"permitted."
        )

    found = sorted(depth_cols.values())
    if found != DEPTHS:
        raise ValueError(
            f"{source_table}: depth grid is {found[:3]}..{found[-3:]} "
            f"({len(found)} points), expected -4..24 (29 points)"
        )

    id_col = next(c for c in meta_cols if COLUMN_ROLES.get(c) == "source_row_id")

    curves, points, attrs = [], [], []
    for _, row in df.iterrows():
        raw_id = clean(row[id_col])
        if raw_id is None:
            continue
        source_row_id = str(int(raw_id)) if isinstance(raw_id, float) else str(raw_id)
        curve_id = f"fl-{version}-{damage_type}-{source_row_id}"

        record = {
            "curve_id": curve_id,
            "peril": "fl",
            "hazus_version": version,
            "damage_type": damage_type,
            "occupancy": None,
            "building_type": None,
            "source_agency": None,
            "description": None,
            "defect_flag": None,
            "source_file": source_file,
            "source_table": source_table,
            "source_row_id": source_row_id,
        }
        for col in meta_cols:
            role = COLUMN_ROLES.get(col)
            if role is None or role == "source_row_id":
                continue
            value = clean(row[col])
            if role.startswith("attr:"):
                if value is not None:
                    attrs.append({"curve_id": curve_id, "key": role[5:],
                                  "value": str(value)})
            else:
                record[role] = value
        curves.append(record)

        for col, depth in depth_cols.items():
            value = row[col]
            # NULL stays NULL. A missing damage value is never filled or interpolated.
            y = None if (isinstance(value, str) and value.strip() in ("", "NULL")) \
                else (None if pd.isna(value) else float(value))
            points.append({"curve_id": curve_id, "x": float(depth), "y": y})

    return (pd.DataFrame(curves), pd.DataFrame(points),
            pd.DataFrame(attrs, columns=["curve_id", "key", "value"]))


def build():
    xl = pd.ExcelFile(RAW / WORKBOOK_61)
    all_curves, all_points, all_attrs = [], [], []

    for damage_type, csv_name, sheet_name, _id in DATASETS:
        df40 = pd.read_csv(RAW / csv_name, dtype=object)
        c, p, a = melt_table(df40, damage_type=damage_type, version="4.0",
                             source_file=csv_name, source_table=csv_name.split(".")[0])
        all_curves.append(c); all_points.append(p); all_attrs.append(a)
        print(f"  4.0 {damage_type:<10} {len(c):>4} curves  {len(p):>6} points")

        df61 = xl.parse(sheet_name)
        c, p, a = melt_table(df61, damage_type=damage_type, version="6.1",
                             source_file=WORKBOOK_61, source_table=sheet_name)
        all_curves.append(c); all_points.append(p); all_attrs.append(a)
        print(f"  6.1 {damage_type:<10} {len(c):>4} curves  {len(p):>6} points")

    curves = pd.concat(all_curves, ignore_index=True)
    points = pd.concat(all_points, ignore_index=True)
    attrs = pd.concat(all_attrs, ignore_index=True)

    # Occupancy dimension, whitespace stripped.
    occ = pd.read_csv(RAW / "OccupancyTypes.csv", dtype=object)
    occ = pd.DataFrame({
        "occupancy": occ["Occupancy"].map(clean),
        "category": occ["Category"].map(clean),
        "description": occ["Description"].map(clean),
    }).drop_duplicates("occupancy")

    DATA.mkdir(parents=True, exist_ok=True)
    curves.to_csv(DATA / "curves_fl.csv", index=False)
    points.to_csv(DATA / "curve_points_fl.csv", index=False)
    attrs.to_csv(DATA / "curve_attributes_fl.csv", index=False)
    occ.to_csv(DATA / "dim_occupancy.csv", index=False)

    print(f"\n  total {len(curves)} flood curves, {len(points)} points, "
          f"{len(attrs)} attributes, {len(occ)} occupancy classes")
    return curves, points, attrs


if __name__ == "__main__":
    build()
