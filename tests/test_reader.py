"""Tests for hazus_curves/reader.py: interpolate() and get_curve()."""

import sys
from pathlib import Path

import pytest

from conftest import REPO, DIST

sys.path.insert(0, str(REPO))
from hazus_curves.reader import interpolate, get_curve, connect, CurveError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_con():
    db = DIST / "hazus_curves.sqlite"
    if not db.exists():
        pytest.skip("dist/hazus_curves.sqlite not present (run build_db.py first)")
    return connect(db)


# ---------------------------------------------------------------------------
# interpolate() — pure unit tests (no file I/O)
# ---------------------------------------------------------------------------

# A simple 3-point curve for synthetic tests
SYNTHETIC_POINTS = [(0.0, 10.0), (5.0, 20.0), (10.0, 30.0)]


def test_interpolate_exact_left_endpoint():
    result = interpolate(SYNTHETIC_POINTS, 0.0)
    assert result == 10.0


def test_interpolate_exact_right_endpoint():
    result = interpolate(SYNTHETIC_POINTS, 10.0)
    assert result == 30.0


def test_interpolate_exact_interior_point():
    result = interpolate(SYNTHETIC_POINTS, 5.0)
    assert result == 20.0


def test_interpolate_linear_midpoint():
    # Midpoint between (0, 10) and (5, 20) should be exactly 15.0
    result = interpolate(SYNTHETIC_POINTS, 2.5)
    assert result == pytest.approx(15.0)


def test_interpolate_linear_quarter_point():
    # x=1.25 is 25% of [0..5]; y should be 10 + 0.25*10 = 12.5
    result = interpolate(SYNTHETIC_POINTS, 1.25)
    assert result == pytest.approx(12.5)


def test_interpolate_raises_below_domain():
    with pytest.raises(CurveError, match="outside the published domain"):
        interpolate(SYNTHETIC_POINTS, -0.001)


def test_interpolate_raises_above_domain():
    with pytest.raises(CurveError, match="outside the published domain"):
        interpolate(SYNTHETIC_POINTS, 10.001)


def test_interpolate_does_not_extrapolate_far_below():
    """Confirm that no result is returned outside the domain (no silent extrapolation)."""
    with pytest.raises(CurveError):
        interpolate(SYNTHETIC_POINTS, -100.0)


def test_interpolate_does_not_extrapolate_far_above():
    with pytest.raises(CurveError):
        interpolate(SYNTHETIC_POINTS, 1000.0)


def test_interpolate_raises_at_gap_endpoint_none():
    """interpolate() raises CurveError when the queried exact x has y=None."""
    points_with_gap = [(0.0, 10.0), (5.0, None), (10.0, 30.0)]
    with pytest.raises(CurveError, match="no published value at x=5"):
        interpolate(points_with_gap, 5.0)


def test_interpolate_raises_across_gap_left_none():
    """interpolate() raises CurveError when the left endpoint y of a segment is None."""
    points_with_gap = [(0.0, None), (5.0, 20.0), (10.0, 30.0)]
    with pytest.raises(CurveError, match="cannot interpolate across a gap"):
        interpolate(points_with_gap, 2.5)


def test_interpolate_raises_across_gap_right_none():
    """interpolate() raises CurveError when the right endpoint y of a segment is None."""
    points_with_gap = [(0.0, 10.0), (5.0, None), (10.0, 30.0)]
    with pytest.raises(CurveError, match="cannot interpolate across a gap"):
        interpolate(points_with_gap, 2.5)


def test_interpolate_known_real_curve():
    """fl-4.0-structure-105 at x=0 should return 18.0 exactly (published point)."""
    # These values are read from the verified tidy CSV; not invented here.
    # y values for fl-4.0-structure-105 at depths -4..0:  0, 0, 0, 0, 18
    points = [(-4.0, 0.0), (-3.0, 0.0), (-2.0, 0.0), (-1.0, 0.0), (0.0, 18.0)]
    assert interpolate(points, 0.0) == 18.0


def test_interpolate_linear_between_real_points():
    """Midpoint between depth 0 (y=18) and depth 1 (y=22) is 20.0 for curve 105."""
    points = [(0.0, 18.0), (1.0, 22.0)]
    result = interpolate(points, 0.5)
    assert result == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# get_curve() — requires the SQLite database
# ---------------------------------------------------------------------------

def test_get_curve_returns_points(db_con):
    curve = get_curve(db_con, "fl-4.0-structure-105")
    assert "points" in curve
    assert len(curve["points"]) == 29


def test_get_curve_returns_attributes(db_con):
    curve = get_curve(db_con, "fl-4.0-structure-105")
    assert "attributes" in curve
    # attributes is a dict; it may be empty or contain comment/default flags
    assert isinstance(curve["attributes"], dict)


def test_get_curve_returns_kind(db_con):
    curve = get_curve(db_con, "fl-4.0-structure-105")
    assert "kind" in curve
    assert curve["kind"] is not None
    assert curve["kind"]["peril"] == "fl"
    assert curve["kind"]["damage_type"] == "structure"


def test_get_curve_raises_for_unknown_id(db_con):
    with pytest.raises(CurveError, match="no such curve"):
        get_curve(db_con, "fl-4.0-structure-99999")


def test_get_curve_raises_for_completely_bogus_id(db_con):
    with pytest.raises(CurveError, match="no such curve"):
        get_curve(db_con, "this-does-not-exist")


def test_get_curve_points_are_sorted_by_x(db_con):
    """Points must be sorted ascending by x (depth)."""
    curve = get_curve(db_con, "fl-4.0-structure-105")
    xs = [p[0] for p in curve["points"]]
    assert xs == sorted(xs), "Points are not sorted by x"


def test_get_curve_105_first_point(db_con):
    """fl-4.0-structure-105 first point is (-4, 0)."""
    curve = get_curve(db_con, "fl-4.0-structure-105")
    first = curve["points"][0]
    assert first == (-4.0, 0.0), f"Expected (-4.0, 0.0), got {first}"
