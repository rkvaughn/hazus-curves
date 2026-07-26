"""Unit and range assertions for flood and hurricane curves.

Flood y values are percentages (0..100).
Hurricane y values depend on damage_type and must NOT be treated as percentages.
"""

import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from conftest import REPO, DATA, DIST

sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def points_fl():
    p = DATA / "curve_points_fl.csv"
    if not p.exists():
        pytest.skip("data/curve_points_fl.csv not present (run build_flood.py first)")
    return pd.read_csv(p)


@pytest.fixture(scope="session")
def hu_con():
    """DuckDB connection over the hurricane parquet files; skip if absent."""
    curves_hu = DIST / "curves_hu.parquet"
    points_hu = DIST / "curve_points_hu.parquet"
    if not curves_hu.exists() or not points_hu.exists():
        pytest.skip("dist/curves_hu.parquet or curve_points_hu.parquet not present")
    con = duckdb.connect()
    # Register as views for convenience
    con.execute(f"CREATE VIEW curves_hu AS SELECT * FROM '{curves_hu}'")
    con.execute(f"CREATE VIEW curve_points_hu AS SELECT * FROM '{points_hu}'")
    return con


@pytest.fixture(scope="session")
def curve_kind_fl():
    p = DIST / "curve_kind.parquet"
    if not p.exists():
        pytest.skip("dist/curve_kind.parquet not present (run build_db.py first)")
    return pd.read_parquet(p)


# ---------------------------------------------------------------------------
# Flood: y is percent, 0..100
# ---------------------------------------------------------------------------

def test_flood_y_in_0_to_100(points_fl):
    """All non-null flood y values must be in [0, 100]. Report excursions, do not clamp."""
    non_null = points_fl[points_fl["y"].notna()]
    out_of_range = non_null[(non_null["y"] < 0) | (non_null["y"] > 100)]
    if len(out_of_range) > 0:
        examples = out_of_range[["curve_id", "x", "y"]].head(10)
        pytest.fail(
            f"{len(out_of_range)} flood point(s) have y outside [0, 100]:\n"
            f"{examples.to_string(index=False)}"
        )


# ---------------------------------------------------------------------------
# Hurricane: units vary by damage_type; must NOT be range-checked as percentages
# ---------------------------------------------------------------------------

# Damage types whose y values are probabilities in [0, 1]
_PROBABILITY_TYPES = {
    "damage_slight", "damage_moderate", "damage_severe", "damage_total",
}
# Damage types whose y values are loss ratios in [0, 1]
_LOSS_RATIO_TYPES = {
    "building_loss", "content_loss",
}
# Damage types whose y values are non-negative real numbers (not ratios)
_NONNEG_TYPES = {
    "loss_of_use",          # days
    "debris_brick_wood",    # lbs_per_sqft
    "debris_concrete_steel",  # lbs_per_sqft
}


# The Hazus 6.1 wind workbook contains probabilities and loss ratios that marginally
# exceed 1.0. Verified by scanning the raw xlsx directly: max 1.001 for damage_slight
# and damage_moderate, 1.000052 for building_loss, 1.000001 for content_loss.
#
# These are upstream values and are published unchanged -- clamping them would
# fabricate data. The counts below are regression anchors: if they move, either the
# upstream file changed or the pipeline started altering values. Both need
# investigating. See docs/data_quality.md.
KNOWN_OVER_ONE = {
    "damage_slight":   (1911, 1.001),
    "damage_moderate":  (982, 1.001),
    "building_loss":   (5402, 1.000052),
    "content_loss":       (2, 1.000001),
}
OVER_ONE_TOLERANCE = 1.01


def _over_one(con, types):
    types_list = ", ".join(f"'{t}'" for t in types)
    return con.execute(f"""
        SELECT c.damage_type, count(*) AS n, max(p.y) AS max_y
        FROM curve_points_hu p
        JOIN curves_hu c USING (curve_id)
        WHERE c.damage_type IN ({types_list})
          AND p.y IS NOT NULL AND p.y > 1
        GROUP BY 1
    """).fetchall()


def test_hurricane_probability_curves_have_no_negative_y(hu_con):
    """Probabilities may marginally exceed 1 upstream, but must never be negative."""
    types_list = ", ".join(f"'{t}'" for t in _PROBABILITY_TYPES)
    bad = hu_con.execute(f"""
        SELECT p.curve_id, p.x, p.y FROM curve_points_hu p
        JOIN curves_hu c USING (curve_id)
        WHERE c.damage_type IN ({types_list}) AND p.y < 0
    """).fetchall()
    assert not bad, f"{len(bad)} negative probability points, e.g. {bad[:5]}"


