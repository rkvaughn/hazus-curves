"""Tests for the flood build: exact counts, depth grid, round-trips, whitespace."""

import sys
from pathlib import Path

import pandas as pd
import pytest

from conftest import REPO, RAW, DATA

sys.path.insert(0, str(REPO))
from scripts.build_flood import depth_of, DATASETS


# ---------------------------------------------------------------------------
# Fixtures: load tidy CSVs once per session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def curves_fl():
    p = DATA / "curves_fl.csv"
    if not p.exists():
        pytest.skip("data/curves_fl.csv not present (run build_flood.py first)")
    df = pd.read_csv(p, dtype={"hazus_version": str, "source_row_id": str})
    assert len(df) > 0, "data/curves_fl.csv is empty"
    return df


@pytest.fixture(scope="session")
def points_fl():
    p = DATA / "curve_points_fl.csv"
    if not p.exists():
        pytest.skip("data/curve_points_fl.csv not present (run build_flood.py first)")
    df = pd.read_csv(p)
    assert len(df) > 0, "data/curve_points_fl.csv is empty"
    return df


@pytest.fixture(scope="session")
def dim_occupancy():
    p = DATA / "dim_occupancy.csv"
    if not p.exists():
        pytest.skip("data/dim_occupancy.csv not present (run build_flood.py first)")
    return pd.read_csv(p)


# ---------------------------------------------------------------------------
# Exact regression counts (verified against upstream sources)
# ---------------------------------------------------------------------------

def test_hazus40_structure_count(curves_fl):
    n = len(curves_fl[(curves_fl["hazus_version"] == "4.0") &
                       (curves_fl["damage_type"] == "structure")])
    assert n == 597, f"Hazus 4.0 structure curves: expected 597, got {n}"


def test_hazus40_contents_count(curves_fl):
    n = len(curves_fl[(curves_fl["hazus_version"] == "4.0") &
                       (curves_fl["damage_type"] == "contents")])
    assert n == 507, f"Hazus 4.0 contents curves: expected 507, got {n}"


def test_hazus40_inventory_count(curves_fl):
    n = len(curves_fl[(curves_fl["hazus_version"] == "4.0") &
                       (curves_fl["damage_type"] == "inventory")])
    assert n == 116, f"Hazus 4.0 inventory curves: expected 116, got {n}"


def test_hazus61_structure_count(curves_fl):
    n = len(curves_fl[(curves_fl["hazus_version"] == "6.1") &
                       (curves_fl["damage_type"] == "structure")])
    assert n == 892, f"Hazus 6.1 structure curves: expected 892, got {n}"


def test_hazus61_contents_count(curves_fl):
    n = len(curves_fl[(curves_fl["hazus_version"] == "6.1") &
                       (curves_fl["damage_type"] == "contents")])
    assert n == 818, f"Hazus 6.1 contents curves: expected 818, got {n}"


def test_hazus61_inventory_count(curves_fl):
    n = len(curves_fl[(curves_fl["hazus_version"] == "6.1") &
                       (curves_fl["damage_type"] == "inventory")])
    assert n == 116, f"Hazus 6.1 inventory curves: expected 116, got {n}"


def test_total_flood_curves(curves_fl):
    assert len(curves_fl) == 3046, (
        f"Total flood curves: expected 3046, got {len(curves_fl)}"
    )


def test_total_flood_points(points_fl):
    assert len(points_fl) == 88334, (
        f"Total flood points: expected 88334, got {len(points_fl)}"
    )


# ---------------------------------------------------------------------------
# Every curve has exactly 29 points at depths -4..24
# ---------------------------------------------------------------------------

def test_every_curve_has_29_points(curves_fl, points_fl):
    expected_depths = set(range(-4, 25))
    counts = points_fl.groupby("curve_id")["x"].agg(["count", set]).rename(
        columns={"count": "n", "set": "depths"})

    wrong_count = counts[counts["n"] != 29]
    if len(wrong_count) > 0:
        sample = wrong_count.head(5)
        pytest.fail(
            f"{len(wrong_count)} curves do not have exactly 29 points.\n"
            f"Sample:\n{sample}"
        )

    wrong_depths = counts[counts["depths"].apply(
        lambda d: {int(x) for x in d} != expected_depths)]
    if len(wrong_depths) > 0:
        sample = wrong_depths.head(3)
        pytest.fail(
            f"{len(wrong_depths)} curves have a wrong depth set.\n"
            f"Sample:\n{sample}"
        )


