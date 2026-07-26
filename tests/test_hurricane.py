"""Tests for the hurricane wind curve build.

All tests skip gracefully if dist/curves_hu.parquet is absent (fresh clone).
Uses DuckDB for fast queries over the 11M-row points file.
"""

import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from conftest import REPO, DIST

sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def hu_con():
    """DuckDB connection with hurricane parquet views; skip entire module if absent."""
    curves_hu = DIST / "curves_hu.parquet"
    points_hu = DIST / "curve_points_hu.parquet"
    attrs_hu = DIST / "curve_attributes_hu.parquet"

    if not curves_hu.exists():
        pytest.skip("dist/curves_hu.parquet not present (run build_hurricane.py first)")
    if not points_hu.exists():
        pytest.skip("dist/curve_points_hu.parquet not present (run build_hurricane.py first)")

    con = duckdb.connect()
    con.execute(f"CREATE VIEW curves_hu AS SELECT * FROM '{curves_hu}'")
    con.execute(f"CREATE VIEW curve_points_hu AS SELECT * FROM '{points_hu}'")
    if attrs_hu.exists():
        con.execute(f"CREATE VIEW curve_attributes_hu AS SELECT * FROM '{attrs_hu}'")
    return con


@pytest.fixture(scope="session")
def curves_hu_df():
    p = DIST / "curves_hu.parquet"
    if not p.exists():
        pytest.skip("dist/curves_hu.parquet not present")
    return pd.read_parquet(p)


# ---------------------------------------------------------------------------
# Exact regression counts
# ---------------------------------------------------------------------------

def test_hurricane_curve_count(hu_con):
    n = hu_con.execute("SELECT COUNT(*) FROM curves_hu").fetchone()[0]
    assert n == 275220, f"Total hurricane curves: expected 275220, got {n}"


def test_hurricane_point_count(hu_con):
    n = hu_con.execute("SELECT COUNT(*) FROM curve_points_hu").fetchone()[0]
    assert n == 11284020, (
        f"Total hurricane points: expected 11284020, got {n}. "
        f"(275220 curves * 41 wind speeds)"
    )


def test_hurricane_points_equals_curves_times_41(hu_con):
    """Cross-check: point count == curve count * 41."""
    n_curves = hu_con.execute("SELECT COUNT(*) FROM curves_hu").fetchone()[0]
    n_points = hu_con.execute("SELECT COUNT(*) FROM curve_points_hu").fetchone()[0]
    assert n_points == n_curves * 41, (
        f"Points ({n_points}) != curves ({n_curves}) * 41. "
        f"Some curves may have extra or missing wind-speed points."
    )


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------

def test_hurricane_distinct_specific_building_types(hu_con):
    n = hu_con.execute(
        "SELECT COUNT(DISTINCT building_type) FROM curves_hu"
    ).fetchone()[0]
    assert n == 39, f"Distinct specific building types: expected 39, got {n}"


def test_hurricane_distinct_wind_building_type_id(hu_con):
    """curve_attributes_hu must have 6116 distinct wind_building_type_id values."""
    attrs_hu = DIST / "curve_attributes_hu.parquet"
    if not attrs_hu.exists():
        pytest.skip("dist/curve_attributes_hu.parquet not present")
    con = duckdb.connect()
    n = con.execute(
        f"SELECT COUNT(DISTINCT value) FROM '{attrs_hu}' "
        f"WHERE key = 'wind_building_type_id'"
    ).fetchone()[0]
    assert n == 6116, (
        f"Distinct wind_building_type_id attribute values: expected 6116, got {n}"
    )


# ---------------------------------------------------------------------------
# Wind speed grid
# ---------------------------------------------------------------------------

def test_hurricane_wind_speeds_are_50_to_250_step_5(hu_con):
    """x values must be exactly 50, 55, 60, ..., 250 (41 values in 5 mph steps)."""
    speeds = [row[0] for row in hu_con.execute(
        "SELECT DISTINCT x FROM curve_points_hu ORDER BY x"
    ).fetchall()]

    expected = [float(s) for s in range(50, 255, 5)]  # 50..250 inclusive, step 5
    assert len(speeds) == 41, f"Expected 41 distinct wind speeds, got {len(speeds)}"
    assert speeds == expected, (
        f"Wind speeds do not match expected 50..250 in 5 mph steps.\n"
        f"Got: {speeds}"
    )


def test_every_hurricane_curve_has_exactly_41_points(hu_con):
    """Every curve must have exactly one point per wind speed (no missing, no extras)."""
    bad = hu_con.execute("""
        SELECT curve_id, COUNT(*) AS n
        FROM curve_points_hu
        GROUP BY curve_id
        HAVING n != 41
        LIMIT 10
    """).fetchall()
    assert not bad, (
        f"{len(bad)} hurricane curve(s) do not have exactly 41 points: {bad}"
    )


# ---------------------------------------------------------------------------
# Defect flags
# ---------------------------------------------------------------------------

def test_hurricane_defect_flag_count(hu_con):
    """Exactly 34560 curves must carry a non-null defect_flag."""
    n = hu_con.execute(
        "SELECT COUNT(*) FROM curves_hu WHERE defect_flag IS NOT NULL"
    ).fetchone()[0]
    assert n == 34560, (
        f"Curves with non-null defect_flag: expected 34560, got {n}"
    )


def test_hurricane_defect_flag_only_on_expected_building_types(hu_con):
    """defect_flag must only appear on WMUH2, WMUH3, MMUH2, MMUH3."""
    expected = {"WMUH2", "WMUH3", "MMUH2", "MMUH3"}
    actual = {row[0] for row in hu_con.execute(
        "SELECT DISTINCT building_type FROM curves_hu WHERE defect_flag IS NOT NULL"
    ).fetchall()}
    unexpected = actual - expected
    assert not unexpected, (
        f"defect_flag found on unexpected building_type(s): {unexpected}. "
        f"Expected only: {expected}"
    )
    # Also assert that all expected types ARE flagged
    missing = expected - actual
    assert not missing, (
        f"Expected building_type(s) missing from defect_flag: {missing}"
    )


# ---------------------------------------------------------------------------
# defect_verified column
# ---------------------------------------------------------------------------

def test_defect_verified_column_exists(curves_hu_df):
    assert "defect_verified" in curves_hu_df.columns, (
        "Column 'defect_verified' is missing from curves_hu.parquet"
    )


def test_defect_verified_identical_to_1_story_count(curves_hu_df):
    """Exactly 15200 curves must have defect_verified == 'identical_to_1_story'."""
    n = (curves_hu_df["defect_verified"] == "identical_to_1_story").sum()
    assert n == 15200, (
        f"Curves with defect_verified='identical_to_1_story': expected 15200, got {n}"
    )