def test_hurricane_over_one_values_match_known_upstream_quirk(hu_con):
    """Pin the exact known out-of-range values so any change is caught.

    This documents an upstream data characteristic. It must never be "fixed" by
    clamping -- the values are what FEMA published.
    """
    observed = {dt: (n, mx) for dt, n, mx in
                _over_one(hu_con, _PROBABILITY_TYPES | _LOSS_RATIO_TYPES)}
    assert observed == KNOWN_OVER_ONE, (
        "out-of-range hurricane values changed.\n"
        f"  expected: {KNOWN_OVER_ONE}\n"
        f"  observed: {observed}\n"
        "Either the upstream workbook changed or the pipeline is altering values."
    )
    for _dt, (_n, max_y) in observed.items():
        assert max_y < OVER_ONE_TOLERANCE, (
            f"y={max_y} exceeds 1 by more than rounding noise -- this is no longer a "
            f"benign upstream quirk and needs investigation."
        )


def test_hurricane_nonneg_curves_are_nonneg(hu_con):
    """Days and lbs_per_sqft hurricane curves must have non-negative y."""
    types_list = ", ".join(f"'{t}'" for t in _NONNEG_TYPES)
    result = hu_con.execute(f"""
        SELECT p.curve_id, p.x, p.y, c.damage_type
        FROM curve_points_hu p
        JOIN curves_hu c USING (curve_id)
        WHERE c.damage_type IN ({types_list})
          AND p.y IS NOT NULL
          AND p.y < 0
    """).fetchall()
    if result:
        pytest.fail(
            f"{len(result)} days/lbs_per_sqft curve point(s) have negative y:\n"
            f"First 5: {result[:5]}"
        )


def test_hurricane_not_checked_as_flood_percentages(hu_con):
    """Verify that hurricane y values are NOT all within 0..100.

    This test MUST fail if someone accidentally range-checks hurricane curves as
    percentages (0..100). We assert that at least some values exceed 1, which would
    be impossible if they were all probabilities and would be wrong to treat as pct.
    Days and lbs/sqft curves routinely exceed 1, so this is always true when the
    data is present.
    """
    nonneg_types = ", ".join(f"'{t}'" for t in _NONNEG_TYPES)
    count = hu_con.execute(f"""
        SELECT COUNT(*)
        FROM curve_points_hu p
        JOIN curves_hu c USING (curve_id)
        WHERE c.damage_type IN ({nonneg_types})
          AND p.y IS NOT NULL
          AND p.y > 1
    """).fetchone()[0]
    assert count > 0, (
        "Expected at least some hurricane y values > 1 (days / lbs_per_sqft), "
        "but found none. If this passes after applying a 0..100 range check, "
        "something is wrong with the hurricane build."
    )


# ---------------------------------------------------------------------------
# Every (peril, damage_type) present in curves has a curve_kind row
# ---------------------------------------------------------------------------

def test_flood_peril_damage_types_covered_by_curve_kind(curve_kind_fl):
    p = DATA / "curves_fl.csv"
    if not p.exists():
        pytest.skip("data/curves_fl.csv not present")
    curves = pd.read_csv(p)
    actual_pairs = set(
        zip(curves["peril"].tolist(), curves["damage_type"].tolist())
    )
    kind_pairs = set(
        zip(curve_kind_fl["peril"].tolist(), curve_kind_fl["damage_type"].tolist())
    )
    missing = actual_pairs - kind_pairs
    assert not missing, (
        f"(peril, damage_type) pairs in curves_fl not covered by curve_kind: {missing}"
    )


def test_hurricane_peril_damage_types_covered_by_curve_kind(hu_con):
    """Every (peril, damage_type) in curves_hu must have a row in curve_kind."""
    ck_path = DIST / "curve_kind.parquet"
    if not ck_path.exists():
        pytest.skip("dist/curve_kind.parquet not present")
    ck = pd.read_parquet(ck_path)
    kind_pairs = set(zip(ck["peril"].tolist(), ck["damage_type"].tolist()))

    actual_pairs = hu_con.execute(
        "SELECT DISTINCT peril, damage_type FROM curves_hu ORDER BY 1, 2"
    ).fetchall()

    missing = [(p, d) for p, d in actual_pairs if (p, d) not in kind_pairs]
    assert not missing, (
        f"(peril, damage_type) pairs in curves_hu not covered by curve_kind: {missing}"
    )