# ---------------------------------------------------------------------------
# Round-trip: rebuild curve_points from original raw source and compare exactly
# ---------------------------------------------------------------------------

def _get_tidy_y(points_fl: pd.DataFrame, curve_id: str) -> list:
    """Return the tidy y values for curve_id, sorted by depth ascending."""
    sub = points_fl[points_fl["curve_id"] == curve_id].sort_values("x")
    assert len(sub) == 29, f"{curve_id}: expected 29 tidy points, got {len(sub)}"
    return sub["y"].tolist()


def _raw_y_from_csv(csv_name: str, id_col: str, row_id: str) -> list:
    """Read the raw 4.0 CSV and return y values for row_id in depth order -4..24."""
    df = pd.read_csv(RAW / csv_name, dtype=object)
    depth_cols_sorted = sorted(
        [(depth_of(c), c) for c in df.columns if depth_of(c) is not None]
    )
    row = df[df[id_col] == row_id]
    assert len(row) == 1, (
        f"{csv_name}: expected exactly 1 row with {id_col}={row_id!r}, "
        f"got {len(row)}"
    )
    result = []
    for _, col in depth_cols_sorted:
        v = row[col].values[0]
        # mirror build_flood.py clean() + NaN handling
        if isinstance(v, str) and v.strip() in ("", "NULL"):
            result.append(None)
        else:
            try:
                result.append(float(v))
            except (TypeError, ValueError):
                result.append(None)
    return result


def _raw_y_from_xlsx(sheet: str, id_col: str, row_id) -> list:
    """Read the 6.1 workbook and return y values for row_id in depth order -4..24."""
    xl = pd.ExcelFile(RAW / "HazusFloodDamageFunctions_Hazus61.xlsx")
    df = xl.parse(sheet)
    depth_cols_sorted = sorted(
        [(depth_of(c), c) for c in df.columns if depth_of(c) is not None]
    )
    row = df[df[id_col] == row_id]
    assert len(row) == 1, (
        f"{sheet}: expected exactly 1 row with {id_col}={row_id!r}, "
        f"got {len(row)}"
    )
    result = []
    for _, col in depth_cols_sorted:
        v = row[col].values[0]
        if pd.isna(v):
            result.append(None)
        else:
            result.append(float(v))
    return result


def test_roundtrip_40_structure_105(points_fl):
    """fl-4.0-structure-105: tidy points match raw CSV exactly."""
    if not (RAW / "flBldgStructDmgFn.csv").exists():
        pytest.skip("raw/flBldgStructDmgFn.csv not present")
    tidy = _get_tidy_y(points_fl, "fl-4.0-structure-105")
    raw = _raw_y_from_csv("flBldgStructDmgFn.csv", "BldgDmgFnID", "105")
    assert tidy == raw, (
        f"fl-4.0-structure-105: tidy values differ from raw CSV.\n"
        f"tidy: {tidy}\nraw:  {raw}"
    )


def test_roundtrip_40_contents_21(points_fl):
    """fl-4.0-contents-21: tidy points match raw CSV exactly."""
    if not (RAW / "flBldgContDmgFn.csv").exists():
        pytest.skip("raw/flBldgContDmgFn.csv not present")
    tidy = _get_tidy_y(points_fl, "fl-4.0-contents-21")
    raw = _raw_y_from_csv("flBldgContDmgFn.csv", "ContDmgFnId", "21")
    assert tidy == raw, (
        f"fl-4.0-contents-21: tidy values differ from raw CSV.\n"
        f"tidy: {tidy}\nraw:  {raw}"
    )


def test_roundtrip_40_inventory_1(points_fl):
    """fl-4.0-inventory-1: tidy points match raw CSV exactly."""
    if not (RAW / "flBldgInvDmgFn.csv").exists():
        pytest.skip("raw/flBldgInvDmgFn.csv not present")
    tidy = _get_tidy_y(points_fl, "fl-4.0-inventory-1")
    raw = _raw_y_from_csv("flBldgInvDmgFn.csv", "InvDmgFnId", "1")
    assert tidy == raw, (
        f"fl-4.0-inventory-1: tidy values differ from raw CSV.\n"
        f"tidy: {tidy}\nraw:  {raw}"
    )


def _xlsx_roundtrip(points_fl, curve_id, sheet, id_col, row_id_int):
    if not (RAW / "HazusFloodDamageFunctions_Hazus61.xlsx").exists():
        pytest.skip("raw/HazusFloodDamageFunctions_Hazus61.xlsx not present")
    tidy = _get_tidy_y(points_fl, curve_id)
    raw = _raw_y_from_xlsx(sheet, id_col, row_id_int)
    assert tidy == raw, (
        f"{curve_id}: tidy values differ from xlsx {sheet} row {row_id_int}.\n"
        f"tidy: {tidy}\nraw:  {raw}"
    )


def test_roundtrip_61_structure_105(points_fl):
    """fl-6.1-structure-105: tidy points match xlsx flBldgStrucDmgFn exactly."""
    _xlsx_roundtrip(points_fl, "fl-6.1-structure-105", "flBldgStrucDmgFn",
                    "BldgDmgFnID", 105)


def test_roundtrip_61_contents_21(points_fl):
    """fl-6.1-contents-21: tidy points match xlsx flBldgContDmgFunc exactly."""
    _xlsx_roundtrip(points_fl, "fl-6.1-contents-21", "flBldgContDmgFunc",
                    "ContDmgFnId", 21)


def test_roundtrip_61_inventory_1(points_fl):
    """fl-6.1-inventory-1: tidy points match xlsx flBldgInvDmgFn exactly."""
    _xlsx_roundtrip(points_fl, "fl-6.1-inventory-1", "flBldgInvDmgFn",
                    "InvDmgFnId", 1)


# ---------------------------------------------------------------------------
# Specific anchor: fl-4.0-structure-105
# ---------------------------------------------------------------------------

def test_curve_105_y_values_exact(points_fl):
    """fl-4.0-structure-105 has exactly these 29 y values at depths -4..24."""
    expected = [0, 0, 0, 0, 18, 22, 25, 28, 30, 31, 40, 43, 43, 45, 46, 47, 47,
                49, 50, 50, 50, 51, 51, 52, 52, 53, 53, 54, 54]
    sub = points_fl[points_fl["curve_id"] == "fl-4.0-structure-105"].sort_values("x")
    assert len(sub) == 29, (
        f"fl-4.0-structure-105: expected 29 points, got {len(sub)}"
    )
    actual = sub["y"].tolist()
    assert actual == [float(v) for v in expected], (
        f"fl-4.0-structure-105 y values mismatch.\n"
        f"expected: {expected}\n"
        f"actual:   {actual}"
    )


# ---------------------------------------------------------------------------
# No whitespace in occupancy values
# ---------------------------------------------------------------------------

def test_no_whitespace_in_dim_occupancy(dim_occupancy):
    bad = [v for v in dim_occupancy["occupancy"].dropna()
           if v != v.strip()]
    assert not bad, (
        f"dim_occupancy has {len(bad)} occupancy value(s) with leading/trailing "
        f"whitespace: {bad[:10]}"
    )


def test_no_whitespace_in_curves_occupancy(curves_fl):
    bad = [v for v in curves_fl["occupancy"].dropna()
           if v != v.strip()]
    assert not bad, (
        f"curves_fl has {len(bad)} occupancy value(s) with whitespace: {bad[:10]}"
    )


# ---------------------------------------------------------------------------
# depth_of() mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("col,expected", [
    ("m4",    -4),
    ("m1",    -1),
    ("p0",     0),
    ("p24",   24),
    ("ft04m", -4),
    ("ft03m", -3),
    ("ft02m", -2),
    ("ft01m", -1),   # -1 ft, NOT +1
    ("ft00",   0),
    ("ft01",  +1),   # +1 ft, NOT -1 (tricky: no trailing m)
    ("ft24",  24),
    ("Occupancy", None),
    ("Source",    None),
    ("Comment",   None),
    ("Default",   None),
    ("Description", None),
])
def test_depth_of(col, expected):
    result = depth_of(col)
    assert result == expected, (
        f"depth_of({col!r}): expected {expected}, got {result}"
    )


def test_depth_of_ft01m_vs_ft01_are_distinct():
    """ft01m is -1 and ft01 is +1; these must differ."""
    assert depth_of("ft01m") == -1
    assert depth_of("ft01") == +1
    assert depth_of("ft01m") != depth_of("ft01")
